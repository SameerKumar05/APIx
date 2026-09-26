"""Test suite and verification script for APIx Ingestion Repository.

Validates:
1. High-throughput bulk insertion of 500 records.
2. Cryptographic deduplication & duplicate suppression (ON CONFLICT DO NOTHING).
3. Scraping run execution tracking & telemetry updates.
4. Automated 90-day retention pruning while preserving daily indices.
5. Fast time-series query performance (< 50ms) leveraging composite indexes.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

# Ensure repo root is on sys.path
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

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.ingestion_repo import (
    IngestionRepo,
    bulk_insert_raw_fares,
    cleanup_old_raw_fares,
    compute_dedup_hash,
    count_raw_fares,
    create_scraping_run,
    get_raw_fares,
    get_raw_fares_for_calculation,
    get_scraping_run,
    record_scraping_run,
    update_scraping_run,
)
from backend.app.db.session import Base
from backend.app.models.index import NationalDailyIndex, RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.scraping import ScrapingRun


def generate_mock_records(
    count: int = 500,
    batch_id: str = "batch-test-001",
    base_date: date | None = None,
    days_offset: int = 0,
) -> list[dict]:
    """Generate deterministic mock raw fare records for testing."""
    records = []
    routes = [
        ("DEL", "BOM"),
        ("BOM", "DEL"),
        ("BLR", "DEL"),
        ("DEL", "BLR"),
        ("BOM", "BLR"),
    ]
    airlines = ["6E", "AI", "IX", "QP", "SG"]
    windows = ["T+1", "T+7", "T+15", "T+30", "T+45"]

    effective_date = base_date or (date(2026, 10, 1) + timedelta(days=days_offset))
    now_utc = datetime.now(UTC) - timedelta(days=abs(days_offset))

    for i in range(count):
        origin, dest = routes[i % len(routes)]
        airline = airlines[(i // len(routes)) % len(airlines)]
        window = windows[(i // (len(routes) * len(airlines))) % len(windows)]
        flight_no = f"{airline}-{100 + (i % 50)}"

        flight_day = effective_date + timedelta(days=(i % 14))
        dep_dt = datetime(
            flight_day.year,
            flight_day.month,
            flight_day.day,
            6 + (i % 14),
            0,
            0,
            tzinfo=UTC,
        )
        arr_dt = dep_dt + timedelta(hours=2, minutes=15)

        base_fare = 3500.0 + (i * 7.5) % 8000
        taxes = base_fare * 0.12
        total_fare = round(base_fare + taxes, 2)

        dedup_hash = compute_dedup_hash(
            airline_code=airline,
            flight_number=flight_no,
            origin=origin,
            destination=dest,
            departure_time=dep_dt,
            booking_window=window,
            flight_date=flight_day,
        )

        records.append(
            {
                "batch_id": batch_id,
                "origin": origin,
                "destination": dest,
                "flight_date": flight_day,
                "booking_window": window,
                "airline_code": airline,
                "flight_number": flight_no,
                "departure_time": dep_dt,
                "arrival_time": arr_dt,
                "duration_minutes": 135,
                "stops": 0,
                "fare_class": "Economy",
                "base_fare": base_fare,
                "taxes_and_fees": taxes,
                "total_fare": total_fare,
                "source_platform": "synthetic",
                "scraped_at": now_utc,
                "hash_id": dedup_hash,
                "is_synthetic": True,
            }
        )

    return records


def run_tests() -> bool:
    print("=" * 70)
    print("APIx Ingestion Repository Verification Test Suite")
    print("=" * 70)

    # 1. Setup in-memory SQLite database
    print("\n[1/6] Booting in-memory database and creating tables...")
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    repo = IngestionRepo(db)
    print("  -> Tables initialized successfully.")

    # 2. Bulk insertion of 500 records
    print("\n[2/6] Testing bulk insertion of 500 records...")
    batch_1 = generate_mock_records(500, batch_id="batch-500-test")
    assert len(batch_1) == 500, f"Expected 500 generated records, got {len(batch_1)}"

    t0 = time.perf_counter()
    res1 = repo.bulk_insert(batch_1, batch_size=250)
    t_insert = (time.perf_counter() - t0) * 1000

    print(f"  -> Bulk insert completed in {t_insert:.2f}ms")
    print(
        f"  -> Result: received={res1['received']}, inserted={res1['inserted']}, duplicates={res1['duplicates']}"
    )

    assert res1["received"] == 500, f"Expected received 500, got {res1['received']}"
    assert res1["inserted"] == 500, f"Expected inserted 500, got {res1['inserted']}"
    assert res1["duplicates"] == 0, f"Expected duplicates 0, got {res1['duplicates']}"

    db_count = repo.count()
    assert db_count == 500, f"Expected 500 records in DB, got {db_count}"
    print(f"  -> Total records in DB verified: {db_count} (PASS)")

    # 3. Duplicate suppression test
    print("\n[3/6] Testing duplicate suppression & idempotency...")
    # Attempt re-inserting the exact same 500 records
    t0 = time.perf_counter()
    res2 = repo.bulk_insert(batch_1, batch_size=250)
    t_dup = (time.perf_counter() - t0) * 1000

    print(f"  -> Replay insert completed in {t_dup:.2f}ms")
    print(
        f"  -> Result: received={res2['received']}, inserted={res2['inserted']}, duplicates={res2['duplicates']}"
    )

    assert res2["received"] == 500, f"Expected received 500, got {res2['received']}"
    assert res2["inserted"] == 0, f"Expected inserted 0, got {res2['inserted']}"
    assert (
        res2["duplicates"] == 500
    ), f"Expected duplicates 500, got {res2['duplicates']}"

    db_count_after = repo.count()
    assert db_count_after == 500, f"Expected DB count to stay 500, got {db_count_after}"
    print(
        f"  -> Database count remains unchanged: {db_count_after} (100% duplicate suppression confirmed)"
    )

    # In-batch duplicate test
    batch_with_internal_dups = [
        batch_1[0],
        batch_1[0],
        batch_1[0],  # 3 copies of record 0
        batch_1[1],
        batch_1[1],  # 2 copies of record 1
    ]
    res_in_batch = repo.bulk_insert(batch_with_internal_dups)
    assert res_in_batch["received"] == 5
    assert res_in_batch["inserted"] == 0
    assert res_in_batch["duplicates"] == 5
    print("  -> In-batch duplicate suppression verified (PASS)")

    # 4. ScrapingRun telemetry tracking
    print("\n[4/6] Testing ScrapingRun execution telemetry...")
    run_id = "run-crawldelta-20261001"
    run = repo.create_run(
        batch_id=run_id,
        source_platform="synthetic",
        status="RUNNING",
        routes_attempted=10,
    )
    assert run.batch_id == run_id
    assert run.status == "RUNNING"
    assert run.routes_attempted == 10

    # Update run metrics
    updated_run = repo.update_run(
        batch_id=run_id,
        status="COMPLETED",
        routes_succeeded=10,
        fares_collected=500,
        fares_deduplicated=500,
    )
    assert updated_run is not None
    assert updated_run.status == "COMPLETED"
    assert updated_run.routes_succeeded == 10
    assert updated_run.fares_collected == 500
    assert updated_run.fares_deduplicated == 500
    assert updated_run.completed_at is not None
    print(
        f"  -> ScrapingRun lifecycle verified: status={updated_run.status}, duration={updated_run.duration_seconds}s (PASS)"
    )

    # 5. Automated retention pruning (90 days)
    print("\n[5/6] Testing 90-day retention pruning & index preservation...")
    # Insert older raw fares (100 days old)
    old_records = generate_mock_records(
        count=150,
        batch_id="batch-old-100d",
        base_date=date.today() - timedelta(days=120),
        days_offset=-100,
    )
    res_old = repo.bulk_insert(old_records)
    print(f"  -> Inserted {res_old['inserted']} old raw fare records (100+ days old)")

    route_idx = RouteDailyIndex(
        origin="DEL",
        destination="BOM",
        index_date=date.today() - timedelta(days=100),
        booking_window="T+7",
        index_type="geometric_mean",
        index_value=112.5,
        mean_fare=4500.0,
        sample_size=40,
    )
    nat_idx = NationalDailyIndex(
        index_date=date.today() - timedelta(days=100),
        booking_window="COMPOSITE",
        index_type="laspeyres",
        index_value=105.8,
    )
    db.add_all([route_idx, nat_idx])
    db.commit()

    total_fares_before = repo.count()
    assert (
        total_fares_before == 650
    ), f"Expected 650 total fares, got {total_fares_before}"

    # Perform cleanup of records older than 90 days
    pruned = repo.cleanup_old_fares(days=90)
    print(f"  -> Pruned records count: {pruned}")
    assert pruned == 150, f"Expected exactly 150 old records pruned, got {pruned}"

    total_fares_after = repo.count()
    assert (
        total_fares_after == 500
    ), f"Expected 500 fares remaining, got {total_fares_after}"
    print(f"  -> Remaining raw fares in DB: {total_fares_after} (PASS)")

    # Assert daily indices are completely preserved
    saved_route_indices = db.scalars(select(RouteDailyIndex)).all()
    saved_nat_indices = db.scalars(select(NationalDailyIndex)).all()
    assert (
        len(saved_route_indices) == 1
    ), "RouteDailyIndex must be preserved after pruning!"
    assert (
        len(saved_nat_indices) == 1
    ), "NationalDailyIndex must be preserved after pruning!"
    print(
        f"  -> Daily indices preserved intact: RouteDailyIndex={len(saved_route_indices)}, NationalDailyIndex={len(saved_nat_indices)} (PASS)"
    )

    # 6. Time-series query helpers and performance assertion
    print("\n[6/6] Testing query helpers and time-series latency...")
    # Fetch sample for DEL -> BOM, T+7 on 2026-10-01
    t0 = time.perf_counter()
    fares = repo.get_fares_for_calculation(
        origin="DEL",
        destination="BOM",
        booking_window="T+7",
        calculation_date=date(2026, 10, 1),
    )
    q_latency_ms = (time.perf_counter() - t0) * 1000
    print(
        f"  -> Route-window-date calculation lookup returned {len(fares)} fares in {q_latency_ms:.3f}ms"
    )

    # Benchmark query latency across 100 consecutive queries
    latencies = []
    for _ in range(100):
        t0 = time.perf_counter()
        _ = repo.get_fares_for_calculation(
            origin="DEL",
            destination="BOM",
            booking_window="T+7",
            calculation_date=date(2026, 10, 1),
        )
        latencies.append((time.perf_counter() - t0) * 1000)

    avg_latency = sum(latencies) / len(latencies)
    p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
    print(
        f"  -> Benchmark (100 runs): avg={avg_latency:.3f}ms, p95={p95_latency:.3f}ms"
    )

    assert (
        p95_latency < 50.0
    ), f"p95 latency {p95_latency:.2f}ms exceeds 50ms performance threshold!"
    print("  -> Query performance assertion (< 50ms): PASSED")

    # Verify query results ordering and content
    assert len(fares) > 0, "Query should return matching fares"
    for i in range(len(fares) - 1):
        assert (
            fares[i].total_fare <= fares[i + 1].total_fare
        ), "Fares should be sorted by total_fare ascending"
    print("  -> Fare ordering invariant verified (PASS)")

    # Multi-parameter query test
    del_fares = repo.query_fares(origin="DEL", limit=10)
    assert len(del_fares) <= 10
    assert all(f.origin == "DEL" for f in del_fares)
    print("  -> Multi-parameter query filtering verified (PASS)")

    print("\n" + "=" * 70)
    print("ALL 6 INGESTION REPOSITORY VERIFICATION CHECKS PASSED (100%)")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
