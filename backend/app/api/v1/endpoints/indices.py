from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.models.econometrics import MospiCpiSeries
from backend.app.models.index import NationalDailyIndex, RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.route import Route
from backend.app.schemas.analytics import SectorHeatmapResponse
from backend.app.schemas.index import (
    NationalIndexHistoryResponse,
    NationalIndexLatestResponse,
    NationalIndexPoint,
    RouteHistoryResponse,
    RouteListResponse,
    RouteOverviewItem,
)
from backend.app.services.mospi_provenance import source_cites_press_note

router = APIRouter()

_WINDOW_DAYS = {"T+1": 1, "T+7": 7, "T+15": 15, "T+30": 30, "T+45": 45}


def _horizon_context(db: Session, index_value: float) -> dict:
    """Derive the Overview benchmark fields from tables that actually hold data.

    Returns mospi_cpi / divergence / weighted median fare / T+1 and T+30 horizon
    indices. Every field is None when its source table is empty, so the UI can
    report no coverage rather than substitute a constant.
    """
    out: dict = {}

    mospi = db.query(MospiCpiSeries).order_by(MospiCpiSeries.year_month.desc()).first()
    if (
        mospi is not None
        and mospi.cpi_transport_index
        and source_cites_press_note(mospi.source)
    ):
        out["mospi_cpi"] = round(float(mospi.cpi_transport_index), 2)
        out["mospi_cpi_divergence"] = round(
            index_value - float(mospi.cpi_transport_index), 2
        )
        out["mospi_source"] = mospi.source

    weights = {
        f"{origin}-{destination}": float(weight)
        for origin, destination, weight in db.query(
            Route.origin, Route.destination, Route.weight
        )
        .filter(Route.is_active.is_(True))
        .all()
        if weight
    }
    rows = db.query(
        RouteDailyIndex.origin, RouteDailyIndex.destination, RouteDailyIndex.mean_fare
    ).all()
    num = den = 0.0
    for origin, destination, mean_fare in rows:
        if not mean_fare:
            continue
        w = weights.get(f"{origin}-{destination}")
        if w is None:
            continue
        num += float(mean_fare) * w
        den += w
    if den > 0 and num > 0:
        out["weighted_median_fare_inr"] = round(num / den, 2)

    horizon: dict[int, list[float]] = {}
    overall = db.query(func.avg(RawFare.total_fare)).scalar()
    for window, fare in db.query(RawFare.booking_window, RawFare.total_fare).all():
        days = _WINDOW_DAYS.get((window or "").strip().upper())
        if days and fare:
            horizon.setdefault(days, []).append(float(fare))
    if overall and overall > 0:
        for days, field in ((1, "t1_index"), (30, "t30_index")):
            values = horizon.get(days)
            if values:
                out[field] = round(
                    (sum(values) / len(values)) / float(overall) * index_value, 2
                )
    return out


