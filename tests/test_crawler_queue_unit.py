from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.crawler_job_repo import (
    claim_next_job,
    complete_job,
    enqueue_job,
    get_active_worker,
    get_active_worker_count,
    get_job_by_id,
    heartbeat_job,
    reap_stale_jobs,
    register_worker_heartbeat,
    retire_worker,
    update_worker_heartbeat,
)
from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.models.crawler_job import CrawlerJob, WorkerHeartbeat
from backend.app.models.route import Route
from backend.app.models.telemetry import ScraperTelemetry
from ingestion.base import ScrapeResult
from ingestion.config import IngestionConfig
from ingestion.worker import CrawlerWorker


def test_enqueue_job_and_idempotent_deduplication(db_session: Session) -> None:
    job1 = enqueue_job(
        db=db_session,
        crawler_name="makemytrip",
        route_code="DEL-BOM",
        booking_window="T+1",
        priority=10,
    )
    assert job1.id is not None
    assert job1.job_id.startswith("trig-")
    assert job1.status == "PENDING"
    assert job1.attempts == 0

    job2 = enqueue_job(
        db=db_session,
        crawler_name="makemytrip",
        route_code="DEL-BOM",
        booking_window="T+1",
        priority=10,
    )
    assert job2.id == job1.id
    assert job2.job_id == job1.job_id

    total_jobs = db_session.scalar(select(func.count(CrawlerJob.id)))
    assert total_jobs == 1


def test_claim_next_job_atomic_winner(db_session: Session) -> None:
    job = enqueue_job(
        db=db_session,
        crawler_name="spicejet",
        route_code="DEL-BLR",
        booking_window="T+7",
    )

    claimed1 = claim_next_job(
        db=db_session,
        worker_id="worker-alpha",
        lease_seconds=60,
    )
    assert claimed1 is not None
    assert claimed1.id == job.id
    assert claimed1.status == "CLAIMED"
    assert claimed1.worker_id == "worker-alpha"
    assert claimed1.lease_token is not None
    assert claimed1.attempts == 1
    assert claimed1.claimed_at is not None

    claimed2 = claim_next_job(
        db=db_session,
        worker_id="worker-beta",
        lease_seconds=60,
    )
    assert claimed2 is None


def test_heartbeat_job_and_fencing(db_session: Session) -> None:
    enqueue_job(db=db_session, crawler_name="easemytrip", route_code="BOM-DEL")
    claimed = claim_next_job(db=db_session, worker_id="worker-1")
    assert claimed is not None

    initial_expiry = claimed.lease_expires_at
    ok = heartbeat_job(
        db=db_session,
        job_id=claimed.id,
        worker_id="worker-1",
        lease_token=claimed.lease_token,
        lease_seconds=120,
    )
    assert ok is True

    db_session.refresh(claimed)
    assert claimed.lease_expires_at > initial_expiry

    bad_token = heartbeat_job(
        db=db_session,
        job_id=claimed.id,
        worker_id="worker-1",
        lease_token="invalid-token",
    )
    assert bad_token is False

    bad_worker = heartbeat_job(
        db=db_session,
        job_id=claimed.id,
        worker_id="worker-imposter",
        lease_token=claimed.lease_token,
    )
    assert bad_worker is False


def test_complete_job_fenced(db_session: Session) -> None:
    enqueue_job(db=db_session, crawler_name="amadeus", route_code="DEL-HYD")
    claimed = claim_next_job(db=db_session, worker_id="worker-finish")
    assert claimed is not None

    done = complete_job(
        db=db_session,
        job_id=claimed.id,
        worker_id="worker-finish",
        lease_token=claimed.lease_token,
        status="COMPLETED",
        result_summary={"records": 42},
    )
    assert done is True

    db_session.refresh(claimed)
    assert claimed.status == "COMPLETED"
    assert claimed.completed_at is not None

    second_complete = complete_job(
        db=db_session,
        job_id=claimed.id,
        worker_id="worker-finish",
        lease_token=claimed.lease_token,
        status="COMPLETED",
    )
    assert second_complete is False


