"""Database seeding script for APIx.

Populates the 10 trunk corridors with modelled passenger weights (normalized to 1.000)
and five carriers with modelled market-share literals. These figures are not DGCA
statistics and are not an official market-share release.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.session import SessionLocal, init_db
from backend.app.models.airline import Airline
from backend.app.models.route import Route

logger = logging.getLogger("apix.db.seed")

# Modelled corridor weights, not a DGCA release. Total Pax = 2,500,000 | Sum = 1.0000
INITIAL_ROUTES: list[dict[str, Any]] = [
    {
        "origin": "DEL",
        "destination": "BOM",
        "distance_km": 1148.0,
        "dgca_monthly_pax": 437500,
        "weight": 0.175,
        "is_active": True,
    },
    {
        "origin": "BOM",
        "destination": "DEL",
        "distance_km": 1148.0,
        "dgca_monthly_pax": 437500,
        "weight": 0.175,
        "is_active": True,
    },
    {
        "origin": "BLR",
        "destination": "DEL",
        "distance_km": 1740.0,
        "dgca_monthly_pax": 312500,
        "weight": 0.125,
        "is_active": True,
    },
    {
        "origin": "DEL",
        "destination": "BLR",
        "distance_km": 1740.0,
        "dgca_monthly_pax": 312500,
        "weight": 0.125,
        "is_active": True,
    },
    {
        "origin": "BOM",
        "destination": "BLR",
        "distance_km": 842.0,
        "dgca_monthly_pax": 225000,
        "weight": 0.090,
        "is_active": True,
    },
    {
        "origin": "BLR",
        "destination": "BOM",
        "distance_km": 842.0,
        "dgca_monthly_pax": 225000,
        "weight": 0.090,
        "is_active": True,
    },
    {
        "origin": "DEL",
        "destination": "CCU",
        "distance_km": 1305.0,
        "dgca_monthly_pax": 162500,
        "weight": 0.065,
        "is_active": True,
    },
    {
        "origin": "CCU",
        "destination": "DEL",
        "distance_km": 1305.0,
        "dgca_monthly_pax": 162500,
        "weight": 0.065,
        "is_active": True,
    },
    {
        "origin": "DEL",
        "destination": "HYD",
        "distance_km": 1253.0,
        "dgca_monthly_pax": 112500,
        "weight": 0.045,
        "is_active": True,
    },
    {
        "origin": "HYD",
        "destination": "DEL",
        "distance_km": 1253.0,
        "dgca_monthly_pax": 112500,
        "weight": 0.045,
        "is_active": True,
    },
]

# Modelled carrier shares, not official DGCA market share.
INITIAL_AIRLINES: list[dict[str, Any]] = [
    {
        "code": "6E",
        "name": "IndiGo",
        "market_share_pct": 62.0,
        "is_active": True,
    },
    {
        "code": "AI",
        "name": "Air India",
        "market_share_pct": 20.0,
        "is_active": True,
    },
    {
        "code": "IX",
        "name": "Air India Express",
        "market_share_pct": 8.0,
        "is_active": True,
    },
    {
        "code": "QP",
        "name": "Akasa Air",
        "market_share_pct": 5.0,
        "is_active": True,
    },
    {
        "code": "SG",
        "name": "SpiceJet",
        "market_share_pct": 4.0,
        "is_active": True,
    },
]


def seed_routes(session: Session) -> list[Route]:
    """Seed or update the 10 directional corridors idempotently.

    Returns:
        List of Route instances in the session.
    """
    seeded: list[Route] = []
    for r_data in INITIAL_ROUTES:
        stmt = select(Route).where(
            Route.origin == r_data["origin"],
            Route.destination == r_data["destination"],
        )
        existing = session.execute(stmt).scalar_one_or_none()
        if existing:
            existing.distance_km = r_data["distance_km"]
            existing.dgca_monthly_pax = r_data["dgca_monthly_pax"]
            existing.weight = r_data["weight"]
            existing.is_active = r_data["is_active"]
            seeded.append(existing)
        else:
            route = Route(
                origin=r_data["origin"],
                destination=r_data["destination"],
                distance_km=r_data["distance_km"],
                dgca_monthly_pax=r_data["dgca_monthly_pax"],
                weight=r_data["weight"],
                is_active=r_data["is_active"],
            )
            session.add(route)
            seeded.append(route)
    session.flush()
    return seeded


def seed_airlines(session: Session) -> list[Airline]:
    """Seed or update the 5 domestic carriers idempotently.

    Returns:
        List of Airline instances in the session.
    """
    seeded: list[Airline] = []
    for a_data in INITIAL_AIRLINES:
        stmt = select(Airline).where(Airline.code == a_data["code"])
        existing = session.execute(stmt).scalar_one_or_none()
        if existing:
            existing.name = a_data["name"]
            existing.market_share_pct = a_data["market_share_pct"]
            existing.is_active = a_data["is_active"]
            seeded.append(existing)
        else:
            airline = Airline(
                code=a_data["code"],
                name=a_data["name"],
                market_share_pct=a_data["market_share_pct"],
                is_active=a_data["is_active"],
            )
            session.add(airline)
            seeded.append(airline)
    session.flush()
    return seeded


def seed_all(session: Session) -> dict[str, int]:
    """Seed all initial static reference data (routes and airlines).

    Returns:
        Dictionary with count of routes and airlines seeded.
    """
    routes = seed_routes(session)
    airlines = seed_airlines(session)
    session.commit()
    logger.info(
        "Seeded %d routes and %d airlines successfully.",
        len(routes),
        len(airlines),
    )
    return {"routes": len(routes), "airlines": len(airlines)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Initializing database tables...")
    init_db()
    with SessionLocal() as db_session:
        results = seed_all(db_session)
        print(
            f"Seeding complete: {results['routes']} routes, {results['airlines']} airlines."
        )
