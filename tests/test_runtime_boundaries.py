"""Runtime boundary regressions for health, persistence, and crawler auth."""

from __future__ import annotations

import tempfile
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session

import backend.app.models  # noqa: F401
from backend.app.core.config import Settings, settings
from backend.app.db.crawler_job_repo import register_worker_heartbeat
from backend.app.db.ingestion_repo import IngestionRepo, cleanup_old_raw_fares
from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.models.crawler_job import CrawlerJob
from backend.app.models.index import NationalDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.route import Route
from backend.app.models.telemetry import ScraperTelemetry
from backend.app.schemas.ingestion import IngestionBatchRequest, RawFareRecord


def _valid_ingestion_request() -> IngestionBatchRequest:
    """Return one valid, isolated ingestion request."""
    now = datetime.now(UTC)
    return IngestionBatchRequest(
        batch_id="runtime-boundary-test",
        source="verification",
        scraped_at=now,
        records=[
            RawFareRecord(
                airline_code="6E",
                flight_number="QA-BOUNDARY-001",
                origin="DEL",
                destination="BOM",
                departure_datetime=now + timedelta(days=7),
                booking_datetime=now,
                fare_inr=7777.77,
                cabin_class="economy",
                stops=0,
                source="verification",
                booking_window="T+7",
            )
        ],
    )


@pytest.fixture
def unavailable_database_session(tmp_path: Path) -> Generator[Session, None, None]:
    """Create a real SQLAlchemy session whose SQLite parent directory is absent."""
    database_path = tmp_path / "missing" / "apix.db"
    engine = create_engine(f"sqlite:///{database_path}")
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def empty_schema_session(tmp_path: Path) -> Generator[Session, None, None]:
    """Create a reachable SQLite session without APIx tables."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'empty.db'}",
        connect_args={"check_same_thread": False},
    )
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


_QUEUE_TABLES = frozenset({"crawler_jobs", "worker_heartbeats"})


@pytest.fixture
def domain_complete_queue_missing_session(
    tmp_path: Path,
) -> Generator[Session, None, None]:
    """Reachable schema with every domain table, and neither queue table."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'domain-complete.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        for table_name in _QUEUE_TABLES:
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {table_name}")
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_health_endpoints_report_503_when_database_is_unavailable(
    unavailable_database_session: Session,
) -> None:
    """Given no database, both health routes must report service unavailable."""
    app.dependency_overrides[get_db] = lambda: unavailable_database_session
    try:
        with TestClient(app) as client:
            for path in ("/health", "/api/v1/health"):
                response = client.get(path)

                assert response.status_code == 503, path
                assert response.json()["detail"] == "Database unavailable"
    finally:
        app.dependency_overrides.clear()


def test_health_endpoints_report_503_when_schema_is_missing(
    empty_schema_session: Session,
) -> None:
    """Given a reachable database with no schema, health must not report ready."""
    app.dependency_overrides[get_db] = lambda: empty_schema_session
    try:
        with TestClient(app) as client:
            for path in ("/health", "/api/v1/health"):
                response = client.get(path)

                assert response.status_code == 503, path
                assert response.json()["detail"] == "Database unavailable"
    finally:
        app.dependency_overrides.clear()


def test_health_endpoints_report_503_when_domain_tables_exist_but_queue_tables_are_missing(
    domain_complete_queue_missing_session: Session,
) -> None:
    """Given every domain table but no queue tables, neither health route is ready."""
    engine = domain_complete_queue_missing_session.get_bind()
    present = set(inspect(engine).get_table_names())
    domain_tables = frozenset(Base.metadata.tables) - _QUEUE_TABLES
    assert domain_tables <= present
    assert present.isdisjoint(_QUEUE_TABLES)

    app.dependency_overrides[get_db] = lambda: domain_complete_queue_missing_session
    try:
        # Lifespan create_all would recreate the dropped queue tables.
        client = TestClient(app)
        for path in ("/health", "/api/v1/health"):
            response = client.get(path)

            assert response.status_code == 503, path
            assert response.json()["detail"] == "Database unavailable"
        assert set(inspect(engine).get_table_names()).isdisjoint(_QUEUE_TABLES)
    finally:
        app.dependency_overrides.clear()


