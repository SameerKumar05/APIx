#!/usr/bin/env python3
"""Verification Script for Ingestion Scheduler and Proxy Pool Subsystems.

Validates:
1. ProxyPoolManager:
   - Proxy creation, parsing (string, dict, object), and safe serialization.
   - Rotation strategies: best_score, round_robin, lowest_latency, random.
   - Latency scoring using Exponential Weighted Moving Average (EWMA).
   - Auto-blacklisting upon exceeding consecutive failure threshold (default: 3).
   - Cooldown expiration and quarantine recovery.
   - Pool status telemetry reporting and metrics aggregation.
   - Emergency unblacklisting fallback under pool starvation.

2. IngestionScheduler:
   - Route and booking window normalization and alias mapping (e.g. '1-3d' -> 'T+1').
   - Standalone AsyncIOScheduler instantiation and registration of all 40 discrete slots
     (10 DGCA trunk routes x 4 advance booking horizons).
   - Job management: inspection, pause, resume, removal, and trigger reporting.
   - Jittered slot execution, proxy attribution, and telemetry recording.
   - Ad-hoc slot and sweep dispatches (trigger_slot, trigger_all).
   - Scheduler start and graceful shutdown lifecycles.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

# Ensure repository root is on sys.path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from ingestion.base import RawFareRecord, ScrapeResult
from ingestion.config import (
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    BookingWindow,
    IngestionConfig,
    Route,
)
from ingestion.crawlers.synthetic import SyntheticFlightGenerator
from ingestion.orchestrator import IngestionOrchestrator
from ingestion.proxy_pool import (
    DEFAULT_DEMO_PROXIES,
    Proxy,
    ProxyPoolConfig,
    ProxyPoolManager,
)
from ingestion.scheduler import (
    IngestionScheduler,
    SchedulerConfig,
    normalize_route,
    normalize_window,
)

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test.scheduler_and_proxies")


def test_proxy_pool_management() -> None:
    """Tests ProxyPoolManager parsing, rotation, latency scoring, and blacklisting."""
    logger.info("=" * 70)
    logger.info("STAGE 1: PROXY POOL MANAGER & ROTATION VERIFICATION")
    logger.info("=" * 70)

    cfg = ProxyPoolConfig(
        max_consecutive_failures=3,
        cooldown_seconds=2.0,  # Short cooldown for test validation
        degraded_latency_threshold_ms=500.0,
        ewma_alpha=0.3,
        latency_penalty_on_failure_ms=200.0,
    )

    test_proxies = [
        "http://proxy-del.internal:8080",
        "http://proxy-bom.internal:8080",
        "http://user:secret123@proxy-blr.internal:3128",
        {"ip": "10.0.0.1", "port": 8080, "protocol": "http", "latency_ms": 150.0},
        Proxy(ip="10.0.0.2", port=8080, protocol="http", latency_ms=80.0, score=80.0),
    ]

    pool = ProxyPoolManager(proxies=test_proxies, config=cfg, auto_seed=False)
    assert len(pool) == 5, f"Expected 5 proxies in pool, got {len(pool)}"
    logger.info(
        "✓ Proxy pool successfully initialized with %d diverse proxy definitions",
        len(pool),
    )

    # 1. Serialization tests
    blr_proxy = next(p for p in pool._proxies.values() if "proxy-blr" in p.ip)
    safe_dict = blr_proxy.to_dict_safe()
    assert (
        safe_dict.get("password") == "***"
    ), "Password was not redacted in to_dict_safe()"
    assert "secret123" not in safe_dict["url"], "Password leaked in safe URL"
    pw_proxy = blr_proxy.to_playwright_proxy()
    assert pw_proxy["server"] == "http://proxy-blr.internal:3128"
    assert pw_proxy["username"] == "user"
    assert pw_proxy["password"] == "secret123"
    logger.info("✓ Proxy serialization and credential redaction validated")

    # 2. Rotation strategies
    # Lowest latency / best score
    best_p = pool.get_proxy(strategy="best_score")
    assert best_p is not None
    assert (
        best_p.ip == "10.0.0.2"
    ), f"Expected lowest score proxy 10.0.0.2, got {best_p.ip}"

    # Round Robin
    rr_ips = [pool.get_proxy(strategy="round_robin").ip for _ in range(5)]
    assert (
        len(set(rr_ips)) > 1
    ), "Round robin failed to distribute across multiple proxies"
    logger.info("✓ Proxy selection strategies (best_score, round_robin) validated")

    # 3. Latency scoring & EWMA update
    target = pool.get_proxy(strategy="lowest_latency")
    orig_score = target.score
    pool.report_success(target, latency_ms=40.0)
    assert target.success_count == 1
    assert target.consecutive_failures == 0
    # EWMA check: score_new = 0.3 * 40 + 0.7 * orig_score
    expected_score = (0.3 * 40.0) + (0.7 * orig_score)
    assert (
        abs(target.score - expected_score) < 0.01
    ), f"EWMA mismatch: {target.score} vs {expected_score}"
    logger.info(
        "✓ EWMA latency scoring formula verified (Score: %.2f -> %.2f)",
        orig_score,
        target.score,
    )

    # 4. Status degradation
    pool.report_success(target, latency_ms=650.0)
    assert (
        target.status == "degraded"
    ), f"Expected degraded status for 650ms latency, got {target.status}"
    logger.info("✓ Status degradation verified when latency exceeds threshold")

    # 5. Consecutive failure & auto-blacklisting
    victim = next(p for p in pool._proxies.values() if p.ip == "proxy-del.internal")
    assert victim.status == "active"

    pool.report_failure(victim, error="HTTP 429 Too Many Requests", status_code=429)
    assert victim.consecutive_failures == 1
    assert victim.status == "degraded"

    pool.report_failure(victim, error="HTTP 429 Too Many Requests", status_code=429)
    assert victim.consecutive_failures == 2

    pool.report_failure(
        victim, error="HTTP 403 Forbidden Cloudflare Bot", status_code=403
    )
    assert victim.consecutive_failures == 3
    assert (
        victim.status == "blacklisted"
    ), f"Expected blacklisted status, got {victim.status}"
    assert victim.blacklisted_until is not None
    logger.info("✓ Auto-blacklisting confirmed after 3 consecutive failures")

    # Verify blacklisted proxy is excluded from rotation
    for _ in range(10):
        p = pool.get_proxy(strategy="round_robin")
        assert (
            p.ip != "proxy-del.internal"
        ), "Blacklisted proxy was returned by get_proxy()"
    logger.info("✓ Blacklisted proxy successfully isolated from routing selection")

    # 6. Cooldown expiration and recovery
    time.sleep(2.1)  # Exceed cooldown_seconds = 2.0s
    recovered = pool.check_cooldowns()
    assert any(
        p.ip == "proxy-del.internal" for p in recovered
    ), "Cooldown recovery failed"
    assert victim.status == "testing"
    assert victim.consecutive_failures == 0
    logger.info("✓ Cooldown expiration and automatic quarantine recovery verified")

    # 7. Emergency recovery under total blackout
    for p in pool._proxies.values():
        pool.blacklist_proxy(
            p, reason="Simulated cluster blackout", cooldown_seconds=600.0
        )
    assert sum(1 for p in pool._proxies.values() if p.status == "blacklisted") == len(
        pool
    )

    emergency_p = pool.get_proxy(strategy="best_score")
    assert (
        emergency_p is not None
    ), "Emergency recovery failed to provide a fallback proxy"
    assert emergency_p.status == "testing"
    logger.info("✓ Emergency unblacklisting fallback prevented total pool starvation")

    # 8. Pool status summary
    status = pool.get_pool_status()
    assert status["total"] == 5
    assert "avg_latency_ms" in status
    assert "proxies" in status
    logger.info(
        "✓ Pool status metrics validated (Total: %d, Available: %d, Avg Latency: %.1fms)",
        status["total"],
        status["available_count"],
        status["avg_latency_ms"],
    )


async def test_scheduler_orchestration() -> None:
    """Tests IngestionScheduler job registration, normalization, jitter, and execution."""
    logger.info("=" * 70)
    logger.info("STAGE 2: INGESTION SCHEDULER & 70-SLOT DISPATCH VERIFICATION")
    logger.info("=" * 70)

    # 1. Normalization and alias tests
    w1 = normalize_window("1-3d")
    assert w1.code == "T+1", f"Expected T+1 for '1-3d', got {w1.code}"
    w7 = normalize_window("4-7days")
    assert w7.code == "T+7", f"Expected T+7 for '4-7days', got {w7.code}"
    w15 = normalize_window("t15")
    assert w15.code == "T+15", f"Expected T+15 for 't15', got {w15.code}"
    w30 = normalize_window("15-30d")
    assert w30.code == "T+30", f"Expected T+30 for '15-30d', got {w30.code}"

    r_obj = normalize_route("DEL-BOM")
    assert r_obj.origin == "DEL" and r_obj.destination == "BOM"
    r_tuple = normalize_route(("BLR", "DEL"))
    assert r_tuple.origin == "BLR" and r_tuple.destination == "DEL"
    logger.info(
        "✓ Window alias and route normalizations verified across all horizon representations"
    )

    # 2. Instantiate synthetic orchestrator for fast deterministic verification
    synth_config = IngestionConfig(ingestion_mode="synthetic")
    synth_scraper = SyntheticFlightGenerator(config=synth_config)
    orchestrator = IngestionOrchestrator(
        config=synth_config,
        scraper=synth_scraper,
        jitter_range=(0.0, 0.0),  # Bypass orchestrator internal jitter for testing
    )

    sched_cfg = SchedulerConfig(
        interval_minutes=360,
        jitter_min_seconds=0.01,
        jitter_max_seconds=0.05,
        stagger_seconds=0.01,
    )

    scheduler = IngestionScheduler(
        config=sched_cfg,
        orchestrator=orchestrator,
    )

    # 3. Verify exactly 70 registered slots (14 routes * 5 windows)
    status = scheduler.get_job_status()
    total_registered = status["total_registered_jobs"]
    expected_slots = len(DEFAULT_ROUTES) * len(BOOKING_WINDOWS)  # 14 * 5 = 70
    assert (
        total_registered == expected_slots
    ), f"Expected {expected_slots} registered slot jobs, got {total_registered}"
    assert (
        total_registered == 70
    ), f"Expected exactly 70 registered slot jobs, got {total_registered}"
    logger.info(
        "✓ APScheduler successfully registered all %d discrete slot jobs",
        total_registered,
    )

    # Verify new PSD corridors are among registered slots
    maa_del_job = next(
        (j for j in status["jobs"] if j["id"] == "slot_MAA_DEL_T+1"), None
    )
    assert (
        maa_del_job is not None
    ), "MAA-DEL slot job missing from scheduler registration"
    blr_hyd_job = next(
        (j for j in status["jobs"] if j["id"] == "slot_BLR_HYD_T+1"), None
    )
    assert (
        blr_hyd_job is not None
    ), "BLR-HYD slot job missing from scheduler registration"
    # Verify job naming and IDs
    sample_job = next(j for j in status["jobs"] if j["id"] == "slot_DEL_BOM_T+1")
    assert sample_job["route"] == "DEL-BOM"
    assert sample_job["booking_window"] == "T+1"
    assert "interval" in sample_job["trigger"].lower()
    logger.info(
        "✓ Slot job metadata and trigger structure confirmed (ID: %s)", sample_job["id"]
    )

    # 4. Job lifecycle management: pause, resume, remove
    job_to_pause = "slot_DEL_BOM_T+1"
    assert scheduler.pause_job(job_to_pause) is True
    assert scheduler.resume_job(job_to_pause) is True
    assert scheduler.remove_job("non_existent_job") is False
    logger.info("✓ Job lifecycle operations (pause, resume) verified")

    # 5. Ad-Hoc Single Slot Execution with Jitter and Proxy Attribution
    logger.info("Executing ad-hoc slot trigger (DEL-BOM, T+1) with anti-bot jitter...")
    exec_record = await scheduler.trigger_slot(
        origin="DEL",
        destination="BOM",
        window="1-3d",  # Testing alias resolution
        apply_jitter=True,
    )

    assert (
        exec_record["success"] is True
    ), f"Slot execution failed: {exec_record.get('error')}"
    assert (
        exec_record["records_count"] > 0
    ), "No fares were extracted from synthetic orchestrator"
    assert exec_record["booking_window"] == "T+1"
    assert exec_record["route"] == "DEL-BOM"
    assert exec_record["proxy_url"] is not None
    assert exec_record["duration_ms"] > 0.0
    logger.info(
        "✓ Ad-hoc slot executed successfully! Records: %d, Latency: %.1fms, Proxy: %s",
        exec_record["records_count"],
        exec_record["duration_ms"],
        exec_record["proxy_ip"],
    )

    # 6. Ad-Hoc Sweep Dispatch across representative subset
    logger.info("Triggering mini-sweep across 4 horizons for route BOM-BLR...")
    sweep_scheduler = IngestionScheduler(
        config=sched_cfg,
        orchestrator=orchestrator,
        routes=[normalize_route("BOM-BLR")],
        windows=BOOKING_WINDOWS,
    )
    sweep_results = await sweep_scheduler.trigger_all(
        stagger_seconds=0.01, apply_jitter=False
    )
    assert (
        len(sweep_results) == 5
    ), f"Expected 5 sweep results, got {len(sweep_results)}"
    assert all(r["success"] is True for r in sweep_results)
    logger.info("✓ Multi-slot sweep successfully executed with 100% success rate")

    # 7. Execution history and audit logging
    sweep_status = sweep_scheduler.get_job_status()
    history = sweep_status["history_summary"]
    assert history["total_executions"] == 5
    assert history["total_successes"] == 5
    assert history["total_failures"] == 0
    assert history["success_rate_percent"] == 100.0
    logger.info("✓ Execution history and audit metrics verified: %s", history)

    # 8. Scheduler daemon start and shutdown
    sweep_scheduler.start()
    assert sweep_scheduler.is_running is True
    assert sweep_scheduler.scheduler.state == 1  # STATE_RUNNING
    logger.info("✓ Scheduler daemon successfully started (State: RUNNING)")

    sweep_scheduler.shutdown(wait=False)
    assert sweep_scheduler.is_running is False
    logger.info("✓ Scheduler daemon gracefully shutdown (State: STOPPED)")


async def main_async() -> int:
    """Master asynchronous test orchestrator."""
    start = time.perf_counter()
    logger.info("Starting Premier Verification of Ingestion Scheduler and Proxy Pool")

    try:
        # Step 1: Proxy pool tests
        test_proxy_pool_management()

        # Step 2: Scheduler tests
        await test_scheduler_orchestration()

        elapsed = time.perf_counter() - start
        logger.info("=" * 70)
        logger.info("ALL TESTS PASSED PREMIER VERIFICATION (%.2f seconds)", elapsed)
        logger.info("=" * 70)
        return 0

    except Exception as exc:
        logger.error("Verification failed with exception: %s", exc, exc_info=True)
        return 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
