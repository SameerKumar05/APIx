"""Index models for route-level and national aggregated airfare price indices."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.session import Base


class RouteDailyIndex(Base):
    """Daily route-level airfare price index and distribution statistics.

    Computed across scraped flight fares for a specific city-pair corridor,
    date, advance booking window, and aggregation method.
    """

    __tablename__ = "route_daily_indices"
    __table_args__ = (
        UniqueConstraint(
            "origin",
            "destination",
            "index_date",
            "booking_window",
            "index_type",
            name="uq_route_daily_index",
        ),
        Index(
            "ix_route_daily_index_lookup",
            "origin",
            "destination",
            "index_date",
            "booking_window",
        ),
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
        doc="Origin airport IATA code (e.g. DEL)",
    )
    destination: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        index=True,
        doc="Destination airport IATA code (e.g. BOM)",
    )
    index_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        doc="Reference observation date",
    )
    booking_window: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        default="COMPOSITE",
        doc="Booking window (T+1, T+7, T+15, T+30, or COMPOSITE)",
    )
    index_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="weighted_median",
        doc="Formula type: weighted_median, laspeyres, fisher, paasche",
    )
    sample_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Count of valid fare quotes contributing to this index",
    )
    median_fare: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Median fare in INR",
    )
    mean_fare: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Arithmetic mean fare in INR",
    )
    min_fare: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Lowest fare observed in INR",
    )
    max_fare: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Highest fare observed in INR",
    )
    percentile_25: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="25th percentile (Q1) fare in INR",
    )
    percentile_75: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="75th percentile (Q3) fare in INR",
    )
    std_dev: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Standard deviation of fares in INR",
    )
    index_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=100.0,
        doc="Normalized price index value relative to base period (base = 100.0)",
    )
    base_period: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default="2026-01-01",
        doc="Base reference period identifier",
    )
    calculation_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        doc="Timestamp when index value was computed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Optional relationship to Route
    route = relationship("Route", foreign_keys=[route_id], lazy="joined")

    @property
    def route_code(self) -> str:
        return f"{self.origin}-{self.destination}"

    def to_dict(self) -> dict[str, Any]:
        """Convert RouteDailyIndex instance to dictionary."""
        return {
            "id": self.id,
            "route_id": self.route_id,
            "origin": self.origin,
            "destination": self.destination,
            "route_code": self.route_code,
            "index_date": self.index_date.isoformat() if self.index_date else None,
            "booking_window": self.booking_window,
            "index_type": self.index_type,
            "sample_size": self.sample_size,
            "median_fare": self.median_fare,
            "mean_fare": self.mean_fare,
            "min_fare": self.min_fare,
            "max_fare": self.max_fare,
            "percentile_25": self.percentile_25,
            "percentile_75": self.percentile_75,
            "std_dev": self.std_dev,
            "index_value": self.index_value,
            "base_period": self.base_period,
            "calculation_timestamp": (
                self.calculation_timestamp.isoformat()
                if self.calculation_timestamp
                else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<RouteDailyIndex {self.origin}->{self.destination} "
            f"date={self.index_date} window={self.booking_window} "
            f"idx={self.index_value:.2f} median={self.median_fare:.1f}>"
        )


class NationalDailyIndex(Base):
    """National composite daily airfare price index.

    Aggregates all monitored domestic routes using DGCA passenger traffic
    weights to construct the national airfare inflation benchmark for CPI augmentation.
    """

    __tablename__ = "national_daily_indices"
    __table_args__ = (
        UniqueConstraint(
            "index_date",
            "booking_window",
            "index_type",
            name="uq_national_daily_index",
        ),
        Index(
            "ix_national_daily_index_lookup",
            "index_date",
            "booking_window",
            "index_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        doc="Reference observation date",
    )
    booking_window: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        default="COMPOSITE",
        doc="Advance booking window (T+1, T+7, T+15, T+30, or COMPOSITE)",
    )
    index_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="weighted_median",
        doc="Formula type: weighted_median, laspeyres, fisher, paasche",
    )
    index_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=100.0,
        doc="National price index value relative to base period (base = 100.0)",
    )
    weighted_median_fare: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="DGCA passenger-weighted median fare across routes in INR",
    )
    weighted_mean_fare: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="DGCA passenger-weighted mean fare across routes in INR",
    )
    total_samples: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Total number of flight quotes aggregated across all routes",
    )
    routes_covered: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of active domestic routes included in calculation",
    )
    inflation_dod_pct: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Day-over-day inflation rate percentage",
    )
    inflation_mom_pct: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Month-over-month inflation rate percentage",
    )
    base_period: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default="2026-01-01",
        doc="Base reference period identifier",
    )
    calculation_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        doc="Timestamp when index value was computed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert NationalDailyIndex instance to dictionary."""
        return {
            "id": self.id,
            "index_date": self.index_date.isoformat() if self.index_date else None,
            "booking_window": self.booking_window,
            "index_type": self.index_type,
            "index_value": self.index_value,
            "weighted_median_fare": self.weighted_median_fare,
            "weighted_mean_fare": self.weighted_mean_fare,
            "total_samples": self.total_samples,
            "routes_covered": self.routes_covered,
            "inflation_dod_pct": self.inflation_dod_pct,
            "inflation_mom_pct": self.inflation_mom_pct,
            "base_period": self.base_period,
            "calculation_timestamp": (
                self.calculation_timestamp.isoformat()
                if self.calculation_timestamp
                else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<NationalDailyIndex date={self.index_date} window={self.booking_window} "
            f"type={self.index_type} idx={self.index_value:.2f} dod={self.inflation_dod_pct:+.2f}%>"
        )
