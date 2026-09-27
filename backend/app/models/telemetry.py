"""Telemetry models for scraper execution tracking, error metrics, and proxy health monitoring."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class ScraperTelemetry(Base):
    """Telemetry record for individual crawler task execution.

    Captures execution status, response duration, records gathered,
    proxy usage, and error diagnostics across flight booking queries.
    """

    __tablename__ = "scraper_telemetry"
    __table_args__ = (
        Index("ix_scraper_telemetry_crawler_created", "crawler_name", "created_at"),
        Index("ix_scraper_telemetry_route_window", "route", "booking_window"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        doc="Unique primary key identifier",
    )
    crawler_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        doc="Identifier of the scraper crawler (e.g. makemytrip, easemytrip, ixigo, spicejet, amadeus, synthetic)",
    )
    route: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        doc="Origin-destination route corridor (e.g. DEL-BOM, BOM-DEL, BLR-DEL)",
    )
    booking_window: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        index=True,
        doc="Advance booking window horizon (e.g. T+1, T+7, T+15, T+30, 7d, 14d, 21d)",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        doc="Execution status (e.g. SUCCESS, FAILED, PARTIAL, TIMEOUT, fallback_amadeus, fallback_synthetic)",
    )
    response_time_ms: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Crawler execution response time in milliseconds",
    )
    proxy_ip: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
        doc="IP address or host of the proxy server utilized",
    )
    records_extracted: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of flight price quotes successfully extracted",
    )
    error_details: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Exception message, traceback, or failure explanation if status != SUCCESS",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
        doc="UTC timestamp when telemetry was captured",
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert ScraperTelemetry instance to dictionary representation."""
        return {
            "id": self.id,
            "crawler_name": self.crawler_name,
            "route": self.route,
            "booking_window": self.booking_window,
            "status": self.status,
            "response_time_ms": self.response_time_ms,
            "proxy_ip": self.proxy_ip,
            "records_extracted": self.records_extracted,
            "error_details": self.error_details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<ScraperTelemetry(id={self.id}, crawler='{self.crawler_name}', "
            f"route='{self.route}', status='{self.status}', "
            f"time_ms={self.response_time_ms:.1f}, records={self.records_extracted})>"
        )


class ProxyHealthRecord(Base):
    """Health diagnostic observation for an egress proxy endpoint.

    Monitors round-trip latency, connection success/failure rates,
    consecutive failures (for circuit breaking), and health classification.
    """

    __tablename__ = "proxy_health_records"
    __table_args__ = (
        Index("ix_proxy_health_status_latency", "status", "latency_ms"),
        Index("ix_proxy_health_proxy_checked", "proxy_ip", "last_checked_at"),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        doc="Unique primary key identifier",
    )
    proxy_ip: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        doc="Proxy host/IP address or URL endpoint",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="HEALTHY",
        index=True,
        doc="Health status (e.g. HEALTHY, DEGRADED, BANNED, TIMEOUT, DEAD)",
    )
    latency_ms: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Round-trip ping or request latency in milliseconds",
    )
    success_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Cumulative successful requests handled by this proxy",
    )
    failure_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Cumulative failed requests encountered by this proxy",
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Consecutive failure count for circuit breaking / quarantine",
    )
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
        doc="UTC timestamp of the most recent health check probe",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Most recent error message, HTTP status code, or failure description",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
        doc="UTC timestamp when record was created",
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert ProxyHealthRecord instance to dictionary representation."""
        return {
            "id": self.id,
            "proxy_ip": self.proxy_ip,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "consecutive_failures": self.consecutive_failures,
            "last_checked_at": (
                self.last_checked_at.isoformat() if self.last_checked_at else None
            ),
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<ProxyHealthRecord(id={self.id}, proxy='{self.proxy_ip}', "
            f"status='{self.status}', latency_ms={self.latency_ms:.1f}, "
            f"consec_failures={self.consecutive_failures})>"
        )