def test_reap_stale_jobs_requeues_expired_lease(db_session: Session) -> None:
    enqueue_job(db=db_session, crawler_name="synthetic", route_code="DEL-CCU")
    claimed = claim_next_job(db=db_session, worker_id="worker-dead")
    assert claimed is not None

    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    db_session.commit()

    stats = reap_stale_jobs(db_session)
    assert stats["requeued"] == 1
    assert stats["dead"] == 0

    db_session.refresh(claimed)
    assert claimed.status == "PENDING"
    assert claimed.worker_id is None
    assert claimed.lease_token is None


def test_reap_stale_jobs_dead_letters_exhausted(db_session: Session) -> None:
    enqueue_job(db=db_session, crawler_name="synthetic", route_code="CCU-DEL")
    claimed = claim_next_job(db=db_session, worker_id="worker-failing")
    assert claimed is not None

    claimed.attempts = claimed.max_attempts
    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    db_session.commit()

    stats = reap_stale_jobs(db_session)
    assert stats["dead"] == 1

    db_session.refresh(claimed)
    assert claimed.status == "DEAD"


def test_worker_heartbeat_and_liveness_helpers(db_session: Session) -> None:
    w = register_worker_heartbeat(
        db=db_session,
        worker_id="worker-live-1",
        hostname="node-1",
        pid=1234,
    )
    assert w.status == "ALIVE"

    count = get_active_worker_count(db_session, threshold_seconds=60)
    assert count == 1

    active = get_active_worker(db_session, threshold_seconds=60)
    assert active is not None
    assert active.worker_id == "worker-live-1"

    update_worker_heartbeat(
        db=db_session,
        worker_id="worker-live-1",
        jobs_completed_increment=5,
    )
    db_session.refresh(w)
    assert w.jobs_completed == 5

    retire_worker(db_session, "worker-live-1")
    db_session.refresh(w)
    assert w.status == "DEAD"

    count_after = get_active_worker_count(db_session, threshold_seconds=60)
    assert count_after == 0


class _StubOrchestrator:
    """Keeps this test off the network.

    A real orchestrator made the outcome environment-dependent: CI returned
    captcha_hits > 0 with no records, which telemetry_status_for calls CAPTCHA,
    and the job was marked FAILED. Pass 388 locally, fail in CI, no code change.
    """

    scraper_source = "synthetic"

    def scrape_slot(
        self,
        origin: object,
        window_code: object,
        scraper_source: str | None = None,
    ) -> ScrapeResult:
        # Empty records with no CAPTCHA marker keeps the job COMPLETED.
        return ScrapeResult(source="synthetic", success=True, records=[], errors=[])


def test_crawler_worker_process_single_job_simulation(db_session: Session) -> None:
    from sqlalchemy.orm import sessionmaker

    testing_session_factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)

    enqueue_job(
        db=db_session,
        crawler_name="synthetic",
        route_code="DEL-BOM",
        booking_window="T+1",
    )

    worker = CrawlerWorker(
        worker_id="test-sim-worker",
        config=IngestionConfig(ingestion_mode="synthetic"),
        session_factory=testing_session_factory,
        orchestrator=_StubOrchestrator(),
    )

    job = worker._claim_job()
    assert job is not None
    assert job.status == "CLAIMED"

    worker._process_job(job)

    updated_job = db_session.get(CrawlerJob, job.id)
    assert updated_job is not None
    assert updated_job.status == "COMPLETED"
    assert updated_job.completed_at is not None

    telemetry_rows = db_session.scalars(
        select(ScraperTelemetry).where(ScraperTelemetry.crawler_name == "synthetic")
    ).all()
    assert len(telemetry_rows) >= 1
    assert telemetry_rows[0].status in ("SUCCESS", "PARTIAL")


def test_init_db_creates_queue_tables_on_fresh_database(tmp_path) -> None:
    """Fresh deployments must create the durable queue tables before workers start."""
    from sqlalchemy import create_engine

    from backend.app.db.session import init_db

    engine = create_engine(f"sqlite:///{tmp_path / 'fresh-queue.db'}")
    try:
        init_db(engine)
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {"crawler_jobs", "worker_heartbeats"}.issubset(table_names)


class _BlockingOrchestrator:
    """Holds scrape_slot open so a test can observe work that must happen during it."""

    def __init__(self) -> None:
        self.scraper_source = "synthetic"
        self.started = threading.Event()
        self.release = threading.Event()

    def scrape_slot(
        self,
        origin: object,
        window_code: object,
        scraper_source: str | None = None,
    ) -> ScrapeResult:
        self.started.set()
        assert self.release.wait(timeout=5)
        return ScrapeResult(source="synthetic", success=True, records=[], errors=[])


