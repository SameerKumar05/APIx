"""Guard against the ORM and the database schema drifting apart.

This exists because of a real near-miss. A migration added four columns to the
raw_fares model, every test passed, and the suite stayed green, because tests
build their database from Base.metadata.create_all and therefore always contain
whatever the ORM declares. The live apix.db did not have those columns, so six
read paths that hydrate full rows failed with "no such column", and the running
server only looked healthy because it still held pre-migration code in memory.

create_all creates missing tables. It does not add columns to existing ones. So a
green suite proves nothing about a deployed database, and a deployment that
skips `alembic upgrade head` breaks every full-row read.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect

import backend.app.models  # noqa: F401  (registers every mapper on Base.metadata)
from backend.app.db.session import Base

EXPECTED_PS_COLUMNS = {
    "booking_class",
    "udf_fee",
    "convenience_fee",
    "flight_status",
}


def test_orm_declares_every_ps_column() -> None:
    columns = set(Base.metadata.tables["raw_fares"].columns.keys())
    assert EXPECTED_PS_COLUMNS <= columns, sorted(EXPECTED_PS_COLUMNS - columns)


def test_migration_chain_reaches_a_schema_matching_the_orm(
    tmp_path, monkeypatch
) -> None:
    """alembic upgrade head must produce exactly the schema the ORM expects."""
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "drift.db"
    # migrations/env.py resolves the URL from DATABASE_URL and overrides any
    # sqlalchemy.url set on the Config, so the env var is the supported lever.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")

    command.upgrade(config, "head")

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    migrated = {c["name"] for c in inspector.get_columns("raw_fares")}
    orm = set(Base.metadata.tables["raw_fares"].columns.keys())

    assert migrated == orm, {
        "in_orm_not_in_db": sorted(orm - migrated),
        "in_db_not_in_orm": sorted(migrated - orm),
    }


def test_upgrading_a_pre_populated_table_is_additive(tmp_path, monkeypatch) -> None:
    """An existing database keeps its rows and gains the columns as NULL."""
    import sqlite3

    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        "CREATE TABLE raw_fares (id INTEGER PRIMARY KEY, total_fare FLOAT NOT NULL, hash_id VARCHAR(64) NOT NULL)"
    )
    legacy.execute("INSERT INTO raw_fares (total_fare, hash_id) VALUES (4200.0, 'abc')")
    legacy.commit()
    legacy.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    config = Config("alembic.ini")
    config.set_main_option("script_location", "migrations")
    command.upgrade(config, "head")

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT total_fare FROM raw_fares").fetchall()
    columns = {r[1] for r in conn.execute("PRAGMA table_info(raw_fares)")}
    conn.close()

    assert rows == [(4200.0,)]
    assert EXPECTED_PS_COLUMNS <= columns