def test_ingestion_returns_503_when_persistence_fails(
    unavailable_database_session: Session,
) -> None:
    """Given a failed insert, ingestion must not claim that records were stored."""
    app.dependency_overrides[get_db] = lambda: unavailable_database_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/ingestion/batch",
                headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
                json=_valid_ingestion_request().model_dump(mode="json"),
            )

            assert response.status_code == 503
            assert response.json()["detail"] == "Failed to persist ingested fares"
    finally:
        app.dependency_overrides.clear()


def test_cors_configuration_rejects_wildcard_origin() -> None:
    """Credentialed CORS must never accept an arbitrary origin."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, BACKEND_CORS_ORIGINS=["*"])


def test_cors_allows_only_configured_origins(db_session: Session) -> None:
    """Given configured and unapproved origins, only the configured one is allowed."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            approved = client.get(
                "/health",
                headers={"Origin": "http://localhost:3000"},
            )
            unapproved = client.get(
                "/health",
                headers={"Origin": "https://evil.example"},
            )

            assert (
                approved.headers["access-control-allow-origin"]
                == "http://localhost:3000"
            )
            assert approved.headers["access-control-allow-credentials"] == "true"
            assert "access-control-allow-origin" not in unapproved.headers
    finally:
        app.dependency_overrides.clear()


def test_crawler_trigger_requires_authentication(db_session: Session) -> None:
    """Given no ingestion key, crawler dispatch must be rejected before any write."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            unauthorized = client.post(
                "/api/v1/ingestion/trigger",
                json={"crawler_name": "makemytrip", "route_code": "DEL-BOM"},
            )

            assert unauthorized.status_code == 401
            telemetry_count = db_session.scalar(select(func.count(ScraperTelemetry.id)))
            assert telemetry_count == 0

            register_worker_heartbeat(
                db=db_session,
                worker_id="worker-test-auth",
                hostname="localhost",
                pid=10001,
            )

            authorized = client.post(
                "/api/v1/ingestion/trigger",
                headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
                json={"crawler_name": "makemytrip", "route_code": "DEL-BOM"},
            )
            assert authorized.status_code == 202
            assert authorized.json()["status"] == "QUEUED"
            assert "queued" in authorized.json()["message"].lower()
            assert authorized.json()["task_id"].startswith("trig-")

            job_count = db_session.scalar(select(func.count(CrawlerJob.id)))
            assert job_count == 1
            assert db_session.scalar(select(func.count(ScraperTelemetry.id))) == 0
    finally:
        app.dependency_overrides.clear()


def test_crawler_trigger_returns_503_when_database_is_unavailable(
    unavailable_database_session: Session,
) -> None:
    app.dependency_overrides[get_db] = lambda: unavailable_database_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/ingestion/trigger",
                headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
                json={"crawler_name": "makemytrip", "route_code": "DEL-BOM"},
            )
            assert response.status_code == 503
            assert response.json()["detail"] == "Database unavailable"
    finally:
        app.dependency_overrides.clear()


def test_crawler_trigger_returns_503_when_no_active_worker(
    db_session: Session,
) -> None:
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/ingestion/trigger",
                headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
                json={"crawler_name": "makemytrip", "route_code": "DEL-BOM"},
            )
            assert response.status_code == 503
            assert response.json()["detail"] == "No active crawler worker available"
    finally:
        app.dependency_overrides.clear()


def test_retention_cleanup_handles_sqlite_naive_timestamps(tmp_path: Path) -> None:
    """Given SQLite-loaded timestamps, retention must prune by age without a timezone crash."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'retention.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    now = datetime.now(UTC)
    try:
        session.add_all(
            [
                RawFare(
                    batch_id="retention-boundary",
                    origin="DEL",
                    destination="BOM",
                    flight_date=(now - timedelta(days=age)).date(),
                    booking_window="T+7",
                    airline_code="6E",
                    flight_number=f"RETENTION-{age}",
                    departure_time=now - timedelta(days=age),
                    arrival_time=now - timedelta(days=age, hours=-2),
                    duration_minutes=120,
                    stops=0,
                    fare_class="Economy",
                    base_fare=5000.0,
                    taxes_and_fees=1000.0,
                    total_fare=6000.0,
                    source_platform="verification",
                    scraped_at=now - timedelta(days=age),
                    hash_id=f"{age:064d}",
                    is_synthetic=False,
                )
                for age in (120, 89, 1)
            ]
        )
        session.commit()
        session.expire_all()
        loaded = session.scalars(select(RawFare).order_by(RawFare.id)).all()
        assert all(value.scraped_at.tzinfo is None for value in loaded)

        pruned = cleanup_old_raw_fares(session, days=90, commit=True)

        assert pruned == 1
        assert session.scalar(select(func.count(RawFare.id))) == 2
    finally:
        session.close()
        engine.dispose()