def test_worker_refreshes_heartbeat_while_job_is_blocked(tmp_path: Path) -> None:
    """Given a scrape that has not returned, the worker heartbeat must advance."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'heartbeat.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    orchestrator = _BlockingOrchestrator()
    try:
        with factory() as db:
            enqueue_job(
                db=db,
                crawler_name="synthetic",
                route_code="DEL-BOM",
                booking_window="T+1",
            )
            register_worker_heartbeat(
                db=db,
                worker_id="heartbeat-probe",
                hostname="probe",
                pid=1,
            )

        worker = CrawlerWorker(
            worker_id="heartbeat-probe",
            config=IngestionConfig(ingestion_mode="synthetic"),
            orchestrator=orchestrator,
            session_factory=factory,
            heartbeat_interval=0.05,
        )
        refresh_count = 0
        refreshed = threading.Event()
        send_heartbeat = worker._send_heartbeat

        def _counting_heartbeat(current_job_id: str | None = None) -> None:
            nonlocal refresh_count
            send_heartbeat(current_job_id)
            if current_job_id is None:
                return
            refresh_count += 1
            refreshed.set()

        worker._send_heartbeat = _counting_heartbeat
        job = worker._claim_job()
        assert job is not None

        runner = threading.Thread(target=worker._process_job, args=(job,))
        runner.start()
        try:
            assert orchestrator.started.wait(timeout=2)
            deadline = datetime.now(UTC) + timedelta(seconds=1)
            while datetime.now(UTC) < deadline and refresh_count < 2:
                refreshed.wait(timeout=0.05)
                refreshed.clear()

            assert refresh_count >= 2
            assert not orchestrator.release.is_set()
            with factory() as db:
                heartbeat = db.scalars(
                    select(WorkerHeartbeat).where(
                        WorkerHeartbeat.worker_id == "heartbeat-probe"
                    )
                ).one()
            assert heartbeat.current_job_id == job.job_id
            assert heartbeat.status == "ALIVE"
        finally:
            orchestrator.release.set()
            runner.join(timeout=5)
        assert not runner.is_alive()
    finally:
        engine.dispose()


def test_stop_releases_only_this_workers_active_lease(db_session: Session) -> None:
    """Given two claimed jobs, graceful stop frees this worker's lease and leaves the other."""
    factory = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    enqueue_job(
        db=db_session,
        crawler_name="synthetic",
        route_code="DEL-BOM",
        booking_window="T+1",
    )
    enqueue_job(
        db=db_session,
        crawler_name="synthetic",
        route_code="BOM-DEL",
        booking_window="T+7",
    )
    stopping = CrawlerWorker(worker_id="stopping-worker", session_factory=factory)
    other = CrawlerWorker(worker_id="other-worker", session_factory=factory)
    owned = stopping._claim_job()
    foreign = other._claim_job()
    assert owned is not None
    assert foreign is not None

    stopping.stop()

    db_session.expire_all()
    released = db_session.get(CrawlerJob, owned.id)
    held = db_session.get(CrawlerJob, foreign.id)
    assert released is not None
    assert held is not None
    assert released.status == "PENDING"
    assert released.worker_id is None
    assert released.lease_token is None
    assert held.status == "CLAIMED"
    assert held.worker_id == "other-worker"
    reclaimed = claim_next_job(db=db_session, worker_id="replacement-worker")
    assert reclaimed is not None
    assert reclaimed.id == owned.id


