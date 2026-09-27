"""Database migration module for updating existing apix.db instances with new corridors.

Ensures that any existing SQLite or PostgreSQL database instance gains the 4 new
directional corridors (DEL-MAA, MAA-DEL, BLR-HYD, HYD-BLR) and re-normalizes
all 14 corridor weights to sum to exactly 1.000000.
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from backend.app.db.seed import seed_routes
from backend.app.db.session import engine as default_engine
from backend.app.models.route import Route

logger = logging.getLogger("apix.db.migrate_corridors")


def migrate_corridors(
    session: Session | None = None,
    engine: Engine | None = None,
) -> list[Route]:
    """Ensure routes table in the target database has all 14 corridors with re-normalized weights.

    Idempotent: safe to run multiple times against any database.
    """
    if session is not None:
        return seed_routes(session)

    target_engine = engine or default_engine
    with Session(target_engine, expire_on_commit=False) as db_session:
        routes = seed_routes(db_session)
        db_session.commit()
        return routes


def main() -> int:
    """CLI entrypoint for corridor migration."""
    routes = migrate_corridors()
    print(f"Successfully migrated {len(routes)} corridors into the database.")
    for r in routes:
        print(
            f"  - {r.origin}->{r.destination}: weight={r.weight:.4f}, pax={r.dgca_monthly_pax}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
