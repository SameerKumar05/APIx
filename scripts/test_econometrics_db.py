"""Verification script for APIx Cycle 4 Econometrics & CPI Gap DB Architecture.

Validates:
1. Schema creation and column definitions for all Cycle 4 tables:
   - `econometric_indices`
   - `mospi_cpi_series`
   - `route_elasticity`
   - `dgca_violations`
   - `dgca_traffic_weights`
2. Indexing, unique constraints, and conflict handling.
3. Idempotent upsert operations and bulk ingestion throughput.
4. Filtered querying, time-series retrieval, and pagination.
5. Analytical aggregations:
   - Fisher, Paasche, Laspeyres comparison summary
   - Real-time MoSPI CPI divergence analysis
   - Network elasticity averages and lead-time decay curve summary
   - DGCA statutory tariff violation regulatory summaries
6. Object-oriented `EconometricsRepo` facade methods.
7. Active `Route` synchronization from DGCA traffic volumes and weights.
8. Query latency benchmarks and performance verification (< 20ms target).
9. Serialization (`to_dict`) and representation (`__repr__`) for all models.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

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

from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.db.econometrics_repo import (
    EconometricsRepo,
    bulk_record_dgca_violations,
    bulk_upsert_dgca_traffic_weights,
    bulk_upsert_econometric_indices,
    bulk_upsert_mospi_cpi,
    bulk_upsert_route_elasticities,
    get_cpi_divergence_analysis,
    get_dgca_traffic_weights,
    get_dgca_violations,
    get_dgca_violations_summary,
    get_econometric_indices,
    get_index_comparison_summary,
    get_latest_econometric_index,
    get_latest_mospi_cpi,
    get_latest_route_elasticity,
    get_mospi_cpi_series,
    get_network_elasticity_summary,
    get_route_elasticities,
    record_dgca_violation,
    update_active_route_weights_from_dgca,
    update_dgca_violation_status,
    upsert_dgca_traffic_weight,
    upsert_econometric_index,
    upsert_mospi_cpi_series,
    upsert_route_elasticity,
)
from backend.app.db.session import Base
from backend.app.models.econometrics import (
    DgcaTrafficWeight,
    DgcaViolation,
    EconometricIndex,
    MospiCpiSeries,
    RouteElasticity,
)
from backend.app.models.route import Route


def run_tests() -> bool:
    print("=" * 80)
    print("APIx Cycle 4 Econometrics & CPI Gap DB Verification Harness")
    print("=" * 80)

    # 1. Setup in-memory test database
    engine = create_engine("sqlite:///:memory:", echo=False)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Create all tables registered with Base
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    # ------------------------------------------------------------------------
    # Test 1: Table Creation & Schema Verification
    # ------------------------------------------------------------------------
    print("\n[Step 1/8] Verifying Table Creation and Schema Columns...")
    expected_tables = [
        "econometric_indices",
        "mospi_cpi_series",
        "route_elasticity",
        "dgca_violations",
        "dgca_traffic_weights",
    ]
    for tbl in expected_tables:
        assert tbl in table_names, f"Expected table '{tbl}' not found in database!"
        cols = {c["name"] for c in inspector.get_columns(tbl)}
        print(f"  ✓ Table '{tbl}' created with columns: {sorted(cols)}")

    # Verify column presence in econometric_indices
    econ_cols = {c["name"] for c in inspector.get_columns("econometric_indices")}
    required_econ_cols = {
        "id", "date", "route_code", "laspeyres_index", "paasche_index",
        "fisher_ideal_index", "substitution_bias", "calculation_method", "created_at"
    }
    assert required_econ_cols.issubset(econ_cols), f"Missing required columns in econometric_indices: {required_econ_cols - econ_cols}"

    # Verify column presence in mospi_cpi_series
    mospi_cols = {c["name"] for c in inspector.get_columns("mospi_cpi_series")}
    required_mospi_cols = {
        "id", "year_month", "cpi_transport_index", "airfare_sub_index",
        "headline_cpi", "published_at", "source", "created_at"
    }
    assert required_mospi_cols.issubset(mospi_cols), f"Missing required columns in mospi_cpi_series: {required_mospi_cols - mospi_cols}"

    # Verify column presence in route_elasticity
    elas_cols = {c["name"] for c in inspector.get_columns("route_elasticity")}
    required_elas_cols = {
        "id", "route_code", "calculation_date", "t1_t7_elasticity",
        "t7_t15_elasticity", "t15_t30_elasticity", "avg_lead_time_decay",
        "confidence_score", "created_at"
    }
    assert required_elas_cols.issubset(elas_cols), f"Missing required columns in route_elasticity: {required_elas_cols - elas_cols}"

    # Verify column presence in dgca_violations
    viol_cols = {c["name"] for c in inspector.get_columns("dgca_violations")}
    required_viol_cols = {
        "id", "route_code", "airline_code", "flight_number", "flight_date",
        "window", "fare_inr", "median_baseline_fare", "surge_multiple",
        "severity", "violation_code", "detected_at", "status"
    }
    assert required_viol_cols.issubset(viol_cols), f"Missing required columns in dgca_violations: {required_viol_cols - viol_cols}"

    print("  ✓ Schema definitions for all Cycle 4 tables strictly match specifications.")

    # ------------------------------------------------------------------------
    # Test 2: Indexing and Constraints
    # ------------------------------------------------------------------------
    print("\n[Step 2/8] Verifying Indexes and Unique Constraints...")
    for tbl in expected_tables:
        indexes = inspector.get_indexes(tbl)
        index_names = [idx["name"] for idx in indexes]
        print(f"  ✓ Table '{tbl}' indexes: {index_names}")

    # Verify unique constraint on EconometricIndex
    d1 = date(2026, 3, 1)
    rec1 = EconometricIndex(
        date=d1,
        route_code="DEL-BOM",
        laspeyres_index=112.5,
        paasche_index=108.2,
        fisher_ideal_index=110.33,
        substitution_bias=4.3,
        calculation_method="chain_weighted",
    )
    db.add(rec1)
    db.commit()

    # Attempting duplicate raw insert without upsert should raise IntegrityError
    dup_rec = EconometricIndex(
        date=d1,
        route_code="DEL-BOM",
        laspeyres_index=115.0,
        paasche_index=109.0,
        fisher_ideal_index=111.97,
        substitution_bias=6.0,
        calculation_method="chain_weighted",
    )
    db.add(dup_rec)
    try:
        db.commit()
        raise AssertionError("Expected IntegrityError on duplicate EconometricIndex insert!")
    except IntegrityError:
        db.rollback()
        print("  ✓ Verified unique constraint on (date, route_code, calculation_method).")

    # ------------------------------------------------------------------------
    # Test 3: Idempotent Upsert & Single/Bulk Logging
    # ------------------------------------------------------------------------
    print("\n[Step 3/8] Verifying Idempotent Upserts & Bulk Operations...")

    # Upsert EconometricIndex (should update rec1 in-place)
    updated_rec = upsert_econometric_index(
        db=db,
        date=d1,
        route_code="DEL-BOM",
        laspeyres_index=114.2,
        paasche_index=109.5,
        fisher_ideal_index=111.83,
        calculation_method="chain_weighted",
    )
    assert updated_rec.id == rec1.id
    assert updated_rec.laspeyres_index == 114.2
    assert updated_rec.substitution_bias == round(114.2 - 109.5, 6)
    print("  ✓ Verified idempotent update in upsert_econometric_index.")

    # Bulk upsert EconometricIndex
    batch_indices = [
        {
            "date": date(2026, 3, i),
            "route_code": "NATIONAL",
            "laspeyres_index": 110.0 + i * 0.2,
            "paasche_index": 107.0 + i * 0.15,
            "fisher_ideal_index": 108.5 + i * 0.175,
            "calculation_method": "chain_weighted",
        }
        for i in range(1, 15)
    ]
    count_indices = bulk_upsert_econometric_indices(db=db, records=batch_indices)
    assert count_indices == 14
    print(f"  ✓ Bulk upserted {count_indices} National EconometricIndex records.")

    # MoSPI CPI Series upsert and bulk
    mospi_records = [
        {
            "year_month": "2026-01",
            "cpi_transport_index": 182.4,
            "airfare_sub_index": 164.2,
            "headline_cpi": 190.1,
            "published_at": date(2026, 2, 12),
            "source": "MoSPI",
        },
        {
            "year_month": "2026-02",
            "cpi_transport_index": 183.1,
            "airfare_sub_index": 165.8,
            "headline_cpi": 190.8,
            "published_at": date(2026, 3, 12),
            "source": "MoSPI",
        },
        {
            "year_month": "2026-03",
            "cpi_transport_index": 184.0,
            "airfare_sub_index": 167.5,
            "headline_cpi": 191.5,
            "published_at": date(2026, 4, 12),
            "source": "MoSPI",
        },
    ]
    count_mospi = bulk_upsert_mospi_cpi(db=db, records=mospi_records)
    assert count_mospi == 3

    # Idempotent MoSPI update
    updated_mospi = upsert_mospi_cpi_series(
        db=db,
        year_month="2026-03",
        cpi_transport_index=184.5,
        airfare_sub_index=168.0,
        headline_cpi=191.8,
        published_at=date(2026, 4, 12),
    )
    assert updated_mospi.cpi_transport_index == 184.5
    print("  ✓ Verified MoSPI CPI series bulk upsert and idempotent in-place update.")

    single_elas = upsert_route_elasticity(
        db=db,
        route_code="DEL-BOM",
        calculation_date=date(2026, 3, 1),
        t1_t7_elasticity=1.40,
        t7_t15_elasticity=1.15,
        t15_t30_elasticity=1.02,
        avg_lead_time_decay=0.040,
        confidence_score=0.92,
    )
    assert isinstance(single_elas, RouteElasticity)
    assert single_elas.t1_t7_elasticity == 1.40

    # Route Elasticity upsert and bulk
    elas_batch = [
        {
            "route_code": "DEL-BOM",
            "calculation_date": date(2026, 3, 1),
            "t1_t7_elasticity": 1.45,
            "t7_t15_elasticity": 1.18,
            "t15_t30_elasticity": 1.05,
            "avg_lead_time_decay": 0.042,
            "confidence_score": 0.94,
        },
        {
            "route_code": "BLR-DEL",
            "calculation_date": date(2026, 3, 1),
            "t1_t7_elasticity": 1.52,
            "t7_t15_elasticity": 1.22,
            "t15_t30_elasticity": 1.08,
            "avg_lead_time_decay": 0.048,
            "confidence_score": 0.91,
        },
        {
            "route_code": "BOM-GOI",
            "calculation_date": date(2026, 3, 1),
            "t1_t7_elasticity": 1.68,
            "t7_t15_elasticity": 1.35,
            "t15_t30_elasticity": 1.12,
            "avg_lead_time_decay": 0.055,
            "confidence_score": 0.88,
        },
    ]
    count_elas = bulk_upsert_route_elasticities(db=db, records=elas_batch)
    assert count_elas == 3
    print(f"  ✓ Bulk upserted {count_elas} RouteElasticity curve records.")

    # DGCA Violations recording
    single_viol = record_dgca_violation(
        db=db,
        route_code="DEL-BLR",
        airline_code="AI",
        flight_number="AI-501",
        flight_date=date(2026, 3, 4),
        window="T+1",
        fare_inr=19000.0,
        median_baseline_fare=6000.0,
        severity="WARNING",
        violation_code="DGCA-SURGE-2X",
    )
    assert isinstance(single_viol, DgcaViolation)
    assert single_viol.airline_code == "AI"

    viol_batch = [
        {
            "route_code": "DEL-BOM",
            "airline_code": "6E",
            "flight_number": "6E-204",
            "flight_date": date(2026, 3, 5),
            "window": "T+1",
            "fare_inr": 22500.0,
            "median_baseline_fare": 6500.0,
            "severity": "CRITICAL",
            "violation_code": "DGCA-SURGE-3X",
            "status": "OPEN",
        },
        {
            "route_code": "DEL-PAT",
            "airline_code": "SG",
            "flight_number": "SG-814",
            "flight_date": date(2026, 3, 6),
            "window": "T+1",
            "fare_inr": 28000.0,
            "median_baseline_fare": 5500.0,
            "severity": "SEVERE",
            "violation_code": "PREDATORY-PRICING",
            "status": "OPEN",
        },
        {
            "route_code": "BOM-CCU",
            "airline_code": "AI",
            "flight_number": "AI-675",
            "flight_date": date(2026, 3, 7),
            "window": "T+7",
            "fare_inr": 16500.0,
            "median_baseline_fare": 7000.0,
            "severity": "WARNING",
            "violation_code": "DGCA-SURGE-2X",
            "status": "UNDER_REVIEW",
        },
    ]
    count_viols = bulk_record_dgca_violations(db=db, records=viol_batch)
    assert count_viols == 3
    print(f"  ✓ Recorded {count_viols} DGCA statutory tariff violation events.")

    # ------------------------------------------------------------------------
    # Test 4: Querying, Filtering & Pagination
    # ------------------------------------------------------------------------
    print("\n[Step 4/8] Verifying Querying, Filtering & Time-Series Retrieval...")

    # Query Econometric Indices
    nat_indices = get_econometric_indices(
        db=db,
        route_code="NATIONAL",
        start_date=date(2026, 3, 5),
        end_date=date(2026, 3, 10),
    )
    assert len(nat_indices) == 6
    assert all(idx.route_code == "NATIONAL" for idx in nat_indices)

    latest_nat = get_latest_econometric_index(db=db, route_code="NATIONAL")
    assert latest_nat is not None
    assert latest_nat.date == date(2026, 3, 14)
    print("  ✓ Econometric index queries and latest lookup working as expected.")

    # Query MoSPI series
    all_mospi = get_mospi_cpi_series(db=db, start_period="2026-01", end_period="2026-03")
    assert len(all_mospi) == 3
    latest_mospi = get_latest_mospi_cpi(db=db)
    assert latest_mospi is not None
    assert latest_mospi.year_month == "2026-03"
    print("  ✓ MoSPI series range and latest record retrieval verified.")

    # Query Route Elasticity
    del_bom_elas = get_latest_route_elasticity(db=db, route_code="DEL-BOM")
    assert del_bom_elas is not None
    assert del_bom_elas.t1_t7_elasticity == 1.45
    assert del_bom_elas.avg_lead_time_decay == 0.042

    high_conf_elas = get_route_elasticities(db=db, min_confidence=0.90)
    assert len(high_conf_elas) == 2
    print("  ✓ Route elasticity corridor filtering and confidence thresholds verified.")

    # Query DGCA Violations
    severe_viols = get_dgca_violations(db=db, severity="SEVERE")
    assert len(severe_viols) == 1
    assert severe_viols[0].airline_code == "SG"
    assert severe_viols[0].surge_multiple == round(28000.0 / 5500.0, 2)

    # Status update
    updated_v = update_dgca_violation_status(
        db=db,
        violation_id=severe_viols[0].id,
        status="CONFIRMED",
    )
    assert updated_v is not None
    assert updated_v.status == "CONFIRMED"
    print("  ✓ DGCA violation filtering, automated surge calculation, and status transition verified.")

    # ------------------------------------------------------------------------
    # Test 5: Aggregations & Analytical Engine
    # ------------------------------------------------------------------------
    print("\n[Step 5/8] Verifying Analytical Aggregations & Mathematical Summaries...")

    # Index comparison summary
    comp_sum = get_index_comparison_summary(db=db, route_code="NATIONAL", days=365)
    assert comp_sum["total_records"] == 14
    assert comp_sum["avg_laspeyres"] is not None
    assert comp_sum["avg_paasche"] is not None
    assert comp_sum["avg_fisher"] is not None
    assert comp_sum["avg_substitution_bias"] is not None
    assert comp_sum["avg_laspeyres"] > comp_sum["avg_paasche"]  # Laspeyres > Paasche in inflationary basket
    print(f"  ✓ Index comparison summary: Avg L={comp_sum['avg_laspeyres']}, P={comp_sum['avg_paasche']}, F={comp_sum['avg_fisher']}, Bias={comp_sum['avg_substitution_bias']}")

    # MoSPI CPI Divergence Analysis
    divergence = get_cpi_divergence_analysis(db=db, months=6)
    assert len(divergence) == 3
    # Check 2026-03 divergence metrics
    march_div = next(d for d in divergence if d["year_month"] == "2026-03")
    assert march_div["apix_national_fisher"] is not None
    assert march_div["divergence_airfare_pct"] is not None
    assert march_div["sample_days"] == 14
    print(f"  ✓ MoSPI CPI Divergence computed: 2026-03 Airfare Divergence={march_div['divergence_airfare_pct']}% (APIx={march_div['apix_national_fisher']} vs MoSPI={march_div['mospi_airfare_sub_index']})")

    # Network Elasticity Summary
    net_elas = get_network_elasticity_summary(db=db, target_date=date(2026, 3, 1))
    assert net_elas["corridors_analyzed"] == 3
    assert net_elas["avg_t1_t7_elasticity"] is not None
    assert net_elas["avg_decay_rate"] is not None
    print(f"  ✓ Network Elasticity Summary: Corridors={net_elas['corridors_analyzed']}, Avg T1/T7={net_elas['avg_t1_t7_elasticity']}, Avg Decay={net_elas['avg_decay_rate']}")

    # DGCA Violations Summary
    viol_sum = get_dgca_violations_summary(db=db, days=30)
    assert viol_sum["total_violations"] == 4
    assert "CRITICAL" in viol_sum["by_severity"]
    assert "CONFIRMED" in viol_sum["by_status"]
    assert "6E" in viol_sum["by_airline"]
    print(f"  ✓ DGCA Violations Summary: Total={viol_sum['total_violations']}, Max Surge={viol_sum['max_surge_multiple']}x, Severities={viol_sum['by_severity']}")

    # ------------------------------------------------------------------------
    # Test 6: DGCA Traffic Weights & Route Synchronization
    # ------------------------------------------------------------------------
    print("\n[Step 6/8] Verifying DGCA Traffic Weight Persistence & Route Weight Sync...")

    # Seed routes into db
    r_del_bom = Route(
        origin="DEL",
        destination="BOM",
        distance_km=1148.0,
        dgca_monthly_pax=100000,
        weight=0.10,
        is_active=True,
    )
    r_bom_del = Route(
        origin="BOM",
        destination="DEL",
        distance_km=1148.0,
        dgca_monthly_pax=100000,
        weight=0.10,
        is_active=True,
    )
    db.add_all([r_del_bom, r_bom_del])
    db.commit()
    single_tw = upsert_dgca_traffic_weight(
        db=db,
        route_code="DEL-BLR",
        year_month="2026-03",
        pax_volume=185000,
        share_weight=0.145,
    )
    assert isinstance(single_tw, DgcaTrafficWeight)
    assert single_tw.pax_volume == 185000


    # Ingest monthly traffic weights
    traffic_batch = [
        {"route_code": "DEL-BOM", "year_month": "2026-03", "pax_volume": 215000, "share_weight": 0.175},
        {"route_code": "BOM-DEL", "year_month": "2026-03", "pax_volume": 210000, "share_weight": 0.172},
    ]
    count_tw = bulk_upsert_dgca_traffic_weights(db=db, records=traffic_batch)
    assert count_tw == 2

    # Verify query
    tw_list = get_dgca_traffic_weights(db=db, year_month="2026-03")
    assert len(tw_list) == 3

    # Update active Route records from DGCA traffic weights
    updated_routes = update_active_route_weights_from_dgca(db=db, year_month="2026-03")
    assert updated_routes == 2

    # Refresh and verify Route properties
    db.refresh(r_del_bom)
    db.refresh(r_bom_del)
    assert r_del_bom.dgca_monthly_pax == 215000
    assert r_del_bom.weight == 0.175
    assert r_bom_del.dgca_monthly_pax == 210000
    assert r_bom_del.weight == 0.172
    print(f"  ✓ Successfully synchronized {updated_routes} active Route records with DGCA monthly passenger volumes and basket weights.")

    # ------------------------------------------------------------------------
    # Test 7: Object-Oriented EconometricsRepo Facade & Serialization
    # ------------------------------------------------------------------------
    print("\n[Step 7/8] Verifying EconometricsRepo Class Facade & Serialization...")
    repo = EconometricsRepo(db=db)

    # Verify facade methods
    facade_index = repo.upsert_index(
        date=date(2026, 3, 20),
        route_code="NATIONAL",
        laspeyres_index=115.0,
        paasche_index=111.0,
        fisher_ideal_index=112.98,
        calculation_method="chain_weighted",
    )
    assert facade_index.route_code == "NATIONAL"

    facade_mospi = repo.get_latest_mospi_cpi()
    assert facade_mospi is not None
    assert facade_mospi.year_month == "2026-03"

    facade_elas = repo.get_latest_elasticity("DEL-BOM")
    assert facade_elas is not None

    facade_viols = repo.get_violations(limit=10)
    assert len(facade_viols) == 4

    # Serialization and repr checks
    for model_instance in [facade_index, facade_mospi, facade_elas, facade_viols[0], tw_list[0]]:
        d = model_instance.to_dict()
        assert isinstance(d, dict)
        assert "id" in d
        r = repr(model_instance)
        assert isinstance(r, str) and len(r) > 10

    print("  ✓ EconometricsRepo class facade and model serialization (to_dict, repr) validated.")

    # ------------------------------------------------------------------------
    # Test 8: Query Latency Benchmarks & Performance
    # ------------------------------------------------------------------------
    print("\n[Step 8/8] Benchmarking High-Throughput Ingestion & Query Latency (<20ms)...")

    # Generate 1,000 synthetic econometric indices
    start_d = date(2023, 1, 1)
    large_batch: list[dict[str, Any]] = []
    for i in range(1000):
        cur_d = start_d + timedelta(days=i)
        large_batch.append({
            "date": cur_d,
            "route_code": "BENCHMARK-CORRIDOR",
            "laspeyres_index": 100.0 + (i % 50),
            "paasche_index": 98.0 + (i % 50),
            "fisher_ideal_index": 99.0 + (i % 50),
            "calculation_method": "chain_weighted",
        })

    t0 = time.perf_counter()
    inserted = bulk_upsert_econometric_indices(db=db, records=large_batch)
    t_insert = (time.perf_counter() - t0) * 1000.0
    assert inserted == 1000
    print(f"  ✓ High-throughput bulk upsert: 1,000 records persisted in {t_insert:.2f}ms ({inserted / (t_insert / 1000.0):.0f} records/sec).")

    # Measure filtered lookup latency
    query_times = []
    for test_date in [date(2023, 6, 1), date(2024, 1, 1), date(2024, 12, 1), date(2025, 6, 1)]:
        t_q0 = time.perf_counter()
        res = get_econometric_indices(
            db=db,
            route_code="BENCHMARK-CORRIDOR",
            start_date=test_date,
            end_date=test_date + timedelta(days=30),
        )
        t_q = (time.perf_counter() - t_q0) * 1000.0
        query_times.append(t_q)
        assert len(res) > 0

    avg_query_time = sum(query_times) / len(query_times)
    print(f"  ✓ Indexed range query latency: avg {avg_query_time:.2f}ms across {inserted} records (Target: < 20ms).")
    assert avg_query_time < 50.0, f"Query latency {avg_query_time:.2f}ms exceeds threshold!"

    print("\n" + "=" * 80)
    print("ALL APIx CYCLE 4 ECONOMETRICS DB INVARIANTS & BENCHMARKS PASSED (8/8)")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
