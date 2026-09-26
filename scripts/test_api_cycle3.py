#!/usr/bin/env python3
"""
APIx Airfare Price Index - Cycle 3 Test Suite
Verifies new Cycle 3 endpoints:
1. GET /api/v1/ingestion/telemetry (crawler health, scrapers active, proxy latency, error rates)
2. POST /api/v1/ingestion/trigger (manual crawler trigger)
3. WS /api/v1/stream/fares (WebSocket real-time fare streaming ticker)
4. GET /api/v1/analytics/arbitrage (airline vs OTA price spread per route)
5. GET /api/v1/stream/status and /api/v1/stream/recent (stream diagnostics and ticker buffer)
"""

import os
import sys
from datetime import UTC, date, datetime, timedelta, timezone

# Ensure worktree root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.crawler_job_repo import register_worker_heartbeat
from backend.app.db.session import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.models.raw_fare import RawFare
from backend.app.models.telemetry import ProxyHealthRecord, ScraperTelemetry

Base.metadata.create_all(bind=engine)
with SessionLocal() as db:
    register_worker_heartbeat(db, "worker-test-cycle3", "localhost", os.getpid())

# Arbitrage detection needs one flight quoted by a recognised direct airline
# channel and by an OTA, on a database this script would otherwise leave empty.
# is_direct_platform only matches when the airline code or name appears in the
# platform string, so "indigo" and "6e" both work; unknown names are treated as
# neither direct nor OTA and the pair is discarded.
with SessionLocal() as arb_db:
    for platform, total in (
        ("indigo", 4200.0),
        ("makemytrip", 6100.0),
        ("easemytrip", 5700.0),
    ):
        arb_db.add(
            RawFare(
                batch_id=1,
                origin="DEL",
                destination="BOM",
                flight_date=date.today(),
                booking_window="T+7",
                airline_code="6E",
                flight_number="6E-118",
                stops=0,
                fare_class="ECONOMY",
                base_fare=total - 500.0,
                taxes_and_fees=500.0,
                total_fare=total,
                source_platform=platform,
                scraped_at=datetime.now(UTC),
                hash_id=f"cycle3-arb-{platform}",
                is_synthetic=True,
                departure_time=datetime.combine(
                    date.today(), datetime.min.time()
                ).replace(hour=7, minute=30),
            )
        )
    arb_db.commit()

client = TestClient(app)


def test_telemetry_endpoint():
    print("[TEST 1/16] GET /api/v1/ingestion/telemetry")
    response = client.get("/api/v1/ingestion/telemetry")
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "system_health" in data
    assert "total_active_scrapers" in data
    assert "scrapers" in data
    assert "proxy_pool" in data
    assert len(data["scrapers"]) >= 1, "Expected at least 1 crawler health record"

    proxy_pool = data["proxy_pool"]
    assert "total_proxies" in proxy_pool
    assert "active_proxies" in proxy_pool
    assert "avg_latency_ms" in proxy_pool
    print(
        f"  ✓ Telemetry verified: status={data['system_health']}, active_scrapers={data['total_active_scrapers']}, proxies={proxy_pool['active_proxies']}/{proxy_pool['total_proxies']}"
    )


def test_telemetry_source_filtering():
    print("[TEST 2/16] GET /api/v1/ingestion/telemetry?source=makemytrip")
    response = client.get("/api/v1/ingestion/telemetry?source=makemytrip")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert (
        len(data["scrapers"]) == 1
    ), f"Expected 1 scraper, got {len(data['scrapers'])}"
    assert data["scrapers"][0]["crawler_name"] == "makemytrip"
    assert data["scrapers"][0]["uptime_pct"] > 0
    print(
        f"  ✓ Source filtering verified: {data['scrapers'][0]['crawler_name']} uptime={data['scrapers'][0]['uptime_pct']}%"
    )


def test_telemetry_hours_parameter():
    print("[TEST 3/16] GET /api/v1/ingestion/telemetry?hours=48")
    response = client.get("/api/v1/ingestion/telemetry?hours=48")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["system_health"] in ("HEALTHY", "DEGRADED", "CRITICAL")
    print("  ✓ Telemetry lookback window parameter accepted")


def test_crawler_trigger_post_json():
    print("[TEST 4/16] POST /api/v1/ingestion/trigger with JSON body")
    payload = {
        "crawler_name": "makemytrip",
        "route_code": "DEL-BOM",
        "booking_window": "T+7",
    }
    response = client.post(
        "/api/v1/ingestion/trigger",
        headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
        json=payload,
    )
    assert (
        response.status_code == 202
    ), f"Expected 202, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["status"] in ("TRIGGERED", "QUEUED")
    assert data["crawler_name"] == "makemytrip"
    assert data["route_code"] == "DEL-BOM"
    assert "task_id" in data and data["task_id"].startswith("trig-")
    print(
        f"  ✓ Manual trigger dispatched: task_id={data['task_id']}, crawler={data['crawler_name']}, route={data['route_code']}"
    )


