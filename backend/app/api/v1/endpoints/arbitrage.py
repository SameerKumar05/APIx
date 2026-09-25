"""Arbitrage endpoint analyzing price spreads between direct airline booking channels and OTAs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.arbitrage import ArbitrageItem, ArbitrageResponse

logger = logging.getLogger("apix.api.arbitrage")

router = APIRouter()

@router.get(
    "",
    response_model=ArbitrageResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
@router.get(
    "/",
    response_model=ArbitrageResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
@router.get(
    "/arbitrage",
    response_model=ArbitrageResponse,
    status_code=status.HTTP_200_OK,
    summary="Get cross-platform flight price arbitrage spreads",
    description=(
        "Returns calculated price discrepancies between direct airline booking channels and "
        "major online travel agencies (OTAs) for identical flights across domestic routes."
    ),
)
async def get_arbitrage_opportunities(
    route_code: Optional[str] = Query(None, description="Optional route filter (e.g. DEL-BOM)"),
    airline_code: Optional[str] = Query(None, description="Optional airline filter (e.g. 6E, AI)"),
    min_spread_pct: float = Query(0.0, ge=0.0, description="Minimum spread percentage threshold"),
    actionable_only: bool = Query(False, description="Filter only actionable opportunities"),
    limit: int = Query(50, ge=1, le=500, description="Max opportunities to return"),
    db: Session = Depends(get_db),
) -> ArbitrageResponse:
    """Analyze price discrepancies across airline direct websites vs OTAs."""
    opportunities: List[ArbitrageItem] = []
    now = datetime.now(timezone.utc)

    # 1. Attempt to resolve from ArbitrageDetector service and database
    try:
        from backend.app.services.arbitrage_detector import get_current_arbitrage_opportunities

        db_opps = get_current_arbitrage_opportunities(
            db=db,
            min_spread_pct=min_spread_pct,
            limit=limit,
        )
        if db_opps:
            for opp in db_opps:
                # Convert ArbitrageOpportunity to ArbitrageItem
                d = opp.to_dict()
                opp_route = f"{d.get('origin', '')}-{d.get('destination', '')}".upper()
                if route_code and route_code.strip().upper() != opp_route:
                    continue
                if airline_code and airline_code.strip().upper() != d.get("airline_code", "").upper():
                    continue
                if actionable_only and not d.get("actionable", False):
                    continue

                item = ArbitrageItem(
                    route_code=opp_route,
                    airline_code=d.get("airline_code", ""),
                    flight_number=d.get("flight_number", ""),
                    origin=d.get("origin", ""),
                    destination=d.get("destination", ""),
                    departure_datetime=str(d.get("departure_datetime", "")),
                    cabin_class=d.get("cabin_class", "economy"),
                    direct_platform=d.get("direct_platform"),
                    direct_fare=d.get("direct_fare"),
                    ota_platform=d.get("ota_platform"),
                    ota_fare=d.get("ota_fare"),
                    buy_venue=d.get("buy_venue", "ota"),
                    buy_fare=float(d.get("buy_fare", 0.0)),
                    sell_venue=d.get("sell_venue", "direct"),
                    sell_fare=float(d.get("sell_fare", 0.0)),
                    spread_inr=float(d.get("spread_inr", 0.0)),
                    spread_percentage=float(d.get("spread_percentage", 0.0)),
                    direction=d.get("direction", "OTA_CHEAPER").upper(),
                    actionable=bool(d.get("actionable", True)),
                    detected_at=now,
                    net_profit_inr=float(d.get("net_profit_inr", 0.0)),
                )
                opportunities.append(item)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc

    # Limit results
    opportunities = opportunities[:limit]

    # Calculate aggregate summary stats
    routes_evaluated = len(set(o.route_code for o in opportunities))
    total_savings = round(sum(o.spread_inr for o in opportunities), 2)
    avg_spread = (
        round(sum(o.spread_percentage for o in opportunities) / max(len(opportunities), 1), 2)
        if opportunities
        else 0.0
    )

    return ArbitrageResponse(
        generated_at=now,
        routes_evaluated=routes_evaluated,
        opportunities_count=len(opportunities),
        total_potential_savings_inr=total_savings,
        avg_spread_percentage=avg_spread,
        items=opportunities,
    )
