"""Anomaly alert model for monitoring abnormal airfare spikes, drops, and surges."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.session import Base


class AnomalyAlert(Base):
    """Regulatory and market oversight alert for abnormal airfare movements.

    Detects statistical spikes (z-score > 2.5), sudden tariff hikes, price gouging,
    extreme volatility, and missing route data to notify DGCA analysts.
    """

    __tablename__ = "anomaly_alerts"
    __table_args__ = (
        Index("ix_anomaly_alerts_route_date", "origin", "destination", "flight_date"),
        Index("ix_anomaly_alerts_status_severity", "status", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("routes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Optional foreign key to routes table",
    )
    origin: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        index=True,
        doc="Origin airport IATA code",
    )
    destination: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        index=True,
        doc="Destination airport IATA code",
    )
    airline_code: Mapped[str | None] = mapped_column(
        String(3),
        nullable=True,
        index=True,
        doc="Specific airline code if anomaly is carrier-specific",
    )
    alert_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Type: SPIKE, DROP, VOLATILITY, SURGE_PRICING, MISSING_DATA",
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="MEDIUM",
        index=True,
        doc="Severity level: LOW, MEDIUM, HIGH, CRITICAL",
    )
    flight_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
        doc="Date of affected flight",
    )
    booking_window: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        doc="Booking window tag (e.g. T+1, T+7, T+15, T+30)",
    )
    detected_fare: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Anomalous fare observed in INR",
    )
    baseline_fare: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Expected benchmark fare (historical median/mean) in INR",
    )
    z_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Statistical z-score deviation from historical distribution",
    )
    pct_change: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Percentage deviation from baseline fare",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Detailed human-readable explanation of the detected anomaly",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="OPEN",
        index=True,
        doc="Alert lifecycle status: OPEN, ACKNOWLEDGED, RESOLVED, FALSE_POSITIVE",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when alert was resolved or closed",
    )

    # Relationship to Route
    route = relationship("Route", foreign_keys=[route_id], lazy="joined")

    @property
    def route_code(self) -> str:
        return f"{self.origin}-{self.destination}"

    def to_dict(self) -> dict[str, Any]:
        """Convert AnomalyAlert instance to dictionary."""
        return {
            "id": self.id,
            "route_id": self.route_id,
            "origin": self.origin,
            "destination": self.destination,
            "route_code": self.route_code,
            "airline_code": self.airline_code,
            "alert_type": self.alert_type,
            "severity": self.severity,
            "flight_date": self.flight_date.isoformat() if self.flight_date else None,
            "booking_window": self.booking_window,
            "detected_fare": self.detected_fare,
            "baseline_fare": self.baseline_fare,
            "z_score": self.z_score,
            "pct_change": self.pct_change,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": (self.resolved_at.isoformat() if self.resolved_at else None),
        }

    def __repr__(self) -> str:
        return (
            f"<AnomalyAlert id={self.id} {self.origin}->{self.destination} "
            f"type={self.alert_type} sev={self.severity} status={self.status}>"
        )
