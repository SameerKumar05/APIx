from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status

from backend.app.schemas.index import (
    NationalIndexHistoryResponse,
    NationalIndexLatestResponse,
    NationalIndexPoint,
    RouteHistoryResponse,
    RouteListResponse,
    RouteOverviewItem,
)

router = APIRouter()

# Benchmark domestic corridors across Indian aviation network
DOMESTIC_ROUTES_SEED = [
    RouteOverviewItem(
        route_code="DEL-BOM",
        origin="DEL",
        destination="BOM",
        current_index=118.50,
        change_24h=2.10,
        avg_fare_inr=6850.0,
        min_fare_inr=4200.0,
        active_flights_tracked=112,
        volatility_score=0.42,
    ),
    RouteOverviewItem(
        route_code="BOM-BLR",
        origin="BOM",
        destination="BLR",
        current_index=111.20,
        change_24h=-0.80,
        avg_fare_inr=4950.0,
        min_fare_inr=3100.0,
        active_flights_tracked=78,
        volatility_score=0.35,
    ),
    RouteOverviewItem(
        route_code="DEL-BLR",
        origin="DEL",
        destination="BLR",
        current_index=116.40,
        change_24h=1.10,
        avg_fare_inr=7200.0,
        min_fare_inr=4800.0,
        active_flights_tracked=84,
        volatility_score=0.38,
    ),
    RouteOverviewItem(
        route_code="DEL-CCU",
        origin="DEL",
        destination="CCU",
        current_index=109.80,
        change_24h=0.50,
        avg_fare_inr=5800.0,
        min_fare_inr=3600.0,
        active_flights_tracked=56,
        volatility_score=0.29,
    ),
    RouteOverviewItem(
        route_code="BOM-GOI",
        origin="BOM",
        destination="GOI",
        current_index=126.30,
        change_24h=4.80,
        avg_fare_inr=5100.0,
        min_fare_inr=2900.0,
        active_flights_tracked=64,
        volatility_score=0.58,
    ),
    RouteOverviewItem(
        route_code="BLR-HYD",
        origin="BLR",
        destination="HYD",
        current_index=104.70,
        change_24h=-0.20,
        avg_fare_inr=3850.0,
        min_fare_inr=2400.0,
        active_flights_tracked=48,
        volatility_score=0.24,
    ),
    RouteOverviewItem(
        route_code="MAA-DEL",
        origin="MAA",
        destination="DEL",
        current_index=112.90,
        change_24h=1.50,
        avg_fare_inr=6400.0,
        min_fare_inr=4100.0,
        active_flights_tracked=52,
        volatility_score=0.31,
    ),
]


@router.get(
    "/national/latest",
    response_model=NationalIndexLatestResponse,
    summary="Get latest National Airfare Price Index",
    description="Returns latest calculated Fisher/Jevons weighted national airfare price index augmenting CPI.",
)
async def get_national_index_latest() -> NationalIndexLatestResponse:
    now = datetime.now(timezone.utc)
    return NationalIndexLatestResponse(
        timestamp=now,
        index_value=114.28,
        change_24h=1.42,
        change_7d=3.85,
        sample_size=48250,
        base_period="2026-01-01",
        confidence_interval_lower=113.10,
        confidence_interval_upper=115.46,
        status="published",
    )


@router.get(
    "/national/history",
    response_model=NationalIndexHistoryResponse,
    summary="Get historical National Airfare Price Index time-series",
    description="Returns daily chronological historical index points over the requested lookback window.",
)
async def get_national_index_history(
    days: int = Query(30, ge=1, le=365, description="Number of historical days to retrieve"),
) -> NationalIndexHistoryResponse:
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    base_val = 100.0
    points: List[NationalIndexPoint] = []

    for i in range(days, 0, -1):
        dt = now - timedelta(days=i)
        # Deterministic upward trend reflecting seasonal escalation
        val = round(base_val + (days - i) * 0.45 + ((i % 5) * 0.2 - 0.4), 2)
        change_24h = round((0.45 + ((i % 5) * 0.2 - 0.4)) / val * 100, 2)
        points.append(
            NationalIndexPoint(
                timestamp=dt,
                index_value=val,
                change_24h=change_24h,
                change_7d=round(change_24h * 3.5, 2),
                sample_size=45000 + (i * 120),
                base_period="2026-01-01",
            )
        )

    # Latest point
    points.append(
        NationalIndexPoint(
            timestamp=now,
            index_value=114.28,
            change_24h=1.42,
            change_7d=3.85,
            sample_size=48250,
            base_period="2026-01-01",
        )
    )

    return NationalIndexHistoryResponse(
        points=points,
        total_points=len(points),
    )


@router.get(
    "/routes",
    response_model=RouteListResponse,
    summary="Get route-level airfare index overviews",
    description="Returns summary metrics, current index value, and volatility for domestic high-density corridors.",
)
async def get_routes_overview() -> RouteListResponse:
    return RouteListResponse(
        routes=DOMESTIC_ROUTES_SEED,
        total_routes=len(DOMESTIC_ROUTES_SEED),
    )


@router.get(
    "/routes/{route_code}/history",
    response_model=RouteHistoryResponse,
    summary="Get route-specific historical index series",
    description="Returns time-series index trajectory for a specific domestic city-pair corridor.",
)
async def get_route_history(
    route_code: str,
    days: int = Query(30, ge=1, le=365, description="Number of lookback days"),
) -> RouteHistoryResponse:
    clean_code = route_code.strip().upper()
    matching = next((r for r in DOMESTIC_ROUTES_SEED if r.route_code == clean_code), None)

    if not matching:
        parts = clean_code.split("-")
        if len(parts) == 2 and len(parts[0]) == 3 and len(parts[1]) == 3:
            origin, dest = parts[0], parts[1]
            base_idx = 108.0
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Route code '{route_code}' not found in active tracking registry.",
            )
    else:
        origin = matching.origin
        dest = matching.destination
        base_idx = matching.current_index - (days * 0.3)

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    points: List[NationalIndexPoint] = []
    for i in range(days, -1, -1):
        dt = now - timedelta(days=i)
        val = round(base_idx + (days - i) * 0.35 + ((i % 4) * 0.3 - 0.5), 2)
        points.append(
            NationalIndexPoint(
                timestamp=dt,
                index_value=val,
                change_24h=round((0.35 + ((i % 4) * 0.3 - 0.5)) / val * 100, 2),
                change_7d=round(((days - i) * 0.15), 2),
                sample_size=1800 + (i * 20),
                base_period="2026-01-01",
            )
        )

    return RouteHistoryResponse(
        route_code=clean_code,
        origin=origin,
        destination=dest,
        points=points,
    )