@router.get(
    "/national/latest",
    response_model=NationalIndexLatestResponse,
    summary="Get latest National Airfare Price Index",
    description="Returns latest calculated Fisher/Jevons weighted national airfare price index augmenting CPI.",
)
async def get_national_index_latest(
    db: Session = Depends(get_db),
) -> NationalIndexLatestResponse:
    try:
        base_query = db.query(NationalDailyIndex).filter(
            NationalDailyIndex.booking_window == "COMPOSITE"
        )
        latest = (
            (
                base_query.filter(NationalDailyIndex.index_type == "laspeyres")
                .order_by(NationalDailyIndex.index_date.desc())
                .first()
            )
            or base_query.order_by(
                NationalDailyIndex.index_date.desc(), NationalDailyIndex.id.desc()
            ).first()
            or (
                db.query(NationalDailyIndex)
                .order_by(
                    NationalDailyIndex.index_date.desc(), NationalDailyIndex.id.desc()
                )
                .first()
            )
        )
        if latest is not None:
            ts = datetime.combine(latest.index_date, datetime.min.time(), tzinfo=UTC)
            if latest.calculation_timestamp:
                ts = latest.calculation_timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
            change_24h = round(latest.inflation_dod_pct, 2)
            val = round(latest.index_value, 2)
            prior = (
                db.query(NationalDailyIndex)
                .filter(
                    NationalDailyIndex.booking_window == latest.booking_window,
                    NationalDailyIndex.index_type == latest.index_type,
                    NationalDailyIndex.index_date
                    == latest.index_date - timedelta(days=7),
                )
                .order_by(NationalDailyIndex.id.desc())
                .first()
            )
            change_7d = None
            if prior is not None and prior.index_value:
                change_7d = round(
                    (latest.index_value - prior.index_value)
                    / prior.index_value
                    * 100.0,
                    2,
                )
            return NationalIndexLatestResponse(
                timestamp=ts,
                index_value=val,
                change_24h=change_24h,
                change_7d=change_7d,
                sample_size=latest.total_samples or 0,
                base_period=latest.base_period or "2026-01-01",
                status="published",
                **_horizon_context(db, val),
            )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Index not yet computed. Run the index pipeline before requesting the latest value.",
        ) from exc

    raise HTTPException(
        status_code=503,
        detail="Index not yet computed. Run the index pipeline before requesting the latest value.",
    )


@router.get(
    "/national/history",
    response_model=NationalIndexHistoryResponse,
    summary="Get historical National Airfare Price Index time-series",
    description=(
        "Returns chronological index points aggregated at the requested frequency. "
        "Daily uses the stored daily observations. Weekly buckets by ISO week and "
        "monthly by calendar month, averaging the index and summing the sample count. "
        "An empty series means no index has been computed for the window, not that "
        "prices were flat."
    ),
)
async def get_national_index_history(
    days: int = Query(365, ge=1, le=1095, description="Lookback window in days"),
    frequency: str = Query(
        "daily",
        pattern="^(daily|weekly|monthly)$",
        description="Aggregation frequency for the returned series",
    ),
    booking_window: str = Query(
        "COMPOSITE", description="Booking window filter (default: COMPOSITE)"
    ),
    db: Session = Depends(get_db),
) -> NationalIndexHistoryResponse:
    cutoff = date.today() - timedelta(days=days)
    clean_window = (booking_window or "COMPOSITE").strip().upper()
    base_query = db.query(NationalDailyIndex).filter(NationalDailyIndex.index_date >= cutoff)
    if clean_window != "ALL":
        base_query = base_query.filter(func.upper(NationalDailyIndex.booking_window) == clean_window)
    records = (
        base_query
        .filter(
            func.lower(func.coalesce(NationalDailyIndex.index_type, "")) == "fisher"
        )
        .order_by(NationalDailyIndex.index_date.asc())
        .all()
    )
    if not records:
        records = (
            base_query
            .filter(
                func.lower(func.coalesce(NationalDailyIndex.index_type, "")) == "laspeyres"
            )
            .order_by(NationalDailyIndex.index_date.asc())
            .all()
        )
    if not records:
        records = base_query.order_by(NationalDailyIndex.index_date.asc()).all()
    buckets: dict[str, list[NationalDailyIndex]] = {}
    for r in records:
        buckets.setdefault(_bucket_key(r.index_date, frequency), []).append(r)

    points: list[NationalIndexPoint] = []
    previous_value: float | None = None
    for key in sorted(buckets):
        group = buckets[key]
        index_value = sum(g.index_value for g in group) / len(group)
        sample_size = sum(g.total_samples or 0 for g in group)
        bucket_date = (
            date.fromisoformat(f"{key}-01")
            if frequency == "monthly"
            else group[-1].index_date
        )
        change = (
            0.0
            if previous_value in (None, 0)
            else round((index_value - previous_value) / previous_value * 100.0, 2)
        )
        points.append(
            NationalIndexPoint(
                timestamp=datetime.combine(
                    bucket_date, datetime.min.time(), tzinfo=UTC
                ),
                index_value=round(index_value, 2),
                change_24h=change if frequency == "daily" else 0.0,
                change_7d=change,
                sample_size=sample_size,
                base_period=group[-1].base_period or "2026-01-01",
            )
        )
        previous_value = index_value

    return NationalIndexHistoryResponse(
        points=points,
        total_points=len(points),
        frequency=frequency,
        data_available=bool(points),
    )