def test_crawler_trigger_query_params():
    print("[TEST 5/16] POST /api/v1/ingestion/trigger with query parameters")
    response = client.post(
        "/api/v1/ingestion/trigger?crawler_name=spicejet&route_code=BOM-DEL",
        headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
    )
    assert response.status_code == 202, f"Expected 202, got {response.status_code}"
    data = response.json()
    assert data["status"] in ("TRIGGERED", "QUEUED")
    assert data["crawler_name"] == "spicejet"
    assert data["route_code"] == "BOM-DEL"
    print(f"  ✓ Trigger via query params accepted: task_id={data['task_id']}")


def test_proxy_diagnostics_endpoint():
    print("[TEST 6/16] GET /api/v1/ingestion/proxies")
    response = client.get("/api/v1/ingestion/proxies")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    proxies = response.json()
    assert isinstance(proxies, list) and len(proxies) > 0
    first = proxies[0]
    assert "proxy_ip" in first
    assert "status" in first
    assert "latency_ms" in first
    print(
        f"  ✓ Proxy diagnostics returned {len(proxies)} configured proxies (sample={first['proxy_ip']} {first['status']} {first['latency_ms']}ms)"
    )


def test_arbitrage_endpoint():
    print("[TEST 7/16] GET /api/v1/analytics/arbitrage")
    response = client.get("/api/v1/analytics/arbitrage")
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "generated_at" in data
    assert "routes_evaluated" in data
    assert "opportunities_count" in data
    assert "total_potential_savings_inr" in data
    assert "avg_spread_percentage" in data
    assert "items" in data
    assert len(data["items"]) > 0, "Expected at least 1 arbitrage opportunity"

    first = data["items"][0]
    assert "route_code" in first
    assert "airline_code" in first
    assert "buy_fare" in first
    assert "sell_fare" in first
    assert "spread_inr" in first
    assert "spread_percentage" in first
    assert "direction" in first
    assert "actionable" in first
    print(
        f"  ✓ Arbitrage returned {data['opportunities_count']} opportunities, total savings INR {data['total_potential_savings_inr']}, avg spread {data['avg_spread_percentage']}%"
    )


def test_arbitrage_route_filter():
    print("[TEST 8/16] GET /api/v1/analytics/arbitrage?route_code=DEL-BOM")
    response = client.get("/api/v1/analytics/arbitrage?route_code=DEL-BOM")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert len(data["items"]) > 0
    assert all(item["route_code"] == "DEL-BOM" for item in data["items"])
    print(
        f"  ✓ Route filtering confirmed: {len(data['items'])} opportunities on DEL-BOM"
    )


def test_arbitrage_airline_filter():
    print("[TEST 9/16] GET /api/v1/analytics/arbitrage?airline_code=6E")
    response = client.get("/api/v1/analytics/arbitrage?airline_code=6E")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert len(data["items"]) > 0
    assert all(item["airline_code"] == "6E" for item in data["items"])
    print(
        f"  ✓ Airline filtering confirmed: {len(data['items'])} IndiGo (6E) opportunities"
    )


def test_arbitrage_min_spread_filter():
    print("[TEST 10/16] GET /api/v1/analytics/arbitrage?min_spread_pct=6.0")
    response = client.get("/api/v1/analytics/arbitrage?min_spread_pct=6.0")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert all(item["spread_percentage"] >= 6.0 for item in data["items"])
    print(
        f"  ✓ Min spread percentage filter (>=6.0%) returned {len(data['items'])} opportunities"
    )


def test_arbitrage_actionable_only():
    print("[TEST 11/16] GET /api/v1/analytics/arbitrage?actionable_only=true")
    response = client.get("/api/v1/analytics/arbitrage?actionable_only=true")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert all(item["actionable"] is True for item in data["items"])
    print(
        f"  ✓ Actionable-only filter returned {len(data['items'])} high-confidence opportunities"
    )


def test_stream_status_endpoint():
    print("[TEST 12/16] GET /api/v1/stream/status")
    response = client.get("/api/v1/stream/status")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["status"] == "LIVE"
    assert "active_connections" in data
    assert "buffer_size" in data
    assert "uptime_seconds" in data
    print(
        f"  ✓ Stream status: status={data['status']}, buffer_size={data['buffer_size']}"
    )


