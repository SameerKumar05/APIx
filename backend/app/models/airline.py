"""Airline model representing scheduled commercial passenger carriers in India."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class Airline(Base):
    """Indian domestic passenger airline carrier.

    Tracks airline IATA code, legal name, DGCA domestic market share percentage,
    and operational status.
    """

    __tablename__ = "airlines"

    code: Mapped[str] = mapped_column(
        String(3),
        primary_key=True,
        doc="2 or 3-letter IATA airline code (e.g. 6E, AI, IX, QP, SG)",
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Full commercial or brand name of the airline",
    )
    market_share_pct: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="DGCA domestic market share percentage (e.g. 62.0 for 6E)",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        doc="Whether the airline is currently monitored",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert Airline instance to dictionary representation."""
        return {
            "code": self.code,
            "name": self.name,
            "market_share_pct": self.market_share_pct,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<Airline code={self.code} name='{self.name}' share={self.market_share_pct}%>"
