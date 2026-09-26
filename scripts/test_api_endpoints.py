#!/usr/bin/env python3
"""
APIx Airfare Price Index - Cycle 1 Test Suite
Verifies FastAPI routing, Pydantic v2 validation, authentication, and endpoint contracts.
"""

import os
import sys
from datetime import UTC, date, datetime, timedelta, timezone

# Ensure worktree root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.seed import seed_routes
from backend.app.db.session import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.models.anomaly import AnomalyAlert
from backend.app.models.econometrics import DgcaViolation
from backend.app.models.index import RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.route import Route

# Ensure tables exist in database for endpoints using DB sessions
Base.metadata.create_all(bind=engine)

# verify_all.sh deletes apix.db immediately before this script, so the assertions
# below need their own rows. /indices/routes only reports corridors holding a stored
# RouteDailyIndex, and its 24h change divides by a prior day, hence two dates each.
with SessionLocal() as seed_db:
    seed_routes(seed_db)
    for route in seed_db.query(Route).filter(Route.is_active.is_(True)).all():
        for days_ago in (1, 0):
            seed_db.add(
                RouteDailyIndex(
                    origin=route.origin,
                    destination=route.destination,
                    index_date=date.today() - timedelta(days=days_ago),
                    booking_window="T+7",
                    index_type="composite",
                    sample_size=4,
                    median_fare=5000.0 + days_ago * 100,
                    mean_fare=5100.0 + days_ago * 100,
                    min_fare=4500.0,
                    max_fare=6000.0,
                    percentile_25=4800.0,
                    percentile_75=5400.0,
                    std_dev=350.0,
                    index_value=100.0 + days_ago * 2.0,
                    base_period="synthetic",
                    calculation_timestamp=datetime.now(UTC),
                    created_at=datetime.now(UTC),
                )
            )
    seed_db.commit()

def _seed_fare(session, origin, destination, window, total_fare, departure, tag):
    session.add(
        RawFare(
            batch_id=1,
            origin=origin,
            destination=destination,
            flight_date=date.today() + timedelta(days=30),
            booking_window=window,
            airline_code="6E",
            flight_number=f"6E-{tag}",
            stops=0,
            fare_class="ECONOMY",
            base_fare=total_fare - 500.0,
            taxes_and_fees=500.0,
            total_fare=total_fare,
            source_platform="synthetic",
            scraped_at=datetime.now(UTC),
            hash_id=f"apitest-{tag}",
            is_synthetic=True,
            departure_time=departure,
            duration_minutes=120,
        )
    )


# The lead-time curve buckets RawFare by booking window, and the heatmap emits one
# cell per observed (weekday, hour) rather than zero-filling, so its 168-cell
# assertion needs 7x24 real rows. Curve rows stay on DEL-BOM to keep that count
# at exactly 11; heatmap rows go on the reverse corridor to avoid adding windows.
_LEAD_WINDOWS = ["T+0", "T+1", "T+3", "T+7", "T+14", "T+21", "T+30", "T+45", "T+60", "T+75", "T+90"]
with SessionLocal() as fare_db:
    for i, win in enumerate(_LEAD_WINDOWS):
        _seed_fare(
            fare_db, "DEL", "BOM", win, 5500.0 - i * 150.0,
            datetime(2026, 1, 5, 9, 0), f"lead{i}",
        )
    for day in range(7):
        for hour in range(24):
            _seed_fare(
                fare_db, "BOM", "DEL", "T+7", 4200.0 + hour * 10.0 + day,
                datetime(2026, 1, 5 + day, hour, 0), f"heat{day}-{hour}",
            )
    fare_db.commit()

# The anomalies endpoint reads stored alerts, so the assertions need some present.
with SessionLocal() as alert_db:
    for alert_type, severity in (
        ("SPIKE", "CRITICAL"),
        ("SURGE_PRICING", "WARNING"),
        ("DGCA_CAP_EXCEEDED", "HIGH"),
    ):
        alert_db.add(
            AnomalyAlert(
                origin="DEL",
                destination="BOM",
                alert_type=alert_type,
                severity=severity,
                status="OPEN",
                created_at=datetime.now(UTC),
            )
        )
    alert_db.commit()

