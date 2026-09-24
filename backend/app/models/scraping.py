"""Scraping run model for tracking scraper execution, batch health, and throughput."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class ScrapingRun(Base):
    """Execution telemetry and batch status for web scrapers.

    Tracks jobs executed across Playwright/HTTP scrapers, recording execution state,
    total routes queried, raw quotes harvested, deduplicated records, and failures.
    """

    __tablename__ = "scraping_runs"
    __table_args__ = (
        Index("ix_scraping_runs_status_platform", "status", "source_platform"),
        Index("ix_scraping_runs_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
        doc="Unique identifier for the batch run (UUID or prefixed timestamp)",
    )
    source_platform: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Target portal scraped (e.g. makemytrip, easemytrip, ixigo, portal_direct)",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
        index=True,
        doc="Run state: PENDING, RUNNING, COMPLETED, FAILED",
    )
    routes_attempted: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Total number of route corridors scheduled in this run",
    )
    routes_succeeded: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of route corridors successfully scraped without error",
    )
    fares_collected: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Gross count of raw fare quotes scraped before deduplication",
    )
    fares_deduplicated: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Net count of new unique fare quotes stored after deduplication",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Error traceback or failure description if run failed",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        doc="Timestamp when scraping process was initiated",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when scraping process finished",
    )
    duration_seconds: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Total runtime in seconds from start to completion",
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert ScrapingRun instance to dictionary."""
        return {
            "id": self.id,
            "batch_id": self.batch_id,
            "source_platform": self.source_platform,
            "status": self.status,
            "routes_attempted": self.routes_attempted,
            "routes_succeeded": self.routes_succeeded,
            "fares_collected": self.fares_collected,
            "fares_deduplicated": self.fares_deduplicated,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "duration_seconds": self.duration_seconds,
        }

    def __repr__(self) -> str:
        return (
            f"<ScrapingRun batch={self.batch_id} platform={self.source_platform} "
            f"status={self.status} collected={self.fares_collected}>"
        )
