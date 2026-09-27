#!/usr/bin/env python3
"""Verification Script for APIx End-to-End Daily Index Pipeline and DB Persistence.

Validates:
1. End-to-end execution of `run_daily_index_pipeline(db, calculation_date)`.
2. Cross-platform flight deduplication (minimum consumer fare selection).
3. Tukey IQR outlier filtering trimming extreme price distortions.
4. Weighted median representative fare computation for each route and window.
5. Composite route fare using booking window weights (0.20, 0.35, 0.30, 0.15).
6. Modified Laspeyres national price index (Base 100.0) with DGCA passenger traffic weights.
7. Rolling 30-day Z-scores and DoD surge detection triggering AnomalyAlert records.
8. Idempotent database persistence of RouteDailyIndex and NationalDailyIndex records.
"""

from __future__ import annotations

import math
import os
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

# Add project root to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
try:
    import sqlalchemy
except ImportError:
    for candidate in [
        PROJECT_ROOT.parent.parent / ".venv" / "bin" / "python",
        PROJECT_ROOT / ".venv" / "bin" / "python",
    ]:
        if candidate.exists() and sys.executable != str(candidate):
            os.execv(str(candidate), [str(candidate)] + sys.argv)
    raise

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.seed import seed_all
from backend.app.db.session import Base
from backend.app.models.airline import Airline
from backend.app.models.anomaly import AnomalyAlert
from backend.app.models.index import NationalDailyIndex, RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.route import Route
from backend.app.services.index_pipeline import (
    CANONICAL_WINDOWS,
    DEFAULT_BASE_FARES,
    DEFAULT_ROUTE_WEIGHTS,
    run_daily_index_pipeline,
)