# The DGCA audit reports stored violation rows grouped by route; the assertions
# expect five evaluated routes and at least one fare above its statutory band cap.
with SessionLocal() as dgca_db:
    for idx, route_code in enumerate(["DEL-BOM", "BOM-BLR", "BLR-DEL", "DEL-BLR", "BOM-DEL"]):
        dgca_db.add(
            DgcaViolation(
                route_code=route_code,
                airline_code="6E",
                flight_number=f"6E-dgca{idx}",
                flight_date=date.today() + timedelta(days=30),
                window="T+7",
                fare_inr=9500.0 + idx * 100,
                median_baseline_fare=5000.0,
                surge_multiple=1.9 + idx * 0.05,
                severity="CRITICAL",
                violation_code="DGCA_CAP_EXCEEDED",
                detected_at=datetime.now(UTC),
                status="OPEN",
            )
        )
    dgca_db.commit()

client = TestClient(app)


def test_health_endpoint():
    print("[TEST 1/13] GET /health")
    response = client.get("/health")
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert (
        data["status"] == "healthy"
    ), f"Expected status 'healthy', got {data.get('status')}"
    assert data["service"] == "apix-backend-api"
    assert "timestamp" in data
    print("  ✓ Health check passed with 200 OK")


def test_root_endpoint():
    print("[TEST 2/13] GET /")
    response = client.get("/")
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["status"] == "operational"
    assert "/docs" in data["docs"]
    print("  ✓ Root index passed with 200 OK")


def test_ingestion_batch_unauthorized_missing_header():
    print("[TEST 3/13] POST /api/v1/ingestion/batch without header (expect 401)")
    payload = {
        "source": "easemytrip_scraper",
        "scraped_at": datetime.now(UTC).isoformat(),
        "records": [
            {
                "airline_code": "6E",
                "flight_number": "6E-205",
                "origin": "DEL",
                "destination": "BOM",
                "departure_datetime": (
                    datetime.now(UTC) + timedelta(days=7)
                ).isoformat(),
                "booking_datetime": datetime.now(UTC).isoformat(),
                "fare_inr": 6250.0,
                "cabin_class": "economy",
                "stops": 0,
                "source": "easemytrip_scraper",
            }
        ],
    }
    response = client.post("/api/v1/ingestion/batch", json=payload)
    assert (
        response.status_code == 401
    ), f"Expected 401, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["error"] is True
    assert "Missing required authentication header" in data["detail"]
    print("  ✓ Rejected unauthenticated batch with 401 Unauthorized")


def test_ingestion_batch_unauthorized_invalid_key():
    print("[TEST 4/13] POST /api/v1/ingestion/batch with invalid key (expect 401)")
    payload = {
        "source": "easemytrip_scraper",
        "scraped_at": datetime.now(UTC).isoformat(),
        "records": [
            {
                "airline_code": "6E",
                "flight_number": "6E-205",
                "origin": "DEL",
                "destination": "BOM",
                "departure_datetime": (
                    datetime.now(UTC) + timedelta(days=7)
                ).isoformat(),
                "booking_datetime": datetime.now(UTC).isoformat(),
                "fare_inr": 6250.0,
            }
        ],
    }
    headers = {"X-Ingestion-Key": "completely-invalid-key-xyz"}
    response = client.post("/api/v1/ingestion/batch", json=payload, headers=headers)
    assert (
        response.status_code == 401
    ), f"Expected 401, got {response.status_code}: {response.text}"
    data = response.json()
    assert "Invalid X-Ingestion-Key" in data["detail"]
    print("  ✓ Rejected invalid key with 401 Unauthorized")


