from datetime import datetime, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.anomaly import AnomalyAlert
from backend.app.models.econometrics import DgcaViolation
from backend.app.models.raw_fare import RawFare
from backend.app.schemas.analytics import (
    AnomalyAlertItem,
    AnomalyAlertsResponse,
    DGCAValidationItem,
    DGCAValidationResponse,
    HeatmapCell,
    HeatmapMatrixResponse,
    LeadTimeCurvePoint,
    LeadTimeCurveResponse,
)
router = APIRouter()

_IST = ZoneInfo("Asia/Kolkata")
_DISMISSED = "DISMISSED"


def _normalize_route(route_code: Optional[str]) -> str:
    return (route_code or "NATIONAL").strip().upper()


def _route_airports(route_code: str) -> tuple[str, str] | None:
    parts = route_code.split("-")
    if len(parts) == 2 and len(parts[0]) == 3 and len(parts[1]) == 3:
        return parts[0], parts[1]
    return None


def _window_days(tag: str) -> int | None:
    cleaned = tag.strip().upper()
    if cleaned.startswith("T+"):
        tail = cleaned[2:]
        if tail.isdigit():
            return int(tail)
    if cleaned.isdigit():
        return int(cleaned)
    return None


def _linear_percentile(values: list[float], percentile: float) -> float:
    """Linear percentile (numpy/R type 7) of a non-empty fare list."""
    ordered = sorted(values)
    count = len(ordered)
    if count == 1:
        return ordered[0]
    index = percentile * (count - 1)
    lower = int(index)
    upper = min(lower + 1, count - 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _departure_slot(departure: datetime) -> tuple[int, int]:
    clock = departure if departure.tzinfo is None else departure.astimezone(_IST)
    return clock.weekday(), clock.hour


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database unavailable",
    )


@router.get(
    "/lead-time-curve",
    response_model=LeadTimeCurveResponse,
    summary="Get advance purchase lead-time elasticity curve",
    description="Returns pricing curve dynamics from stored fares grouped by booking window.",
)
async def get_lead_time_curve(
    route_code: Optional[str] = Query("NATIONAL", description="Route code (e.g., DEL-BOM) or NATIONAL"),
    db: Session = Depends(get_db),
) -> LeadTimeCurveResponse:
    target_route = _normalize_route(route_code)
    generated_at = datetime.now(timezone.utc)
    empty = LeadTimeCurveResponse(
        route_code=target_route,
        curve_points=[],
        generated_at=generated_at,
        data_available=False,
    )
    airports = None if target_route == "NATIONAL" else _route_airports(target_route)
    if target_route != "NATIONAL" and airports is None:
        return empty

    try:
        query = db.query(RawFare.booking_window, RawFare.total_fare)
        if airports is not None:
            query = query.filter(RawFare.origin == airports[0], RawFare.destination == airports[1])
        rows = query.all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise _unavailable() from exc

    buckets: dict[int, list[float]] = {}
    for window, fare in rows:
        if fare is None:
            continue
        days = _window_days(window or "")
        if days is None:
            continue
        buckets.setdefault(days, []).append(float(fare))
    if not buckets:
        return empty

    baseline_median = _linear_percentile(buckets[max(buckets)], 0.5)
    curve_points: List[LeadTimeCurvePoint] = []
    for days in sorted(buckets, reverse=True):
        fares = buckets[days]
        median = _linear_percentile(fares, 0.5)
        factor = round(median / baseline_median, 3) if baseline_median > 0 else None
        curve_points.append(
            LeadTimeCurvePoint(
                days_before_departure=days,
                avg_fare_inr=round(sum(fares) / len(fares), 2),
                median_fare_inr=round(median, 2),
                p10_fare_inr=round(_linear_percentile(fares, 0.10), 2),
                p90_fare_inr=round(_linear_percentile(fares, 0.90), 2),
                elasticity_factor=factor,
            )
        )
    return LeadTimeCurveResponse(
        route_code=target_route,
        curve_points=curve_points,
        generated_at=generated_at,
        data_available=True,
    )


@router.get(
    "/heatmap",
    response_model=HeatmapMatrixResponse,
    summary="Get 7x24 Day-of-Week vs Hour-of-Day pricing heatmap",
    description="Returns observed departure-slot fares. Slots with no observations are omitted.",
)
async def get_heatmap_matrix(
    route_code: Optional[str] = Query("NATIONAL", description="Route code or NATIONAL"),
    metric: str = Query("avg_fare", description="Metric to project: 'avg_fare' or 'fare_index'"),
    db: Session = Depends(get_db),
) -> HeatmapMatrixResponse:
    target_route = _normalize_route(route_code)
    empty = HeatmapMatrixResponse(
        route_code=target_route,
        metric=metric,
        matrix=[],
        min_val=None,
        max_val=None,
        data_available=False,
    )
    airports = None if target_route == "NATIONAL" else _route_airports(target_route)
    if target_route != "NATIONAL" and airports is None:
        return empty

    try:
        query = db.query(RawFare.departure_time, RawFare.total_fare)
        if airports is not None:
            query = query.filter(RawFare.origin == airports[0], RawFare.destination == airports[1])
        rows = query.all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise _unavailable() from exc

    slots: dict[tuple[int, int], list[float]] = {}
    for departure, fare in rows:
        if departure is None or fare is None:
            continue
        slots.setdefault(_departure_slot(departure), []).append(float(fare))
    if not slots:
        return empty

    observed = [fare for fares in slots.values() for fare in fares]
    overall = sum(observed) / len(observed)
    matrix: List[HeatmapCell] = []
    scale: list[float] = []
    for (day, hour), fares in sorted(slots.items()):
        cell_avg = round(sum(fares) / len(fares), 2)
        fare_index = round(cell_avg / overall * 100.0, 2) if overall > 0 else None
        matrix.append(
            HeatmapCell(
                day_of_week=day,
                hour_of_day=hour,
                fare_index=fare_index,
                avg_fare_inr=cell_avg,
            )
        )
        selected = fare_index if metric == "fare_index" else cell_avg
        if selected is not None:
            scale.append(selected)

    return HeatmapMatrixResponse(
        route_code=target_route,
        metric=metric,
        matrix=matrix,
        min_val=min(scale) if scale else None,
        max_val=max(scale) if scale else None,
        data_available=True,
    )


