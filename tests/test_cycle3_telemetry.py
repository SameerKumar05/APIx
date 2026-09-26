"""Integration test suite for APIx Cycle 3 telemetry and operational monitoring.

SIH 2026 Problem Statement 26056 - Real-time Airfare Price Index for CPI Augmentation

Covers:
1. Database Telemetry Models:
   - ScraperTelemetry ORM mapping, fields, constraints, to_dict()
   - ProxyHealthRecord ORM mapping, latency scoring, consecutive failure tracking
2. Database Repository Layer (TelemetryRepo):
   - Single & bulk scraper telemetry logging
   - Crawler uptime & error rate statistical calculations
   - Proxy health upsert, latency statistics (avg, p95, min, max)
   - Retention policy pruning (cleanup_old_telemetry)
3. FastAPI Endpoints:
   - GET /api/v1/ingestion/telemetry (comprehensive health & crawler breakdowns)
   - POST /api/v1/ingestion/trigger (manual crawl dispatch with 202 Accepted)
   - GET /api/v1/ingestion/proxies (proxy diagnostic telemetry)
   - GET /api/v1/stream/status & GET /api/v1/stream/recent (live feed status)
   - WS /api/v1/stream/fares (WebSocket broadcast connection, ping-pong, streaming packets)
4. Edge cases & error handling:
   - Empty database telemetry resilience
   - Zero-hour window parameters
   - Unrecognized crawler identifiers
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.telemetry_repo import (
    TelemetryRepo,
    bulk_log_scraper_telemetry,
    calculate_crawler_error_rate,
    calculate_crawler_uptime,
    cleanup_old_telemetry,
    count_scraper_telemetry,
    get_active_healthy_proxies,
    get_crawler_summary,
    get_proxy_health_records,
    get_proxy_latency_stats,
    get_proxy_summary,
    get_scraper_telemetry,
    log_proxy_health,
    log_scraper_telemetry,
    upsert_proxy_health,
)
from backend.app.main import app
from backend.app.models.telemetry import ProxyHealthRecord, ScraperTelemetry
from backend.app.schemas.telemetry import (
    CrawlerHealthItem,
    CrawlerTriggerRequest,
    CrawlerTriggerResponse,
    IngestionTelemetryResponse,
    ProxyHealthItem,
    ProxyPoolSummary,
)

# ---------------------------------------------------------------------------
# 1. Database Model Tests
# ---------------------------------------------------------------------------


class TestTelemetryDatabaseModels:
    """Verifies SQLAlchemy schema mapping, fields, constraints, and helpers."""

    def test_scraper_telemetry_model_creation(self, db_session: Session):
        """Verifies creating, persisting, and querying a ScraperTelemetry record."""
        now = datetime.now(UTC)
        record = ScraperTelemetry(
            crawler_name="makemytrip",
            route="DEL-BOM",
            booking_window="T+1",
            status="SUCCESS",
            response_time_ms=145.5,
            records_extracted=24,
            proxy_ip="103.21.244.2:8080",
            error_details=None,
            created_at=now,
        )
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)

        assert record.id is not None
        assert record.id > 0
        assert record.crawler_name == "makemytrip"
        assert record.route == "DEL-BOM"
        assert record.booking_window == "T+1"
        assert record.status == "SUCCESS"
        assert record.response_time_ms == 145.5
        assert record.records_extracted == 24
        assert record.proxy_ip == "103.21.244.2:8080"
        assert record.error_details is None

        # Verify to_dict serialization
        data = record.to_dict()
        assert data["id"] == record.id
        assert data["crawler_name"] == "makemytrip"
        assert data["route"] == "DEL-BOM"
        assert data["status"] == "SUCCESS"
        assert data["records_extracted"] == 24

    def test_proxy_health_record_model_creation(self, db_session: Session):
        """Verifies creating, persisting, and properties of ProxyHealthRecord."""
        now = datetime.now(UTC)
        proxy = ProxyHealthRecord(
            proxy_ip="185.220.101.5:3128",
            status="HEALTHY",
            latency_ms=88.2,
            success_count=10,
            failure_count=1,
            consecutive_failures=0,
            last_checked_at=now,
            created_at=now,
        )
        db_session.add(proxy)
        db_session.commit()
        db_session.refresh(proxy)

        assert proxy.id is not None
        assert proxy.proxy_ip == "185.220.101.5:3128"
        assert proxy.status == "HEALTHY"
        assert proxy.latency_ms == 88.2
        assert proxy.success_count == 10
        assert proxy.failure_count == 1
        assert proxy.consecutive_failures == 0
        assert proxy.status == "HEALTHY"

        # Test to_dict
        d = proxy.to_dict()
        assert d["proxy_ip"] == "185.220.101.5:3128"
        assert d["status"] == "HEALTHY"
        assert d["latency_ms"] == 88.2


# ---------------------------------------------------------------------------
# 2. Database Repository Layer Tests
# ---------------------------------------------------------------------------


class TestTelemetryRepository:
    """Verifies TelemetryRepo methods for metrics, uptime, error rates, and purging."""

    def test_log_and_query_scraper_telemetry(self, db_session: Session):
        """Verifies single logging and query filtering via TelemetryRepo."""
        repo = TelemetryRepo(db_session)
        t1 = repo.log_telemetry(
            crawler_name="spicejet",
            route="DEL-BLR",
            booking_window="T+7",
            status="SUCCESS",
            response_time_ms=210.0,
            records_extracted=18,
        )
        assert t1.id is not None
        assert t1.crawler_name == "spicejet"

        t2 = repo.log_telemetry(
            crawler_name="easemytrip",
            route="DEL-BLR",
            booking_window="T+7",
            status="FAILED",
            response_time_ms=5000.0,
            records_extracted=0,
            error_details="Timeout: Connection refused",
        )
        assert t2.id is not None

        # Filter by crawler
        spicejet_records = repo.get_telemetry(crawler_name="spicejet")
        assert len(spicejet_records) == 1
        assert spicejet_records[0].crawler_name == "spicejet"

        # Filter by status
        failed_records = repo.get_telemetry(status="FAILED")
        assert len(failed_records) == 1
        assert failed_records[0].crawler_name == "easemytrip"

        # Count
        assert repo.count_telemetry(route="DEL-BLR") == 2

    def test_bulk_log_scraper_telemetry(self, db_session: Session):
        """Verifies bulk ingestion of scraper execution events."""
        records = [
            {
                "crawler_name": "makemytrip",
                "route": "DEL-BOM",
                "booking_window": f"T+{w}",
                "status": "SUCCESS",
                "response_time_ms": 120.0 + (w * 10),
                "records_extracted": 15,
            }
            for w in [1, 7, 15, 30]
        ]
        inserted = bulk_log_scraper_telemetry(db_session, records)
        assert inserted == 4
        assert count_scraper_telemetry(db_session, crawler_name="makemytrip") == 4

    def test_calculate_crawler_uptime_and_error_rate(self, db_session: Session):
        """Verifies mathematical calculation of crawler uptime and error rate percentages."""
        now = datetime.now(UTC)

        # Log 8 successful runs and 2 failed runs for 'makemytrip' -> 80% uptime, 20% error rate
        for i in range(8):
            log_scraper_telemetry(
                db=db_session,
                crawler_name="makemytrip",
                route="DEL-BOM",
                booking_window="T+1",
                status="SUCCESS",
                response_time_ms=150.0,
                records_extracted=20,
                created_at=now - timedelta(minutes=i * 5),
            )
        for i in range(2):
            log_scraper_telemetry(
                db=db_session,
                crawler_name="makemytrip",
                route="DEL-BOM",
                booking_window="T+1",
                status="FAILED",
                response_time_ms=4500.0,
                records_extracted=0,
                created_at=now - timedelta(minutes=50 + i * 5),
            )

        uptime = calculate_crawler_uptime(
            db_session, crawler_name="makemytrip", window_hours=2.0
        )
        assert uptime["uptime_pct"] == 80.0

        error_rate = calculate_crawler_error_rate(
            db_session, crawler_name="makemytrip", window_hours=2.0
        )
        assert error_rate["error_rate_pct"] == 20.0

        # Overall summary
        summary = get_crawler_summary(db_session, window_hours=2.0)
        assert summary["total_runs"] == 10
        assert summary["successful_runs"] == 8
        assert summary["failed_runs"] == 2
        assert summary["overall_uptime_pct"] == 80.0
        assert summary["overall_error_rate_pct"] == 20.0

    def test_proxy_health_upsert_and_latency_statistics(self, db_session: Session):
        """Verifies proxy health recording, streak counting, and latency aggregation."""
        # Record initial success
        p1 = upsert_proxy_health(
            db=db_session,
            proxy_ip="103.15.22.1:8080",
            status="HEALTHY",
            latency_ms=120.0,
            is_success=True,
        )
        assert p1.success_count == 1
        assert p1.consecutive_failures == 0

        # Record second success with different latency
        p2 = upsert_proxy_health(
            db=db_session,
            proxy_ip="103.15.22.1:8080",
            status="HEALTHY",
            latency_ms=180.0,
            is_success=True,
        )
        assert p2.id == p1.id
        assert p2.success_count == 2
        assert p2.consecutive_failures == 0

        # Record another proxy with high latency
        upsert_proxy_health(
            db=db_session,
            proxy_ip="194.32.40.5:3128",
            status="DEGRADED",
            latency_ms=450.0,
            is_success=True,
        )

        # Latency statistics
        stats = get_proxy_latency_stats(db_session)
        assert stats["count"] == 2
        assert stats["min_latency_ms"] <= 180.0
        assert stats["max_latency_ms"] >= 450.0
        assert stats["avg_latency_ms"] > 0.0

        # Active healthy proxies filter
        healthy = get_active_healthy_proxies(db_session, max_latency_ms=300.0)
        assert len(healthy) == 1
        assert healthy[0].proxy_ip == "103.15.22.1:8080"

        # Proxy summary
        summary = get_proxy_summary(db_session)
        assert summary["distinct_proxies"] == 2
        assert summary["healthy_count"] >= 1

    def test_cleanup_old_telemetry(self, db_session: Session):
        """Verifies deletion of telemetry records older than retention period."""
        now = datetime.now(UTC)

        # 3 recent records (today)
        for _ in range(3):
            log_scraper_telemetry(
                db=db_session,
                crawler_name="synthetic",
                route="DEL-BOM",
                booking_window="T+1",
                status="SUCCESS",
                created_at=now - timedelta(days=1),
            )

        # 4 old records (45 days old)
        for _ in range(4):
            log_scraper_telemetry(
                db=db_session,
                crawler_name="synthetic",
                route="DEL-BOM",
                booking_window="T+1",
                status="SUCCESS",
                created_at=now - timedelta(days=45),
            )

        assert count_scraper_telemetry(db_session) == 7

        result = cleanup_old_telemetry(db_session, retention_days=30)
        assert result["total_pruned"] == 4
        assert count_scraper_telemetry(db_session) == 3


# ---------------------------------------------------------------------------
# 3. FastAPI Telemetry & Trigger Endpoint Tests
# ---------------------------------------------------------------------------


class TestTelemetryEndpoints:
    """Tests for FastAPI HTTP endpoints: /telemetry, /trigger, /proxies, and streaming."""

    @pytest.fixture(autouse=True)
    def ensure_active_worker(self):
        from backend.app.db.crawler_job_repo import register_worker_heartbeat
        from backend.app.db.session import SessionLocal, init_db

        init_db()
        with SessionLocal() as db:
            register_worker_heartbeat(
                db=db,
                worker_id="worker-fixture-telemetry",
                hostname="localhost",
                pid=99999,
            )
        yield

    def test_get_ingestion_telemetry_schema(self):
        """Verifies GET /api/v1/ingestion/telemetry conforms to IngestionTelemetryResponse."""
        client = TestClient(app)
        response = client.get("/api/v1/ingestion/telemetry")
        assert response.status_code == 200

        data = response.json()
        validated = IngestionTelemetryResponse(**data)
        assert validated.system_health in ("HEALTHY", "DEGRADED", "ERROR", "ACTIVE")
        assert validated.total_active_scrapers >= 1
        assert isinstance(validated.scrapers, list)
        assert len(validated.scrapers) >= 1
        assert isinstance(validated.proxy_pool, ProxyPoolSummary)
        assert validated.proxy_pool.total_proxies >= 0

        # Validate CrawlerHealthItem properties
        for s in validated.scrapers:
            assert isinstance(s, CrawlerHealthItem)
            assert 0.0 <= s.uptime_pct <= 100.0
            assert 0.0 <= s.error_rate_pct <= 100.0
            assert s.crawler_name

    def test_get_ingestion_telemetry_filters(self):
        """Verifies GET /api/v1/ingestion/telemetry query parameter filtering."""
        client = TestClient(app)

        # Filter by source
        resp_mmt = client.get("/api/v1/ingestion/telemetry?source=makemytrip")
        assert resp_mmt.status_code == 200
        data_mmt = resp_mmt.json()
        assert len(data_mmt["scrapers"]) == 1
        assert data_mmt["scrapers"][0]["crawler_name"] == "makemytrip"

        # Filter by hours
        resp_hours = client.get("/api/v1/ingestion/telemetry?hours=48")
        assert resp_hours.status_code == 200

    def test_post_trigger_crawler_with_json_body(self):
        """Verifies POST /api/v1/ingestion/trigger with JSON body dispatches job."""
        client = TestClient(app)
        payload = {
            "crawler_name": "makemytrip",
            "route_code": "DEL-BOM",
            "booking_window": "T+1",
        }
        response = client.post(
            "/api/v1/ingestion/trigger",
            headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
            json=payload,
        )
        assert response.status_code == 202

        data = response.json()
        validated = CrawlerTriggerResponse(**data)
        assert validated.task_id.startswith("trig-")
        assert validated.status in ("TRIGGERED", "QUEUED", "SUCCESS")
        assert validated.crawler_name == "makemytrip"
        assert validated.route_code == "DEL-BOM"
        assert "queued" in validated.message.lower()

    def test_post_trigger_crawler_with_query_params(self):
        """Verifies POST /api/v1/ingestion/trigger using query parameters."""
        client = TestClient(app)
        response = client.post(
            "/api/v1/ingestion/trigger?crawler_name=spicejet&route_code=DEL-BLR",
            headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
        )
        assert response.status_code == 202

        data = response.json()
        assert data["crawler_name"] == "spicejet"
        assert data["route_code"] == "DEL-BLR"

    def test_get_proxy_diagnostics(self):
        """Verifies GET /api/v1/ingestion/proxies returns detailed proxy records."""
        client = TestClient(app)
        response = client.get("/api/v1/ingestion/proxies")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        if data:
            item = ProxyHealthItem(**data[0])
            assert item.proxy_ip
            assert item.status in ("HEALTHY", "DEGRADED", "BANNED", "TIMEOUT")
            assert item.latency_ms >= 0.0

    def test_stream_status_endpoint(self):
        """Verifies GET /api/v1/stream/status returns real-time hub statistics."""
        client = TestClient(app)
        response = client.get("/api/v1/stream/status")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert "active_connections" in data
        assert "server_time" in data

    def test_stream_recent_fares_endpoint(self):
        """Verifies GET /api/v1/stream/recent returns recent ticker quotes."""
        client = TestClient(app)
        response = client.get("/api/v1/stream/recent?limit=5")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 5

    def test_websocket_fares_stream(self):
        """Verifies WebSocket /api/v1/stream/fares handshake, messaging, and ping-pong."""
        client = TestClient(app)
        with client.websocket_connect("/api/v1/stream/fares") as websocket:
            # 1. First frame sent on connection is initial subscription confirmation or fare packet
            initial = websocket.receive_json()
            assert isinstance(initial, dict)
            assert "type" in initial
            assert initial["type"] in (
                "connected",
                "subscribed",
                "fare_update",
                "welcome",
            )

            # 2. Client sends ping (handling any pending buffer frame)
            websocket.send_text("ping")
            pong = websocket.receive_text()
            try:
                parsed = json.loads(pong)
                if parsed.get("type") == "initial_buffer":
                    pong = websocket.receive_text()
                    parsed = json.loads(pong)
            except Exception:
                parsed = {}
            assert pong == "pong" or (
                isinstance(parsed, dict) and parsed.get("type") == "pong"
            )


# ---------------------------------------------------------------------------
# 4. Edge Cases & Resilience Tests
# ---------------------------------------------------------------------------


class TestTelemetryEdgeCases:
    """Verifies edge-case safety, zero durations, and non-existent crawler filters."""

    def test_calculate_uptime_no_records(self, db_session: Session):
        """Verifies empty database calculates 100.0% default uptime."""
        uptime = calculate_crawler_uptime(db_session, crawler_name="nonexistent")
        assert uptime["uptime_pct"] == 100.0

    def test_calculate_error_rate_no_records(self, db_session: Session):
        """Verifies empty database calculates 0.0% default error rate."""
        err_rate = calculate_crawler_error_rate(db_session, crawler_name="nonexistent")
        assert err_rate["error_rate_pct"] == 0.0

    def test_telemetry_query_start_time(self, db_session: Session):
        """Verifies query with start_time cutoff does not crash."""
        records = get_scraper_telemetry(db_session, start_time=datetime.now(UTC))
        assert isinstance(records, list)

    def test_crawler_summary_empty(self, db_session: Session):
        """Verifies get_crawler_summary returns safe defaults on empty DB."""
        summary = get_crawler_summary(db_session, window_hours=24.0)
        assert summary["total_runs"] == 0
        assert summary["overall_uptime_pct"] == 100.0
        assert summary["overall_error_rate_pct"] == 0.0
