"""Repository for econometric indices, MoSPI CPI benchmarking, route elasticity curves,
and DGCA statutory tariff violation audits.

Provides high-performance persistence, idempotent upserting, analytical queries,
and data aggregation helpers for the APIx econometric and regulatory engine.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.app.models.econometrics import (
    DgcaTrafficWeight,
    DgcaViolation,
    EconometricIndex,
    MospiCpiSeries,
    RouteElasticity,
)
from backend.app.models.route import Route

logger = logging.getLogger("backend.app.db.econometrics_repo")


# ============================================================================
# Helpers
# ============================================================================


def _parse_date(val: date | datetime | str | None) -> date | None:
    """Parse date or ISO string to standard date object."""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        clean_str = val.strip().split("T")[0]
        return date.fromisoformat(clean_str)
    return None


def _parse_datetime(val: datetime | date | str | None) -> datetime | None:
    """Parse datetime or ISO string to timezone-aware UTC datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo is not None else val.replace(tzinfo=UTC)
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time(), tzinfo=UTC)
    if isinstance(val, str):
        clean_str = val.strip()
        dt = datetime.fromisoformat(clean_str)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    return None


# ============================================================================
# 1. Econometric Index Repository Operations
# ============================================================================


def upsert_econometric_index(
    db: Session,
    date: date | str,
    route_code: str,
    laspeyres_index: float,
    paasche_index: float,
    fisher_ideal_index: float,
    substitution_bias: float | None = None,
    calculation_method: str = "chain_weighted",
    commit: bool = True,
) -> EconometricIndex:
    """Upsert an axiomatic econometric price index record.

    If a record with matching (date, route_code, calculation_method) already exists,
    it is updated in-place; otherwise a new record is created.
    """
    obs_date = _parse_date(date)
    if obs_date is None:
        raise ValueError("Invalid date provided for EconometricIndex")

    clean_route = route_code.strip().upper()
    sub_bias = (
        substitution_bias
        if substitution_bias is not None
        else round(laspeyres_index - paasche_index, 6)
    )

    stmt = select(EconometricIndex).where(
        EconometricIndex.date == obs_date,
        EconometricIndex.route_code == clean_route,
        EconometricIndex.calculation_method == calculation_method,
    )
    existing = db.execute(stmt).scalar_one_or_none()

    if existing:
        existing.laspeyres_index = float(laspeyres_index)
        existing.paasche_index = float(paasche_index)
        existing.fisher_ideal_index = float(fisher_ideal_index)
        existing.substitution_bias = float(sub_bias)
        record = existing
    else:
        record = EconometricIndex(
            date=obs_date,
            route_code=clean_route,
            laspeyres_index=float(laspeyres_index),
            paasche_index=float(paasche_index),
            fisher_ideal_index=float(fisher_ideal_index),
            substitution_bias=float(sub_bias),
            calculation_method=calculation_method,
        )
        db.add(record)

    if commit:
        try:
            db.commit()
            db.refresh(record)
        except Exception:
            db.rollback()
            raise
    else:
        db.flush()

    return record


def bulk_upsert_econometric_indices(
    db: Session,
    records: list[dict[str, Any] | EconometricIndex],
    commit: bool = True,
) -> int:
    """Bulk upsert econometric index records.

    Returns the count of persisted or updated records.
    """
    count = 0
    for rec in records:
        if isinstance(rec, EconometricIndex):
            d = rec.date
            rc = rec.route_code
            l_idx = rec.laspeyres_index
            p_idx = rec.paasche_index
            f_idx = rec.fisher_ideal_index
            sb: float | None = rec.substitution_bias
            cm = rec.calculation_method
        elif isinstance(rec, dict):
            d = rec["date"]
            rc = rec["route_code"]
            l_idx = rec["laspeyres_index"]
            p_idx = rec["paasche_index"]
            f_idx = rec["fisher_ideal_index"]
            sb = rec.get("substitution_bias")
            cm = rec.get("calculation_method", "chain_weighted")
        else:
            continue

        upsert_econometric_index(
            db=db,
            date=d,
            route_code=rc,
            laspeyres_index=l_idx,
            paasche_index=p_idx,
            fisher_ideal_index=f_idx,
            substitution_bias=sb,
            calculation_method=cm,
            commit=False,
        )
        count += 1

    if commit and count > 0:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return count


