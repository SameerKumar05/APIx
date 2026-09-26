"""Distributed Task Scheduler for APIx Airfare Price Index Ingestion.

Coordinates high-frequency scraping across all 10 domestic trunk routes
and 4 advance booking horizons (40 discrete slots) using APScheduler
(AsyncIOScheduler), applying randomized anti-bot jitter, dynamic proxy rotation,
and robust error isolation.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ingestion.base import BaseScraper, RawFareRecord, ScrapeResult
from ingestion.config import (
    BOOKING_WINDOW_MAP,
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    BookingWindow,
    IngestionConfig,
    Route,
)
from ingestion.orchestrator import IngestionOrchestrator, SlotResultSummary
from ingestion.proxy_pool import Proxy, ProxyPoolManager, get_proxy_pool

logger = logging.getLogger("ingestion.scheduler")

# Mapping of common alias strings to canonical booking window codes
WINDOW_ALIAS_MAP: Dict[str, str] = {
    "1-3d": "T+1",
    "1-3days": "T+1",
    "1d": "T+1",
    "t1": "T+1",
    "t+1": "T+1",
    "4-7d": "T+7",
    "4-7days": "T+7",
    "7d": "T+7",
    "t7": "T+7",
    "t+7": "T+7",
    "8-14d": "T+15",
    "8-14days": "T+15",
    "15d": "T+15",
    "t15": "T+15",
    "t+15": "T+15",
    "15-30d": "T+30",
    "15-30days": "T+30",
    "30d": "T+30",
    "t30": "T+30",
    "t+30": "T+30",
}


def normalize_window(window_in: Union[str, BookingWindow]) -> BookingWindow:
    """Resolves arbitrary window string representations or aliases into a canonical BookingWindow."""
    if isinstance(window_in, BookingWindow):
        return window_in

    key = str(window_in).strip().lower()
    canonical_code = WINDOW_ALIAS_MAP.get(key, key.upper())

    if canonical_code in BOOKING_WINDOW_MAP:
        return BOOKING_WINDOW_MAP[canonical_code]

    # Fallback to default T+1 window if unknown
    logger.warning("Unrecognized booking window '%s'; defaulting to T+1", window_in)
    return BOOKING_WINDOW_MAP["T+1"]


def normalize_route(route_in: Union[str, Route, Tuple[str, str]]) -> Route:
    """Resolves route string (e.g. 'DEL-BOM'), tuple, or Route object into canonical Route."""
    if isinstance(route_in, Route):
        return route_in

    if isinstance(route_in, tuple):
        orig, dest = route_in[0].strip().upper(), route_in[1].strip().upper()
    elif isinstance(route_in, str):
        parts = route_in.replace("_", "-").split("-")
        if len(parts) >= 2:
            orig, dest = parts[0].strip().upper(), parts[1].strip().upper()
        else:
            orig, dest = "DEL", "BOM"
    else:
        orig, dest = "DEL", "BOM"

    # Search in default calibrated routes
    for r in DEFAULT_ROUTES:
        if r.origin == orig and r.destination == dest:
            return r

    # Create dynamic Route instance if not in standard list
    return Route(
        origin=orig,
        destination=dest,
        distance_km=1200,
        typical_duration_min=130,
        dgca_weight=0.05,
    )


@dataclass
class JobExecutionRecord:
    """Historical telemetry record for a scheduled or ad-hoc slot execution."""

    execution_id: str
    job_id: str
    route: str
    origin: str
    destination: str
    booking_window: str
    started_at: str
    completed_at: str
    duration_ms: float
    success: bool
    records_count: int
    proxy_url: Optional[str] = None
    proxy_ip: Optional[str] = None
    error: Optional[str] = None
    tier: int = 1
    source_platform: Optional[str] = None


@dataclass
class SchedulerConfig:
    """Runtime configuration for IngestionScheduler."""

    cron_expr: Optional[str] = None  # e.g. "0 2,8,14,20 * * *"
    interval_minutes: Optional[int] = 360  # Default: Sweep every 6 hours
    jitter_min_seconds: float = 5.0
    jitter_max_seconds: float = 15.0
    stagger_seconds: float = 1.0  # Delay between individual slot triggers in a sweep
    max_history_records: int = 500
    auto_start: bool = False


class IngestionScheduler:
    """Master AsyncIOScheduler managing 40 discrete ingestion slots with anti-bot jitter and proxy rotation."""

    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        orchestrator: Optional[IngestionOrchestrator] = None,
        proxy_pool: Optional[ProxyPoolManager] = None,
        routes: Optional[List[Route]] = None,
        windows: Optional[List[BookingWindow]] = None,
    ) -> None:
        self.config = config or SchedulerConfig()
        self.orchestrator = orchestrator or IngestionOrchestrator()
        self.proxy_pool = proxy_pool or get_proxy_pool()
        self.target_routes = routes or list(DEFAULT_ROUTES)
        self.target_windows = windows or list(BOOKING_WINDOWS)

        # APScheduler AsyncIOScheduler instance
        self.scheduler = AsyncIOScheduler()
        self.is_running = False

        # Execution audit history
        self._history: List[JobExecutionRecord] = []
        self._slot_execution_counts: Dict[str, int] = {}
        self._lock = asyncio.Lock()

        # Wire internal job listener
        self.scheduler.add_listener(
            self._on_job_executed,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR,
        )

        # Pre-register all 40 slots
        self.register_all_slots()

    def _on_job_executed(self, event: JobExecutionEvent) -> None:
        """Internal callback for monitoring APScheduler job lifecycle events."""
        if event.exception:
            logger.error("Job %s encountered an unhandled exception: %s", event.job_id, event.exception)
        else:
            logger.debug("Job %s executed successfully (return value: %s)", event.job_id, type(event.retval))

    def _format_slot_job_id(self, origin: str, destination: str, window_code: str) -> str:
        """Generates deterministic unique job ID for a slot."""
        return f"slot_{origin}_{destination}_{window_code}"

    def register_all_slots(
        self,
        routes: Optional[List[Route]] = None,
        windows: Optional[List[BookingWindow]] = None,
    ) -> int:
        """Registers all 40 route-window combinations as individual jobs in the scheduler."""
        active_routes = routes or self.target_routes
        active_windows = windows or self.target_windows
        registered_count = 0

        for r in active_routes:
            for w in active_windows:
                job_id = self._format_slot_job_id(r.origin, r.destination, w.code)
                job_name = f"Scrape {r.origin}-{r.destination} ({w.code})"

                # Build trigger based on configuration
                trigger: Union[CronTrigger, IntervalTrigger]
                if self.config.cron_expr:
                    trigger = CronTrigger.from_crontab(self.config.cron_expr)
                else:
                    minutes = self.config.interval_minutes or 360
                    trigger = IntervalTrigger(minutes=minutes)

                # Replace existing job if already registered
                if self.scheduler.get_job(job_id):
                    self.scheduler.remove_job(job_id)

                self.scheduler.add_job(
                    func=self.execute_slot_job,
                    trigger=trigger,
                    args=[r.origin, r.destination, w.code],
                    kwargs={"apply_jitter": True},
                    id=job_id,
                    name=job_name,
                    replace_existing=True,
                    misfire_grace_time=300,
                )
                registered_count += 1

        logger.info(
            "Registered %d discrete slot jobs in APScheduler (Routes: %d, Windows: %d)",
            registered_count,
            len(active_routes),
            len(active_windows),
        )
        return registered_count

    async def execute_slot_job(
        self,
        origin: str,
        destination: str,
        window: str,
        apply_jitter: bool = True,
        base_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Asynchronously executes an individual slot scrape with jitter and proxy rotation."""
        import uuid

        exec_id = f"exec-{uuid.uuid4().hex[:8]}"
        route = normalize_route((origin, destination))
        b_window = normalize_window(window)
        slot_key = f"{route.origin}-{route.destination}:{b_window.code}"
        job_id = self._format_slot_job_id(route.origin, route.destination, b_window.code)

        # 1. Anti-Bot Randomized Jitter
        jitter_applied = 0.0
        if apply_jitter:
            min_j = self.config.jitter_min_seconds
            max_j = self.config.jitter_max_seconds
            if max_j > 0.0:
                jitter_applied = random.uniform(min_j, max_j)
                logger.info(
                    "[%s] Applying anti-bot jitter: sleeping %.2fs for %s",
                    exec_id,
                    jitter_applied,
                    slot_key,
                )
                await asyncio.sleep(jitter_applied)

        # 2. Assign Health-Scored Proxy from Pool
        assigned_proxy: Optional[Proxy] = self.proxy_pool.get_proxy(strategy="best_score")
        proxy_url = assigned_proxy.url if assigned_proxy else None
        proxy_ip = assigned_proxy.ip if assigned_proxy else None

        start_dt = datetime.now(timezone.utc)
        start_time = time.perf_counter()

        logger.info(
            "[%s] Initiating slot scrape: %s | Proxy: %s",
            exec_id,
            slot_key,
            assigned_proxy.identifier if assigned_proxy else "direct",
        )

        scrape_res: Optional[ScrapeResult] = None
        summary: Optional[SlotResultSummary] = None
        error_msg: Optional[str] = None
        is_success = False
        records_count = 0
        tier = 1
        source_plat = "unknown"

        try:
            # Execute synchronous orchestrator slot within asyncio worker thread
            slot_idx = self._slot_execution_counts.get(job_id, 0)
            scrape_res, summary = await asyncio.to_thread(
                self.orchestrator.run_slot,
                route=route,
                window=b_window,
                slot_index=slot_idx,
                base_date=base_date,
                proxy=proxy_url,
            )

            records_count = len(scrape_res.records)
            is_success = scrape_res.success and records_count > 0
            tier = summary.tier
            source_plat = summary.source_platform

            # 3. Report Proxy Telemetry
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            if assigned_proxy:
                if is_success:
                    self.proxy_pool.report_success(assigned_proxy, latency_ms=duration_ms)
                else:
                    err_summary = "; ".join(summary.errors) if summary.errors else "Zero records returned"
                    self.proxy_pool.report_failure(assigned_proxy, error=err_summary)

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_msg = str(exc)
            logger.error("[%s] Error executing slot %s: %s", exec_id, slot_key, exc, exc_info=True)
            if assigned_proxy:
                self.proxy_pool.report_failure(assigned_proxy, error=error_msg)

        completed_dt = datetime.now(timezone.utc)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Record in execution history
        record = JobExecutionRecord(
            execution_id=exec_id,
            job_id=job_id,
            route=f"{route.origin}-{route.destination}",
            origin=route.origin,
            destination=route.destination,
            booking_window=b_window.code,
            started_at=start_dt.isoformat(),
            completed_at=completed_dt.isoformat(),
            duration_ms=round(duration_ms, 2),
            success=is_success,
            records_count=records_count,
            proxy_url=proxy_url,
            proxy_ip=proxy_ip,
            error=error_msg or ("; ".join(summary.errors) if summary and summary.errors else None),
            tier=tier,
            source_platform=source_plat,
        )

        async with self._lock:
            self._history.append(record)
            if len(self._history) > self.config.max_history_records:
                self._history.pop(0)
            self._slot_execution_counts[job_id] = self._slot_execution_counts.get(job_id, 0) + 1

        logger.info(
            "[%s] Completed slot %s | Success: %s | Fares: %d | Latency: %.1fms | Tier: %d (%s)",
            exec_id,
            slot_key,
            is_success,
            records_count,
            duration_ms,
            tier,
            source_plat,
        )

        return asdict(record)

    async def trigger_slot(
        self,
        origin: str,
        destination: str,
        window: str,
        apply_jitter: bool = False,
    ) -> Dict[str, Any]:
        """Dispatches an immediate on-demand execution for a specific route and booking horizon."""
        return await self.execute_slot_job(
            origin=origin,
            destination=destination,
            window=window,
            apply_jitter=apply_jitter,
        )

    async def trigger_all(
        self,
        stagger_seconds: Optional[float] = None,
        apply_jitter: bool = False,
    ) -> List[Dict[str, Any]]:
        """Dispatches an immediate full-sweep scrape across all 40 registered slots."""
        stagger = stagger_seconds if stagger_seconds is not None else self.config.stagger_seconds
        results: List[Dict[str, Any]] = []

        logger.info("Triggering immediate master sweep across all registered slots (stagger=%.2fs)", stagger)

        for route in self.target_routes:
            for window in self.target_windows:
                res = await self.execute_slot_job(
                    origin=route.origin,
                    destination=route.destination,
                    window=window.code,
                    apply_jitter=apply_jitter,
                )
                results.append(res)
                if stagger > 0.0:
                    await asyncio.sleep(stagger)

        logger.info("Completed master sweep of %d slots", len(results))
        return results

    def pause_job(self, job_id: str) -> bool:
        """Pauses a registered job."""
        job = self.scheduler.get_job(job_id)
        if job:
            job.pause()
            logger.info("Paused job: %s", job_id)
            return True
        return False

    def resume_job(self, job_id: str) -> bool:
        """Resumes a paused job."""
        job = self.scheduler.get_job(job_id)
        if job:
            job.resume()
            logger.info("Resumed job: %s", job_id)
            return True
        return False

    def remove_job(self, job_id: str) -> bool:
        """Removes a job from the scheduler."""
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info("Removed job: %s", job_id)
            return True
        return False

    def get_job_status(self) -> Dict[str, Any]:
        """Provides monitoring status for all registered jobs, triggers, and execution counts."""
        jobs_info: List[Dict[str, Any]] = []

        for job in self.scheduler.get_jobs():
            next_run_dt = getattr(job, "next_run_time", None)
            next_run = next_run_dt.isoformat() if next_run_dt else None
            trigger_repr = str(job.trigger)

            # Determine route and window from job ID
            parts = job.id.split("_")
            orig = parts[1] if len(parts) >= 4 else "UNKNOWN"
            dest = parts[2] if len(parts) >= 4 else "UNKNOWN"
            win = parts[3] if len(parts) >= 4 else "UNKNOWN"

            jobs_info.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": next_run,
                    "trigger": trigger_repr,
                    "route": f"{orig}-{dest}",
                    "booking_window": win,
                    "executions_count": self._slot_execution_counts.get(job.id, 0),
                }
            )

        total_execs = len(self._history)
        successes = sum(1 for h in self._history if h.success)
        failures = total_execs - successes
        success_rate = (successes / total_execs * 100.0) if total_execs > 0 else 100.0

        return {
            "is_running": self.is_running,
            "scheduler_state": self.scheduler.state,
            "total_registered_jobs": len(jobs_info),
            "jobs": jobs_info,
            "history_summary": {
                "total_executions": total_execs,
                "total_successes": successes,
                "total_failures": failures,
                "success_rate_percent": round(success_rate, 2),
            },
            "recent_executions": [asdict(h) for h in reversed(self._history[-20:])],
        }

    def start(self) -> None:
        """Starts the APScheduler background daemon."""
        if not self.is_running:
            self.scheduler.start()
            self.is_running = True
            logger.info("IngestionScheduler started with %d registered jobs", len(self.scheduler.get_jobs()))

    def shutdown(self, wait: bool = False) -> None:
        """Stops the scheduler and shuts down its threadpool/event handlers."""
        if self.is_running:
            self.scheduler.shutdown(wait=wait)
            self.is_running = False
            logger.info("IngestionScheduler stopped successfully")