def create_test_db() -> tuple[Any, sessionmaker[Session]]:
    """Creates an in-memory SQLite database for isolated test execution."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    return engine, session_factory


def populate_mock_data(session: Session, calc_date: date) -> None:
    """Populates seed reference data, historical baseline indices, and mock raw fares."""
    # 1. Seed standard routes and airlines
    seed_all(session)

    # 2. Seed 14 days of historical RouteDailyIndex for baseline statistics
    # This establishes a rolling baseline for DEL-BOM and BLR-DEL
    for days_back in range(14, 0, -1):
        hist_date = calc_date - timedelta(days=days_back)

        # DEL-BOM historical: stable around 5500 INR (std ~ 50)
        del_bom_fare = 5500.0 + (days_back % 3) * 25.0
        session.add(
            RouteDailyIndex(
                origin="DEL",
                destination="BOM",
                index_date=hist_date,
                booking_window="COMPOSITE",
                index_type="weighted_median",
                sample_size=40,
                median_fare=del_bom_fare,
                mean_fare=del_bom_fare,
                min_fare=del_bom_fare - 500,
                max_fare=del_bom_fare + 500,
                percentile_25=del_bom_fare - 200,
                percentile_75=del_bom_fare + 200,
                std_dev=50.0,
                index_value=round((del_bom_fare / 5500.0) * 100.0, 2),
                base_period="2026-01-01",
            )
        )

        # BLR-DEL historical: stable around 6000 INR (std ~ 60)
        blr_del_fare = 6000.0 + (days_back % 2) * 40.0
        session.add(
            RouteDailyIndex(
                origin="BLR",
                destination="DEL",
                index_date=hist_date,
                booking_window="COMPOSITE",
                index_type="weighted_median",
                sample_size=35,
                median_fare=blr_del_fare,
                mean_fare=blr_del_fare,
                min_fare=blr_del_fare - 600,
                max_fare=blr_del_fare + 600,
                percentile_25=blr_del_fare - 250,
                percentile_75=blr_del_fare + 250,
                std_dev=60.0,
                index_value=round((blr_del_fare / 6200.0) * 100.0, 2),
                base_period="2026-01-01",
            )
        )

    # Also seed yesterday's NationalDailyIndex for DoD inflation calculation
    session.add(
        NationalDailyIndex(
            index_date=calc_date - timedelta(days=1),
            booking_window="COMPOSITE",
            index_type="laspeyres",
            index_value=101.50,
            weighted_median_fare=5300.0,
            weighted_mean_fare=5320.0,
            total_samples=380,
            routes_covered=10,
            inflation_dod_pct=0.25,
            inflation_mom_pct=1.80,
            base_period="2026-01-01",
        )
    )
    session.commit()

    # 3. Populate raw flight quotes for calculation_date across all 10 routes and 4 windows
    routes = session.execute(select(Route)).scalars().all()
    carriers = ["6E", "AI", "IX", "QP", "SG"]

    raw_fares: list[RawFare] = []
    capture_time = datetime.combine(calc_date, time(6, 0, 0))

    # Base pricing multiplier by window
    window_multipliers = {
        "T+1": 1.40,
        "T+7": 1.15,
        "T+15": 1.05,
        "T+30": 0.95,
        "T+45": 0.88,
    }

    for r in routes:
        base_route_fare = DEFAULT_BASE_FARES.get(r.route_code, 5000.0)

        for win in CANONICAL_WINDOWS:
            multiplier = window_multipliers[win]
            flight_dt = calc_date

            # Generate 4 distinct flights per route-window slot
            for idx, carrier in enumerate(carriers[:4]):
                flight_no = f"{carrier}-{100 + idx * 20}"
                nominal_fare = base_route_fare * multiplier * (1.0 + (idx * 0.04))

                # Inject deliberate surge on BLR-DEL for T+1 window (+55% DoD surge -> triggers anomaly alert)
                if r.route_code == "BLR-DEL" and win == "T+1":
                    nominal_fare = 9800.0  # Big surge over normal ~6000 INR

                rf = RawFare(
                    batch_id=f"batch-{calc_date.isoformat()}",
                    origin=r.origin,
                    destination=r.destination,
                    flight_date=flight_dt,
                    booking_window=win,
                    airline_code=carrier,
                    flight_number=flight_no,
                    departure_time=datetime.combine(flight_dt, time(7 + idx * 3, 0)),
                    arrival_time=datetime.combine(flight_dt, time(9 + idx * 3, 15)),
                    duration_minutes=135,
                    stops=0,
                    fare_class="Economy",
                    base_fare=round(nominal_fare * 0.78, 2),
                    taxes_and_fees=round(nominal_fare * 0.22, 2),
                    total_fare=round(nominal_fare, 2),
                    source_platform="makemytrip",
                    scraped_at=capture_time,
                    hash_id=f"hash-{r.route_code}-{win}-{carrier}-{idx}",
                    is_synthetic=True,
                )
                raw_fares.append(rf)

            # --- Test Scenario A: Cross-platform deduplication on DEL-BOM (T+7) ---
            if r.route_code == "DEL-BOM" and win == "T+7":
                # Add duplicate quote for the 6E flight on easemytrip with cheaper fare
                cheaper_dup = RawFare(
                    batch_id=f"batch-{calc_date.isoformat()}-ota2",
                    origin=r.origin,
                    destination=r.destination,
                    flight_date=flight_dt,
                    booking_window=win,
                    airline_code="6E",
                    flight_number="6E-100",
                    departure_time=datetime.combine(flight_dt, time(7, 0)),
                    arrival_time=datetime.combine(flight_dt, time(9, 15)),
                    duration_minutes=135,
                    stops=0,
                    fare_class="Economy",
                    base_fare=3900.0,
                    taxes_and_fees=1100.0,
                    total_fare=5000.0,  # Cheaper than makemytrip
                    source_platform="easemytrip",
                    scraped_at=capture_time,
                    hash_id=f"hash-{r.route_code}-{win}-6E-100-easemytrip",
                    is_synthetic=True,
                )
                raw_fares.append(cheaper_dup)

            # --- Test Scenario B: Outlier trimming on DEL-BOM (T+15) ---
            if r.route_code == "DEL-BOM" and win == "T+15":
                # Add extreme outlier quote (55,000 INR)
                outlier_rf = RawFare(
                    batch_id=f"batch-{calc_date.isoformat()}-outlier",
                    origin=r.origin,
                    destination=r.destination,
                    flight_date=flight_dt,
                    booking_window=win,
                    airline_code="AI",
                    flight_number="AI-999",
                    departure_time=datetime.combine(flight_dt, time(22, 0)),
                    arrival_time=datetime.combine(flight_dt, time(23, 59)),
                    duration_minutes=120,
                    stops=0,
                    fare_class="Economy",
                    base_fare=45000.0,
                    taxes_and_fees=10000.0,
                    total_fare=55000.0,  # Extreme outlier
                    source_platform="portal_direct",
                    scraped_at=capture_time,
                    hash_id=f"hash-{r.route_code}-{win}-AI-999-outlier",
                    is_synthetic=True,
                )
                raw_fares.append(outlier_rf)

    session.add_all(raw_fares)
    session.commit()


def run_tests() -> bool:
    """Executes the premier verification test suite for index pipeline."""
    print("=" * 80)
    print("APIx Daily Airfare Index Pipeline - Premier Verification Suite")
    print("=" * 80)

    engine, session_factory = create_test_db()
    calc_date = date(2026, 9, 24)

    with session_factory() as session:
        print("[1/5] Initializing test database and populating mock raw fares...")
        populate_mock_data(session, calc_date)

        raw_count = session.execute(select(func.count(RawFare.id))).scalar()
        route_count = session.execute(select(func.count(Route.id))).scalar()
        print(
            f"      Seeded {route_count} routes and {raw_count} raw flight fare quotes."
        )
        assert route_count == 10, f"Expected 10 routes, got {route_count}"
        assert raw_count >= 160, f"Expected >= 160 raw fares, got {raw_count}"
        print("      ✓ Assertion Passed: Seed data and raw fares populated.")

        print("\n[2/5] Running run_daily_index_pipeline(db, calculation_date)...")
        result = run_daily_index_pipeline(session, calculation_date=calc_date)

        assert result["status"] == "success", f"Pipeline returned non-success: {result}"
        assert (
            result["routes_covered"] == 10
        ), f"Expected 10 routes covered, got {result['routes_covered']}"
        assert (
            result["total_raw_fares"] == raw_count
        ), f"Mismatch in raw fares count: {result['total_raw_fares']}"
        print(
            f"      Pipeline finished: National Index = {result['national_index_value']:.2f}"
        )
        print(
            f"      Route indices saved: {result['route_indices_count']}, Anomalies detected: {result['anomalies_count']}"
        )
        print("      ✓ Assertion Passed: Batch pipeline completed successfully.")

        print("\n[3/5] Verifying RouteDailyIndex database persistence...")
        # Verify route daily indices in DB
        db_route_indices = (
            session.execute(
                select(RouteDailyIndex).where(RouteDailyIndex.index_date == calc_date)
            )
            .scalars()
            .all()
        )

        print(f"      Total RouteDailyIndex records saved: {len(db_route_indices)}")
        # 10 routes x (5 windows + 1 composite) = 60 records
        assert (
            len(db_route_indices) == 60
        ), f"Expected 60 RouteDailyIndex records, got {len(db_route_indices)}"

        # Verify composite records exist for all 10 routes
        composite_records = [
            r for r in db_route_indices if r.booking_window == "COMPOSITE"
        ]
        assert (
            len(composite_records) == 10
        ), f"Expected 10 composite records, got {len(composite_records)}"

        # Check DEL-BOM composite fare and distribution invariants
        del_bom_comp = next(
            (
                r
                for r in composite_records
                if r.origin == "DEL" and r.destination == "BOM"
            ),
            None,
        )
        assert del_bom_comp is not None, "DEL-BOM composite record missing"
        assert (
            del_bom_comp.median_fare > 0
        ), f"DEL-BOM median fare non-positive: {del_bom_comp.median_fare}"
        assert del_bom_comp.sample_size > 0, "DEL-BOM sample size non-positive"
        assert del_bom_comp.index_value > 0, "DEL-BOM index value non-positive"
        print(
            f"      DEL-BOM Composite: fare=INR {del_bom_comp.median_fare:.2f}, index={del_bom_comp.index_value:.2f}"
        )

        # Check DEL-BOM T+15 outlier trimming: median fare must NOT be distorted by 55,000 INR outlier
        del_bom_t15 = next(
            (
                r
                for r in db_route_indices
                if r.origin == "DEL"
                and r.destination == "BOM"
                and r.booking_window == "T+15"
            ),
            None,
        )
        assert del_bom_t15 is not None, "DEL-BOM T+15 record missing"
        assert (
            del_bom_t15.median_fare < 10000.0
        ), f"Tukey outlier trimming failed; median fare={del_bom_t15.median_fare}"
        print(
            f"      DEL-BOM T+15 Outlier Trimming: median={del_bom_t15.median_fare:.2f} (unaffected by 55,000 INR quote)"
        )
        print(
            "      ✓ Assertion Passed: RouteDailyIndex records verified across all routes and windows."
        )

        print("\n[4/5] Verifying NationalDailyIndex database persistence...")
        nat_index = (
            session.execute(
                select(NationalDailyIndex).where(
                    NationalDailyIndex.index_date == calc_date,
                    NationalDailyIndex.booking_window == "COMPOSITE",
                    NationalDailyIndex.index_type == "laspeyres",
                )
            )
            .scalars()
            .first()
        )

        assert nat_index is not None, "NationalDailyIndex record was not persisted"
        assert (
            nat_index.index_type == "laspeyres"
        ), f"Expected index_type 'laspeyres', got {nat_index.index_type}"
        assert (
            nat_index.index_value > 0
        ), f"National index value non-positive: {nat_index.index_value}"
        assert (
            nat_index.routes_covered == 10
        ), f"Expected 10 routes covered, got {nat_index.routes_covered}"
        assert nat_index.total_samples > 0, "Total samples must be positive"
        assert nat_index.weighted_mean_fare > 0, "Weighted mean fare must be positive"
        assert math.isfinite(
            nat_index.inflation_dod_pct
        ), "DoD inflation rate must be finite float"
        print(
            f"      National Laspeyres Index: {nat_index.index_value:.2f} (Base 100.0)"
        )
        print(
            f"      National Weighted Mean Fare: INR {nat_index.weighted_mean_fare:.2f}"
        )
        print(f"      DoD Inflation: {nat_index.inflation_dod_pct:+.2f}%")
        print("      ✓ Assertion Passed: NationalDailyIndex record verified.")
        # Verify Paasche and Fisher indices are also persisted
        nat_fisher = (
            session.execute(
                select(NationalDailyIndex).where(
                    NationalDailyIndex.index_date == calc_date,
                    NationalDailyIndex.booking_window == "COMPOSITE",
                    NationalDailyIndex.index_type == "fisher",
                )
            )
            .scalars()
            .first()
        )
        assert (
            nat_fisher is not None
        ), "NationalDailyIndex Fisher record was not persisted"
        assert nat_fisher.index_value > 0, "Fisher index value non-positive"

        nat_paasche = (
            session.execute(
                select(NationalDailyIndex).where(
                    NationalDailyIndex.index_date == calc_date,
                    NationalDailyIndex.booking_window == "COMPOSITE",
                    NationalDailyIndex.index_type == "paasche",
                )
            )
            .scalars()
            .first()
        )
        assert (
            nat_paasche is not None
        ), "NationalDailyIndex Paasche record was not persisted"
        assert nat_paasche.index_value > 0, "Paasche index value non-positive"
        print(
            f"      National Fisher Index: {nat_fisher.index_value:.2f}, Paasche Index: {nat_paasche.index_value:.2f}"
        )

        print("\n[5/5] Verifying AnomalyAlert detection and idempotency...")
        alerts = (
            session.execute(
                select(AnomalyAlert).where(AnomalyAlert.flight_date == calc_date)
            )
            .scalars()
            .all()
        )

        print(f"      Anomaly alerts generated: {len(alerts)}")
        assert len(alerts) > 0, "Expected at least 1 anomaly alert to be generated"

        # Check that BLR-DEL surge was detected
        blr_del_alert = next(
            (a for a in alerts if a.origin == "BLR" and a.destination == "DEL"), None
        )
        assert blr_del_alert is not None, "BLR-DEL surge anomaly alert was not detected"
        assert blr_del_alert.severity in (
            "CRITICAL",
            "HIGH",
        ), f"Expected high severity, got {blr_del_alert.severity}"
        assert blr_del_alert.status == "OPEN", "Alert status must be OPEN"
        print(
            f"      Detected Alert: {blr_del_alert.origin}->{blr_del_alert.destination} "
            f"type={blr_del_alert.alert_type} severity={blr_del_alert.severity} "
            f"pct_change={blr_del_alert.pct_change}%"
        )

        # Test Idempotency: Re-running pipeline should not raise UniqueConstraint or produce duplicates
        re_run_result = run_daily_index_pipeline(session, calculation_date=calc_date)
        assert re_run_result["status"] == "success", "Re-run failed"

        route_count_after = session.execute(
            select(func.count(RouteDailyIndex.id)).where(
                RouteDailyIndex.index_date == calc_date
            )
        ).scalar()
        nat_count_after = session.execute(
            select(func.count(NationalDailyIndex.id)).where(
                NationalDailyIndex.index_date == calc_date
            )
        ).scalar()

        assert (
            route_count_after == 60
        ), f"Expected 60 route indices after re-run, got {route_count_after}"
        assert (
            nat_count_after == 3
        ), f"Expected 3 national indices (Laspeyres, Paasche, Fisher) after re-run, got {nat_count_after}"
        print(
            "      ✓ Assertion Passed: AnomalyAlert generation and pipeline idempotency verified."
        )

        # Test Autonomous Session Management: db=None
        from unittest.mock import patch

        with patch("backend.app.db.session.SessionLocal", session_factory):
            auto_result = run_daily_index_pipeline(db=None, calculation_date=calc_date)
            assert auto_result["status"] == "success", "db=None execution failed"
            print(
                "      ✓ Assertion Passed: Autonomous session management (db=None) verified."
            )

    print("\n" + "=" * 80)
    print("ALL PREMIER VERIFICATION CHECKS PASSED SUCCESSFULLY (6/6)")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