def test_claim_failure_is_logged_and_backs_off(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Given a database error on claim, the worker logs it and waits longer than a poll."""

    def broken_session() -> Session:
        raise SQLAlchemyError("queue claim failed")

    worker = CrawlerWorker(
        worker_id="claim-backoff",
        session_factory=broken_session,
        poll_interval=0.2,
    )
    worker.claim_backoff_seconds = 7.5
    worker._last_heartbeat_time = datetime.now(UTC).timestamp()
    worker._last_reaper_time = worker._last_heartbeat_time
    slept: list[float] = []

    with caplog.at_level(logging.ERROR, logger="ingestion.worker"):
        with patch(
            "ingestion.worker.time.sleep",
            side_effect=lambda seconds: slept.append(seconds),
        ):
            worker._tick()

    assert slept == [7.5]
    assert any(
        record.levelno == logging.ERROR and "Claim attempt failed" in record.message
        for record in caplog.records
    )


def test_reap_dead_letters_passed_deadline_with_attempts_remaining(
    db_session: Session,
) -> None:
    """Given a live lease and a passed deadline, the job is dead-lettered before attempts run out."""
    enqueue_job(db=db_session, crawler_name="synthetic", route_code="DEL-HYD")
    claimed = claim_next_job(
        db=db_session, worker_id="worker-deadline", max_runtime_seconds=900
    )
    assert claimed is not None
    assert claimed.attempts < claimed.max_attempts
    claimed.deadline_at = datetime.now(UTC) - timedelta(seconds=5)
    claimed.lease_expires_at = datetime.now(UTC) + timedelta(seconds=60)
    db_session.commit()

    stats = reap_stale_jobs(db_session)

    assert stats["dead"] == 1
    assert stats["requeued"] == 0
    db_session.refresh(claimed)
    assert claimed.status == "DEAD"
    assert claimed.attempts == 1
    assert claimed.error_message is not None
    assert "deadline" in claimed.error_message


def test_reap_does_not_requeue_when_deadline_and_lease_have_both_expired(
    db_session: Session,
) -> None:
    """Given an expired lease and a passed deadline, remaining attempts do not put the job back."""
    enqueue_job(db=db_session, crawler_name="synthetic", route_code="HYD-DEL")
    claimed = claim_next_job(db=db_session, worker_id="worker-both-expired")
    assert claimed is not None
    claimed.deadline_at = datetime.now(UTC) - timedelta(seconds=5)
    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
    db_session.commit()

    stats = reap_stale_jobs(db_session)

    assert stats["dead"] == 1
    assert stats["requeued"] == 0
    db_session.refresh(claimed)
    assert claimed.status == "DEAD"


def test_health_fails_when_routes_exist_but_queue_tables_are_missing(
    tmp_path: Path,
) -> None:
    """Given routes without crawler queue tables, /health must not report ready."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'routes-only.db'}",
        connect_args={"check_same_thread": False},
    )
    Route.__table__.create(bind=engine)
    session = Session(engine)
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["detail"] == "Database unavailable"
        assert "crawler_jobs" not in inspect(engine).get_table_names()
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_enqueue_dedup_window_is_not_concurrency_safe(tmp_path: Path) -> None:
    """Overlapping inserts for one in-flight key both commit until a migration adds a unique key."""
    engine = create_engine(f"sqlite:///{tmp_path / 'dedup-race.db'}")
    CrawlerJob.__table__.create(bind=engine)
    try:
        unique_names = {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints("crawler_jobs")
        }
        unique_indexes = {
            tuple(index["column_names"])
            for index in inspect(engine).get_indexes("crawler_jobs")
            if index.get("unique")
        }
        dedup_key = ("crawler_name", "route_code", "booking_window")
        assert dedup_key not in unique_names
        assert dedup_key not in unique_indexes

        factory = sessionmaker(bind=engine, expire_on_commit=False)
        now = datetime.now(UTC)
        left = factory()
        right = factory()
        try:
            left.add(
                CrawlerJob(
                    job_id="trig-race-left",
                    crawler_name="makemytrip",
                    route_code="DEL-BOM",
                    booking_window="T+1",
                    status="PENDING",
                    payload_json="{}",
                    created_at=now,
                    scheduled_at=now,
                )
            )
            right.add(
                CrawlerJob(
                    job_id="trig-race-right",
                    crawler_name="makemytrip",
                    route_code="DEL-BOM",
                    booking_window="T+1",
                    status="PENDING",
                    payload_json="{}",
                    created_at=now,
                    scheduled_at=now,
                )
            )
            left.commit()
            right.commit()
        finally:
            left.close()
            right.close()

        with factory() as db:
            duplicates = db.scalar(
                select(func.count(CrawlerJob.id)).where(
                    CrawlerJob.crawler_name == "makemytrip",
                    CrawlerJob.route_code == "DEL-BOM",
                    CrawlerJob.booking_window == "T+1",
                    CrawlerJob.status == "PENDING",
                )
            )
        assert duplicates == 2
    finally:
        engine.dispose()