# Global singleton instance container
_GLOBAL_SCHEDULER: Optional[IngestionScheduler] = None


def get_scheduler(
    config: Optional[SchedulerConfig] = None,
    orchestrator: Optional[IngestionOrchestrator] = None,
    proxy_pool: Optional[ProxyPoolManager] = None,
) -> IngestionScheduler:
    """Returns the process-wide singleton IngestionScheduler instance."""
    global _GLOBAL_SCHEDULER
    if _GLOBAL_SCHEDULER is None:
        _GLOBAL_SCHEDULER = IngestionScheduler(
            config=config,
            orchestrator=orchestrator,
            proxy_pool=proxy_pool,
        )
    return _GLOBAL_SCHEDULER


def parse_args() -> argparse.Namespace:
    """Parses CLI arguments for standalone scheduler execution."""
    parser = argparse.ArgumentParser(description="APIx Distributed Ingestion Scheduler")
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=360,
        help="Recurring sweep interval in minutes (default: 360 = 6 hours)",
    )
    parser.add_argument(
        "--cron",
        type=str,
        default=None,
        help="Cron expression for scheduling sweeps (e.g. '0 2,8,14,20 * * *')",
    )
    parser.add_argument(
        "--jitter-min",
        type=float,
        default=5.0,
        help="Minimum anti-bot jitter in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--jitter-max",
        type=float,
        default=15.0,
        help="Maximum anti-bot jitter in seconds (default: 15.0)",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Trigger a single sweep of all slots immediately and exit",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level",
    )
    return parser.parse_args()


async def async_main() -> int:
    """Async entrypoint for standalone daemon execution."""
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    cfg = SchedulerConfig(
        cron_expr=args.cron,
        interval_minutes=args.interval_minutes,
        jitter_min_seconds=args.jitter_min,
        jitter_max_seconds=args.jitter_max,
    )

    scheduler = IngestionScheduler(config=cfg)

    if args.run_once:
        logger.info("Executing on-demand single sweep of all slots...")
        await scheduler.trigger_all(stagger_seconds=0.5, apply_jitter=False)
        status = scheduler.get_job_status()
        print(f"Sweep complete: {status['history_summary']}")
        return 0

    scheduler.start()
    logger.info("Scheduler running. Press Ctrl+C to terminate.")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received.")
    finally:
        scheduler.shutdown()

    return 0


def main() -> int:
    """CLI wrapper for asyncio execution."""
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
