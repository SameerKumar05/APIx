"""Econometric models for advanced index computation, MoSPI CPI benchmarking,
route-level elasticity curves, and DGCA statutory tariff violation audits.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class EconometricIndex(Base):
    """Axiomatic price indices (Laspeyres, Paasche, Fisher Ideal) and substitution bias.

    Tracks formula divergence and consumer substitution effects across Indian
    aviation corridors or nationally aggregated flight baskets.
    """

    __tablename__ = "econometric_indices"
    __table_args__ = (
        UniqueConstraint(
            "date",
            "route_code",
            "calculation_method",
            name="uq_econometric_index_date_route_method",
        ),
        Index("ix_econometric_index_route_date", "route_code", "date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        doc="Observation date for index calculation",
    )
    route_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        doc="Corridor code (e.g. DEL-BOM) or 'NATIONAL'",
    )
    laspeyres_index: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Base-period expenditure weighted price index",
    )
    paasche_index: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Current-period volume/traffic weighted price index",
    )
    fisher_ideal_index: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Geometric mean Fisher Ideal index sqrt(Laspeyres * Paasche)",
    )
    substitution_bias: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Substitution bias delta: Laspeyres - Paasche",
    )
    calculation_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="chain_weighted",
        index=True,
        doc="Weighting methodology: chain_weighted, fixed_base, rolling_window",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert EconometricIndex instance to dictionary representation."""
        return {
            "id": self.id,
            "date": self.date.isoformat() if self.date else None,
            "route_code": self.route_code,
            "laspeyres_index": self.laspeyres_index,
            "paasche_index": self.paasche_index,
            "fisher_ideal_index": self.fisher_ideal_index,
            "substitution_bias": self.substitution_bias,
            "calculation_method": self.calculation_method,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<EconometricIndex id={self.id} route={self.route_code} date={self.date} "
            f"L={self.laspeyres_index:.2f} P={self.paasche_index:.2f} F={self.fisher_ideal_index:.2f}>"
        )


class MospiCpiSeries(Base):
    """Official Ministry of Statistics and Programme Implementation (MoSPI) CPI benchmarks.

    Tracks monthly official Consumer Price Index releases for transport & communication
    and airfare sub-indices for divergence analytics against APIx real-time indices.
    """

    __tablename__ = "mospi_cpi_series"
    __table_args__ = (
        Index("ix_mospi_cpi_series_year_month", "year_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year_month: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
        unique=True,
        doc="MoSPI reporting period in format YYYY-MM (e.g. 2026-03)",
    )
    cpi_transport_index: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="MoSPI Consumer Price Index for Transport and Communication (Base 2012=100)",
    )
    airfare_sub_index: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Official MoSPI sub-index specifically tracking domestic airfare component",
    )
    headline_cpi: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="All-India Headline Consumer Price Index Combined (Base 2012=100)",
    )
    published_at: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        doc="Official MoSPI press release publication date",
    )
    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="MoSPI",
        doc="Authoritative publishing agency or statistical office",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert MospiCpiSeries instance to dictionary representation."""
        return {
            "id": self.id,
            "year_month": self.year_month,
            "cpi_transport_index": self.cpi_transport_index,
            "airfare_sub_index": self.airfare_sub_index,
            "headline_cpi": self.headline_cpi,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<MospiCpiSeries period={self.year_month} transport={self.cpi_transport_index:.2f} "
            f"airfare={self.airfare_sub_index:.2f} headline={self.headline_cpi:.2f}>"
        )


class RouteElasticity(Base):
    """Route-level advance booking price elasticity curves and lead-time decay metrics.

    Measures booking window price responsiveness between T+1, T+7, T+15, and T+30
    along with exponential decay coefficients and curve fit confidence scores.
    """

    __tablename__ = "route_elasticity"
    __table_args__ = (
        UniqueConstraint(
            "route_code",
            "calculation_date",
            name="uq_route_elasticity_route_date",
        ),
        Index("ix_route_elasticity_lookup", "route_code", "calculation_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        doc="Directional route corridor (e.g. DEL-BOM)",
    )
    calculation_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        doc="Date the elasticity curve was evaluated",
    )
    t1_t7_elasticity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Price ratio / elasticity gradient between T+1 (urgent) and T+7 windows",
    )
    t7_t15_elasticity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Price ratio / elasticity gradient between T+7 and T+15 windows",
    )
    t15_t30_elasticity: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Price ratio / elasticity gradient between T+15 and T+30 (advance) windows",
    )
    avg_lead_time_decay: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Exponential rate parameter lambda for fare decay over days-to-departure",
    )
    confidence_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        doc="Statistical R-squared or confidence metric (0.0 to 1.0)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert RouteElasticity instance to dictionary representation."""
        return {
            "id": self.id,
            "route_code": self.route_code,
            "calculation_date": (
                self.calculation_date.isoformat() if self.calculation_date else None
            ),
            "t1_t7_elasticity": self.t1_t7_elasticity,
            "t7_t15_elasticity": self.t7_t15_elasticity,
            "t15_t30_elasticity": self.t15_t30_elasticity,
            "avg_lead_time_decay": self.avg_lead_time_decay,
            "confidence_score": self.confidence_score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<RouteElasticity route={self.route_code} date={self.calculation_date} "
            f"decay={self.avg_lead_time_decay:.4f} conf={self.confidence_score:.2f}>"
        )


