"""Repository for durable cross-process crawler job queue and worker heartbeat operations.

Implements dialect-agnostic, portable atomic job claiming and fencing compatible
with both SQLite 3.35+ and PostgreSQL 16 using single-statement UPDATE ... RETURNING,
without requiring SELECT FOR UPDATE SKIP LOCKED or Redis.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.crawler_job import CrawlerJob, WorkerHeartbeat

logger = logging.getLogger("backend.app.db.crawler_job_repo")


# ============================================================================
# Job Enqueue & Querying
# ============================================================================

def enqueue_job(
    db: Session,
    crawler_name: str,
    route_code: str | None = None,
    booking_window: str | None = None,
    payload: dict[str, Any] | None = None,
    priority: int = 0,
    dedup_window_seconds: int = 300,
    queue_name: str = "crawl",
) -> CrawlerJob:
    """Reuse an in-flight job for sequential callers, then insert.

    This check-then-insert is not concurrency-safe. Two overlapping transactions
    can both observe no active row and both commit. `crawler_jobs` has no unique
    dedup key, and `create_all` cannot add one to a table that already exists.
    A portable unique constraint needs a migration, which this repository does
    not run. Callers must not treat sequential dedup as a concurrency guarantee.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=dedup_window_seconds)

    existing = db.scalars(
        select(CrawlerJob)
        .where(
            CrawlerJob.queue_name == queue_name,
            CrawlerJob.crawler_name == crawler_name,
            CrawlerJob.route_code == route_code,
            CrawlerJob.booking_window == booking_window,
            CrawlerJob.status.in_(["PENDING", "CLAIMED", "RUNNING"]),
            CrawlerJob.created_at >= cutoff,
        )
        .order_by(CrawlerJob.id.desc())
    ).first()

    if existing:
        logger.info(
            "Found existing active job %s for crawler=%s route=%s window=%s",
            existing.job_id,
            crawler_name,
            route_code,
            booking_window,
        )
        return existing

    job_id = f"trig-{uuid.uuid4().hex[:10]}"
    job = CrawlerJob(
        job_id=job_id,
        queue_name=queue_name,
        crawler_name=crawler_name,
        route_code=route_code,
        booking_window=booking_window,
        status="PENDING",
        priority=priority,
        payload_json=json.dumps(payload or {}),
        created_at=now,
        scheduled_at=now,
        attempts=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info("Enqueued new crawler job %s (id=%d)", job.job_id, job.id)
    return job


def get_job_by_id(db: Session, job_id: str) -> CrawlerJob | None:
    """Retrieve a job by its public job_id string."""
    return db.scalars(
        select(CrawlerJob).where(CrawlerJob.job_id == job_id)
    ).first()


# ============================================================================
# Atomic Claiming & Fencing (Dialect-Agnostic SQLite + PostgreSQL)
# ============================================================================

def claim_next_job(
    db: Session,
    worker_id: str,
    lease_seconds: int = 90,
    max_runtime_seconds: int = 900,
    queue_name: str = "crawl",
) -> CrawlerJob | None:
    """Atomically claim the highest-priority oldest pending job.

    Uses a single-statement UPDATE ... WHERE id = (SELECT id ... LIMIT 1) AND status = 'PENDING'
    with RETURNING. Compatible with SQLite 3.35+ and PostgreSQL without SKIP LOCKED.
    Returns None if no pending job is available or if lost to a concurrent claimant.
    """
    now = datetime.now(UTC)
    lease_token = uuid.uuid4().hex[:16]

    # Subquery selects the single oldest pending job ID
    subquery = (
        select(CrawlerJob.id)
        .where(
            CrawlerJob.queue_name == queue_name,
            CrawlerJob.status == "PENDING",
            CrawlerJob.scheduled_at <= now,
        )
        .order_by(CrawlerJob.priority.desc(), CrawlerJob.id.asc())
        .limit(1)
        .scalar_subquery()
    )

    # Atomic single-statement update with RETURNING
    stmt = (
        update(CrawlerJob)
        .where(CrawlerJob.id == subquery, CrawlerJob.status == "PENDING")
        .values(
            status="CLAIMED",
            worker_id=worker_id,
            lease_token=lease_token,
            claimed_at=now,
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
            deadline_at=now + timedelta(seconds=max_runtime_seconds),
            attempts=CrawlerJob.attempts + 1,
        )
        .returning(CrawlerJob)
    )

    try:
        claimed = db.scalars(stmt).first()
        if claimed:
            db.commit()
            logger.info("Worker %s claimed job %s (id=%d, attempt=%d)", worker_id, claimed.job_id, claimed.id, claimed.attempts)
            return claimed
        db.rollback()
        return None
    except SQLAlchemyError:
        db.rollback()
        raise


def heartbeat_job(
    db: Session,
    job_id: int,
    worker_id: str,
    lease_token: str,
    lease_seconds: int = 90,
) -> bool:
    """Fenced heartbeat renewal.

    Returns False if the lease was lost to a reaper or stolen by another worker.
    """
    now = datetime.now(UTC)
    stmt = (
        update(CrawlerJob)
        .where(
            CrawlerJob.id == job_id,
            CrawlerJob.worker_id == worker_id,
            CrawlerJob.lease_token == lease_token,
            CrawlerJob.status.in_(["CLAIMED", "RUNNING"]),
        )
        .values(
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
    )
    result = db.execute(stmt)
    db.commit()
    renewed = result.rowcount > 0
    if not renewed:
        logger.warning(
            "Heartbeat failed for job id=%d: worker %s no longer holds lease token %s",
            job_id,
            worker_id,
            lease_token,
        )
    return renewed


def complete_job(
    db: Session,
    job_id: int,
    worker_id: str,
    lease_token: str,
    status: str,  # COMPLETED or FAILED
    result_summary: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> bool:
    """Fenced terminal job completion.

    Only updates the job if the worker still holds the lease.
    """
    now = datetime.now(UTC)
    stmt = (
        update(CrawlerJob)
        .where(
            CrawlerJob.id == job_id,
            CrawlerJob.worker_id == worker_id,
            CrawlerJob.lease_token == lease_token,
            CrawlerJob.status.in_(["CLAIMED", "RUNNING"]),
        )
        .values(
            status=status,
            completed_at=now,
            result_summary=json.dumps(result_summary or {}),
            error_message=error_message,
        )
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount > 0


# ============================================================================
# Stale Job Reaper & Dead-Letter Recovery
# ============================================================================

def reap_stale_jobs(db: Session) -> dict[str, int]:
    """Reclaim expired leases and dead-letter jobs whose deadline has passed."""
    now = datetime.now(UTC)
    active = CrawlerJob.status.in_(["CLAIMED", "RUNNING"])
    deadline_passed = and_(CrawlerJob.deadline_at.is_not(None), CrawlerJob.deadline_at < now)
    lease_expired = and_(CrawlerJob.lease_expires_at.is_not(None), CrawlerJob.lease_expires_at < now)

    dead_deadline = db.execute(
        update(CrawlerJob)
        .where(active, deadline_passed)
        .values(
            status="DEAD",
            completed_at=now,
            error_message="Dead-lettered: execution deadline exceeded",
        )
        .execution_options(synchronize_session="fetch")
    ).rowcount
    dead_attempts = db.execute(
        update(CrawlerJob)
        .where(active, lease_expired, CrawlerJob.attempts >= CrawlerJob.max_attempts)
        .values(
            status="DEAD",
            completed_at=now,
            error_message="Dead-lettered: max retry attempts exceeded",
        )
        .execution_options(synchronize_session="fetch")
    ).rowcount
    requeued = db.execute(
        update(CrawlerJob)
        .where(
            active,
            lease_expired,
            CrawlerJob.attempts < CrawlerJob.max_attempts,
            or_(CrawlerJob.deadline_at.is_(None), CrawlerJob.deadline_at >= now),
        )
        .values(
            status="PENDING",
            worker_id=None,
            lease_token=None,
            heartbeat_at=None,
            lease_expires_at=None,
            error_message="Worker lease expired; re-queued by reaper",
        )
        .execution_options(synchronize_session="fetch")
    ).rowcount

    dead = int(dead_deadline) + int(dead_attempts)
    db.commit()
    if requeued > 0 or dead > 0:
        logger.info("Reaper sweep completed: %d re-queued, %d dead-lettered", requeued, dead)
    return {"requeued": int(requeued), "dead": dead}


def release_worker_leases(db: Session, worker_id: str) -> int:
    """Return this worker's claimed jobs to the queue on graceful shutdown."""
    released = db.execute(
        update(CrawlerJob)
        .where(
            CrawlerJob.worker_id == worker_id,
            CrawlerJob.status.in_(["CLAIMED", "RUNNING"]),
        )
        .values(
            status="PENDING",
            worker_id=None,
            lease_token=None,
            heartbeat_at=None,
            lease_expires_at=None,
            error_message="Released on worker shutdown",
        )
    ).rowcount
    db.commit()
    if released:
        logger.info("Released %d active leases for worker %s", released, worker_id)
    return int(released)


# ============================================================================
# Worker Heartbeat & Liveness Management
# ============================================================================

def register_worker_heartbeat(
    db: Session,
    worker_id: str,
    hostname: str,
    pid: int,
    worker_type: str = "crawler_worker",
    metadata: dict[str, Any] | None = None,
) -> WorkerHeartbeat:
    """Register or refresh worker liveness record upon process startup."""
    now = datetime.now(UTC)
    worker = db.scalars(
        select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id)
    ).first()

    if worker:
        worker.hostname = hostname
        worker.pid = pid
        worker.worker_type = worker_type
        worker.status = "ALIVE"
        worker.last_heartbeat_at = now
        worker.metadata_json = json.dumps(metadata or {})
    else:
        worker = WorkerHeartbeat(
            worker_id=worker_id,
            hostname=hostname,
            pid=pid,
            worker_type=worker_type,
            status="ALIVE",
            started_at=now,
            last_heartbeat_at=now,
            metadata_json=json.dumps(metadata or {}),
        )
        db.add(worker)

    db.commit()
    db.refresh(worker)
    return worker


def update_worker_heartbeat(
    db: Session,
    worker_id: str,
    current_job_id: str | None = None,
    status: str = "ALIVE",
    jobs_completed_increment: int = 0,
    jobs_failed_increment: int = 0,
) -> bool:
    """Update ongoing worker heartbeat timestamp and job stats."""
    now = datetime.now(UTC)
    stmt = (
        update(WorkerHeartbeat)
        .where(WorkerHeartbeat.worker_id == worker_id)
        .values(
            last_heartbeat_at=now,
            status=status,
            current_job_id=current_job_id,
            jobs_completed=WorkerHeartbeat.jobs_completed + jobs_completed_increment,
            jobs_failed=WorkerHeartbeat.jobs_failed + jobs_failed_increment,
        )
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount > 0


def retire_worker(db: Session, worker_id: str) -> None:
    """Mark worker as STOPPING or DEAD on process shutdown."""
    now = datetime.now(UTC)
    stmt = (
        update(WorkerHeartbeat)
        .where(WorkerHeartbeat.worker_id == worker_id)
        .values(status="DEAD", last_heartbeat_at=now)
    )
    db.execute(stmt)
    db.commit()


def get_active_worker(
    db: Session,
    threshold_seconds: int = 60,
) -> WorkerHeartbeat | None:
    """Return the most recently active healthy worker within threshold_seconds."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=threshold_seconds)
    return db.scalars(
        select(WorkerHeartbeat)
        .where(
            WorkerHeartbeat.status == "ALIVE",
            WorkerHeartbeat.last_heartbeat_at >= cutoff,
        )
        .order_by(WorkerHeartbeat.last_heartbeat_at.desc())
    ).first()


def get_active_worker_count(
    db: Session,
    threshold_seconds: int = 60,
) -> int:
    """Count live workers with fresh heartbeats within threshold_seconds."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=threshold_seconds)
    from sqlalchemy import func
    count = db.scalar(
        select(func.count(WorkerHeartbeat.id))
        .where(
            WorkerHeartbeat.status == "ALIVE",
            WorkerHeartbeat.last_heartbeat_at >= cutoff,
        )
    )
    return int(count or 0)