def _bucket_key(value: date, frequency: str) -> str:
    if frequency == "monthly":
        return f"{value.year:04d}-{value.month:02d}"
    if frequency == "weekly":
        iso = value.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"
    return value.isoformat()


@router.get(
    "/routes",
    response_model=RouteListResponse,
    summary="Get route-level airfare index overviews",
    description="Returns summary metrics for corridors that have a stored daily index.",
)
async def get_routes_overview(
    db: Session = Depends(get_db),
) -> RouteListResponse:
    try:
        db_routes = db.query(Route).filter(Route.is_active.is_(True)).all()
        if db_routes:
            routes_list: list[RouteOverviewItem] = []
            for r in db_routes:
                latest_idx = (
                    db.query(RouteDailyIndex)
                    .filter(
                        RouteDailyIndex.origin == r.origin,
                        RouteDailyIndex.destination == r.destination,
                    )
                    .order_by(
                        RouteDailyIndex.index_date.desc(), RouteDailyIndex.id.desc()
                    )
                    .first()
                )
                if latest_idx:
                    prior_idx = (
                        db.query(RouteDailyIndex)
                        .filter(
                            RouteDailyIndex.origin == r.origin,
                            RouteDailyIndex.destination == r.destination,
                            RouteDailyIndex.index_date < latest_idx.index_date,
                        )
                        .order_by(RouteDailyIndex.index_date.desc())
                        .first()
                    )
                    change_24h = (
                        round(
                            (
                                (latest_idx.index_value - prior_idx.index_value)
                                / prior_idx.index_value
                            )
                            * 100.0,
                            2,
                        )
                        if prior_idx is not None and prior_idx.index_value
                        else None
                    )
                    volatility = (
                        round(latest_idx.std_dev / latest_idx.mean_fare, 2)
                        if latest_idx.mean_fare
                        else None
                    )
                    routes_list.append(
                        RouteOverviewItem(
                            route_code=r.route_code,
                            origin=r.origin,
                            destination=r.destination,
                            current_index=round(latest_idx.index_value, 2),
                            change_24h=change_24h,
                            avg_fare_inr=round(latest_idx.mean_fare, 2),
                            min_fare_inr=round(latest_idx.min_fare, 2),
                            active_flights_tracked=latest_idx.sample_size,
                            volatility_score=volatility,
                        )
                    )
            return RouteListResponse(
                routes=routes_list,
                total_routes=len(routes_list),
                data_available=bool(routes_list),
            )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc

    return RouteListResponse(routes=[], total_routes=0, data_available=False)