@router.get(
    "/anomalies",
    response_model=AnomalyAlertsResponse,
    summary="Get detected airfare anomaly alerts",
    description="Returns pricing surges, flash sales, price crashes, and DGCA regulatory cap breaches.",
)
async def get_anomalies(
    route_code: Optional[str] = Query(None, description="Filter by route code (e.g. DEL-BOM)"),
    severity: Optional[str] = Query(None, description="Filter by severity ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')"),
    status: Optional[str] = Query(None, description="Filter by status ('ACTIVE', 'OPEN', 'INVESTIGATING', 'RESOLVED')"),
    db: Session = Depends(get_db),
) -> AnomalyAlertsResponse:
    try:
        total_db_count = db.query(func.count(AnomalyAlert.id)).scalar() or 0
        if total_db_count > 0:
            query = db.query(AnomalyAlert)

            if route_code:
                clean_route = route_code.strip().upper()
                parts = clean_route.split("-")
                if len(parts) == 2:
                    query = query.filter(
                        func.upper(AnomalyAlert.origin) == parts[0],
                        func.upper(AnomalyAlert.destination) == parts[1],
                    )
                else:
                    query = query.filter(
                        func.upper(AnomalyAlert.origin + "-" + AnomalyAlert.destination) == clean_route
                    )

            if severity:
                clean_sev = severity.strip().upper()
                query = query.filter(func.upper(AnomalyAlert.severity) == clean_sev)

            if status:
                clean_status = status.strip().upper()
                if clean_status in ("ACTIVE", "OPEN"):
                    query = query.filter(func.upper(AnomalyAlert.status).in_(["ACTIVE", "OPEN"]))
                else:
                    query = query.filter(func.upper(AnomalyAlert.status) == clean_status)

            db_alerts = query.order_by(AnomalyAlert.created_at.desc(), AnomalyAlert.id.desc()).all()
            items: List[AnomalyAlertItem] = []
            for a in db_alerts:
                dt = a.created_at
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                items.append(
                    AnomalyAlertItem(
                        id=f"anom-{a.origin.lower()}-{a.destination.lower()}-{a.id:03d}",
                        route_code=f"{a.origin}-{a.destination}",
                        airline_code=a.airline_code or "ALL",
                        flight_number=None,
                        detected_at=dt,
                        anomaly_type=a.alert_type or "SURGE",
                        severity=(a.severity or "MEDIUM").upper(),
                        observed_fare_inr=round(a.detected_fare or 0.0, 2),
                        expected_fare_inr=round(a.baseline_fare or 0.0, 2),
                        deviation_percent=round(a.pct_change or 0.0, 2),
                        status=(a.status or "ACTIVE").upper(),
                    )
                )
            return AnomalyAlertsResponse(
                alerts=items,
                total_alerts=len(items),
            )
    except SQLAlchemyError as exc:
        db.rollback()
        raise _unavailable() from exc

    return AnomalyAlertsResponse(alerts=[], total_alerts=0)


@router.get(
    "/dgca-validation",
    response_model=DGCAValidationResponse,
    summary="Get DGCA statutory fare band compliance audit",
    description="Reports stored dgca_violations rows. An empty ledger is not evaluated, not a clean audit.",
)
async def get_dgca_validation(
    db: Session = Depends(get_db),
) -> DGCAValidationResponse:
    checked_at = datetime.now(timezone.utc)
    try:
        rows = db.query(DgcaViolation).all()
    except SQLAlchemyError as exc:
        db.rollback()
        raise _unavailable() from exc

    active = [row for row in rows if (row.status or "").upper() != _DISMISSED]
    if not rows:
        return DGCAValidationResponse(
            checked_at=checked_at,
            total_routes_evaluated=0,
            total_violations=0,
            violations=[],
            data_available=False,
            evaluation_status="not_evaluated",
        )

    grouped: dict[str, list[DgcaViolation]] = {}
    for row in active:
        grouped.setdefault(row.route_code, []).append(row)

    violations: List[DGCAValidationItem] = []
    for route_code in sorted(grouped):
        group = grouped[route_code]
        peak = max(group, key=lambda item: item.fare_inr)
        violations.append(
            DGCAValidationItem(
                route_code=route_code,
                statutory_band_cap_inr=round(peak.median_baseline_fare, 2),
                observed_max_fare_inr=round(peak.fare_inr, 2),
                violations_count=len(group),
                compliance_status="BREACH_DETECTED",
            )
        )

    return DGCAValidationResponse(
        checked_at=checked_at,
        total_routes_evaluated=len(violations),
        total_violations=sum(item.violations_count for item in violations),
        violations=violations,
        data_available=True,
        evaluation_status="evaluated",
    )