def test_routes_overview_does_not_fabricate_when_database_is_unavailable(
    unavailable_database_session: Session,
) -> None:
    """Given an unreachable database, routes must fail closed rather than answer with the hardcoded benchmark corridors."""
    app.dependency_overrides[get_db] = lambda: unavailable_database_session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/indices/routes")

        assert response.status_code == 503, response.text
        assert response.json()["detail"] == "Database unavailable"
    finally:
        app.dependency_overrides.clear()


def test_routes_overview_reports_no_coverage_instead_of_seeded_corroridors(
    tmp_path: Path,
) -> None:
    """Given a reachable database with no active routes, coverage must read as zero rather than seven invented corridors."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'no-active-routes.db'}",
        connect_args={"check_same_thread": False},
    )
    Route.__table__.create(bind=engine)
    session = Session(engine)
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/indices/routes")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["routes"] == []
        assert body["total_routes"] == 0
        seeded = {6850.0, 4950.0, 7200.0, 5800.0, 5100.0, 3850.0, 6400.0}
        assert not seeded.intersection(
            {item["avg_fare_inr"] for item in body["routes"] if "avg_fare_inr" in item}
        )
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_ingestion_defaults_to_synthetic_when_provenance_is_absent(
    tmp_path: Path,
) -> None:
    """Omitting is_synthetic must fail closed, so a forgetful writer cannot produce real-looking rows."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'provenance.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    try:
        unlabelled = {
            "flight_number": "ZZ-9999",
            "flight_date": "2026-11-11",
            "airline_code": "ZZ",
            "origin": "DEL",
            "destination": "BOM",
            "booking_window": "T+1",
            "total_fare": 5000.0,
            "source_platform": "makemytrip",
        }
        assert (
            IngestionRepo(session).bulk_insert([unlabelled], batch_id="absent")[
                "inserted"
            ]
            == 1
        )
        session.commit()
        stored = session.scalars(
            select(RawFare).where(RawFare.flight_number == "ZZ-9999")
        ).one()
        assert stored.is_synthetic is True

        declared = {
            **unlabelled,
            "flight_number": "ZZ-8888",
            "flight_date": "2026-12-12",
            "is_synthetic": False,
        }
        assert (
            IngestionRepo(session).bulk_insert([declared], batch_id="explicit")[
                "inserted"
            ]
            == 1
        )
        session.commit()
        trusted = session.scalars(
            select(RawFare).where(RawFare.flight_number == "ZZ-8888")
        ).one()
        assert trusted.is_synthetic is False
    finally:
        session.close()
        engine.dispose()