@router.get(
    "/routes/{route_code}/history",
    response_model=RouteHistoryResponse,
    summary="Get route-specific historical index series",
    description="Returns the stored time-series for a corridor. An empty series means no index has been computed.",
)
async def get_route_history(
    route_code: str,
    days: int = Query(30, ge=1, le=365, description="Number of lookback days"),
    booking_window: str = Query(
        "COMPOSITE", description="Booking window filter (default: COMPOSITE)"
    ),
    frequency: str = Query(
        "daily",
        pattern="^(daily|weekly|monthly)$",
        description="Aggregation frequency for the returned series",
    ),
    db: Session = Depends(get_db),
) -> RouteHistoryResponse:
    clean_code = route_code.strip().upper()
    parts = clean_code.split("-")
    if len(parts) != 2 or len(parts[0]) != 3 or len(parts[1]) != 3:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Route code '{route_code}' not found in active tracking registry.",
        )
    origin, dest = parts[0], parts[1]

    try:
        clean_window = (booking_window or "COMPOSITE").strip().upper()
        base_query = db.query(RouteDailyIndex).filter(
            RouteDailyIndex.origin == origin,
            RouteDailyIndex.destination == dest,
        )
        route_indices = (
            base_query.filter(
                func.upper(RouteDailyIndex.booking_window) == clean_window
            )
            .order_by(RouteDailyIndex.index_date.desc())
            .limit(days)
            .all()
        )
        if not route_indices and clean_window == "COMPOSITE":
            route_indices = (
                base_query.order_by(RouteDailyIndex.index_date.desc()).limit(days).all()
            )
        if route_indices:
            route_indices.reverse()
            if frequency in ("weekly", "monthly"):
                buckets: dict[str, list[RouteDailyIndex]] = {}
                for r in route_indices:
                    buckets.setdefault(_bucket_key(r.index_date, frequency), []).append(r)

                points: list[NationalIndexPoint] = []
                previous_value: float | None = None
                for key in sorted(buckets):
                    group = buckets[key]
                    index_value = sum(g.index_value for g in group) / len(group)
                    sample_size = sum(g.sample_size or 0 for g in group)
                    bucket_date = (
                        date.fromisoformat(f"{key}-01")
                        if frequency == "monthly"
                        else group[-1].index_date
                    )
                    change = (
                        0.0
                        if previous_value in (None, 0)
                        else round((index_value - previous_value) / previous_value * 100.0, 2)
                    )
                    points.append(
                        NationalIndexPoint(
                            timestamp=datetime.combine(
                                bucket_date, datetime.min.time(), tzinfo=UTC
                            ),
                            index_value=round(index_value, 2),
                            change_24h=change if frequency == "daily" else 0.0,
                            change_7d=change,
                            sample_size=sample_size,
                            base_period=group[-1].base_period or "2026-01-01",
                        )
                    )
                    previous_value = index_value

                return RouteHistoryResponse(
                    route_code=clean_code,
                    origin=origin,
                    destination=dest,
                    points=points,
                    data_available=bool(points),
                    frequency=frequency,
                )
            else:
                by_date = {row.index_date: row for row in route_indices}
                points = []
                for idx, r in enumerate(route_indices):
                    ts = datetime.combine(r.index_date, datetime.min.time(), tzinfo=UTC)
                    if r.calculation_timestamp:
                        ts = r.calculation_timestamp
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=UTC)
                    prev = route_indices[idx - 1] if idx > 0 else None
                    change_24h = (
                        round(
                            ((r.index_value - prev.index_value) / prev.index_value) * 100.0,
                            2,
                        )
                        if prev is not None and prev.index_value
                        else None
                    )
                    week_prior = by_date.get(r.index_date - timedelta(days=7))
                    change_7d = (
                        round(
                            (
                                (r.index_value - week_prior.index_value)
                                / week_prior.index_value
                            )
                            * 100.0,
                            2,
                        )
                        if week_prior is not None and week_prior.index_value
                        else None
                    )
                    points.append(
                        NationalIndexPoint(
                            timestamp=ts,
                            index_value=round(r.index_value, 2),
                            change_24h=change_24h,
                            change_7d=change_7d,
                            sample_size=r.sample_size,
                            base_period=r.base_period or "2026-01-01",
                        )
                    )
                return RouteHistoryResponse(
                    route_code=clean_code,
                    origin=origin,
                    destination=dest,
                    points=points,
                    data_available=True,
                    frequency="daily",
                )
        return RouteHistoryResponse(
            route_code=clean_code,
            origin=origin,
            destination=dest,
            points=[],
            data_available=False,
            frequency=frequency,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc


@router.get(
    "/sector-heatmap",
    response_model=SectorHeatmapResponse,
    summary="Get route sector matrix and advance window pricing",
    description="Returns cross-corridor advance booking window fare matrix and surge multipliers.",
)
async def get_sector_heatmap_alias(
    route_code: str | None = Query(
        None,
        description="Optional route code filter (e.g. DEL-BOM) or None for all routes",
    ),
    db: Session = Depends(get_db),
) -> SectorHeatmapResponse:
    from backend.app.api.v1.endpoints.analytics import (
        get_sector_heatmap as _get_sector_heatmap,
    )

    return await _get_sector_heatmap(route_code=route_code, db=db)
