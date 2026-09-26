"""Econometrics endpoints. Every number in a response is computed from stored rows."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    status,
)
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.core.config import INSECURE_DEFAULT_INGESTION_KEY, settings
from backend.app.db.econometrics_repo import (
    get_cpi_divergence_analysis,
    get_econometric_indices,
    get_latest_mospi_cpi,
    get_latest_route_elasticity,
    update_dgca_violation_status,
    upsert_econometric_index,
)
from backend.app.db.session import get_db
from backend.app.models.econometrics import DgcaViolation, RouteElasticity
from backend.app.models.raw_fare import RawFare
from backend.app.services.mospi_provenance import source_cites_press_note
from backend.app.schemas.econometrics import (
    CarrierViolationDistribution,
    CpiDivergencePoint,
    CpiDivergenceResponse,
    CpiDivergenceSummary,
    DgcaViolationItem,
    DgcaViolationsResponse,
    DgcaViolationsSummary,
    DgcaViolationStatusUpdateRequest,
    EconometricIndexPoint,
    EconometricIndicesResponse,
    EconometricIndicesSummary,
    EconometricRecalculateRequest,
    EconometricRecalculateResponse,
    ElasticityGradientPoint,
    ElasticityResponse,
    ElasticitySegments,
)
from backend.app.services.econometric_engine import EconometricEngine

router = APIRouter()

AIRLINE_NAMES: dict[str, str] = {
    "6E": "IndiGo",
    "AI": "Air India",
    "IX": "Air India Express",
    "QP": "Akasa Air",
    "SG": "SpiceJet",
    "UK": "Vistara",
}

_INSUFFICIENT_OVERLAP = "insufficient overlapping observations"
_WINDOW_DAYS: dict[str, int] = {"T+30": 30, "T+15": 15, "T+7": 7, "T+1": 1}
_WINDOW_ELASTICITY: dict[str, str] = {
    "T+1": "t1_t7_elasticity",
    "T+7": "t7_t15_elasticity",
    "T+15": "t15_t30_elasticity",
}


def configured_api_keys() -> frozenset[str]:
    """Keys accepted for this process, read from the environment at call time.

    Compiled-in admin tokens are never accepted. Outside development, the
    published ingestion default is not treated as a configured key.
    """
    keys = {part.strip() for part in os.environ.get("APIX_API_KEYS", "").split(",") if part.strip()}
    ingestion = os.environ.get("INGESTION_API_KEY", "").strip()
    environment = os.environ.get("ENVIRONMENT", settings.ENVIRONMENT).strip().lower()
    if environment == "development":
        if ingestion:
            keys.add(ingestion)
        elif settings.INGESTION_API_KEY:
            keys.add(settings.INGESTION_API_KEY)
        return frozenset(keys)
    if ingestion and ingestion != INSECURE_DEFAULT_INGESTION_KEY:
        keys.add(ingestion)
    elif not ingestion and settings.INGESTION_API_KEY != INSECURE_DEFAULT_INGESTION_KEY:
        keys.add(settings.INGESTION_API_KEY)
    return frozenset(keys)


def verify_optional_auth(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_ingestion_key: str | None = Header(None, alias="X-Ingestion-Key"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> str | None:
    """Validate a presented credential. Missing credentials are allowed on reads."""
    token: str | None = None
    if x_api_key:
        token = x_api_key.strip()
    elif x_ingestion_key:
        token = x_ingestion_key.strip()
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif authorization:
        token = authorization.strip()

    if token is None:
        return None
    if token not in configured_api_keys():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key or authorization token provided",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return token


def verify_required_auth(
    auth_token: str | None = Depends(verify_optional_auth),
) -> str:
    """Require a credential that was configured in the environment."""
    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please provide X-API-Key, X-Ingestion-Key, or Bearer token.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return auth_token


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _pearson(left: list[float], right: list[float]) -> float | None:
    """Pearson correlation, or None when the series cannot define one."""
    count = len(left)
    if count < 2 or len(right) != count:
        return None
    mean_left = sum(left) / count
    mean_right = sum(right) / count
    covariance = sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right, strict=True))
    variance_left = sum((x - mean_left) ** 2 for x in left)
    variance_right = sum((y - mean_right) ** 2 for y in right)
    if variance_left <= 0 or variance_right <= 0:
        return None
    return covariance / math.sqrt(variance_left * variance_right)


def _period_start(period: str) -> date | None:
    try:
        year_text, month_text = period.split("-", 1)
        return date(int(year_text), int(month_text), 1)
    except ValueError:
        return None


def _optimal_lead_days(
    periods: list[str],
    apix: list[float],
    mospi: list[float],
    max_lead_days: int,
) -> tuple[int | None, str | None]:
    """Lead in days that maximizes cross-correlation, using observed month spacing.

    Ties resolve to the lag closest to zero, so a series that is no more
    correlated at a lead does not get a published lead.
    """
    if len(periods) < 3:
        return None, "insufficient overlapping observations to estimate a lead"
    starts = [_period_start(period) for period in periods]
    if any(start is None for start in starts):
        return None, "observation periods are not monthly dates"
    spacings = [
        (starts[index + 1] - starts[index]).days
        for index in range(len(starts) - 1)
        if starts[index] is not None and starts[index + 1] is not None
    ]
    if not spacings or any(spacing <= 0 for spacing in spacings):
        return None, "observation periods are not ordered monthly dates"
    mean_spacing = sum(spacings) / len(spacings)
    best_lag: int | None = None
    best_corr: float | None = None
    for lag in range(-2, 3):
        if lag > 0:
            lagged_apix, lagged_mospi = apix[:-lag], mospi[lag:]
        elif lag < 0:
            lagged_apix, lagged_mospi = apix[-lag:], mospi[:lag]
        else:
            lagged_apix, lagged_mospi = apix, mospi
        correlation = _pearson(lagged_apix, lagged_mospi)
        if correlation is None:
            continue
        lead_days = round(lag * mean_spacing)
        if abs(lead_days) > max_lead_days:
            continue
        closer_tie = (
            best_corr is not None
            and best_lag is not None
            and abs(correlation - best_corr) <= 1e-12
            and abs(lag) < abs(best_lag)
        )
        if best_corr is None or correlation > best_corr + 1e-12 or closer_tie:
            best_corr = correlation
            best_lag = lag
    if best_lag is None:
        return None, "overlapping observations have no defined cross-correlation"
    return round(best_lag * mean_spacing), None


@dataclass(frozen=True, slots=True)
class _ComputedIndex:
    laspeyres: float
    paasche: float
    fisher: float
    substitution_bias: float
    routes_processed: int
    observation_date: date


def _indices_from_raw_fares(db: Session, route_code: str) -> _ComputedIndex:
    """Build Laspeyres, Paasche, and Fisher inputs from stored fares and run the engine."""
    rows = list(db.execute(select(RawFare)).scalars().all())
    by_route_date: dict[tuple[str, date], list[float]] = {}
    for row in rows:
        code = f"{row.origin.strip().upper()}-{row.destination.strip().upper()}"
        if route_code != "NATIONAL" and code != route_code:
            continue
        fare = float(row.total_fare)
        if fare <= 0:
            continue
        observed = row.scraped_at.date() if row.scraped_at is not None else row.flight_date
        by_route_date.setdefault((code, observed), []).append(fare)
    if not by_route_date:
        raise ValueError("no raw fares available to compute an index")

    dates = sorted({observed for _, observed in by_route_date})
    earliest, latest = dates[0], dates[-1]
    base_fares: dict[str, float] = {}
    current_fares: dict[str, float] = {}
    base_weights: dict[str, float] = {}
    current_weights: dict[str, float] = {}
    for code in {route for route, _ in by_route_date}:
        base_vals = by_route_date.get((code, earliest))
        current_vals = by_route_date.get((code, latest))
        if not base_vals or not current_vals:
            continue
        base_fares[code] = _median(base_vals)
        current_fares[code] = _median(current_vals)
        base_weights[code] = float(len(base_vals))
        current_weights[code] = float(len(current_vals))
    if not current_fares:
        raise ValueError("raw fares do not cover a common route on the base and current dates")

    result = EconometricEngine(
        base_fares=base_fares,
        base_value=settings.INDEX_BASE_VALUE,
    ).calculate_all_indices(
        current_fares=current_fares,
        base_fares=base_fares,
        laspeyres_weights=base_weights,
        paasche_weights=current_weights,
    )
    return _ComputedIndex(
        laspeyres=float(result["laspeyres_index"]),
        paasche=float(result["paasche_index"]),
        fisher=float(result["fisher_index"]),
        substitution_bias=float(result["substitution_bias_points"]),
        routes_processed=len(current_fares),
        observation_date=latest,
    )


def _latest_transport_cpi(db: Session) -> float | None:
    row = get_latest_mospi_cpi(db)
    if row is None or row.cpi_transport_index is None:
        return None
    if not source_cites_press_note(row.source):
        return None
    return float(row.cpi_transport_index)


def _empty_indices() -> EconometricIndicesResponse:
    return EconometricIndicesResponse(
        base_period=None,
        laspeyres_index=None,
        paasche_index=None,
        fisher_index=None,
        substitution_bias=None,
        series=[],
        items=[],
        total=0,
        summary=None,
        data_available=False,
    )


@router.get(
    "/indices",
    response_model=EconometricIndicesResponse,
    summary="Get axiomatic econometric price indices",
)
def get_econometric_indices_endpoint(
    route_code: str | None = Query(None, description="Optional route corridor (e.g. DEL-BOM) or 'NATIONAL'"),
    start_date: str | None = Query(None, description="Start date filter (YYYY-MM-DD)"),
    end_date: str | None = Query(None, description="End date filter (YYYY-MM-DD)"),
    calculation_method: str | None = Query(None, description="Methodology filter (e.g. 'chain_weighted')"),
    limit: int = Query(100, ge=1, le=1000, description="Max observations to return"),
    db: Session = Depends(get_db),
    _: str | None = Depends(verify_optional_auth),
) -> EconometricIndicesResponse:
    target_route = route_code.strip().upper() if route_code else "NATIONAL"
    records = get_econometric_indices(
        db=db,
        route_code=None if target_route == "ALL" else target_route,
        start_date=start_date,
        end_date=end_date,
        calculation_method=calculation_method,
        limit=limit,
    )
    if not records:
        return _empty_indices()

    transport_cpi = _latest_transport_cpi(db)
    series_points = [
        EconometricIndexPoint(
            date=rec.date.isoformat() if hasattr(rec.date, "isoformat") else str(rec.date),
            laspeyres=rec.laspeyres_index,
            paasche=rec.paasche_index,
            fisher=rec.fisher_ideal_index,
            mospi_cpi=transport_cpi,
            substitution_bias=rec.substitution_bias,
            route_code=rec.route_code,
            calculation_method=rec.calculation_method,
        )
        for rec in reversed(records)
    ]
    latest = series_points[-1]
    biases = [point.substitution_bias for point in series_points if point.substitution_bias is not None]
    summary = EconometricIndicesSummary(
        current_fisher=latest.fisher,
        current_laspeyres=latest.laspeyres,
        current_paasche=latest.paasche,
        avg_substitution_bias=sum(biases) / len(biases) if biases else latest.laspeyres - latest.fisher,
        max_substitution_bias=max(biases) if biases else None,
        total_observations=len(series_points),
    )
    return EconometricIndicesResponse(
        base_period=series_points[0].date,
        laspeyres_index=latest.laspeyres,
        paasche_index=latest.paasche,
        fisher_index=latest.fisher,
        substitution_bias=latest.substitution_bias if latest.substitution_bias is not None else latest.laspeyres - latest.fisher,
        series=series_points,
        items=series_points,
        total=len(series_points),
        summary=summary,
        data_available=True,
    )


def _cpi_response(
    points: list[CpiDivergencePoint],
    correlation: float | None,
    lead_days: int | None,
    reason: str | None,
) -> CpiDivergenceResponse:
    gaps = [point.gap for point in points]
    mean_gap = sum(gaps) / len(gaps) if gaps else None
    tracking_error = None
    if len(gaps) >= 2 and mean_gap is not None:
        variance = sum((gap - mean_gap) ** 2 for gap in gaps) / (len(gaps) - 1)
        tracking_error = math.sqrt(variance)
    summary = CpiDivergenceSummary(
        mean_divergence=mean_gap,
        tracking_error=tracking_error,
        correlation=correlation,
        lead_lag_days=lead_days,
        optimal_lead_days=lead_days,
        reason=reason,
        last_updated=datetime.now(UTC).isoformat(),
    )
    return CpiDivergenceResponse(
        current_divergence_pts=points[-1].gap if points else None,
        inflation_lead_days=lead_days,
        correlation_coefficient=correlation,
        divergence_series=points,
        series=points,
        summary=summary,
        data_available=bool(points),
        reason=reason,
    )


@router.get(
    "/cpi-divergence",
    response_model=CpiDivergenceResponse,
    summary="Get APIx Airfare Index vs MoSPI CPI Transport Sub-Index divergence",
)
@router.get(
    "/cpi-gap",
    response_model=CpiDivergenceResponse,
    include_in_schema=False,
    summary="Alias for /cpi-divergence",
)
def get_cpi_divergence_endpoint(
    start_month: str | None = Query(None, description="Starting month in format YYYY-MM"),
    end_month: str | None = Query(None, description="Ending month in format YYYY-MM"),
    months: int = Query(12, ge=1, le=60, description="Lookback window in months"),
    lag_days: int = Query(38, ge=0, le=180, description="Maximum lead window to search, in days"),
    db: Session = Depends(get_db),
    _: str | None = Depends(verify_optional_auth),
) -> CpiDivergenceResponse:
    points: list[CpiDivergencePoint] = []
    rows = list(get_cpi_divergence_analysis(db=db, months=months))
    cited_rows = [row for row in rows if source_cites_press_note(row.get("source"))]
    if rows and not cited_rows:
        return _cpi_response(
            [],
            None,
            None,
            "stored CPI rows do not cite a press note and are not an official MoSPI series",
        )
    for row in cited_rows:
        period = str(row.get("year_month") or "")
        if start_month and period < start_month:
            continue
        if end_month and period > end_month:
            continue
        raw_apix = row.get("apix_national_fisher")
        raw_mospi = row.get("mospi_transport_cpi")
        if raw_apix is None or raw_mospi is None:
            continue
        apix_value = float(raw_apix)
        mospi_value = float(raw_mospi)
        if apix_value <= 0 or mospi_value <= 0:
            continue
        gap = apix_value - mospi_value
        points.append(
            CpiDivergencePoint(
                date=period,
                apix_index=apix_value,
                mospi_cpi=mospi_value,
                gap=gap,
                airfare_subindex=row.get("mospi_airfare_sub_index"),
                headline_cpi=row.get("mospi_headline_cpi"),
                divergence_pct=(gap / mospi_value) * 100.0,
            )
        )
    points.sort(key=lambda point: point.date)
    if len(points) < 2:
        return _cpi_response(points, None, None, _INSUFFICIENT_OVERLAP)

    apix = [point.apix_index for point in points]
    mospi = [point.mospi_cpi for point in points]
    correlation = _pearson(apix, mospi)
    if correlation is None:
        return _cpi_response(points, None, None, "overlapping observations have zero variance")
    lead_days, lead_reason = _optimal_lead_days(
        [point.date for point in points],
        apix,
        mospi,
        max_lead_days=lag_days,
    )
    return _cpi_response(points, correlation, lead_days, lead_reason)


def _window_medians(db: Session, route_code: str) -> dict[str, float]:
    stmt = select(RawFare)
    if route_code != "NATIONAL" and "-" in route_code:
        origin, destination = route_code.split("-", 1)
        stmt = stmt.where(RawFare.origin == origin, RawFare.destination == destination)
    grouped: dict[str, list[float]] = {}
    for row in db.execute(stmt).scalars():
        if row.total_fare is None or float(row.total_fare) <= 0:
            continue
        grouped.setdefault(row.booking_window.strip().upper(), []).append(float(row.total_fare))
    return {window: _median(values) for window, values in grouped.items()}


def _gradient_from_fares(
    fares: dict[str, float],
    elasticity: RouteElasticity,
) -> list[ElasticityGradientPoint]:
    if not fares:
        return []
    baseline = fares.get("T+30")
    points: list[ElasticityGradientPoint] = []
    for window, days in _WINDOW_DAYS.items():
        fare = fares.get(window)
        if fare is None:
            continue
        attribute = _WINDOW_ELASTICITY.get(window)
        price_elasticity = getattr(elasticity, attribute) if attribute else None
        surge = fare / baseline if baseline is not None and baseline > 0 else None
        points.append(
            ElasticityGradientPoint(
                lead_window=window,
                window=window,
                days_before_departure=days,
                surge_multiplier=surge,
                avg_fare_inr=fare,
                price_elasticity=price_elasticity,
            )
        )
    return points


@router.get(
    "/elasticity",
    response_model=ElasticityResponse,
    summary="Get advance booking price elasticity curves",
)
def get_elasticity_endpoint(
    route_code: str = Query("NATIONAL", description="Route corridor code (e.g. DEL-BOM) or 'NATIONAL'"),
    as_of_date: str | None = Query(None, description="Target evaluation date (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    _: str | None = Depends(verify_optional_auth),
) -> ElasticityResponse:
    clean_route = route_code.strip().upper()
    elasticity = get_latest_route_elasticity(db=db, route_code=clean_route)
    if elasticity is None:
        return ElasticityResponse(
            route_code=clean_route,
            as_of_date=as_of_date,
            gradient_points=[],
            curves=[],
            segments=None,
            data_available=False,
        )
    points = _gradient_from_fares(_window_medians(db, clean_route), elasticity)
    segments = ElasticitySegments(
        t1_t7=elasticity.t1_t7_elasticity,
        t7_t15=elasticity.t7_t15_elasticity,
        t15_t30=elasticity.t15_t30_elasticity,
        avg_lead_time_decay=elasticity.avg_lead_time_decay,
        confidence_score=elasticity.confidence_score,
    )
    evaluated = elasticity.calculation_date.isoformat() if elasticity.calculation_date else as_of_date
    return ElasticityResponse(
        route_code=clean_route,
        as_of_date=evaluated,
        gradient_points=points,
        curves=points,
        segments=segments,
        data_available=True,
    )


def _violation_item(row: DgcaViolation) -> DgcaViolationItem:
    carrier = row.airline_code
    flight_date = row.flight_date.isoformat() if hasattr(row.flight_date, "isoformat") else str(row.flight_date)
    detected = row.detected_at.isoformat() if hasattr(row.detected_at, "isoformat") else str(row.detected_at)
    return DgcaViolationItem(
        id=str(row.id),
        route_code=row.route_code,
        carrier_code=carrier,
        carrier_name=AIRLINE_NAMES.get(carrier, carrier),
        flight_number=row.flight_number,
        flight_date=flight_date,
        window=row.window,
        observed_fare_inr=row.fare_inr,
        statutory_band_cap_inr=row.median_baseline_fare,
        surge_multiplier=row.surge_multiple,
        severity=row.severity,
        compliance_status="BREACH" if row.severity in ("CRITICAL", "SEVERE") else "WARNING",
        violation_code=row.violation_code,
        detected_at=detected,
        description=f"{row.violation_code} on {row.route_code}",
        status=row.status,
        fare_inr=row.fare_inr,
        median_baseline_fare=row.median_baseline_fare,
        surge_multiple=row.surge_multiple,
        airline_code=carrier,
    )


def _matching_violations(
    db: Session,
    route_code: str | None,
    airline_code: str | None,
    severity: str | None,
    status_filter: str | None,
) -> list[DgcaViolation]:
    stmt = select(DgcaViolation)
    if route_code:
        stmt = stmt.where(DgcaViolation.route_code == route_code)
    if airline_code:
        stmt = stmt.where(DgcaViolation.airline_code == airline_code)
    if severity:
        stmt = stmt.where(DgcaViolation.severity == severity)
    if status_filter:
        stmt = stmt.where(DgcaViolation.status == status_filter)
    stmt = stmt.order_by(desc(DgcaViolation.detected_at))
    return list(db.execute(stmt).scalars().all())


def _carrier_distribution(rows: list[DgcaViolation]) -> list[CarrierViolationDistribution]:
    grouped: dict[str, list[DgcaViolation]] = {}
    for row in rows:
        grouped.setdefault(row.airline_code, []).append(row)
    distribution = [
        CarrierViolationDistribution(
            carrier_code=code,
            carrier_name=AIRLINE_NAMES.get(code, code),
            avg_surge_multiplier=sum(float(item.surge_multiple) for item in group) / len(group),
            violations_count=len(group),
            compliance_rate=None,
        )
        for code, group in grouped.items()
    ]
    distribution.sort(key=lambda item: item.violations_count, reverse=True)
    return distribution


@router.get(
    "/dgca-violations",
    response_model=DgcaViolationsResponse,
    summary="Get DGCA statutory tariff violation audit feed",
)
def get_dgca_violations_endpoint(
    severity: str | None = Query(None, description="Filter by severity: 'WARNING', 'CRITICAL', 'SEVERE'"),
    airline_code: str | None = Query(None, description="Filter by operating airline code (e.g. 6E, AI)"),
    route_code: str | None = Query(None, description="Filter by flight route corridor (e.g. DEL-BOM)"),
    status_filter: str | None = Query(None, alias="status", description="Filter by audit status"),
    limit: int = Query(50, ge=1, le=500, description="Max violations to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
    _: str | None = Depends(verify_optional_auth),
) -> DgcaViolationsResponse:
    rows = _matching_violations(
        db,
        route_code.strip().upper() if route_code else None,
        airline_code.strip().upper() if airline_code else None,
        severity.strip().upper() if severity else None,
        status_filter.strip().upper() if status_filter else None,
    )
    page = [_violation_item(row) for row in rows[offset : offset + limit]]
    distribution = _carrier_distribution(rows)
    summary = DgcaViolationsSummary(
        total_violations=len(rows),
        severe_count=sum(1 for row in rows if row.severity == "SEVERE"),
        critical_count=sum(1 for row in rows if row.severity == "CRITICAL"),
        warning_count=sum(1 for row in rows if row.severity == "WARNING"),
        top_violating_carriers=[
            {"airline_code": item.carrier_code, "violations": item.violations_count}
            for item in distribution
        ],
    )
    return DgcaViolationsResponse(
        violations=page,
        items=page,
        carrier_distribution=distribution,
        total_evaluated=len(rows),
        total_violations=len(rows),
        summary=summary,
        data_available=bool(rows),
    )


@router.post(
    "/recalculate",
    response_model=EconometricRecalculateResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger administrative econometric index recomputation",
)
def recalculate_econometric_indices(
    payload: EconometricRecalculateRequest,
    db: Session = Depends(get_db),
    _: str = Depends(verify_required_auth),
) -> EconometricRecalculateResponse:
    target_route = (payload.route_code or "NATIONAL").strip().upper()
    method = payload.calculation_method or "chain_weighted"
    try:
        computed = _indices_from_raw_fares(db, target_route)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    upsert_econometric_index(
        db=db,
        date=computed.observation_date,
        route_code=target_route,
        laspeyres_index=computed.laspeyres,
        paasche_index=computed.paasche,
        fisher_ideal_index=computed.fisher,
        substitution_bias=computed.substitution_bias,
        calculation_method=method,
        commit=True,
    )
    return EconometricRecalculateResponse(
        status="SUCCESS",
        message=f"Axiomatic price indices recomputed for route {target_route}",
        routes_processed=computed.routes_processed,
        indices_generated=1,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.patch(
    "/dgca-violations/{violation_id}/status",
    summary="Update DGCA violation audit review status",
)
def update_violation_status(
    violation_id: str = Path(..., description="Unique violation record identifier"),
    payload: DgcaViolationStatusUpdateRequest = ...,
    db: Session = Depends(get_db),
    _: str = Depends(verify_required_auth),
) -> dict[str, Any]:
    new_status = payload.status.strip().upper()
    valid_statuses = {"OPEN", "UNDER_REVIEW", "CONFIRMED", "DISMISSED", "REPORTED"}
    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status '{payload.status}'. Must be one of: {', '.join(sorted(valid_statuses))}",
        )

    updated = False
    try:
        numeric_id = int(violation_id)
    except ValueError:
        numeric_id = None
    if numeric_id is not None:
        db_rec = update_dgca_violation_status(db=db, violation_id=numeric_id, status=new_status)
        updated = db_rec is not None

    return {
        "id": violation_id,
        "status": new_status,
        "notes": payload.notes,
        "updated_at": datetime.now(UTC).isoformat(),
        "database_updated": updated,
    }


@router.post(
    "/dgca-violations/{violation_id}/acknowledge",
    summary="Acknowledge DGCA violation for auditor review",
)
def acknowledge_violation(
    violation_id: str = Path(..., description="Unique violation record identifier"),
    db: Session = Depends(get_db),
    _: str = Depends(verify_required_auth),
) -> dict[str, Any]:
    return update_violation_status(
        violation_id=violation_id,
        payload=DgcaViolationStatusUpdateRequest(status="UNDER_REVIEW", notes="Auditor review acknowledged"),
        db=db,
        _=_,
    )
