"""Raw fare model representing individual scraped flight ticket quotes."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class RawFare(Base):
    """Individual scraped flight ticket observation.

    Stores pricing, routing, carrier, timing, and metadata for airfare quotes
    scraped across airline portals and OTAs at various advance booking windows.
    Includes a unique hash for automated deduplication.
    """

    __tablename__ = "raw_fares"
    __table_args__ = (
        Index("ix_raw_fares_route_date", "origin", "destination", "flight_date"),
        Index("ix_raw_fares_date_window", "flight_date", "booking_window"),
        Index("ix_raw_fares_batch_airline", "batch_id", "airline_code"),
        Index("ix_raw_fares_scraped_at", "scraped_at"),
        # Optimized composite indexes for fast time-series queries and index calculations
        Index(
            "ix_raw_fares_route_window_date",
            "origin",
            "destination",
            "booking_window",
            "flight_date",
        ),
        Index(
            "ix_raw_fares_route_window_scraped",
            "origin",
            "destination",
            "booking_window",
            "scraped_at",
        ),
        Index("ix_raw_fares_retention_prune", "scraped_at", "flight_date"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    batch_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Ingestion batch or scraping run identifier",
    )
    origin: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        index=True,
        doc="Origin airport 3-letter IATA code (e.g. DEL)",
    )
    destination: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        index=True,
        doc="Destination airport 3-letter IATA code (e.g. BOM)",
    )
    flight_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        doc="Date of flight departure",
    )
    booking_window: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        doc="Advance booking window tag (e.g. T+1, T+7, T+15, T+30)",
    )
    airline_code: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        index=True,
        doc="2 or 3-letter IATA airline code (e.g. 6E, AI, IX, QP, SG)",
    )
    flight_number: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="Flight designator number (e.g. 6E-2015, AI-805)",
    )
    departure_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Scheduled flight departure timestamp",
    )
    arrival_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Scheduled flight arrival timestamp",
    )
    duration_minutes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="Flight duration in minutes",
    )
    stops: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of intermediate stops (0 for non-stop direct flights)",
    )
    fare_class: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="Economy",
        doc="Cabin fare class (Economy, Premium Economy, Business)",
    )
    base_fare: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Base ticket fare before taxes and surcharges in INR",
    )
    taxes_and_fees: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Fuel surcharge, passenger service fee, and GST in INR",
    )
    total_fare: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Final all-inclusive passenger fare in INR",
    )
    source_platform: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Portal where quote was scraped (e.g. makemytrip, easemytrip, ixigo, portal_direct)",
    )
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        doc="Timestamp when price quote was captured",
    )
    hash_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        doc="Cryptographic dedup hash (source + flight_no + departure + window + date)",
    )
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="True if generated by synthetic simulator, False if scraped from real portal",
    )

    # Aliases and compatibility properties for pipeline integration
    @property
    def origin_iata(self) -> str:
        return self.origin

    @origin_iata.setter
    def origin_iata(self, value: str) -> None:
        self.origin = value

    @property
    def destination_iata(self) -> str:
        return self.destination

    @destination_iata.setter
    def destination_iata(self, value: str) -> None:
        self.destination = value

    @property
    def fare_inr(self) -> float:
        return self.total_fare

    @fare_inr.setter
    def fare_inr(self, value: float) -> None:
        self.total_fare = value

    @property
    def cabin_class(self) -> str:
        return self.fare_class

    @cabin_class.setter
    def cabin_class(self, value: str) -> None:
        self.fare_class = value

    @property
    def dedup_hash(self) -> str:
        return self.hash_id

    @dedup_hash.setter
    def dedup_hash(self, value: str) -> None:
        self.hash_id = value

    @property
    def search_timestamp(self) -> datetime:
        return self.scraped_at

    @search_timestamp.setter
    def search_timestamp(self, value: datetime) -> None:
        self.scraped_at = value

    def to_dict(self) -> dict[str, Any]:
        """Convert RawFare instance to dictionary."""
        return {
            "id": self.id,
            "batch_id": self.batch_id,
            "origin": self.origin,
            "destination": self.destination,
            "flight_date": self.flight_date.isoformat() if self.flight_date else None,
            "booking_window": self.booking_window,
            "airline_code": self.airline_code,
            "flight_number": self.flight_number,
            "departure_time": (
                self.departure_time.isoformat() if self.departure_time else None
            ),
            "arrival_time": (
                self.arrival_time.isoformat() if self.arrival_time else None
            ),
            "duration_minutes": self.duration_minutes,
            "stops": self.stops,
            "fare_class": self.fare_class,
            "base_fare": self.base_fare,
            "taxes_and_fees": self.taxes_and_fees,
            "total_fare": self.total_fare,
            "source_platform": self.source_platform,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
            "hash_id": self.hash_id,
            "is_synthetic": self.is_synthetic,
        }

    def __repr__(self) -> str:
        return (
            f"<RawFare id={self.id} {self.origin}->{self.destination} "
            f"{self.airline_code}{self.flight_number} window={self.booking_window} "
            f"fare=INR {self.total_fare:.2f}>"
        )