def get_econometric_indices(
    db: Session,
    route_code: str | None = None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    calculation_method: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[EconometricIndex]:
    """Retrieve econometric price index time-series filtered by corridor, dates, and method."""
    stmt = select(EconometricIndex)

    if route_code:
        stmt = stmt.where(EconometricIndex.route_code == route_code.strip().upper())
    if start_date:
        s_date = _parse_date(start_date)
        if s_date:
            stmt = stmt.where(EconometricIndex.date >= s_date)
    if end_date:
        e_date = _parse_date(end_date)
        if e_date:
            stmt = stmt.where(EconometricIndex.date <= e_date)
    if calculation_method:
        stmt = stmt.where(EconometricIndex.calculation_method == calculation_method)

    stmt = stmt.order_by(desc(EconometricIndex.date)).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def get_latest_econometric_index(
    db: Session,
    route_code: str = "NATIONAL",
    calculation_method: str | None = None,
) -> EconometricIndex | None:
    """Retrieve the most recent econometric index for a corridor or national aggregate."""
    stmt = select(EconometricIndex).where(
        EconometricIndex.route_code == route_code.strip().upper()
    )
    if calculation_method:
        stmt = stmt.where(EconometricIndex.calculation_method == calculation_method)

    stmt = stmt.order_by(desc(EconometricIndex.date)).limit(1)
    return db.execute(stmt).scalar_one_or_none()


def get_index_comparison_summary(
    db: Session,
    route_code: str = "NATIONAL",
    days: int = 30,
) -> dict[str, Any]:
    """Calculate summary statistical aggregations for Laspeyres, Paasche, and Fisher indices."""
    clean_route = route_code.strip().upper()
    cutoff_date = date.today() - timedelta(days=days)

    stmt = select(
        func.count(EconometricIndex.id).label("total_records"),
        func.avg(EconometricIndex.laspeyres_index).label("avg_laspeyres"),
        func.avg(EconometricIndex.paasche_index).label("avg_paasche"),
        func.avg(EconometricIndex.fisher_ideal_index).label("avg_fisher"),
        func.avg(EconometricIndex.substitution_bias).label("avg_substitution_bias"),
        func.max(EconometricIndex.substitution_bias).label("max_substitution_bias"),
        func.min(EconometricIndex.substitution_bias).label("min_substitution_bias"),
    ).where(
        EconometricIndex.route_code == clean_route,
        EconometricIndex.date >= cutoff_date,
    )
    res = db.execute(stmt).one()

    return {
        "route_code": clean_route,
        "days": days,
        "total_records": res.total_records or 0,
        "avg_laspeyres": (
            round(res.avg_laspeyres, 4) if res.avg_laspeyres is not None else None
        ),
        "avg_paasche": (
            round(res.avg_paasche, 4) if res.avg_paasche is not None else None
        ),
        "avg_fisher": round(res.avg_fisher, 4) if res.avg_fisher is not None else None,
        "avg_substitution_bias": (
            round(res.avg_substitution_bias, 4)
            if res.avg_substitution_bias is not None
            else None
        ),
        "max_substitution_bias": (
            round(res.max_substitution_bias, 4)
            if res.max_substitution_bias is not None
            else None
        ),
        "min_substitution_bias": (
            round(res.min_substitution_bias, 4)
            if res.min_substitution_bias is not None
            else None
        ),
    }


# ============================================================================
# 2. MoSPI CPI Series Repository Operations
# ============================================================================


def upsert_mospi_cpi_series(
    db: Session,
    year_month: str,
    cpi_transport_index: float,
    airfare_sub_index: float,
    headline_cpi: float,
    published_at: date | str,
    source: str = "MoSPI",
    commit: bool = True,
) -> MospiCpiSeries:
    """Upsert an official MoSPI monthly CPI benchmark series record."""
    clean_ym = year_month.strip()
    pub_date = _parse_date(published_at)
    if pub_date is None:
        raise ValueError("Invalid published_at date for MospiCpiSeries")

    stmt = select(MospiCpiSeries).where(MospiCpiSeries.year_month == clean_ym)
    existing = db.execute(stmt).scalar_one_or_none()

    if existing:
        existing.cpi_transport_index = float(cpi_transport_index)
        existing.airfare_sub_index = float(airfare_sub_index)
        existing.headline_cpi = float(headline_cpi)
        existing.published_at = pub_date
        existing.source = source
        record = existing
    else:
        record = MospiCpiSeries(
            year_month=clean_ym,
            cpi_transport_index=float(cpi_transport_index),
            airfare_sub_index=float(airfare_sub_index),
            headline_cpi=float(headline_cpi),
            published_at=pub_date,
            source=source,
        )
        db.add(record)

    if commit:
        try:
            db.commit()
            db.refresh(record)
        except Exception:
            db.rollback()
            raise
    else:
        db.flush()

    return record


def bulk_upsert_mospi_cpi(
    db: Session,
    records: list[dict[str, Any]],
    commit: bool = True,
) -> int:
    """Bulk upsert MoSPI CPI series records."""
    count = 0
    for rec in records:
        upsert_mospi_cpi_series(
            db=db,
            year_month=rec["year_month"],
            cpi_transport_index=rec["cpi_transport_index"],
            airfare_sub_index=rec["airfare_sub_index"],
            headline_cpi=rec["headline_cpi"],
            published_at=rec["published_at"],
            source=rec.get("source", "MoSPI"),
            commit=False,
        )
        count += 1

    if commit and count > 0:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return count


def get_mospi_cpi_series(
    db: Session,
    start_period: str | None = None,
    end_period: str | None = None,
    limit: int = 100,
) -> list[MospiCpiSeries]:
    """Query official MoSPI CPI benchmark records ordered newest first."""
    stmt = select(MospiCpiSeries)
    if start_period:
        stmt = stmt.where(MospiCpiSeries.year_month >= start_period.strip())
    if end_period:
        stmt = stmt.where(MospiCpiSeries.year_month <= end_period.strip())

    stmt = stmt.order_by(desc(MospiCpiSeries.year_month)).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_latest_mospi_cpi(db: Session) -> MospiCpiSeries | None:
    """Retrieve the most recent published MoSPI CPI benchmark record."""
    stmt = select(MospiCpiSeries).order_by(desc(MospiCpiSeries.year_month)).limit(1)
    return db.execute(stmt).scalar_one_or_none()


def get_cpi_divergence_analysis(
    db: Session,
    months: int = 12,
) -> list[dict[str, Any]]:
    """Compute gap analytics between real-time APIx airfare indices and official MoSPI benchmarks.

    Compares monthly average APIx Fisher Ideal Index against MoSPI official airfare
    sub-index and transport headline CPI to measure index leading indicators and divergence.
    """
    mospi_records = get_mospi_cpi_series(db=db, limit=months)
    if not mospi_records:
        return []

    results: list[dict[str, Any]] = []
    for m in mospi_records:
        # Determine date bounds for this year_month
        try:
            parts = m.year_month.split("-")
            yr, mo = int(parts[0]), int(parts[1])
            m_start = date(yr, mo, 1)
            if mo == 12:
                m_end = date(yr + 1, 1, 1) - timedelta(days=1)
            else:
                m_end = date(yr, mo + 1, 1) - timedelta(days=1)
        except Exception:
            continue

        # Aggregate APIx National Fisher Index over this period
        stmt = select(
            func.avg(EconometricIndex.fisher_ideal_index).label("avg_fisher"),
            func.avg(EconometricIndex.laspeyres_index).label("avg_laspeyres"),
            func.count(EconometricIndex.id).label("sample_days"),
        ).where(
            EconometricIndex.route_code == "NATIONAL",
            EconometricIndex.date >= m_start,
            EconometricIndex.date <= m_end,
        )
        agg = db.execute(stmt).one()

        apix_fisher = round(agg.avg_fisher, 2) if agg.avg_fisher is not None else None
        apix_laspeyres = (
            round(agg.avg_laspeyres, 2) if agg.avg_laspeyres is not None else None
        )

        gap_airfare_pct = None
        if apix_fisher is not None and m.airfare_sub_index > 0:
            gap_airfare_pct = round(
                ((apix_fisher - m.airfare_sub_index) / m.airfare_sub_index) * 100.0, 2
            )

        gap_transport_pct = None
        if apix_fisher is not None and m.cpi_transport_index > 0:
            gap_transport_pct = round(
                ((apix_fisher - m.cpi_transport_index) / m.cpi_transport_index) * 100.0,
                2,
            )

        results.append(
            {
                "year_month": m.year_month,
                "mospi_headline_cpi": m.headline_cpi,
                "mospi_transport_cpi": m.cpi_transport_index,
                "mospi_airfare_sub_index": m.airfare_sub_index,
                "apix_national_fisher": apix_fisher,
                "apix_national_laspeyres": apix_laspeyres,
                "sample_days": agg.sample_days or 0,
                "divergence_airfare_pct": gap_airfare_pct,
                "divergence_transport_pct": gap_transport_pct,
                "published_at": m.published_at.isoformat() if m.published_at else None,
                "source": m.source,
            }
        )

    return results


# ============================================================================
# 3. Route Elasticity Repository Operations
# ============================================================================


def upsert_route_elasticity(
    db: Session,
    route_code: str,
    calculation_date: date | str,
    t1_t7_elasticity: float,
    t7_t15_elasticity: float,
    t15_t30_elasticity: float,
    avg_lead_time_decay: float,
    confidence_score: float = 1.0,
    commit: bool = True,
) -> RouteElasticity:
    """Upsert a route-level advance booking price elasticity curve record."""
    clean_route = route_code.strip().upper()
    calc_date = _parse_date(calculation_date)
    if calc_date is None:
        raise ValueError("Invalid calculation_date provided for RouteElasticity")

    stmt = select(RouteElasticity).where(
        RouteElasticity.route_code == clean_route,
        RouteElasticity.calculation_date == calc_date,
    )
    existing = db.execute(stmt).scalar_one_or_none()

    if existing:
        existing.t1_t7_elasticity = float(t1_t7_elasticity)
        existing.t7_t15_elasticity = float(t7_t15_elasticity)
        existing.t15_t30_elasticity = float(t15_t30_elasticity)
        existing.avg_lead_time_decay = float(avg_lead_time_decay)
        existing.confidence_score = float(confidence_score)
        record = existing
    else:
        record = RouteElasticity(
            route_code=clean_route,
            calculation_date=calc_date,
            t1_t7_elasticity=float(t1_t7_elasticity),
            t7_t15_elasticity=float(t7_t15_elasticity),
            t15_t30_elasticity=float(t15_t30_elasticity),
            avg_lead_time_decay=float(avg_lead_time_decay),
            confidence_score=float(confidence_score),
        )
        db.add(record)

    if commit:
        try:
            db.commit()
            db.refresh(record)
        except Exception:
            db.rollback()
            raise
    else:
        db.flush()

    return record


def bulk_upsert_route_elasticities(
    db: Session,
    records: list[dict[str, Any]],
    commit: bool = True,
) -> int:
    """Bulk upsert route elasticity curve records."""
    count = 0
    for rec in records:
        upsert_route_elasticity(
            db=db,
            route_code=rec["route_code"],
            calculation_date=rec["calculation_date"],
            t1_t7_elasticity=rec["t1_t7_elasticity"],
            t7_t15_elasticity=rec["t7_t15_elasticity"],
            t15_t30_elasticity=rec["t15_t30_elasticity"],
            avg_lead_time_decay=rec["avg_lead_time_decay"],
            confidence_score=rec.get("confidence_score", 1.0),
            commit=False,
        )
        count += 1

    if commit and count > 0:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return count


def get_route_elasticities(
    db: Session,
    route_code: str | None = None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    min_confidence: float | None = None,
    limit: int = 100,
) -> list[RouteElasticity]:
    """Retrieve route price elasticity records filtered by route, date range, and confidence."""
    stmt = select(RouteElasticity)

    if route_code:
        stmt = stmt.where(RouteElasticity.route_code == route_code.strip().upper())
    if start_date:
        s_date = _parse_date(start_date)
        if s_date:
            stmt = stmt.where(RouteElasticity.calculation_date >= s_date)
    if end_date:
        e_date = _parse_date(end_date)
        if e_date:
            stmt = stmt.where(RouteElasticity.calculation_date <= e_date)
    if min_confidence is not None:
        stmt = stmt.where(RouteElasticity.confidence_score >= float(min_confidence))

    stmt = stmt.order_by(desc(RouteElasticity.calculation_date)).limit(limit)
    return list(db.execute(stmt).scalars().all())


def get_latest_route_elasticity(
    db: Session,
    route_code: str,
) -> RouteElasticity | None:
    """Retrieve the latest elasticity profile for a specific flight corridor."""
    stmt = (
        select(RouteElasticity)
        .where(RouteElasticity.route_code == route_code.strip().upper())
        .order_by(desc(RouteElasticity.calculation_date))
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def get_network_elasticity_summary(
    db: Session,
    target_date: date | str | None = None,
) -> dict[str, Any]:
    """Aggregate network-wide advance booking elasticity metrics across all monitored corridors."""
    stmt = select(
        func.count(RouteElasticity.id).label("corridors_analyzed"),
        func.avg(RouteElasticity.t1_t7_elasticity).label("avg_t1_t7"),
        func.avg(RouteElasticity.t7_t15_elasticity).label("avg_t7_t15"),
        func.avg(RouteElasticity.t15_t30_elasticity).label("avg_t15_t30"),
        func.avg(RouteElasticity.avg_lead_time_decay).label("avg_decay"),
        func.avg(RouteElasticity.confidence_score).label("avg_confidence"),
    )

    t_date = _parse_date(target_date)
    if t_date:
        stmt = stmt.where(RouteElasticity.calculation_date == t_date)

    res = db.execute(stmt).one()

    return {
        "target_date": t_date.isoformat() if t_date else None,
        "corridors_analyzed": res.corridors_analyzed or 0,
        "avg_t1_t7_elasticity": (
            round(res.avg_t1_t7, 4) if res.avg_t1_t7 is not None else None
        ),
        "avg_t7_t15_elasticity": (
            round(res.avg_t7_t15, 4) if res.avg_t7_t15 is not None else None
        ),
        "avg_t15_t30_elasticity": (
            round(res.avg_t15_t30, 4) if res.avg_t15_t30 is not None else None
        ),
        "avg_decay_rate": (
            round(res.avg_decay, 6) if res.avg_decay is not None else None
        ),
        "avg_confidence": (
            round(res.avg_confidence, 4) if res.avg_confidence is not None else None
        ),
    }


# ============================================================================
# 4. DGCA Tariff Violation Audit Repository Operations
# ============================================================================


def record_dgca_violation(
    db: Session,
    route_code: str,
    airline_code: str,
    flight_number: str,
    flight_date: date | str,
    window: str,
    fare_inr: float,
    median_baseline_fare: float,
    surge_multiple: float | None = None,
    severity: str = "WARNING",
    violation_code: str = "DGCA-SURGE-3X",
    detected_at: datetime | str | None = None,
    status: str = "OPEN",
    commit: bool = True,
) -> DgcaViolation:
    """Record an individual DGCA statutory tariff violation event."""
    f_date = _parse_date(flight_date)
    if f_date is None:
        raise ValueError("Invalid flight_date provided for DgcaViolation")

    d_at = _parse_datetime(detected_at) or datetime.now(UTC)

    calc_surge = (
        surge_multiple
        if surge_multiple is not None
        else (
            round(fare_inr / median_baseline_fare, 2)
            if median_baseline_fare > 0
            else 1.0
        )
    )

    record = DgcaViolation(
        route_code=route_code.strip().upper(),
        airline_code=airline_code.strip().upper(),
        flight_number=flight_number.strip().upper(),
        flight_date=f_date,
        window=window.strip().upper(),
        fare_inr=float(fare_inr),
        median_baseline_fare=float(median_baseline_fare),
        surge_multiple=float(calc_surge),
        severity=severity.strip().upper(),
        violation_code=violation_code.strip().upper(),
        detected_at=d_at,
        status=status.strip().upper(),
    )
    db.add(record)

    if commit:
        try:
            db.commit()
            db.refresh(record)
        except Exception:
            db.rollback()
            raise
    else:
        db.flush()

    return record


def bulk_record_dgca_violations(
    db: Session,
    records: list[dict[str, Any]],
    commit: bool = True,
) -> int:
    """Bulk record multiple DGCA violation events."""
    count = 0
    for rec in records:
        record_dgca_violation(
            db=db,
            route_code=rec["route_code"],
            airline_code=rec["airline_code"],
            flight_number=rec["flight_number"],
            flight_date=rec["flight_date"],
            window=rec["window"],
            fare_inr=rec["fare_inr"],
            median_baseline_fare=rec["median_baseline_fare"],
            surge_multiple=rec.get("surge_multiple"),
            severity=rec.get("severity", "WARNING"),
            violation_code=rec.get("violation_code", "DGCA-SURGE-3X"),
            detected_at=rec.get("detected_at"),
            status=rec.get("status", "OPEN"),
            commit=False,
        )
        count += 1

    if commit and count > 0:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return count


def get_dgca_violations(
    db: Session,
    route_code: str | None = None,
    airline_code: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    min_surge: float | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[DgcaViolation]:
    """Query DGCA tariff violation audit logs with multi-parameter filtering and pagination."""
    stmt = select(DgcaViolation)

    if route_code:
        stmt = stmt.where(DgcaViolation.route_code == route_code.strip().upper())
    if airline_code:
        stmt = stmt.where(DgcaViolation.airline_code == airline_code.strip().upper())
    if severity:
        stmt = stmt.where(DgcaViolation.severity == severity.strip().upper())
    if status:
        stmt = stmt.where(DgcaViolation.status == status.strip().upper())
    if start_date:
        s_date = _parse_date(start_date)
        if s_date:
            stmt = stmt.where(DgcaViolation.flight_date >= s_date)
    if end_date:
        e_date = _parse_date(end_date)
        if e_date:
            stmt = stmt.where(DgcaViolation.flight_date <= e_date)
    if min_surge is not None:
        stmt = stmt.where(DgcaViolation.surge_multiple >= float(min_surge))

    stmt = stmt.order_by(desc(DgcaViolation.detected_at)).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def update_dgca_violation_status(
    db: Session,
    violation_id: int,
    status: str,
    commit: bool = True,
) -> DgcaViolation | None:
    """Update regulatory review status of a violation (e.g. UNDER_REVIEW, CONFIRMED, DISMISSED)."""
    stmt = select(DgcaViolation).where(DgcaViolation.id == violation_id)
    record = db.execute(stmt).scalar_one_or_none()
    if record is None:
        return None

    record.status = status.strip().upper()
    if commit:
        try:
            db.commit()
            db.refresh(record)
        except Exception:
            db.rollback()
            raise
    else:
        db.flush()

    return record


def get_dgca_violations_summary(
    db: Session,
    days: int = 30,
) -> dict[str, Any]:
    """Generate regulatory oversight audit summary across airlines, severities, and corridors."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    total_stmt = select(
        func.count(DgcaViolation.id).label("total_violations"),
        func.avg(DgcaViolation.surge_multiple).label("avg_surge_multiple"),
        func.max(DgcaViolation.surge_multiple).label("max_surge_multiple"),
    ).where(DgcaViolation.detected_at >= cutoff)
    totals = db.execute(total_stmt).one()

    # Breakdown by severity
    sev_stmt = (
        select(DgcaViolation.severity, func.count(DgcaViolation.id))
        .where(DgcaViolation.detected_at >= cutoff)
        .group_by(DgcaViolation.severity)
    )
    severity_counts: dict[str, int] = {
        row[0]: row[1] for row in db.execute(sev_stmt).all()
    }

    # Breakdown by airline
    airline_stmt = (
        select(DgcaViolation.airline_code, func.count(DgcaViolation.id))
        .where(DgcaViolation.detected_at >= cutoff)
        .group_by(DgcaViolation.airline_code)
    )
    airline_counts: dict[str, int] = {
        row[0]: row[1] for row in db.execute(airline_stmt).all()
    }

    # Breakdown by status
    status_stmt = (
        select(DgcaViolation.status, func.count(DgcaViolation.id))
        .where(DgcaViolation.detected_at >= cutoff)
        .group_by(DgcaViolation.status)
    )
    status_counts: dict[str, int] = {
        row[0]: row[1] for row in db.execute(status_stmt).all()
    }

    return {
        "period_days": days,
        "total_violations": totals.total_violations or 0,
        "avg_surge_multiple": (
            round(totals.avg_surge_multiple, 2)
            if totals.avg_surge_multiple is not None
            else None
        ),
        "max_surge_multiple": (
            round(totals.max_surge_multiple, 2)
            if totals.max_surge_multiple is not None
            else None
        ),
        "by_severity": severity_counts,
        "by_airline": airline_counts,
        "by_status": status_counts,
    }


# ============================================================================
# 5. DGCA Historical Traffic Weights & Route Sync Operations
# ============================================================================


def upsert_dgca_traffic_weight(
    db: Session,
    route_code: str,
    year_month: str,
    pax_volume: int,
    share_weight: float,
    commit: bool = True,
) -> DgcaTrafficWeight:
    """Upsert monthly corridor passenger traffic statistics and national share weight."""
    clean_route = route_code.strip().upper()
    clean_ym = year_month.strip()

    stmt = select(DgcaTrafficWeight).where(
        DgcaTrafficWeight.route_code == clean_route,
        DgcaTrafficWeight.year_month == clean_ym,
    )
    existing = db.execute(stmt).scalar_one_or_none()

    if existing:
        existing.pax_volume = int(pax_volume)
        existing.share_weight = float(share_weight)
        record = existing
    else:
        record = DgcaTrafficWeight(
            route_code=clean_route,
            year_month=clean_ym,
            pax_volume=int(pax_volume),
            share_weight=float(share_weight),
        )
        db.add(record)

    if commit:
        try:
            db.commit()
            db.refresh(record)
        except Exception:
            db.rollback()
            raise
    else:
        db.flush()

    return record


def bulk_upsert_dgca_traffic_weights(
    db: Session,
    records: list[dict[str, Any]],
    commit: bool = True,
) -> int:
    """Bulk upsert DGCA monthly corridor passenger traffic weight records."""
    count = 0
    for rec in records:
        upsert_dgca_traffic_weight(
            db=db,
            route_code=rec["route_code"],
            year_month=rec["year_month"],
            pax_volume=rec["pax_volume"],
            share_weight=rec["share_weight"],
            commit=False,
        )
        count += 1

    if commit and count > 0:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return count


def get_dgca_traffic_weights(
    db: Session,
    route_code: str | None = None,
    year_month: str | None = None,
    limit: int = 100,
) -> list[DgcaTrafficWeight]:
    """Retrieve historical monthly corridor traffic statistics."""
    stmt = select(DgcaTrafficWeight)
    if route_code:
        stmt = stmt.where(DgcaTrafficWeight.route_code == route_code.strip().upper())
    if year_month:
        stmt = stmt.where(DgcaTrafficWeight.year_month == year_month.strip())

    stmt = stmt.order_by(desc(DgcaTrafficWeight.year_month)).limit(limit)
    return list(db.execute(stmt).scalars().all())


def update_active_route_weights_from_dgca(
    db: Session,
    year_month: str,
    commit: bool = True,
) -> int:
    """Synchronize Route table dgca_monthly_pax and basket weight from DGCA monthly traffic.

    Matches corridor codes (e.g. 'DEL-BOM') against Route origin and destination.
    Returns the count of Route records updated.
    """
    clean_ym = year_month.strip()
    weights = get_dgca_traffic_weights(db=db, year_month=clean_ym, limit=500)
    if not weights:
        return 0

    updated_count = 0
    for w in weights:
        if "-" not in w.route_code:
            continue
        origin, destination = w.route_code.split("-", 1)
        stmt = select(Route).where(
            Route.origin == origin.strip().upper(),
            Route.destination == destination.strip().upper(),
        )
        route_obj = db.execute(stmt).scalar_one_or_none()
        if route_obj:
            route_obj.dgca_monthly_pax = w.pax_volume
            route_obj.weight = w.share_weight
            updated_count += 1

    if commit and updated_count > 0:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return updated_count


# ============================================================================
# 6. Object-Oriented Econometrics Repository Wrapper
# ============================================================================


class EconometricsRepo:
    """Object-oriented repository wrapper for econometrics, CPI divergence,
    elasticity curves, and DGCA regulatory violation audits.

    Provides an instance interface initialized with a SQLAlchemy Session,
    matching the IngestionRepo and TelemetryRepo patterns.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # Econometric Index operations
    def upsert_index(self, **kwargs: Any) -> EconometricIndex:
        """Upsert an econometric price index record."""
        return upsert_econometric_index(self.db, **kwargs)

    def bulk_upsert_indices(
        self, records: list[dict[str, Any] | EconometricIndex], commit: bool = True
    ) -> int:
        """Bulk upsert econometric price index records."""
        return bulk_upsert_econometric_indices(self.db, records=records, commit=commit)

    def get_indices(self, **kwargs: Any) -> list[EconometricIndex]:
        """Retrieve econometric index series."""
        return get_econometric_indices(self.db, **kwargs)

    def get_latest_index(self, **kwargs: Any) -> EconometricIndex | None:
        """Retrieve the latest econometric index."""
        return get_latest_econometric_index(self.db, **kwargs)

    def get_comparison_summary(self, **kwargs: Any) -> dict[str, Any]:
        """Retrieve index comparison summary statistics."""
        return get_index_comparison_summary(self.db, **kwargs)

    # MoSPI CPI Series operations
    def upsert_mospi_cpi(self, **kwargs: Any) -> MospiCpiSeries:
        """Upsert a MoSPI CPI benchmark record."""
        return upsert_mospi_cpi_series(self.db, **kwargs)

    def bulk_upsert_mospi_cpi(
        self, records: list[dict[str, Any]], commit: bool = True
    ) -> int:
        """Bulk upsert MoSPI CPI benchmark records."""
        return bulk_upsert_mospi_cpi(self.db, records=records, commit=commit)

    def get_mospi_cpi(self, **kwargs: Any) -> list[MospiCpiSeries]:
        """Query MoSPI CPI benchmark series."""
        return get_mospi_cpi_series(self.db, **kwargs)

    def get_latest_mospi_cpi(self) -> MospiCpiSeries | None:
        """Retrieve latest published MoSPI CPI benchmark."""
        return get_latest_mospi_cpi(self.db)

    def get_cpi_divergence(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Calculate real-time CPI divergence analytics."""
        return get_cpi_divergence_analysis(self.db, **kwargs)

    # Route Elasticity operations
    upsert_route_elasticity = staticmethod(upsert_route_elasticity)

    def upsert_elasticity(self, **kwargs: Any) -> RouteElasticity:
        """Upsert a route elasticity curve record."""
        return upsert_route_elasticity(self.db, **kwargs)

    def bulk_upsert_elasticities(
        self, records: list[dict[str, Any]], commit: bool = True
    ) -> int:
        """Bulk upsert route elasticity curve records."""
        return bulk_upsert_route_elasticities(self.db, records=records, commit=commit)

    def get_elasticities(self, **kwargs: Any) -> list[RouteElasticity]:
        """Query route elasticity curves."""
        return get_route_elasticities(self.db, **kwargs)

    def get_latest_elasticity(self, route_code: str) -> RouteElasticity | None:
        """Retrieve latest elasticity profile for a corridor."""
        return get_latest_route_elasticity(self.db, route_code=route_code)

    def get_network_elasticity_summary(self, **kwargs: Any) -> dict[str, Any]:
        """Retrieve network-wide elasticity summary."""
        return get_network_elasticity_summary(self.db, **kwargs)

    # DGCA Violations operations
    def record_violation(self, **kwargs: Any) -> DgcaViolation:
        """Record a DGCA tariff violation audit event."""
        return record_dgca_violation(self.db, **kwargs)

    def bulk_record_violations(
        self, records: list[dict[str, Any]], commit: bool = True
    ) -> int:
        """Bulk record DGCA tariff violation audit events."""
        return bulk_record_dgca_violations(self.db, records=records, commit=commit)

    def get_violations(self, **kwargs: Any) -> list[DgcaViolation]:
        """Query DGCA tariff violation audit records."""
        return get_dgca_violations(self.db, **kwargs)

    def update_violation_status(
        self, violation_id: int, status: str, commit: bool = True
    ) -> DgcaViolation | None:
        """Update review status of a violation."""
        return update_dgca_violation_status(
            self.db, violation_id=violation_id, status=status, commit=commit
        )

    def get_violations_summary(self, **kwargs: Any) -> dict[str, Any]:
        """Retrieve DGCA violation audit summary."""
        return get_dgca_violations_summary(self.db, **kwargs)

    # DGCA Historical Traffic Weights & Route Sync
    def upsert_traffic_weight(self, **kwargs: Any) -> DgcaTrafficWeight:
        """Upsert a monthly DGCA corridor traffic weight."""
        return upsert_dgca_traffic_weight(self.db, **kwargs)

    def bulk_upsert_traffic_weights(
        self, records: list[dict[str, Any]], commit: bool = True
    ) -> int:
        """Bulk upsert monthly DGCA corridor traffic weights."""
        return bulk_upsert_dgca_traffic_weights(self.db, records=records, commit=commit)

    def get_traffic_weights(self, **kwargs: Any) -> list[DgcaTrafficWeight]:
        """Query historical monthly corridor traffic statistics."""
        return get_dgca_traffic_weights(self.db, **kwargs)

    def sync_route_weights_from_dgca(self, year_month: str, commit: bool = True) -> int:
        """Synchronize active Route table weights from DGCA traffic."""
        return update_active_route_weights_from_dgca(
            self.db, year_month=year_month, commit=commit
        )