def test_fabrication_endpoints_fail_closed_on_unavailable_database(
    unavailable_database_session: Session,
) -> None:
    """Each endpoint that used to answer from a hardcoded constant must 503, never fabricate."""
    app.dependency_overrides[get_db] = lambda: unavailable_database_session
    try:
        with TestClient(app) as client:
            for path in (
                "/api/v1/indices/routes",
                "/api/v1/indices/routes/DEL-BOM/history",
                "/api/v1/analytics/arbitrage",
                "/api/v1/analytics/anomalies",
                "/api/v1/analytics/lead-time-curve",
                "/api/v1/analytics/heatmap",
                "/api/v1/analytics/dgca-validation",
            ):
                response = client.get(path)

                assert (
                    response.status_code == 503
                ), f"{path} -> {response.status_code} {response.text[:120]}"
                assert response.json()["detail"] == "Database unavailable", path
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def seeded_index_session(tmp_path: Path) -> Generator[Session, None, None]:
    """A reachable database holding a known daily Fisher index series."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'index-history.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    # 70 consecutive days, deterministic ramp, one sample per day.
    start = date(2026, 1, 1)
    for offset in range(70):
        session.add(
            NationalDailyIndex(
                index_date=start + timedelta(days=offset),
                booking_window="COMPOSITE",
                index_type="fisher",
                index_value=100.0 + offset,
                total_samples=10,
                base_period="2026-01-01",
            )
        )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_index_history_reports_missing_data_instead_of_inventing_it(
    tmp_path: Path,
) -> None:
    """An unseeded database must yield an empty, explicitly-unavailable series.

    This endpoint used to fall through to a fabricated ramp with a sample count
    of 45000+ per point, which the dashboard could not distinguish from a real one.
    """
    engine = create_engine(
        f"sqlite:///{tmp_path / 'unseeded.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/indices/national/history")
        assert response.status_code == 200
        body = response.json()
        assert body["points"] == []
        assert body["total_points"] == 0
        assert body["data_available"] is False
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_index_latest_reports_503_when_nothing_is_computed(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'unseeded-latest.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/indices/national/latest")
        assert response.status_code == 503
        assert "not yet computed" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_index_history_aggregates_daily_weekly_and_monthly(
    seeded_index_session: Session,
) -> None:
    """The problem statement requires daily, weekly and monthly frequencies."""
    app.dependency_overrides[get_db] = lambda: seeded_index_session
    try:
        with TestClient(app) as client:
            daily = client.get(
                "/api/v1/indices/national/history", params={"frequency": "daily"}
            )
            weekly = client.get(
                "/api/v1/indices/national/history", params={"frequency": "weekly"}
            )
            monthly = client.get(
                "/api/v1/indices/national/history", params={"frequency": "monthly"}
            )

        assert daily.status_code == weekly.status_code == monthly.status_code == 200

        d, w, m = daily.json(), weekly.json(), monthly.json()
        assert d["data_available"] and w["data_available"] and m["data_available"]

        # 70 daily observations must collapse into fewer weekly and monthly buckets.
        assert d["total_points"] == 70, d["total_points"]
        assert w["total_points"] == 11, w["total_points"]
        assert m["total_points"] == 3, m["total_points"]
        assert w["total_points"] < d["total_points"]

        # Sample counts are summed across the bucket, not averaged away.
        assert d["points"][0]["sample_size"] == 10
        # The first ISO bucket is partial because the series starts on 2026-01-01,
        # so assert conservation across buckets rather than a fixed bucket size.
        assert sum(p["sample_size"] for p in w["points"]) == 70 * 10
        assert sum(p["sample_size"] for p in m["points"]) == 70 * 10

        # The final bucket is March, which holds 11 of the 70 seeded days
        # (offsets 59..69), so its value is the mean of exactly those points.
        assert len(d["points"]) == 70
        assert m["points"][-1]["index_value"] == pytest.approx(
            sum(p["index_value"] for p in d["points"][-11:]) / 11, abs=0.01
        )
        assert m["points"][-1]["index_value"] == pytest.approx(164.0, abs=0.01)
    finally:
        app.dependency_overrides.clear()


def test_index_history_rejects_an_unknown_frequency(
    seeded_index_session: Session,
) -> None:
    app.dependency_overrides[get_db] = lambda: seeded_index_session
    try:
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/indices/national/history", params={"frequency": "fortnightly"}
            )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()
