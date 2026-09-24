"""Route model representing domestic Indian flight corridors with DGCA weighting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class Route(Base):
    """Domestic Indian flight corridor.

    Tracks origin and destination airport IATA codes, flight distance,
    DGCA monthly passenger volume, and normalized basket weight.
    """

    __tablename__ = "routes"
    __table_args__ = (
        UniqueConstraint("origin", "destination", name="uq_routes_origin_destination"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    origin: Mapped[str] = mapped_column(
        String(3), nullable=False, index=True, doc="Origin airport 3-letter IATA code"
    )
    destination: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        index=True,
        doc="Destination airport 3-letter IATA code",
    )
    distance_km: Mapped[float] = mapped_column(
        Float, nullable=False, doc="Great-circle flight distance in kilometers"
    )
    dgca_monthly_pax: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Monthly passenger traffic based on DGCA domestic traffic statistics",
    )
    weight: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Normalized basket weight for CPI index calculation (sums to 1.0)",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        doc="Whether this route is actively scraped and indexed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def route_code(self) -> str:
        """Return directional route code in IATA format e.g. DEL-BOM."""
        return f"{self.origin}-{self.destination}"

    def to_dict(self) -> dict[str, Any]:
        """Convert Route instance to dictionary representation."""
        return {
            "id": self.id,
            "origin": self.origin,
            "destination": self.destination,
            "route_code": self.route_code,
            "distance_km": self.distance_km,
            "dgca_monthly_pax": self.dgca_monthly_pax,
            "weight": self.weight,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<Route id={self.id} {self.origin}->{self.destination} "
            f"weight={self.weight:.4f} active={self.is_active}>"
        )
