"""Tests for database migration logic upgrading existing databases to 14 corridors."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.db.migrate_corridors import migrate_corridors
from backend.app.models.route import Route

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_14_ROUTES = {
    "DEL-BOM",
    "BOM-DEL",
    "BLR-DEL",
    "DEL-BLR",
    "BOM-BLR",
    "BLR-BOM",
    "DEL-CCU",
    "CCU-DEL",
    "DEL-HYD",
    "HYD-DEL",
    "DEL-MAA",
    "MAA-DEL",
    "BLR-HYD",
    "HYD-BLR",
}


def _seed_legacy_10_routes(db_path: Path) -> None:
    """Create a legacy SQLite database containing only the original 10 routes."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin VARCHAR(3) NOT NULL,
            destination VARCHAR(3) NOT NULL,
            distance_km FLOAT NOT NULL,
            dgca_monthly_pax INTEGER NOT NULL,
            weight FLOAT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    legacy_10 = [
        ("DEL", "BOM", 1148.0, 437500, 0.175),
        ("BOM", "DEL", 1148.0, 437500, 0.175),
        ("BLR", "DEL", 1740.0, 312500, 0.125),
        ("DEL", "BLR", 1740.0, 312500, 0.125),
        ("BOM", "BLR", 842.0, 225000, 0.090),
        ("BLR", "BOM", 842.0, 225000, 0.090),
        ("DEL", "CCU", 1305.0, 162500, 0.065),
        ("CCU", "DEL", 1305.0, 162500, 0.065),
        ("DEL", "HYD", 1253.0, 112500, 0.045),
        ("HYD", "DEL", 1253.0, 112500, 0.045),
    ]
    for origin, dest, dist, pax, w in legacy_10:
        conn.execute(
            "INSERT INTO routes (origin, destination, distance_km, dgca_monthly_pax, weight, is_active) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (origin, dest, dist, pax, w),
        )
    conn.commit()
    conn.close()


def test_migrate_corridors_upgrades_legacy_db_to_14_corridors(tmp_path: Path) -> None:
    """Legacy 10-route database gains 4 corridors and updates existing weights."""
    db_file = tmp_path / "legacy.db"
    _seed_legacy_10_routes(db_file)

    test_engine = create_engine(f"sqlite:///{db_file}")

    # Verify starting state: exactly 10 routes
    with Session(test_engine) as session:
        initial_count = len(session.scalars(select(Route)).all())
        assert initial_count == 10

    # Run migration
    routes = migrate_corridors(engine=test_engine)
    assert len(routes) == 14

    # Verify resulting state: exactly 14 routes with 1.000000 weight sum
    with Session(test_engine) as session:
        all_routes = session.scalars(select(Route)).all()
        assert len(all_routes) == 14
        route_pairs = {f"{r.origin}-{r.destination}" for r in all_routes}
        assert route_pairs == EXPECTED_14_ROUTES

        total_weight = sum(r.weight for r in all_routes)
        assert total_weight == pytest.approx(1.0, abs=1e-9)

        # Check newly added corridors
        maa_del = next(
            r for r in all_routes if r.origin == "MAA" and r.destination == "DEL"
        )
        assert maa_del.weight == pytest.approx(0.040)
        assert maa_del.dgca_monthly_pax == 120000

        blr_hyd = next(
            r for r in all_routes if r.origin == "BLR" and r.destination == "HYD"
        )
        assert blr_hyd.weight == pytest.approx(0.025)
        assert blr_hyd.dgca_monthly_pax == 75000


def test_migrate_corridors_is_strictly_idempotent(tmp_path: Path) -> None:
    """Running migrate_corridors multiple times does not duplicate routes or corrupt weights."""
    db_file = tmp_path / "idempotent.db"
    _seed_legacy_10_routes(db_file)
    test_engine = create_engine(f"sqlite:///{db_file}")

    # First run
    migrate_corridors(engine=test_engine)

    # Second run
    routes_run2 = migrate_corridors(engine=test_engine)
    assert len(routes_run2) == 14

    # Third run
    routes_run3 = migrate_corridors(engine=test_engine)
    assert len(routes_run3) == 14

    with Session(test_engine) as session:
        final_routes = session.scalars(select(Route)).all()
        assert len(final_routes) == 14
        assert sum(r.weight for r in final_routes) == pytest.approx(1.0, abs=1e-9)


def test_alembic_migration_upgrades_routes_to_14_corridors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alembic upgrade head applies d9f4e2b1c005 and upgrades routes."""
    db_file = tmp_path / "alembic_test.db"
    _seed_legacy_10_routes(db_file)

    database_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

    command.upgrade(cfg, "head")

    conn = sqlite3.connect(db_file)
    rows = conn.execute(
        "SELECT origin, destination, weight, dgca_monthly_pax FROM routes"
    ).fetchall()
    conn.close()

    assert len(rows) == 14
    pairs = {f"{r[0]}-{r[1]}" for r in rows}
    assert pairs == EXPECTED_14_ROUTES
    total_w = sum(r[2] for r in rows)
    assert total_w == pytest.approx(1.0, abs=1e-9)
