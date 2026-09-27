"""add missing corridors MAA-DEL and BLR-HYD to routes table

Revision ID: d9f4e2b1c005
Revises: b8c3d2e7a004
Create Date: 2026-09-28

"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "d9f4e2b1c005"
down_revision: str | Sequence[str] | None = "b8c3d2e7a004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPDATED_WEIGHTS: list[dict[str, Any]] = [
    {
        "origin": "DEL",
        "destination": "BOM",
        "distance_km": 1148.0,
        "dgca_monthly_pax": 450000,
        "weight": 0.150,
        "is_active": True,
    },
    {
        "origin": "BOM",
        "destination": "DEL",
        "distance_km": 1148.0,
        "dgca_monthly_pax": 450000,
        "weight": 0.150,
        "is_active": True,
    },
    {
        "origin": "BLR",
        "destination": "DEL",
        "distance_km": 1740.0,
        "dgca_monthly_pax": 330000,
        "weight": 0.110,
        "is_active": True,
    },
    {
        "origin": "DEL",
        "destination": "BLR",
        "distance_km": 1740.0,
        "dgca_monthly_pax": 330000,
        "weight": 0.110,
        "is_active": True,
    },
    {
        "origin": "BOM",
        "destination": "BLR",
        "distance_km": 842.0,
        "dgca_monthly_pax": 240000,
        "weight": 0.080,
        "is_active": True,
    },
    {
        "origin": "BLR",
        "destination": "BOM",
        "distance_km": 842.0,
        "dgca_monthly_pax": 240000,
        "weight": 0.080,
        "is_active": True,
    },
    {
        "origin": "DEL",
        "destination": "CCU",
        "distance_km": 1305.0,
        "dgca_monthly_pax": 165000,
        "weight": 0.055,
        "is_active": True,
    },
    {
        "origin": "CCU",
        "destination": "DEL",
        "distance_km": 1305.0,
        "dgca_monthly_pax": 165000,
        "weight": 0.055,
        "is_active": True,
    },
    {
        "origin": "DEL",
        "destination": "HYD",
        "distance_km": 1253.0,
        "dgca_monthly_pax": 120000,
        "weight": 0.040,
        "is_active": True,
    },
    {
        "origin": "HYD",
        "destination": "DEL",
        "distance_km": 1253.0,
        "dgca_monthly_pax": 120000,
        "weight": 0.040,
        "is_active": True,
    },
    {
        "origin": "DEL",
        "destination": "MAA",
        "distance_km": 1757.0,
        "dgca_monthly_pax": 120000,
        "weight": 0.040,
        "is_active": True,
    },
    {
        "origin": "MAA",
        "destination": "DEL",
        "distance_km": 1757.0,
        "dgca_monthly_pax": 120000,
        "weight": 0.040,
        "is_active": True,
    },
    {
        "origin": "BLR",
        "destination": "HYD",
        "distance_km": 504.0,
        "dgca_monthly_pax": 75000,
        "weight": 0.025,
        "is_active": True,
    },
    {
        "origin": "HYD",
        "destination": "BLR",
        "distance_km": 504.0,
        "dgca_monthly_pax": 75000,
        "weight": 0.025,
        "is_active": True,
    },
]


def upgrade() -> None:
    """Synchronize route catalogue to the 14-corridor basket in existing databases."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("routes"):
        return

    routes_table = sa.table(
        "routes",
        sa.column("id", sa.Integer),
        sa.column("origin", sa.String),
        sa.column("destination", sa.String),
        sa.column("distance_km", sa.Float),
        sa.column("dgca_monthly_pax", sa.Integer),
        sa.column("weight", sa.Float),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    existing_rows = bind.execute(
        sa.select(routes_table.c.origin, routes_table.c.destination)
    ).fetchall()
    existing_pairs = {(str(r[0]), str(r[1])) for r in existing_rows}
    now = datetime.now(UTC)

    for r in _UPDATED_WEIGHTS:
        origin = str(r["origin"])
        dest = str(r["destination"])
        if (origin, dest) in existing_pairs:
            bind.execute(
                routes_table.update()
                .where(
                    routes_table.c.origin == origin,
                    routes_table.c.destination == dest,
                )
                .values(
                    distance_km=r["distance_km"],
                    dgca_monthly_pax=r["dgca_monthly_pax"],
                    weight=r["weight"],
                    is_active=r["is_active"],
                    updated_at=now,
                )
            )
        else:
            bind.execute(
                routes_table.insert().values(
                    origin=origin,
                    destination=dest,
                    distance_km=r["distance_km"],
                    dgca_monthly_pax=r["dgca_monthly_pax"],
                    weight=r["weight"],
                    is_active=r["is_active"],
                    created_at=now,
                    updated_at=now,
                )
            )


def downgrade() -> None:
    """Revert routes table to 10-corridor baseline."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("routes"):
        return

    routes_table = sa.table(
        "routes",
        sa.column("origin", sa.String),
        sa.column("destination", sa.String),
    )
    for origin, dest in [
        ("DEL", "MAA"),
        ("MAA", "DEL"),
        ("BLR", "HYD"),
        ("HYD", "BLR"),
    ]:
        bind.execute(
            routes_table.delete().where(
                routes_table.c.origin == origin,
                routes_table.c.destination == dest,
            )
        )
