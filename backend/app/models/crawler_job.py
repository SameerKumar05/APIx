"""SQLAlchemy ORM models for durable cross-process crawler jobs and worker heartbeats."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class CrawlerJob(Base):
    """Durable crawler job record managed across API and worker processes."""

    __tablename__ = "crawler_jobs"
    __table_args__ = (
        Index(
            "ix_crawler_jobs_queue_status_prio_id",
            "queue_name",
            "status",
            "priority",
            "id",
        ),
        Index("ix_crawler_jobs_lease_expiry", "status", "lease_expires_at"),
        Index(
            "ix_crawler_jobs_dedup",
            "crawler_name",
            "route_code",
            "booking_window",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    queue_name: Mapped[str] = mapped_column(
        String(32), default="crawl", nullable=False, index=True
    )
    crawler_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    route_code: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    booking_window: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING",
        nullable=False,
        index=True,
        doc="State: PENDING, CLAIMED, RUNNING, COMPLETED, FAILED, DEAD",
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    # Ownership & Fencing
    worker_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Execution Tracking
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # Timestamps (UTC)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Results & Diagnostics
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "queue_name": self.queue_name,
            "crawler_name": self.crawler_name,
            "route_code": self.route_code,
            "booking_window": self.booking_window,
            "status": self.status,
            "priority": self.priority,
            "worker_id": self.worker_id,
            "attempts": self.attempts,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "claimed_at": self.claimed_at.isoformat() if self.claimed_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "is_synthetic": self.is_synthetic,
            "error_message": self.error_message,
        }

    def __repr__(self) -> str:
        return (
            f"<CrawlerJob(id={self.id}, job_id='{self.job_id}', crawler='{self.crawler_name}', "
            f"route='{self.route_code}', status='{self.status}', attempts={self.attempts})>"
        )


class WorkerHeartbeat(Base):
    """Registration and liveness ledger for out-of-process crawler workers."""

    __tablename__ = "worker_heartbeats"
    __table_args__ = (
        Index("ix_worker_heartbeats_status_hb", "status", "last_heartbeat_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    hostname: Mapped[str] = mapped_column(String(128), nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_type: Mapped[str] = mapped_column(
        String(64), default="crawler_worker", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="ALIVE", nullable=False
    )  # ALIVE, STOPPING, DEAD
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    current_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    jobs_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    jobs_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "worker_id": self.worker_id,
            "hostname": self.hostname,
            "pid": self.pid,
            "worker_type": self.worker_type,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_heartbeat_at": (
                self.last_heartbeat_at.isoformat() if self.last_heartbeat_at else None
            ),
            "current_job_id": self.current_job_id,
            "jobs_completed": self.jobs_completed,
            "jobs_failed": self.jobs_failed,
        }

    def __repr__(self) -> str:
        return (
            f"<WorkerHeartbeat(id={self.id}, worker_id='{self.worker_id}', "
            f"status='{self.status}', last_heartbeat='{self.last_heartbeat_at}')>"
        )
