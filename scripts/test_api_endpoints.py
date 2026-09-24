#!/usr/bin/env python3
"""
APIx Airfare Price Index - Cycle 1 Test Suite
Verifies FastAPI routing, Pydantic v2 validation, authentication, and endpoint contracts.
"""

import sys
import os
from datetime import datetime, timedelta, timezone

# Ensure worktree root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.core.config import settings
from backend.app.db.session import engine, Base

# Ensure tables exist in database for endpoints using DB sessions
Base.metadata.create_all(bind=engine)

client = TestClient(app)


def test_health_endpoint():
    print("[TEST 1/13] GET /health")
    response = client.get("/health")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["status"] == "healthy", f"Expected status 'healthy', got {data.get('status')}"
    assert data["service"] == "apix-backend-api"
    assert "timestamp" in data
    print("  ✓ Health check passed with 200 OK")


def test_root_endpoint():
    print("[TEST 2/13] GET /")
    response = client.get("/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["status"] == "operational"
    assert "/docs" in data["docs"]
    print("  ✓ Root index passed with 200 OK")


def test_ingestion_batch_unauthorized_missing_header():
    print("[TEST 3/13] POST /api/v1/ingestion/batch without header (expect 401)")
    payload = {
        "source": "easemytrip_scraper",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "records": [
            {
                "airline_code": "6E",
                "flight_number": "6E-205",
                "origin": "DEL",
                "destination": "BOM",
                "departure_datetime": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                "booking_datetime": datetime.now(timezone.utc).isoformat(),
                "fare_inr": 6250.0,
                "cabin_class": "economy",
                "stops": 0,
                "source": "easemytrip_scraper",
            }
        ],
    }
    response = client.post("/api/v1/ingestion/batch", json=payload)
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["error"] is True
    assert "Missing required authentication header" in data["detail"]
    print("  ✓ Rejected unauthenticated batch with 401 Unauthorized")


def test_ingestion_batch_unauthorized_invalid_key():
    print("[TEST 4/13] POST /api/v1/ingestion/batch with invalid key (expect 401)")
    payload = {
        "source": "easemytrip_scraper",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "records": [
            {
                "airline_code": "6E",
                "flight_number": "6E-205",
                "origin": "DEL",
                "destination": "BOM",
                "departure_datetime": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                "booking_datetime": datetime.now(timezone.utc).isoformat(),
                "fare_inr": 6250.0,
            }
        ],
    }
    headers = {"X-Ingestion-Key": "completely-invalid-key-xyz"}
    response = client.post("/api/v1/ingestion/batch", json=payload, headers=headers)
    assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
    data = response.json()
    assert "Invalid X-Ingestion-Key" in data["detail"]
    print("  ✓ Rejected invalid key with 401 Unauthorized")


def test_ingestion_batch_authorized_valid():
    print("[TEST 5/13] POST /api/v1/ingestion/batch with valid key and sample batch (expect 200 OK)")
    dep1 = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    dep2 = (datetime.now(timezone.utc) + timedelta(days=12)).isoformat()
    now_str = datetime.now(timezone.utc).isoformat()

    payload = {
        "batch_id": "test-batch-001",
        "source": "makemytrip_pipeline",
        "scraped_at": now_str,
        "records": [
            {
                "airline_code": "6E",
                "flight_number": "6E-205",
                "origin": "DEL",
                "destination": "BOM",
                "departure_datetime": dep1,
                "arrival_datetime": (datetime.now(timezone.utc) + timedelta(days=5, hours=2)).isoformat(),
                "booking_datetime": now_str,
                "fare_inr": 5800.0,
                "cabin_class": "economy",
                "stops": 0,
                "source": "makemytrip_pipeline",
                "booking_window": 5,
            },
            {
                "airline_code": "AI",
                "flight_number": "AI-806",
                "origin": "BOM",
                "destination": "BLR",
                "departure_datetime": dep2,
                "booking_datetime": now_str,
                "fare_inr": 4200.0,
                "cabin_class": "economy",
                "stops": 0,
                "source": "makemytrip_pipeline",
                "booking_window": 12,
            },
        ],
    }
    headers = {"X-Ingestion-Key": settings.INGESTION_API_KEY}
    response = client.post("/api/v1/ingestion/batch", json=payload, headers=headers)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["batch_id"] == "test-batch-001"
    assert data["status"] == "success"
    assert data["records_received"] == 2
    assert data["records_valid"] == 2
    assert len(data["errors"]) == 0
    print(f"  ✓ Ingestion batch succeeded: {data['message']}")


def test_national_index_latest():
    print("[TEST 6/13] GET /api/v1/indices/national/latest")
    response = client.get("/api/v1/indices/national/latest")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "timestamp" in data
    assert data["index_value"] > 0
    assert "change_24h" in data
    assert "change_7d" in data
    assert data["sample_size"] >= 0
    assert data["base_period"] == "2026-01-01"
    assert data["status"] == "published"
    print(f"  ✓ National latest index verified: Index={data['index_value']} (Base 100)")


def test_national_index_history():
    print("[TEST 7/13] GET /api/v1/indices/national/history?days=14")
    response = client.get("/api/v1/indices/national/history?days=14")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "points" in data
    assert len(data["points"]) >= 1
    assert data["total_points"] >= 1
    first_pt = data["points"][0]
    assert "timestamp" in first_pt
    print(f"  ✓ National history returned {len(data['points'])} chronological points")


def test_routes_overview():
    print("[TEST 8/13] GET /api/v1/indices/routes")
    response = client.get("/api/v1/indices/routes")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "routes" in data
    assert len(data["routes"]) >= 5
    route_codes = [r["route_code"] for r in data["routes"]]
    assert "DEL-BOM" in route_codes
    assert "BOM-BLR" in route_codes
    print(f"  ✓ Routes overview returned {len(data['routes'])} active domestic corridors: {route_codes[:4]}...")


def test_route_history():
    print("[TEST 9/13] GET /api/v1/indices/routes/DEL-BOM/history")
    response = client.get("/api/v1/indices/routes/DEL-BOM/history?days=7")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["route_code"] == "DEL-BOM"
    assert data["origin"] == "DEL"
    assert data["destination"] == "BOM"
    assert len(data["points"]) >= 1
    print(f"  ✓ Route DEL-BOM history returned {len(data['points'])} points")


def test_lead_time_curve():
    print("[TEST 10/13] GET /api/v1/analytics/lead-time-curve?route_code=DEL-BOM")
    response = client.get("/api/v1/analytics/lead-time-curve?route_code=DEL-BOM")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["route_code"] == "DEL-BOM"
    assert "curve_points" in data
    points = data["curve_points"]
    assert len(points) == 11
    # Check advance booking hockey-stick trajectory: D-0 fare > D-90 fare
    d90 = next(p for p in points if p["days_before_departure"] == 90)
    d0 = next(p for p in points if p["days_before_departure"] == 0)
    assert d0["avg_fare_inr"] > d90["avg_fare_inr"], f"D-0 fare ({d0['avg_fare_inr']}) must exceed D-90 ({d90['avg_fare_inr']})"
    print(f"  ✓ Lead-time curve verified: D-90 INR {d90['avg_fare_inr']} -> D-0 INR {d0['avg_fare_inr']}")


def test_heatmap_matrix():
    print("[TEST 11/13] GET /api/v1/analytics/heatmap?route_code=NATIONAL")
    response = client.get("/api/v1/analytics/heatmap?route_code=NATIONAL")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["route_code"] == "NATIONAL"
    assert data["metric"] == "avg_fare"
    assert len(data["matrix"]) == 168  # 7 days * 24 hours
    assert data["min_val"] <= data["max_val"]
    print(f"  ✓ Heatmap matrix verified with 168 cells: Min={data['min_val']} Max={data['max_val']}")


def test_anomalies():
    print("[TEST 12/13] GET /api/v1/analytics/anomalies")
    response = client.get("/api/v1/analytics/anomalies")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "alerts" in data
    assert len(data["alerts"]) >= 3
    critical_alert = next((a for a in data["alerts"] if a["severity"] == "CRITICAL"), None)
    assert critical_alert is not None, "Expected at least one CRITICAL anomaly"
    assert critical_alert["anomaly_type"] in ("DGCA_CAP_EXCEEDED", "SPIKE", "SURGE_PRICING", "SURGE")
    print(f"  ✓ Anomaly alerts verified: {data['total_alerts']} alerts, including {critical_alert['id']}")


def test_dgca_validation():
    print("[TEST 13/13] GET /api/v1/analytics/dgca-validation")
    response = client.get("/api/v1/analytics/dgca-validation")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["total_routes_evaluated"] == 5
    assert data["total_violations"] > 0
    assert len(data["violations"]) == 5
    breach = next(v for v in data["violations"] if v["compliance_status"] == "BREACH_DETECTED")
    assert breach["observed_max_fare_inr"] > breach["statutory_band_cap_inr"]
    print(f"  ✓ DGCA statutory validation audit verified: {data['total_violations']} total violations found")


def main():
    print("=" * 70)
    print("Starting APIx Cycle 1 Backend API Test Suite...")
    print("=" * 70)

    try:
        test_health_endpoint()
        test_root_endpoint()
        test_ingestion_batch_unauthorized_missing_header()
        test_ingestion_batch_unauthorized_invalid_key()
        test_ingestion_batch_authorized_valid()
        test_national_index_latest()
        test_national_index_history()
        test_routes_overview()
        test_route_history()
        test_lead_time_curve()
        test_heatmap_matrix()
        test_anomalies()
        test_dgca_validation()
    except AssertionError as e:
        print("\n❌ TEST FAILED:", str(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print("\n💥 UNEXPECTED ERROR:", str(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 70)
    print("ALL 13 API ENDPOINT TESTS PASSED WITH ZERO ERRORS!")
    print("=" * 70)
    sys.exit(0)


if __name__ == "__main__":
    main()
