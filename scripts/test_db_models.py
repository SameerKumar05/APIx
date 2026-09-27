"""Standalone verification script for APIx database models and seed data.

Boots an in-memory SQLite database, verifies table creation across all models,
executes seed data routines, and asserts invariants:
  - Exactly 10 directional corridors seeded
  - Exactly 5 commercial airlines seeded
  - Sum of DGCA passenger weights == 1.000000
  - Table schemas, constraints, and relationships functioning properly
"""

from __future__ import annotations

import math
import os
import sys
from datetime import UTC, date, datetime, timezone
from pathlib import Path

# Ensure backend package is in python path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

# Auto-detect virtualenv if dependencies are not in current python environment
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
from sqlalchemy import create_engine, event, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.db.seed import INITIAL_AIRLINES, INITIAL_ROUTES, seed_all
from backend.app.db.session import Base
from backend.app.models import (
    Airline,
    AnomalyAlert,
    NationalDailyIndex,
    RawFare,
    Route,
    RouteDailyIndex,
    ScrapingRun,
)


def run_tests() -> bool:
    print("=" * 70)
    print("APIx Database Models & DGCA Baseline Verification")
    print("=" * 70)

    # 1. Create In-Memory SQLite Engine
    print("\n[1/6] Initializing in-memory SQLite database...")
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )

    @event.listens_for(test_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestSession = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine, expire_on_commit=False
    )

    # 2. Verify Table Creation
    print("[2/6] Creating all registered tables via Base.metadata.create_all()...")
    Base.metadata.create_all(bind=test_engine)

    inspector = inspect(test_engine)
    created_tables = set(inspector.get_table_names())
    expected_tables = {
        "routes",
        "airlines",
        "raw_fares",
        "route_daily_indices",
        "national_daily_indices",
        "anomaly_alerts",
        "scraping_runs",
    }
    missing_tables = expected_tables - created_tables
    if missing_tables:
        print(f"FAILED: Missing expected tables: {missing_tables}")
        return False
    print(f"  -> All {len(expected_tables)} tables created: {sorted(created_tables)}")

    with TestSession() as session:
        # 3. Seed Reference Data
        print("\n[3/6] Running seed routines (routes & airlines)...")
        seed_result = seed_all(session)
        print(
            f"  -> Seeded {seed_result['routes']} routes and {seed_result['airlines']} airlines."
        )

        # 4. Verify Route Counts and DGCA Weights
        print("\n[4/6] Verifying Route table invariants...")
        routes = session.execute(select(Route)).scalars().all()
        assert len(routes) == 10, f"Expected 10 routes, found {len(routes)}"
        print(f"  -> Route count verified: {len(routes)}/10 directional corridors.")

        expected_pairs = {
            ("DEL", "BOM"),
            ("BOM", "DEL"),
            ("BLR", "DEL"),
            ("DEL", "BLR"),
            ("BOM", "BLR"),
            ("BLR", "BOM"),
            ("DEL", "CCU"),
            ("CCU", "DEL"),
            ("DEL", "HYD"),
            ("HYD", "DEL"),
        }
        actual_pairs = {(r.origin, r.destination) for r in routes}
        assert (
            actual_pairs == expected_pairs
        ), f"Route pairs mismatch: {actual_pairs ^ expected_pairs}"

        total_weight = sum(r.weight for r in routes)
        total_pax = sum(r.dgca_monthly_pax for r in routes)
        print(f"  -> Total DGCA monthly pax: {total_pax:,}")
        print(f"  -> Total basket weight sum: {total_weight:.6f}")

        if not math.isclose(total_weight, 1.0, rel_tol=1e-5):
            print(f"FAILED: Total weight {total_weight} does not equal 1.000!")
            return False
        print("  -> Sum of DGCA route weights == 1.000 (CONFIRMED)")

        # Verify Airlines
        print("\n[5/6] Verifying Airline table invariants...")
        airlines = session.execute(select(Airline)).scalars().all()
        assert len(airlines) == 5, f"Expected 5 airlines, found {len(airlines)}"
        print(f"  -> Airline count verified: {len(airlines)}/5 carriers.")

        airline_dict = {a.code: a for a in airlines}
        for expected in INITIAL_AIRLINES:
            code = expected["code"]
            assert code in airline_dict, f"Missing airline {code}"
            assert airline_dict[code].market_share_pct == expected["market_share_pct"]
            print(
                f"     - {code}: {airline_dict[code].name} ({airline_dict[code].market_share_pct}%)"
            )

        total_airline_share = sum(a.market_share_pct for a in airlines)
        print(f"  -> Total airline market share sum: {total_airline_share:.1f}%")
        if not math.isclose(total_airline_share, 100.0, rel_tol=1e-5):
            print(
                f"FAILED: Total airline share {total_airline_share}% does not equal 100.0%!"
            )
            return False
        print("  -> Sum of airline market shares == 100.0% (CONFIRMED)")

        # 5. Verify Operational Models (RawFare, Index, Anomaly, ScrapingRun)
        print("\n[6/6] Verifying operational models CRUD and constraints...")

        # Test RawFare
        now_utc = datetime.now(UTC)
        test_fare = RawFare(
            batch_id="batch-test-001",
            origin="DEL",
            destination="BOM",
            flight_date=date(2026, 9, 25),
            booking_window="T+1",
            airline_code="6E",
            flight_number="6E-2015",
            departure_time=now_utc,
            arrival_time=now_utc,
            duration_minutes=130,
            stops=0,
            fare_class="Economy",
            base_fare=4500.0,
            taxes_and_fees=650.0,
            total_fare=5150.0,
            source_platform="makemytrip",
            scraped_at=now_utc,
            hash_id="a1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef",
            is_synthetic=False,
        )
        session.add(test_fare)
        session.commit()
        print("  -> RawFare insertion successful.")

        # Test Unique Constraint on hash_id
        duplicate_fare = RawFare(
            batch_id="batch-test-002",
            origin="DEL",
            destination="BOM",
            flight_date=date(2026, 9, 25),
            booking_window="T+1",
            airline_code="6E",
            flight_number="6E-2015",
            total_fare=5150.0,
            source_platform="easemytrip",
            hash_id="a1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef",
        )
        session.add(duplicate_fare)
        try:
            session.commit()
            print("FAILED: Duplicate hash_id was allowed!")
            return False
        except IntegrityError:
            session.rollback()
            print(
                "  -> RawFare unique hash_id constraint verified (duplicate rejected)."
            )

        # Test RouteDailyIndex
        route_del_bom = routes[0]
        route_index = RouteDailyIndex(
            route_id=route_del_bom.id,
            origin="DEL",
            destination="BOM",
            index_date=date(2026, 9, 24),
            booking_window="T+1",
            index_type="weighted_median",
            sample_size=42,
            median_fare=4850.0,
            mean_fare=4920.0,
            min_fare=3800.0,
            max_fare=7200.0,
            percentile_25=4400.0,
            percentile_75=5400.0,
            std_dev=620.0,
            index_value=103.5,
            base_period="2026-01-01",
        )
        session.add(route_index)

        # Test NationalDailyIndex
        nat_index = NationalDailyIndex(
            index_date=date(2026, 9, 24),
            booking_window="COMPOSITE",
            index_type="weighted_median",
            index_value=102.15,
            weighted_median_fare=5120.0,
            weighted_mean_fare=5250.0,
            total_samples=420,
            routes_covered=10,
            inflation_dod_pct=0.45,
            inflation_mom_pct=2.30,
            base_period="2026-01-01",
        )
        session.add(nat_index)

        # Test AnomalyAlert
        alert = AnomalyAlert(
            route_id=route_del_bom.id,
            origin="DEL",
            destination="BOM",
            airline_code="6E",
            alert_type="SPIKE",
            severity="HIGH",
            flight_date=date(2026, 9, 25),
            booking_window="T+1",
            detected_fare=9800.0,
            baseline_fare=4850.0,
            z_score=3.45,
            pct_change=102.06,
            description="Sudden 102% fare spike detected for DEL-BOM T+1 departure",
            status="OPEN",
        )
        session.add(alert)

        # Test ScrapingRun
        run = ScrapingRun(
            batch_id="run-20260924-001",
            source_platform="makemytrip",
            status="COMPLETED",
            routes_attempted=10,
            routes_succeeded=10,
            fares_collected=450,
            fares_deduplicated=420,
            started_at=now_utc,
            completed_at=now_utc,
            duration_seconds=14.5,
        )
        session.add(run)
        session.commit()

        # Query all and assert presence
        assert session.execute(select(func.count(RouteDailyIndex.id))).scalar() == 1
        assert session.execute(select(func.count(NationalDailyIndex.id))).scalar() == 1
        assert session.execute(select(func.count(AnomalyAlert.id))).scalar() == 1
        assert session.execute(select(func.count(ScrapingRun.id))).scalar() == 1
        print(
            "  -> RouteDailyIndex, NationalDailyIndex, AnomalyAlert, and ScrapingRun models verified."
        )

    print("\n" + "=" * 70)
    print(
        "ALL VERIFICATION CHECKS PASSED SUCCESSFULLY (10 routes, 5 airlines, sum=1.000)"
    )
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
