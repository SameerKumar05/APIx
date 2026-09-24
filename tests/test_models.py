"""Unit tests for APIx database models, session management, and DGCA seed data."""

from __future__ import annotations

import math
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

try:
    import sqlalchemy
except ImportError:
    for candidate in [
        repo_root / ".venv" / "bin" / "python",
        repo_root.parent.parent / ".venv" / "bin" / "python",
    ]:
        if candidate.exists() and sys.executable != str(candidate):
            os.execv(str(candidate), [str(candidate)] + sys.argv)
    raise

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.seed import (
    seed_all,
)
from backend.app.db.session import Base
from backend.app.models import (
    AnomalyAlert,
    NationalDailyIndex,
    RawFare,
    Route,
    RouteDailyIndex,
)


@pytest.fixture
def db_session() -> Session:
    """Fixture providing an isolated in-memory SQLite database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_seed_routes_and_airlines(db_session: Session) -> None:
    """Verify that exactly 10 routes and 5 airlines are seeded, and weights sum to 1.000."""
    result = seed_all(db_session)
    assert result["routes"] == 10
    assert result["airlines"] == 5

    routes = db_session.execute(select(Route)).scalars().all()
    assert len(routes) == 10

    total_weight = sum(r.weight for r in routes)
    assert math.isclose(total_weight, 1.0, rel_tol=1e-6)

    total_pax = sum(r.dgca_monthly_pax for r in routes)
    assert total_pax == 2500000

    # Ensure idempotency
    result_second = seed_all(db_session)
    assert result_second["routes"] == 10
    assert result_second["airlines"] == 5
    assert len(db_session.execute(select(Route)).scalars().all()) == 10


def test_raw_fare_unique_hash(db_session: Session) -> None:
    """Verify RawFare table unique hash constraint for deduplication."""
    now_utc = datetime.now(UTC)
    fare1 = RawFare(
        batch_id="batch-01",
        origin="DEL",
        destination="BOM",
        flight_date=date(2026, 9, 25),
        booking_window="T+1",
        airline_code="6E",
        flight_number="6E-2015",
        total_fare=4999.0,
        source_platform="makemytrip",
        scraped_at=now_utc,
        hash_id="unique-hash-12345",
    )
    db_session.add(fare1)
    db_session.commit()

    fare_dup = RawFare(
        batch_id="batch-02",
        origin="DEL",
        destination="BOM",
        flight_date=date(2026, 9, 25),
        booking_window="T+1",
        airline_code="6E",
        flight_number="6E-2015",
        total_fare=4999.0,
        source_platform="easemytrip",
        scraped_at=now_utc,
        hash_id="unique-hash-12345",
    )
    db_session.add(fare_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_daily_indices_and_alerts(db_session: Session) -> None:
    """Verify creation and query of daily indices and anomaly alerts."""
    seed_all(db_session)
    route = db_session.execute(
        select(Route).where(Route.origin == "DEL", Route.destination == "BOM")
    ).scalar_one()

    r_index = RouteDailyIndex(
        route_id=route.id,
        origin=route.origin,
        destination=route.destination,
        index_date=date(2026, 9, 24),
        booking_window="T+1",
        index_type="weighted_median",
        sample_size=50,
        median_fare=4500.0,
        mean_fare=4620.0,
        index_value=101.5,
    )
    db_session.add(r_index)

    n_index = NationalDailyIndex(
        index_date=date(2026, 9, 24),
        booking_window="COMPOSITE",
        index_type="weighted_median",
        index_value=102.10,
        weighted_median_fare=4800.0,
        weighted_mean_fare=4950.0,
        total_samples=500,
        routes_covered=10,
    )
    db_session.add(n_index)

    alert = AnomalyAlert(
        route_id=route.id,
        origin="DEL",
        destination="BOM",
        alert_type="SPIKE",
        severity="HIGH",
        detected_fare=9500.0,
        baseline_fare=4500.0,
        z_score=3.2,
        pct_change=111.1,
    )
    db_session.add(alert)
    db_session.commit()

    assert r_index.id is not None
    assert n_index.id is not None
    assert alert.id is not None
    assert r_index.route.route_code == "DEL-BOM"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main(["-v", __file__]))