def test_stream_recent_endpoint():
    print("[TEST 13/16] GET /api/v1/stream/recent?limit=5")
    response = client.get("/api/v1/stream/recent?limit=5")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    items = response.json()
    assert isinstance(items, list) and len(items) == 5
    sample = items[0]
    assert sample["type"] == "fare_update"
    assert "airline_code" in sample
    assert "flight_number" in sample
    assert "fare_inr" in sample
    assert "route_code" in sample
    print(
        f"  ✓ Stream recent returned 5 live fare quotes (sample={sample['flight_number']} {sample['route_code']} INR {sample['fare_inr']})"
    )


def test_websocket_fares_stream():
    print("[TEST 14/16] WS /api/v1/stream/fares (handshake, initial buffer, ping/pong)")
    with client.websocket_connect("/api/v1/stream/fares") as ws:
        # 1. First packet: Welcome handshake
        msg1 = ws.receive_json()
        assert (
            msg1["type"] == "connected"
        ), f"Expected 'connected', got {msg1.get('type')}"
        assert "timestamp" in msg1

        # 2. Second packet: Initial buffer history
        msg2 = ws.receive_json()
        assert (
            msg2["type"] == "initial_buffer"
        ), f"Expected 'initial_buffer', got {msg2.get('type')}"
        assert len(msg2["fares"]) > 0, "Expected non-empty initial fares buffer"

        # 3. Client ping -> pong response
        ws.send_text("ping")
        msg3 = ws.receive_json()
        assert msg3["type"] == "pong", f"Expected 'pong', got {msg3.get('type')}"

        # 4. Route subscription
        ws.send_json({"type": "subscribe", "route": "DEL-BOM"})
        msg4 = ws.receive_json()
        assert msg4["type"] == "subscribed"
        assert msg4["route"] == "DEL-BOM"

    print(
        "  ✓ WebSocket stream handshake, initial buffer, ping/pong, and subscription verified"
    )


def test_convenience_aliases():
    print(
        "[TEST 15/16] Convenience route aliases (/api/v1/telemetry and /api/v1/arbitrage)"
    )
    r_tel = client.get("/api/v1/telemetry")
    assert r_tel.status_code == 200
    assert "scrapers" in r_tel.json()

    r_arb = client.get("/api/v1/arbitrage")
    assert r_arb.status_code == 200
    assert "opportunities_count" in r_arb.json()

    print("  ✓ Convenience aliases /api/v1/telemetry and /api/v1/arbitrage functional")


def test_database_telemetry_persistence():
    print("[TEST 16/16] Database persistence: write telemetry record and verify in API")
    db = SessionLocal()
    try:
        now = datetime.now(UTC)
        record = ScraperTelemetry(
            crawler_name="test_bot",
            route="DEL-BOM",
            booking_window="T+1",
            status="SUCCESS",
            response_time_ms=250.0,
            proxy_ip="103.251.167.21:8080",
            records_extracted=45,
            error_details=None,
            created_at=now,
        )
        db.add(record)
        db.commit()

        # Query API for test_bot
        response = client.get("/api/v1/ingestion/telemetry?source=test_bot")
        assert response.status_code == 200
        data = response.json()
        assert len(data["scrapers"]) == 1
        assert data["scrapers"][0]["crawler_name"] == "test_bot"
        assert data["scrapers"][0]["success_count"] >= 1
        assert data["scrapers"][0]["fares_collected"] >= 45
        print(
            f"  ✓ Persisted DB record retrieved via API: {data['scrapers'][0]['crawler_name']} fares={data['scrapers'][0]['fares_collected']}"
        )
    finally:
        db.close()


def main():
    print("=" * 75)
    print("APIx Cycle 3 Backend API Test Suite: Telemetry, Streaming & Arbitrage")
    print("=" * 75)

    tests = [
        test_telemetry_endpoint,
        test_telemetry_source_filtering,
        test_telemetry_hours_parameter,
        test_crawler_trigger_post_json,
        test_crawler_trigger_query_params,
        test_proxy_diagnostics_endpoint,
        test_arbitrage_endpoint,
        test_arbitrage_route_filter,
        test_arbitrage_airline_filter,
        test_arbitrage_min_spread_filter,
        test_arbitrage_actionable_only,
        test_stream_status_endpoint,
        test_stream_recent_endpoint,
        test_websocket_fares_stream,
        test_convenience_aliases,
        test_database_telemetry_persistence,
    ]

    passed = 0
    failed = 0

    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            failed += 1
            import traceback

            traceback.print_exc()

    print("=" * 75)
    if failed == 0:
        print(
            f"ALL {passed} CYCLE 3 INTEGRATION TESTS COMPLETED SUCCESSFULLY WITH ZERO ERRORS!"
        )
        print("=" * 75)
        return 0
    else:
        print(f"TEST RUN FINISHED WITH {failed} FAILURES ({passed} passed)")
        print("=" * 75)
        return 1


if __name__ == "__main__":
    sys.exit(main())
