"""Distributed Task Scheduler for APIx Airfare Price Index Ingestion.

Coordinates high-frequency scraping across all 10 domestic trunk routes
and 4 advance booking horizons (40 discrete slots) using APScheduler
(AsyncIOScheduler), applying randomized anti-bot jitter, dynamic proxy rotation,
and robust error isolation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, assert_never

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ingestion.base import ScrapeResult
from ingestion.captcha import BLOCKED_BY_CAPTCHA, consume_challenge
from ingestion.config import (
    BOOKING_WINDOW_MAP,
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    BookingWindow,
    Route,
)
from ingestion.orchestrator import IngestionOrchestrator, SlotResultSummary
from ingestion.proxy_pool import Proxy, ProxyPoolManager, get_proxy_pool
from ingestion.schedule_gate import (
    DispatchMode,
    SweepGate,
    normalize_scraper_source,
    parse_dispatch,
)
from ingestion.scrape_hooks import arm_orchestrator

logger = logging.getLogger("ingestion.scheduler")

# Mapping of common alias strings to canonical booking window codes
WINDOW_ALIAS_MAP: dict[str, str] = {
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


def normalize_window(window_in: str | BookingWindow) -> BookingWindow:
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


def normalize_route(route_in: str | Route | tuple[str, str]) -> Route:
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
    proxy_url: str | None = None
    proxy_ip: str | None = None
    error: str | None = None
    tier: int = 1
    source_platform: str | None = None


@dataclass
class SchedulerConfig:
    """Runtime configuration for IngestionScheduler."""

    cron_expr: str | None = None  # e.g. "0 2,8,14,20 * * *"
    interval_minutes: int | None = 360  # Default: Sweep every 6 hours
    jitter_min_seconds: float = 5.0
    jitter_max_seconds: float = 15.0
    stagger_seconds: float = 1.0  # Delay between individual slot triggers in a sweep
    max_history_records: int = 500
    auto_start: bool = False
    dispatch: DispatchMode = DispatchMode.DIRECT
    ingest: bool = False
    state_dir: str = "artifacts/scheduler"


class IngestionScheduler:
    """Master AsyncIOScheduler managing 40 discrete ingestion slots with anti-bot jitter and proxy rotation."""

    def __init__(
        self,
        config: SchedulerConfig | None = None,
        orchestrator: IngestionOrchestrator | None = None,
        proxy_pool: ProxyPoolManager | None = None,
        routes: list[Route] | None = None,
        windows: list[BookingWindow] | None = None,
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
        self._history: list[JobExecutionRecord] = []
        self._slot_execution_counts: dict[str, int] = {}
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
            logger.error(
                "Job %s encountered an unhandled exception: %s",
                event.job_id,
                event.exception,
            )
        else:
            logger.debug(
                "Job %s executed successfully (return value: %s)",
                event.job_id,
                type(event.retval),
            )

    def _format_slot_job_id(
        self, origin: str, destination: str, window_code: str
    ) -> str:
        """Generates deterministic unique job ID for a slot."""
        return f"slot_{origin}_{destination}_{window_code}"

    def register_all_slots(
        self,
        routes: list[Route] | None = None,
        windows: list[BookingWindow] | None = None,
    ) -> int:
        """Registers all 40 route-window combinations as individual jobs in the scheduler."""
        active_routes = routes or self.target_routes
        active_windows = windows or self.target_windows
        registered_count = 0

        for r in active_routes:
            for w in active_windows:
                job_id = self._format_slot_job_id(r.origin, r.destination, w.code)
                job_name = f"Scrape {r.origin}-{r.destination} ({w.code})"

                trigger: CronTrigger | IntervalTrigger
                if self.config.cron_expr:
                    trigger = CronTrigger.from_crontab(
                        self.config.cron_expr, timezone=UTC
                    )
                else:
                    minutes = self.config.interval_minutes or 360
                    trigger = IntervalTrigger(minutes=minutes)

                if self.scheduler.get_job(job_id):
                    self.scheduler.remove_job(job_id)

                match self.config.dispatch:
                    case DispatchMode.ENQUEUE:
                        job_func = self._enqueue_slot_job
                    case DispatchMode.DIRECT:
                        job_func = self.execute_slot_job
                    case unreachable:
                        assert_never(unreachable)

                self.scheduler.add_job(
                    func=job_func,
                    trigger=trigger,
                    args=[r.origin, r.destination, w.code],
                    kwargs={"apply_jitter": True},
                    id=job_id,
                    name=job_name,
                    replace_existing=True,
                    misfire_grace_time=300,
                    coalesce=True,
                    max_instances=1,
                )
                registered_count += 1

        logger.info(
            "Registered %d discrete slot jobs in APScheduler (Routes: %d, Windows: %d)",
            registered_count,
            len(active_routes),
            len(active_windows),
        )
        return registered_count

    async def _enqueue_slot_job(
        self,
        origin: str,
        destination: str,
        window: str,
        apply_jitter: bool = True,
        base_date: date | None = None,
    ) -> dict[str, Any]:
        """Hand one slot to the worker queue. Does not scrape in this process."""
        del apply_jitter, base_date
        return await asyncio.to_thread(self._enqueue_slot, origin, destination, window)

    def _enqueue_slot(
        self, origin: str, destination: str, window: str
    ) -> dict[str, Any]:
        """Enqueue once per UTC day. A second fire of the same slot is a no-op."""
        from sqlalchemy.exc import SQLAlchemyError

        from backend.app.db.crawler_job_repo import enqueue_job
        from backend.app.db.session import SessionLocal

        route = normalize_route((origin, destination))
        b_window = normalize_window(window)
        job_id = self._format_slot_job_id(
            route.origin, route.destination, b_window.code
        )
        day = datetime.now(UTC).date()
        gate = SweepGate(Path(self.config.state_dir))
        if not gate.claim_slot(day, job_id):
            logger.info("slot %s already scheduled for %s", job_id, day.isoformat())
            return {
                "job_id": job_id,
                "status": "skipped",
                "reason": "already_scheduled",
                "day": day.isoformat(),
            }
        source = os.getenv("SCRAPER_SOURCE", "synthetic")
        try:
            with SessionLocal() as db:
                job = enqueue_job(
                    db=db,
                    crawler_name=source,
                    route_code=f"{route.origin}-{route.destination}",
                    booking_window=b_window.code,
                    dedup_window_seconds=86_400,
                )
        except SQLAlchemyError:
            gate.release_slot(day, job_id)
            raise
        logger.info("enqueued %s as %s", job_id, job.job_id)
        return {
            "job_id": job.job_id,
            "status": "enqueued",
            "slot": job_id,
            "day": day.isoformat(),
        }

    async def execute_slot_job(
        self,
        origin: str,
        destination: str,
        window: str,
        apply_jitter: bool = True,
        base_date: date | None = None,
    ) -> dict[str, Any]:
        """Asynchronously executes an individual slot scrape with jitter and proxy rotation."""
        import uuid

        exec_id = f"exec-{uuid.uuid4().hex[:8]}"
        route = normalize_route((origin, destination))
        b_window = normalize_window(window)
        slot_key = f"{route.origin}-{route.destination}:{b_window.code}"
        job_id = self._format_slot_job_id(
            route.origin, route.destination, b_window.code
        )

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
        assigned_proxy: Proxy | None = self.proxy_pool.get_proxy(strategy="best_score")
        proxy_url = assigned_proxy.url if assigned_proxy else None
        proxy_ip = assigned_proxy.ip if assigned_proxy else None

        start_dt = datetime.now(UTC)
        start_time = time.perf_counter()

        logger.info(
            "[%s] Initiating slot scrape: %s | Proxy: %s",
            exec_id,
            slot_key,
            assigned_proxy.identifier if assigned_proxy else "direct",
        )

        scrape_res: ScrapeResult | None = None
        summary: SlotResultSummary | None = None
        error_msg: str | None = None
        is_success = False
        records_count = 0
        tier = 1
        source_plat = "unknown"

        try:
            slot_idx = self._slot_execution_counts.get(job_id, 0)
            arm_orchestrator(self.orchestrator)

            def _guarded_slot() -> tuple[ScrapeResult, SlotResultSummary]:
                scraped, slot_summary = self.orchestrator.run_slot(
                    route=route,
                    window=b_window,
                    slot_index=slot_idx,
                    base_date=base_date,
                    proxy=proxy_url,
                )
                scraped = consume_challenge(scraped)
                if scraped.metadata.get("outcome") == BLOCKED_BY_CAPTCHA:
                    slot_summary.success = False
                    slot_summary.records_count = 0
                    slot_summary.errors = [BLOCKED_BY_CAPTCHA]
                return scraped, slot_summary

            scrape_res, summary = await asyncio.to_thread(_guarded_slot)
            if scrape_res is None or summary is None:
                raise RuntimeError(f"slot {slot_key} yielded no result")

            records_count = len(scrape_res.records)
            blocked = scrape_res.metadata.get("outcome") == BLOCKED_BY_CAPTCHA
            is_success = scrape_res.success and records_count > 0 and not blocked
            tier = summary.tier
            source_plat = summary.source_platform
            if blocked:
                logger.warning("slot %s blocked_by_captcha; not ingesting", slot_key)

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            if assigned_proxy and not blocked:
                if is_success:
                    self.proxy_pool.report_success(
                        assigned_proxy, latency_ms=duration_ms
                    )
                else:
                    err_summary = (
                        "; ".join(summary.errors)
                        if summary.errors
                        else "Zero records returned"
                    )
                    self.proxy_pool.report_failure(assigned_proxy, error=err_summary)
            if self.config.ingest and is_success and scrape_res.records:
                await asyncio.to_thread(
                    self.orchestrator.client.post_records_chunked,
                    scrape_res.records,
                    scrape_res.source,
                )

        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_msg = str(exc)
            logger.error(
                "[%s] Error executing slot %s: %s",
                exec_id,
                slot_key,
                exc,
                exc_info=True,
            )
            if assigned_proxy:
                self.proxy_pool.report_failure(assigned_proxy, error=error_msg)

        completed_dt = datetime.now(UTC)
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
            error=error_msg
            or ("; ".join(summary.errors) if summary and summary.errors else None),
            tier=tier,
            source_platform=source_plat,
        )

        async with self._lock:
            self._history.append(record)
            if len(self._history) > self.config.max_history_records:
                self._history.pop(0)
            self._slot_execution_counts[job_id] = (
                self._slot_execution_counts.get(job_id, 0) + 1
            )

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
    ) -> dict[str, Any]:
        """Dispatches an immediate on-demand execution for a specific route and booking horizon."""
        return await self.execute_slot_job(
            origin=origin,
            destination=destination,
            window=window,
            apply_jitter=apply_jitter,
        )

    async def trigger_all(
        self,
        stagger_seconds: float | None = None,
        apply_jitter: bool = False,
    ) -> list[dict[str, Any]]:
        """Dispatches an immediate full-sweep scrape across all 40 registered slots."""
        stagger = (
            stagger_seconds
            if stagger_seconds is not None
            else self.config.stagger_seconds
        )
        results: list[dict[str, Any]] = []

        logger.info(
            "Triggering immediate master sweep across all registered slots (stagger=%.2fs)",
            stagger,
        )

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

    def get_job_status(self) -> dict[str, Any]:
        """Provides monitoring status for all registered jobs, triggers, and execution counts."""
        jobs_info: list[dict[str, Any]] = []

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

    def start(self, paused: bool = False) -> None:
        """Starts the APScheduler background daemon. Paused still computes next_run_time."""
        if not self.is_running:
            self.scheduler.start(paused=paused)
            self.is_running = True
            logger.info(
                "IngestionScheduler started with %d registered jobs",
                len(self.scheduler.get_jobs()),
            )

    def shutdown(self, wait: bool = False) -> None:
        """Stops the scheduler and shuts down its threadpool/event handlers."""
        if self.is_running:
            self.scheduler.shutdown(wait=wait)
            self.is_running = False
            logger.info("IngestionScheduler stopped successfully")


# Global singleton instance container
_GLOBAL_SCHEDULER: IngestionScheduler | None = None


def get_scheduler(
    config: SchedulerConfig | None = None,
    orchestrator: IngestionOrchestrator | None = None,
    proxy_pool: ProxyPoolManager | None = None,
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
        default=os.getenv("SCHEDULER_CRON") or None,
        help="UTC cron expression (default: SCHEDULER_CRON, else interval)",
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
        "--print-next",
        action="store_true",
        help="Print the next UTC run time and exit without scraping",
    )
    parser.add_argument(
        "--dry-tick",
        action="store_true",
        help="Start the scheduler, wait for one tick, and exit without scraping",
    )
    parser.add_argument(
        "--state-dir",
        type=str,
        default=os.getenv("SCHEDULER_STATE_DIR", "artifacts/scheduler"),
        help="Directory for the sweep lock and once-per-day markers",
    )
    parser.add_argument(
        "--dispatch",
        type=str,
        default=os.getenv("SCHEDULER_DISPATCH", "direct"),
        choices=["direct", "enqueue"],
        help="direct scrapes here; enqueue hands slots to the worker",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity level",
    )
    return parser.parse_args()


async def _dry_tick() -> int:
    """Prove the engine fires. No scrape, no enqueue."""
    fired = asyncio.Event()
    ticker = AsyncIOScheduler()
    ticker.add_job(
        fired.set, "interval", seconds=1, id="dry-tick", max_instances=1, coalesce=True
    )
    ticker.start()
    try:
        await asyncio.wait_for(fired.wait(), timeout=5)
    finally:
        ticker.shutdown(wait=False)
    print(json.dumps({"ticked": True}))
    return 0


def _apply_source_env() -> None:
    raw = os.getenv("SCRAPER_SOURCE", "")
    if raw:
        os.environ["SCRAPER_SOURCE"] = normalize_scraper_source(raw)


async def async_main() -> int:
    """Async entrypoint for standalone daemon execution."""
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if args.dry_tick:
        return await _dry_tick()

    _apply_source_env()
    dispatch = parse_dispatch(args.dispatch)
    cfg = SchedulerConfig(
        cron_expr=args.cron,
        interval_minutes=args.interval_minutes,
        jitter_min_seconds=args.jitter_min,
        jitter_max_seconds=args.jitter_max,
        dispatch=dispatch,
        ingest=args.run_once or dispatch == DispatchMode.DIRECT,
        state_dir=args.state_dir,
    )
    scheduler = IngestionScheduler(config=cfg)
    gate = SweepGate(Path(args.state_dir))

    if args.print_next:
        scheduler.start(paused=True)
        try:
            jobs = scheduler.scheduler.get_jobs()
            nxt = jobs[0].next_run_time if jobs else None
            print(
                json.dumps(
                    {
                        "next_run_time": nxt.isoformat() if nxt else None,
                        "cron": args.cron,
                        "job_id": jobs[0].id if jobs else None,
                    }
                )
            )
            return 0 if nxt is not None else 1
        finally:
            scheduler.shutdown()

    if args.run_once:
        day = datetime.now(UTC).date()
        claim = gate.claim_run_once(day)
        if not claim.acquired:
            logger.info("daily sweep skipped: %s", claim.reason)
            print(
                json.dumps({"skipped": True, "reason": claim.reason, "day": claim.day})
            )
            return 0
        try:
            logger.info("Executing on-demand single sweep of all slots...")
            await scheduler.trigger_all(stagger_seconds=0.5, apply_jitter=False)
            gate.complete(day)
            status = scheduler.get_job_status()
            print(f"Sweep complete: {status['history_summary']}")
            return 0
        finally:
            gate.release()

    claim = gate.claim_process()
    if not claim.acquired:
        logger.warning("scheduler already running: %s", claim.reason)
        print(json.dumps({"skipped": True, "reason": claim.reason}))
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
        gate.release()

    return 0


def main() -> int:
    """CLI wrapper for asyncio execution."""
    return asyncio.run(async_main())


if __name__ == "__main__":
    sys.exit(main())
