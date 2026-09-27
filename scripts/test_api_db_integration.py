#!/usr/bin/env python3
"""
APIx Cycle 2 End-to-End API and Database Integration Test Suite.

Verifies:
1. Graceful fallback to mock data when database is unseeded.
2. Batch ingestion POST /api/v1/ingestion/batch with IngestionRepo persistence.
3. Detailed statistics response: inserted count, duplicate count, processing time.
4. Idempotent deduplication (ON CONFLICT DO NOTHING) on re-submitting duplicate batches.
5. Automated background execution of run_daily_index_pipeline.
6. Immediate query retrieval of persisted data via indices endpoints:
   - GET /api/v1/indices/national/latest
   - GET /api/v1/indices/national/history
   - GET /api/v1/indices/routes
   - GET /api/v1/indices/routes/{route_code}/history
7. Anomaly alerts query via GET /api/v1/analytics/anomalies with severity and status filters.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta, timezone

# Configure isolated SQLite test database path before loading application modules
temp_db = tempfile.NamedTemporaryFile(suffix="_apix_integration.db", delete=False)
temp_db_path = temp_db.name
temp_db.close()

os.environ["DATABASE_URL"] = f"sqlite:///{temp_db_path}"

# Ensure worktree root is in python path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.ingestion_repo import IngestionRepo
from backend.app.db.seed import seed_all
from backend.app.db.session import SessionLocal, drop_db, engine, init_db
from backend.app.main import app
from backend.app.models.anomaly import AnomalyAlert
from backend.app.models.index import NationalDailyIndex, RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.route import Route

client = TestClient(app)


def test_unseeded_mock_fallback():
    """Verify endpoints return realistic mock data when database tables are empty/unseeded."""
    print("\n[TEST 1/8] Verifying unseeded database mock fallback...")

    # 1. National latest
    resp = client.get("/api/v1/indices/national/latest")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    assert data["index_value"] == 114.28
    assert data["status"] == "published"
    print(
        "  ✓ GET /api/v1/indices/national/latest fell back gracefully to mock index 114.28"
    )

    # 2. National history
    resp = client.get("/api/v1/indices/national/history?days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_points"] >= 7
    print(
        f"  ✓ GET /api/v1/indices/national/history returned {data['total_points']} mock points"
    )

    # 3. Routes overview
    resp = client.get("/api/v1/indices/routes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_routes"] == 7
    print(
        f"  ✓ GET /api/v1/indices/routes returned {data['total_routes']} benchmark corridors"
    )

    # 4. Anomalies
    resp = client.get("/api/v1/analytics/anomalies")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_alerts"] >= 1
    print(
        f"  ✓ GET /api/v1/analytics/anomalies returned {data['total_alerts']} sample anomaly alerts"
    )


def test_batch_ingestion_and_db_persistence():
    """Verify live batch submission to DB and detailed statistics response."""
    print(
        "\n[TEST 2/8] Testing POST /api/v1/ingestion/batch with IngestionRepo persistence..."
    )

    # Seed routes and airlines
    init_db()
    with SessionLocal() as db:
        seed_result = seed_all(db)
        print(
            f"  ✓ Seeded reference master data: {seed_result['routes']} routes, {seed_result['airlines']} airlines"
        )

    now = datetime.now(UTC)
    target_date = now.date()
    records = []

    # 4 monitored corridors x 4 canonical booking windows x 2 airlines = 32 fare quotes
    for orig, dest in [("DEL", "BOM"), ("BOM", "DEL"), ("BLR", "DEL"), ("DEL", "BLR")]:
        for win in ["T+1", "T+7", "T+15", "T+30", "T+45"]:
            for carrier, fno, fare in [
                ("6E", f"6E-{win}01", 5000.0),
                ("AI", f"AI-{win}02", 5200.0),
            ]:
                records.append(
                    {
                        "airline_code": carrier,
                        "flight_number": fno,
                        "origin": orig,
                        "destination": dest,
                        "departure_datetime": datetime.combine(
                            target_date, datetime.min.time(), tzinfo=UTC
                        ).isoformat(),
                        "arrival_datetime": datetime.combine(
                            target_date, datetime.min.time(), tzinfo=UTC
                        ).isoformat(),
                        "booking_datetime": now.isoformat(),
                        "fare_inr": fare,
                        "cabin_class": "economy",
                        "stops": 0,
                        "source": "makemytrip",
                        "booking_window": win,
                    }
                )

    batch_payload = {
        "batch_id": "batch-integration-live-01",
        "source": "makemytrip",
        "scraped_at": now.isoformat(),
        "records": records,
    }

    headers = {"X-Ingestion-Key": settings.INGESTION_API_KEY}
    resp = client.post("/api/v1/ingestion/batch", json=batch_payload, headers=headers)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert data["status"] == "success"
    assert data["records_received"] == 32
    assert data["records_valid"] == 32
    assert data["inserted_count"] == 32
    assert data["duplicate_count"] == 0
    assert data["processing_time_ms"] > 0
    assert len(data["errors"]) == 0
    print("  ✓ Ingestion response returned 200 OK with detailed statistics:")
    print(f"    - Batch ID: {data['batch_id']}")
    print(f"    - Received: {data['records_received']}, Valid: {data['records_valid']}")
    print(
        f"    - Inserted: {data['inserted_count']}, Duplicates: {data['duplicate_count']}"
    )
    print(f"    - Processing Time: {data['processing_time_ms']} ms")
    print(f"    - Message: {data['message']}")

    # Verify directly in DB
    with SessionLocal() as db:
        count = db.query(RawFare).count()
        assert count == 32, f"Expected 32 raw fares in DB, found {count}"
        sample = (
            db.query(RawFare)
            .filter(RawFare.origin == "DEL", RawFare.destination == "BOM")
            .first()
        )
        assert sample is not None
        assert sample.total_fare == 5000.0
        assert sample.booking_window == "T+1"
        assert sample.airline_code == "6E"
        assert sample.hash_id is not None
        print(
            "  ✓ Confirmed 32 RawFare records persisted in database table 'raw_fares'"
        )

    return batch_payload, headers


def test_idempotent_deduplication(batch_payload, headers):
    """Verify re-submitting duplicate records is idempotent (0 inserted, 32 duplicates)."""
    print(
        "\n[TEST 3/8] Testing idempotent deduplication on duplicate batch submission..."
    )
    resp = client.post("/api/v1/ingestion/batch", json=batch_payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["records_received"] == 32
    assert data["records_valid"] == 32
    assert data["inserted_count"] == 0
    assert data["duplicate_count"] == 32
    print("  ✓ Idempotent deduplication confirmed:")
    print(
        f"    - Inserted: {data['inserted_count']}, Duplicates: {data['duplicate_count']}"
    )
    print(f"    - Message: {data['message']}")

    with SessionLocal() as db:
        count = db.query(RawFare).count()
        assert count == 32, f"Expected DB count to stay 32, got {count}"
        print(
            "  ✓ Database row count remained exactly 32 (zero duplicate records stored)"
        )


def test_background_pipeline_execution():
    """Verify background task run_daily_index_pipeline calculated and persisted index models."""
    print(
        "\n[TEST 4/8] Verifying background index pipeline execution and DB persistence..."
    )
    with SessionLocal() as db:
        nat_index = (
            db.query(NationalDailyIndex).order_by(NationalDailyIndex.id.desc()).first()
        )
        assert nat_index is not None, "NationalDailyIndex was not created by pipeline"
        assert (
            nat_index.index_value > 0.0
        ), f"Expected positive index value, got {nat_index.index_value}"
        assert nat_index.total_samples == 32
        print("  ✓ Persisted NationalDailyIndex found in DB:")
        print(f"    - Index Date: {nat_index.index_date}")
        print(f"    - Index Value: {nat_index.index_value:.4f}")
        print(f"    - Total Samples: {nat_index.total_samples}")
        print(f"    - Routes Covered: {nat_index.routes_covered}")

        route_indices = (
            db.query(RouteDailyIndex)
            .filter(RouteDailyIndex.booking_window == "COMPOSITE")
            .all()
        )
        assert (
            len(route_indices) == 4
        ), f"Expected 4 composite route indices, got {len(route_indices)}"
        for r in route_indices:
            print(
                f"    - Corridor {r.origin}->{r.destination}: Index={r.index_value:.2f}, Median Fare=INR {r.median_fare:.2f}"
            )


def test_query_retrieval_national_latest():
    """Verify GET /api/v1/indices/national/latest retrieves the live persisted DB index."""
    print(
        "\n[TEST 5/8] Testing GET /api/v1/indices/national/latest against persisted DB data..."
    )
    resp = client.get("/api/v1/indices/national/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "published"
    assert data["sample_size"] == 32
    assert 80.0 <= data["index_value"] <= 120.0
    assert (
        data["confidence_interval_lower"]
        <= data["index_value"]
        <= data["confidence_interval_upper"]
    )
    print("  ✓ Live National Index retrieved successfully:")
    print(f"    - Timestamp: {data['timestamp']}")
    print(f"    - Index Value: {data['index_value']}")
    print(f"    - Sample Size: {data['sample_size']} observations")
    print(
        f"    - 95% Confidence Interval: [{data['confidence_interval_lower']}, {data['confidence_interval_upper']}]"
    )


def test_query_retrieval_national_history():
    """Verify GET /api/v1/indices/national/history retrieves chronological historical series."""
    print(
        "\n[TEST 6/8] Testing GET /api/v1/indices/national/history against persisted DB data..."
    )
    resp = client.get("/api/v1/indices/national/history?days=30")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_points"] >= 1
    pt = data["points"][0]
    assert pt["sample_size"] == 32
    assert pt["index_value"] > 0
    print(
        f"  ✓ National history returned {data['total_points']} points from database (latest index={pt['index_value']})"
    )


def test_query_retrieval_routes_overview_and_history():
    """Verify GET /api/v1/indices/routes and route history return live persisted route data."""
    print(
        "\n[TEST 7/8] Testing GET /api/v1/indices/routes and route history endpoints..."
    )

    # 1. Routes overview
    resp = client.get("/api/v1/indices/routes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_routes"] == 10
    del_bom = next(r for r in data["routes"] if r["route_code"] == "DEL-BOM")
    assert del_bom["origin"] == "DEL"
    assert del_bom["destination"] == "BOM"
    assert del_bom["current_index"] > 0
    assert del_bom["avg_fare_inr"] == 5000.0
    assert del_bom["active_flights_tracked"] == 8
    print("  ✓ Routes overview returned 10 corridors. Monitored DEL-BOM live metrics:")
    print(f"    - Current Index: {del_bom['current_index']}")
    print(f"    - Avg Observed Fare: INR {del_bom['avg_fare_inr']}")
    print(f"    - Active Flights Tracked: {del_bom['active_flights_tracked']}")

    # 2. Specific corridor history
    resp_hist = client.get("/api/v1/indices/routes/DEL-BOM/history?days=30")
    assert resp_hist.status_code == 200
    data_hist = resp_hist.json()
    assert data_hist["route_code"] == "DEL-BOM"
    assert len(data_hist["points"]) >= 1
    print(
        f"  ✓ Route history for DEL-BOM returned {len(data_hist['points'])} points from database"
    )


def test_analytics_anomalies_filtering():
    """Verify GET /api/v1/analytics/anomalies with severity and status query filters."""
    print(
        "\n[TEST 8/8] Testing GET /api/v1/analytics/anomalies with severity & status filters..."
    )

    # Insert test anomaly alerts into DB
    now = datetime.now(UTC)
    with SessionLocal() as db:
        alert_crit = AnomalyAlert(
            origin="DEL",
            destination="BOM",
            airline_code="6E",
            alert_type="SURGE",
            severity="CRITICAL",
            flight_date=now.date(),
            booking_window="T+1",
            detected_fare=15000.0,
            baseline_fare=5000.0,
            z_score=3.85,
            pct_change=200.0,
            description="Extreme fare spike on DEL-BOM corridor",
            status="OPEN",
            created_at=now,
        )
        alert_low = AnomalyAlert(
            origin="BLR",
            destination="DEL",
            airline_code="AI",
            alert_type="PRICE_DROP",
            severity="LOW",
            flight_date=now.date(),
            booking_window="T+15",
            detected_fare=3200.0,
            baseline_fare=4800.0,
            z_score=-1.85,
            pct_change=-33.3,
            description="Promotional flash sale",
            status="RESOLVED",
            created_at=now - timedelta(hours=2),
        )
        db.add_all([alert_crit, alert_low])
        db.commit()

    # Query with severity=CRITICAL
    resp_crit = client.get("/api/v1/analytics/anomalies?severity=CRITICAL")
    assert resp_crit.status_code == 200
    data_crit = resp_crit.json()
    assert data_crit["total_alerts"] == 1
    assert data_crit["alerts"][0]["severity"] == "CRITICAL"
    assert data_crit["alerts"][0]["route_code"] == "DEL-BOM"
    print(
        f"  ✓ Filter severity=CRITICAL matched {data_crit['total_alerts']} alert: {data_crit['alerts'][0]['id']}"
    )

    # Query with status=RESOLVED
    resp_res = client.get("/api/v1/analytics/anomalies?status=RESOLVED")
    assert resp_res.status_code == 200
    data_res = resp_res.json()
    assert data_res["total_alerts"] == 1
    assert data_res["alerts"][0]["status"] == "RESOLVED"
    print(
        f"  ✓ Filter status=RESOLVED matched {data_res['total_alerts']} alert: {data_res['alerts'][0]['id']}"
    )

    # Query with route_code=DEL-BOM
    resp_route = client.get("/api/v1/analytics/anomalies?route_code=DEL-BOM")
    assert resp_route.status_code == 200
    data_route = resp_route.json()
    assert data_route["total_alerts"] == 1
    assert data_route["alerts"][0]["route_code"] == "DEL-BOM"
    print(f"  ✓ Filter route_code=DEL-BOM matched {data_route['total_alerts']} alert")


def main():
    print("=" * 75)
    print("APIx Cycle 2 API & Database Integration Test Suite")
    print("=" * 75)

    try:
        test_unseeded_mock_fallback()
        batch_payload, headers = test_batch_ingestion_and_db_persistence()
        test_idempotent_deduplication(batch_payload, headers)
        test_background_pipeline_execution()
        test_query_retrieval_national_latest()
        test_query_retrieval_national_history()
        test_query_retrieval_routes_overview_and_history()
        test_analytics_anomalies_filtering()

        print("\n" + "=" * 75)
        print("ALL 8 INTEGRATION TESTS COMPLETED SUCCESSFULLY WITH ZERO ERRORS!")
        print("=" * 75)
        sys.exit(0)
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)


if __name__ == "__main__":
    main()