class DgcaViolation(Base):
    """Statutory and regulatory tariff violations under DGCA Air Transport Circulars.

    Records automated detections of predatory pricing, unconscionable fare surges,
    breaches of statutory corridor caps, and asymmetric route tariff gouging.
    """

    __tablename__ = "dgca_violations"
    __table_args__ = (
        Index("ix_dgca_violations_route_date", "route_code", "flight_date"),
        Index("ix_dgca_violations_airline_status", "airline_code", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        doc="Corridor code e.g. DEL-BOM",
    )
    airline_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
        doc="IATA airline operating carrier code e.g. 6E, AI",
    )
    flight_number: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        doc="Scheduled flight number e.g. 6E-204",
    )
    flight_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        doc="Scheduled departure flight date",
    )
    window: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        doc="Booking advance window tag (e.g. T+1, T+7, T+15, T+30)",
    )
    fare_inr: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Observed ticket fare in INR",
    )
    median_baseline_fare: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Benchmark median baseline fare for route and window in INR",
    )
    surge_multiple: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Multiplier above baseline fare (fare_inr / median_baseline_fare)",
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        doc="Violation severity: WARNING, CRITICAL, SEVERE",
    )
    violation_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Statutory breach code (e.g. DGCA-SURGE-3X, DGCA-CAP-BREACH, PREDATORY-PRICING)",
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
        doc="Timestamp when algorithmic audit flagged the violation",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="OPEN",
        index=True,
        doc="Audit review status: OPEN, UNDER_REVIEW, CONFIRMED, DISMISSED, REPORTED",
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert DgcaViolation instance to dictionary representation."""
        return {
            "id": self.id,
            "route_code": self.route_code,
            "airline_code": self.airline_code,
            "flight_number": self.flight_number,
            "flight_date": self.flight_date.isoformat() if self.flight_date else None,
            "window": self.window,
            "fare_inr": self.fare_inr,
            "median_baseline_fare": self.median_baseline_fare,
            "surge_multiple": self.surge_multiple,
            "severity": self.severity,
            "violation_code": self.violation_code,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "status": self.status,
        }

    def __repr__(self) -> str:
        return (
            f"<DgcaViolation id={self.id} {self.airline_code}-{self.flight_number} "
            f"route={self.route_code} surge={self.surge_multiple:.2f}x sev={self.severity} status={self.status}>"
        )


class DgcaTrafficWeight(Base):
    """Historical monthly city-pair passenger traffic volume and national share weights.

    Provides official DGCA monthly statistics used to dynamically re-weight
    Paasche and Fisher price indices and calibrate basket weights.
    """

    __tablename__ = "dgca_traffic_weights"
    __table_args__ = (
        UniqueConstraint(
            "route_code",
            "year_month",
            name="uq_dgca_traffic_weights_route_period",
        ),
        Index("ix_dgca_traffic_weights_period", "year_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        doc="Corridor code e.g. DEL-BOM",
    )
    year_month: Mapped[str] = mapped_column(
        String(7),
        nullable=False,
        doc="Monthly period in format YYYY-MM (e.g. 2026-03)",
    )
    pax_volume: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Monthly passenger traffic volume recorded by DGCA",
    )
    share_weight: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Corridor share of national domestic passenger traffic (0.0 to 1.0)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert DgcaTrafficWeight instance to dictionary representation."""
        return {
            "id": self.id,
            "route_code": self.route_code,
            "year_month": self.year_month,
            "pax_volume": self.pax_volume,
            "share_weight": self.share_weight,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<DgcaTrafficWeight route={self.route_code} period={self.year_month} "
            f"pax={self.pax_volume} weight={self.share_weight:.4f}>"
        )