def test_ingestion_batch_authorized_valid():
    print(
        "[TEST 5/13] POST /api/v1/ingestion/batch with valid key and sample batch (expect 200 OK)"
    )
    dep1 = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    dep2 = (datetime.now(UTC) + timedelta(days=12)).isoformat()
    now_str = datetime.now(UTC).isoformat()

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
                "arrival_datetime": (
                    datetime.now(UTC) + timedelta(days=5, hours=2)
                ).isoformat(),
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
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
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
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
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
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
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
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "routes" in data
    assert len(data["routes"]) >= 5
    route_codes = [r["route_code"] for r in data["routes"]]
    assert "DEL-BOM" in route_codes
    assert "BOM-BLR" in route_codes
    print(
        f"  ✓ Routes overview returned {len(data['routes'])} active domestic corridors: {route_codes[:4]}..."
    )


def test_route_history():
    print("[TEST 9/13] GET /api/v1/indices/routes/DEL-BOM/history")
    response = client.get("/api/v1/indices/routes/DEL-BOM/history?days=7")
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["route_code"] == "DEL-BOM"
    assert data["origin"] == "DEL"
    assert data["destination"] == "BOM"
    assert len(data["points"]) >= 1
    print(f"  ✓ Route DEL-BOM history returned {len(data['points'])} points")


def test_lead_time_curve():
    print("[TEST 10/13] GET /api/v1/analytics/lead-time-curve?route_code=DEL-BOM")
    response = client.get("/api/v1/analytics/lead-time-curve?route_code=DEL-BOM")
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["route_code"] == "DEL-BOM"
    assert "curve_points" in data
    points = data["curve_points"]
    # The curve has one point per observed booking window. An earlier test in this
    # same script ingests DEL-BOM fares through the API, so the exact count also
    # moves with that; the shape assertion below is the real claim.
    assert len(points) >= 11
    # Check advance booking hockey-stick trajectory: D-0 fare > D-90 fare
    d90 = next(p for p in points if p["days_before_departure"] == 90)
    d0 = next(p for p in points if p["days_before_departure"] == 0)
    assert (
        d0["avg_fare_inr"] > d90["avg_fare_inr"]
    ), f"D-0 fare ({d0['avg_fare_inr']}) must exceed D-90 ({d90['avg_fare_inr']})"
    print(
        f"  ✓ Lead-time curve verified: D-90 INR {d90['avg_fare_inr']} -> D-0 INR {d0['avg_fare_inr']}"
    )


def test_heatmap_matrix():
    print("[TEST 11/13] GET /api/v1/analytics/heatmap?route_code=NATIONAL")
    response = client.get("/api/v1/analytics/heatmap?route_code=NATIONAL")
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["route_code"] == "NATIONAL"
    assert data["metric"] == "avg_fare"
    assert len(data["matrix"]) == 168  # 7 days * 24 hours
    assert data["min_val"] <= data["max_val"]
    print(
        f"  ✓ Heatmap matrix verified with 168 cells: Min={data['min_val']} Max={data['max_val']}"
    )


def test_anomalies():
    print("[TEST 12/13] GET /api/v1/analytics/anomalies")
    response = client.get("/api/v1/analytics/anomalies")
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "alerts" in data
    assert len(data["alerts"]) >= 3
    critical_alert = next(
        (a for a in data["alerts"] if a["severity"] == "CRITICAL"), None
    )
    assert critical_alert is not None, "Expected at least one CRITICAL anomaly"
    assert critical_alert["anomaly_type"] in (
        "DGCA_CAP_EXCEEDED",
        "SPIKE",
        "SURGE_PRICING",
        "SURGE",
    )
    print(
        f"  ✓ Anomaly alerts verified: {data['total_alerts']} alerts, including {critical_alert['id']}"
    )


def test_dgca_validation():
    print("[TEST 13/13] GET /api/v1/analytics/dgca-validation")
    response = client.get("/api/v1/analytics/dgca-validation")
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["total_routes_evaluated"] == 5
    assert data["total_violations"] > 0
    assert len(data["violations"]) == 5
    breach = next(
        v for v in data["violations"] if v["compliance_status"] == "BREACH_DETECTED"
    )
    assert breach["observed_max_fare_inr"] > breach["statutory_band_cap_inr"]
    print(
        f"  ✓ DGCA statutory validation audit verified: {data['total_violations']} total violations found"
    )


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
