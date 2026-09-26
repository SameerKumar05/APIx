"""Alembic upgrade head adds the four raw-fare columns without rewriting rows."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", database_url)
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def test_alembic_upgrade_head_on_empty_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "empty.db"
    url = f"sqlite:///{db_path}"
    command.upgrade(_alembic_config(url, monkeypatch), "head")

    engine = create_engine(url)
    columns = {column["name"] for column in inspect(engine).get_columns("raw_fares")}
    assert {
        "booking_class",
        "udf_fee",
        "convenience_fee",
        "flight_status",
    } <= columns
    engine.dispose()


def test_alembic_upgrade_adds_null_columns_on_populated_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "populated.db"
    url = f"sqlite:///{db_path}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("""
                CREATE TABLE raw_fares (
                    id INTEGER PRIMARY KEY,
                    batch_id VARCHAR(100) NOT NULL,
                    origin VARCHAR(3) NOT NULL,
                    destination VARCHAR(3) NOT NULL,
                    flight_date DATE NOT NULL,
                    booking_window VARCHAR(10) NOT NULL,
                    airline_code VARCHAR(3) NOT NULL,
                    flight_number VARCHAR(20) NOT NULL,
                    stops INTEGER NOT NULL,
                    fare_class VARCHAR(50) NOT NULL,
                    base_fare FLOAT NOT NULL,
                    taxes_and_fees FLOAT NOT NULL,
                    total_fare FLOAT NOT NULL,
                    source_platform VARCHAR(50) NOT NULL,
                    scraped_at DATETIME NOT NULL,
                    hash_id VARCHAR(64) NOT NULL UNIQUE,
                    is_synthetic BOOLEAN NOT NULL
                )
                """))
        connection.execute(text("""
                INSERT INTO raw_fares (
                    batch_id, origin, destination, flight_date, booking_window,
                    airline_code, flight_number, stops, fare_class, base_fare,
                    taxes_and_fees, total_fare, source_platform, scraped_at,
                    hash_id, is_synthetic
                ) VALUES (
                    'legacy', 'DEL', 'BOM', '2026-10-01', 'T+7',
                    '6E', '6E-9', 0, 'Economy', 4250.0,
                    750.0, 5000.0, 'synthetic', '2026-09-01T00:00:00',
                    'legacy-hash', 1
                )
                """))

    command.upgrade(_alembic_config(url, monkeypatch), "head")

    with engine.connect() as connection:
        row = connection.execute(text("""
                SELECT total_fare, base_fare, booking_class, udf_fee,
                       convenience_fee, flight_status
                FROM raw_fares
                WHERE hash_id = 'legacy-hash'
                """)).one()
    assert row.total_fare == 5000.0
    assert row.base_fare == 4250.0
    assert row.booking_class is None
    assert row.udf_fee is None
    assert row.convenience_fee is None
    assert row.flight_status is None
    engine.dispose()
