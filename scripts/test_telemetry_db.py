"""Verification script for APIx scraper telemetry, proxy health models, and telemetry_repo.

Validates:
1. Table creation for `scraper_telemetry` and `proxy_health_records`.
2. Telemetry event logging (single and bulk) with serialization (to_dict, repr).
3. Querying and filtering across routes, crawlers, statuses, and time windows.
4. Crawler uptime and error rate aggregation calculations.
5. Proxy health tracking, circuit-break state transitions, and latency statistics (avg, min, max, p95).
6. Automated retention pruning for telemetry and proxy records.
7. Object-oriented TelemetryRepo wrapper methods.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
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

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from backend.app.db.session import Base
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
from backend.app.models import ProxyHealthRecord, ScraperTelemetry


def run_tests() -> bool:
    print("=" * 75)
    print("APIx Cycle 3 Telemetry & Proxy Health DB Verification")
    print("=" * 75)

    # 1. Database Initialization
    print("\n[1/7] Initializing in-memory SQLite database and creating schema...")
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "scraper_telemetry" in tables, f"scraper_telemetry missing in {tables}"
    assert "proxy_health_records" in tables, f"proxy_health_records missing in {tables}"
    print("  ✓ Tables 'scraper_telemetry' and 'proxy_health_records' verified.")

    # Inspect columns
    telemetry_cols = {col["name"] for col in inspector.get_columns("scraper_telemetry")}
    expected_t_cols = {
        "id",
        "crawler_name",
        "route",
        "booking_window",
        "status",
        "response_time_ms",
        "proxy_ip",
        "records_extracted",
        "error_details",
        "created_at",
    }
    assert expected_t_cols.issubset(telemetry_cols), f"Missing telemetry columns: {expected_t_cols - telemetry_cols}"
    print(f"  ✓ ScraperTelemetry columns verified: {sorted(list(expected_t_cols))}")

    proxy_cols = {col["name"] for col in inspector.get_columns("proxy_health_records")}
    expected_p_cols = {
        "id",
        "proxy_ip",
        "status",
        "latency_ms",
        "success_count",
        "failure_count",
        "consecutive_failures",
        "last_checked_at",
        "error_message",
        "created_at",
    }
    assert expected_p_cols.issubset(proxy_cols), f"Missing proxy columns: {expected_p_cols - proxy_cols}"
    print(f"  ✓ ProxyHealthRecord columns verified: {sorted(list(expected_p_cols))}")

    # 2. Scraper Telemetry Logging
    print("\n[2/7] Testing individual and bulk scraper telemetry logging...")
    t1 = log_scraper_telemetry(
        db=db,
        crawler_name="makemytrip",
        route="DEL-BOM",
        booking_window="T+1",
        status="SUCCESS",
        response_time_ms=1240.5,
        records_extracted=42,
        proxy_ip="192.168.1.101:8080",
    )
    assert t1.id is not None
    assert t1.crawler_name == "makemytrip"
    assert t1.records_extracted == 42
    assert "makemytrip" in repr(t1)
    d1 = t1.to_dict()
    assert d1["crawler_name"] == "makemytrip"
    assert d1["status"] == "SUCCESS"
    assert d1["response_time_ms"] == 1240.5
    print("  ✓ Single telemetry log & serialization passed.")

    # Bulk insert
    bulk_data = [
        {
            "crawler_name": "makemytrip",
            "route": "BOM-DEL",
            "booking_window": "T+7",
            "status": "SUCCESS",
            "response_time_ms": 1150.0,
            "records_extracted": 38,
            "proxy_ip": "192.168.1.101:8080",
        },
        {
            "crawler_name": "makemytrip",
            "route": "BLR-DEL",
            "booking_window": "T+15",
            "status": "FAILED",
            "response_time_ms": 5000.0,
            "records_extracted": 0,
            "proxy_ip": "192.168.1.102:8080",
            "error_details": "HTTP 403 Forbidden - Cloudflare challenge triggered",
        },
        {
            "crawler_name": "spicejet",
            "route": "DEL-BOM",
            "booking_window": "T+1",
            "status": "SUCCESS",
            "response_time_ms": 820.0,
            "records_extracted": 15,
            "proxy_ip": "192.168.1.103:8080",
        },
        {
            "crawler_name": "spicejet",
            "route": "DEL-BOM",
            "booking_window": "T+7",
            "status": "SUCCESS",
            "response_time_ms": 890.0,
            "records_extracted": 18,
            "proxy_ip": "192.168.1.103:8080",
        },
        {
            "crawler_name": "easemytrip",
            "route": "DEL-BOM",
            "booking_window": "T+1",
            "status": "fallback_amadeus",
            "response_time_ms": 1450.0,
            "records_extracted": 25,
            "proxy_ip": None,
        },
        {
            "crawler_name": "easemytrip",
            "route": "DEL-BOM",
            "booking_window": "T+30",
            "status": "TIMEOUT",
            "response_time_ms": 8000.0,
            "records_extracted": 0,
            "proxy_ip": "192.168.1.104:8080",
            "error_details": "ConnectionTimeout after 8000ms",
        },
    ]
    inserted = bulk_log_scraper_telemetry(db, bulk_data)
    assert inserted == len(bulk_data), f"Expected {len(bulk_data)}, got {inserted}"

    total_count = count_scraper_telemetry(db)
    assert total_count == 7, f"Expected 7 records, got {total_count}"

    # Query with filters
    mmt_records = get_scraper_telemetry(db, crawler_name="makemytrip")
    assert len(mmt_records) == 3, f"Expected 3 MMT records, got {len(mmt_records)}"

    failed_records = get_scraper_telemetry(db, status="FAILED")
    assert len(failed_records) == 1
    assert failed_records[0].error_details is not None
    print(f"  ✓ Bulk logged {inserted} records. Query filters verified.")

    # 3. Crawler Uptime and Error Rate Aggregations
    print("\n[3/7] Testing crawler uptime and error rate aggregation calculations...")
    # makemytrip has 3 runs: 2 SUCCESS, 1 FAILED -> 66.67% uptime, 33.33% error rate
    mmt_uptime = calculate_crawler_uptime(db, crawler_name="makemytrip", window_hours=24)
    assert mmt_uptime["total_runs"] == 3
    assert mmt_uptime["successful_runs"] == 2
    assert mmt_uptime["failed_runs"] == 1
    assert mmt_uptime["uptime_pct"] == 66.67
    assert mmt_uptime["total_records_extracted"] == 80  # 42 + 38 + 0
    print(f"  ✓ MakeMyTrip uptime: {mmt_uptime['uptime_pct']}% (2/3 runs)")

    mmt_error = calculate_crawler_error_rate(db, crawler_name="makemytrip", window_hours=24)
    assert mmt_error["total_runs"] == 3
    assert mmt_error["error_runs"] == 1
    assert mmt_error["error_rate_pct"] == 33.33
    assert "FAILED" in mmt_error["errors_by_status"]
    assert len(mmt_error["recent_errors"]) == 1
    print(f"  ✓ MakeMyTrip error rate: {mmt_error['error_rate_pct']}%")

    # spicejet has 2 runs: 2 SUCCESS -> 100% uptime, 0% error rate
    sp_uptime = calculate_crawler_uptime(db, crawler_name="spicejet", window_hours=24)
    assert sp_uptime["uptime_pct"] == 100.0
    assert sp_uptime["successful_runs"] == 2

    # easemytrip has 2 runs: 1 fallback_amadeus (considered successful degraded), 1 TIMEOUT
    emt_uptime = calculate_crawler_uptime(db, crawler_name="easemytrip", window_hours=24)
    assert emt_uptime["total_runs"] == 2
    assert emt_uptime["successful_runs"] == 1
    assert emt_uptime["uptime_pct"] == 50.0

    # Aggregate across all crawlers (7 total: 5 success, 2 failed -> 71.43%)
    all_uptime = calculate_crawler_uptime(db, crawler_name=None, window_hours=24)
    assert all_uptime["total_runs"] == 7
    assert all_uptime["successful_runs"] == 5
    assert all_uptime["failed_runs"] == 2
    assert all_uptime["uptime_pct"] == 71.43
    assert "makemytrip" in all_uptime["crawlers"]
    assert "spicejet" in all_uptime["crawlers"]
    assert "easemytrip" in all_uptime["crawlers"]
    print(f"  ✓ Global crawler uptime: {all_uptime['uptime_pct']}% across 3 platforms")

    # Empty state handling
    empty_uptime = calculate_crawler_uptime(db, crawler_name="nonexistent_crawler", window_hours=24)
    assert empty_uptime["total_runs"] == 0
    assert empty_uptime["uptime_pct"] == 100.0
    empty_error = calculate_crawler_error_rate(db, crawler_name="nonexistent_crawler", window_hours=24)
    assert empty_error["error_rate_pct"] == 0.0
    print("  ✓ Empty state defaults (100% uptime, 0% error) verified.")

    # Crawler summary composite
    summary = get_crawler_summary(db, window_hours=24)
    assert summary["total_runs"] == 7
    assert summary["overall_uptime_pct"] == 71.43
    assert summary["overall_error_rate_pct"] == 28.57
    print(f"  ✓ Composite crawler summary verified: {summary['overall_uptime_pct']}% uptime, {summary['total_records_extracted']} total records.")

    # 4. Proxy Health Logging and State Transitions
    print("\n[4/7] Testing proxy health logging, circuit breaking, and upsert...")
    p1 = log_proxy_health(
        db=db,
        proxy_ip="10.0.0.1:3128",
        status="HEALTHY",
        latency_ms=150.0,
        success_count=10,
        failure_count=0,
    )
    assert p1.id is not None
    assert p1.status == "HEALTHY"
    p1_dict = p1.to_dict()
    assert p1_dict["proxy_ip"] == "10.0.0.1:3128"
    assert "10.0.0.1:3128" in repr(p1)
    print("  ✓ ProxyHealthRecord created & serialized.")

    # Upsert proxy health transitions
    target_proxy = "10.0.0.2:8080"
    # 1st success
    u1 = upsert_proxy_health(db, proxy_ip=target_proxy, latency_ms=180.0, is_success=True)
    assert u1.success_count == 1
    assert u1.consecutive_failures == 0
    assert u1.status == "HEALTHY"

    # 2nd success
    u2 = upsert_proxy_health(db, proxy_ip=target_proxy, latency_ms=160.0, is_success=True)
    assert u2.success_count == 2
    assert u2.consecutive_failures == 0

    # 1st failure
    u3 = upsert_proxy_health(db, proxy_ip=target_proxy, latency_ms=1200.0, is_success=False, error_message="Connect timeout")
    assert u3.failure_count == 1
    assert u3.consecutive_failures == 1
    assert u3.status == "HEALTHY"  # below circuit break threshold

    # 2nd failure
    u4 = upsert_proxy_health(db, proxy_ip=target_proxy, latency_ms=2500.0, is_success=False)
    assert u4.failure_count == 2
    assert u4.consecutive_failures == 2
    assert u4.status == "HEALTHY"

    # 3rd failure -> circuit break trigger (DEGRADED)
    u5 = upsert_proxy_health(db, proxy_ip=target_proxy, latency_ms=5000.0, is_success=False, error_message="Circuit break threshold reached")
    assert u5.failure_count == 3
    assert u5.consecutive_failures == 3
    assert u5.status == "DEGRADED"
    print(f"  ✓ Proxy circuit breaker auto-transition to DEGRADED verified after 3 consecutive failures.")

    # Recovery: 1 success resets consecutive failures and restores HEALTHY
    u6 = upsert_proxy_health(db, proxy_ip=target_proxy, latency_ms=140.0, is_success=True)
    assert u6.consecutive_failures == 0
    assert u6.status == "HEALTHY"
    print(f"  ✓ Proxy recovery to HEALTHY verified upon successful request.")

    # 5. Proxy Latency Statistics and Active Proxy Filtering
    print("\n[5/7] Testing proxy latency statistics and pool retrieval...")
    # Add a few more proxies
    log_proxy_health(db, proxy_ip="10.0.0.3:8080", status="HEALTHY", latency_ms=85.0)
    log_proxy_health(db, proxy_ip="10.0.0.4:8080", status="HEALTHY", latency_ms=95.0)
    log_proxy_health(db, proxy_ip="10.0.0.5:8080", status="DEGRADED", latency_ms=450.0, consecutive_failures=4)
    log_proxy_health(db, proxy_ip="10.0.0.6:8080", status="BANNED", latency_ms=5000.0, consecutive_failures=10)

    # Filter active healthy proxies
    healthy_pool = get_active_healthy_proxies(db, max_latency_ms=200.0, max_consecutive_failures=3)
    healthy_ips = [p.proxy_ip for p in healthy_pool]
    assert "10.0.0.3:8080" in healthy_ips
    assert "10.0.0.4:8080" in healthy_ips
    assert "10.0.0.5:8080" not in healthy_ips
    assert "10.0.0.6:8080" not in healthy_ips
    print(f"  ✓ Active healthy proxy filtering returned {len(healthy_pool)} valid proxies.")

    # Latency stats
    p_stats = get_proxy_latency_stats(db, window_hours=24)
    assert p_stats["count"] >= 5
    assert p_stats["min_latency_ms"] == 85.0
    assert p_stats["max_latency_ms"] >= 450.0
    assert p_stats["healthy_count"] >= 3
    assert p_stats["degraded_count"] >= 1
    assert p_stats["banned_count"] >= 1
    print(f"  ✓ Proxy latency statistics: min={p_stats['min_latency_ms']}ms, avg={p_stats['avg_latency_ms']}ms, p95={p_stats['p95_latency_ms']}ms")

    # Proxy summary
    p_summary = get_proxy_summary(db, window_hours=24)
    assert p_summary["distinct_proxies"] >= 4
    assert p_summary["healthy_count"] >= 3
    print(f"  ✓ Proxy pool summary verified: {p_summary['distinct_proxies']} distinct proxies.")

    # 6. Retention and Storage Cleanup
    print("\n[6/7] Testing automated retention pruning for stale telemetry...")
    stale_date = datetime.now(timezone.utc) - timedelta(days=45)

    # Insert old telemetry and old proxy record
    old_t = ScraperTelemetry(
        crawler_name="synthetic",
        route="DEL-BOM",
        booking_window="T+1",
        status="SUCCESS",
        response_time_ms=500.0,
        records_extracted=10,
        created_at=stale_date,
    )
    old_p = ProxyHealthRecord(
        proxy_ip="10.99.99.99:8080",
        status="DEAD",
        latency_ms=9999.0,
        created_at=stale_date,
        last_checked_at=stale_date,
    )
    db.add_all([old_t, old_p])
    db.commit()

    count_before_t = count_scraper_telemetry(db)
    prune_res = cleanup_old_telemetry(db, retention_days=30)
    assert prune_res["scraper_telemetry_pruned"] >= 1
    assert prune_res["proxy_health_pruned"] >= 1

    count_after_t = count_scraper_telemetry(db)
    assert count_after_t == count_before_t - prune_res["scraper_telemetry_pruned"]

    # Verify stale records are gone, but recent records remain
    old_query = get_scraper_telemetry(db, crawler_name="synthetic")
    assert len(old_query) == 0, "Old telemetry should be pruned"
    recent_query = get_scraper_telemetry(db, crawler_name="makemytrip")
    assert len(recent_query) > 0, "Recent telemetry should be preserved"
    print(f"  ✓ Pruned {prune_res['scraper_telemetry_pruned']} stale telemetry and {prune_res['proxy_health_pruned']} proxy records. Recent data preserved.")

    # 7. Object-Oriented TelemetryRepo Wrapper
    print("\n[7/7] Testing TelemetryRepo OOP wrapper...")
    repo = TelemetryRepo(db)
    t_obj = repo.log_telemetry(
        crawler_name="amadeus",
        route="BOM-DEL",
        booking_window="T+1",
        status="SUCCESS",
        response_time_ms=650.0,
        records_extracted=30,
    )
    assert t_obj.crawler_name == "amadeus"
    repo_t_list = repo.get_telemetry(crawler_name="amadeus")
    assert len(repo_t_list) == 1
    repo_uptime = repo.get_crawler_uptime(crawler_name="amadeus")
    assert repo_uptime["uptime_pct"] == 100.0

    repo_proxy = repo.upsert_proxy(proxy_ip="10.0.0.99:8080", latency_ms=110.0, is_success=True)
    assert repo_proxy.status == "HEALTHY"
    repo_summary = repo.get_crawler_summary()
    assert repo_summary["total_runs"] > 0
    print("  ✓ TelemetryRepo class methods verified successfully.")

    db.close()
    print("\n" + "=" * 75)
    print("ALL CYCLE 3 TELEMETRY DATABASE TESTS PASSED SUCCESSFULLY!")
    print("=" * 75)
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
