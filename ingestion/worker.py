"""Cross-process crawler worker daemon for APIx.

Polls the durable crawler_jobs queue using atomic conditional updates,
maintains heartbeat liveness in worker_heartbeats, sweeps stale leases,
executes scraper slots via IngestionOrchestrator, and dispatches harvested
quotes to the Ingestion API via IngestionClient.
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import socket
import sys
import threading
import time
import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from backend.app.db.crawler_job_repo import (
    claim_next_job,
    complete_job,
    heartbeat_job,
    reap_stale_jobs,
    register_worker_heartbeat,
    release_worker_leases,
    retire_worker,
    update_worker_heartbeat,
)
from backend.app.db.session import SessionLocal
from backend.app.db.telemetry_repo import log_scraper_telemetry
from backend.app.models.crawler_job import CrawlerJob
from ingestion.base import RawFareRecord
from ingestion.captcha import BLOCKED_BY_CAPTCHA, consume_challenge, telemetry_status_for
from ingestion.client import IngestionClient
from ingestion.config import (
    BOOKING_WINDOW_MAP,
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    BookingWindow,
    IngestionConfig,
    Route,
)
from ingestion.orchestrator import IngestionOrchestrator
from ingestion.scrape_hooks import arm_orchestrator

logger = logging.getLogger("ingestion.worker")


class CrawlerWorker:
    """Autonomous worker daemon consuming crawler jobs from the durable queue."""

    def __init__(
        self,
        worker_id: str | None = None,
        config: IngestionConfig | None = None,
        orchestrator: IngestionOrchestrator | None = None,
        client: IngestionClient | None = None,
        session_factory: Any | None = None,
        poll_interval: float = 2.0,
        heartbeat_interval: float = 15.0,
        reaper_interval: float = 30.0,
        lease_seconds: int = 90,
    ) -> None:
        self.hostname = socket.gethostname()
        self.pid = os.getpid()
        self.worker_id = worker_id or f"worker-{self.hostname}-{self.pid}-{uuid.uuid4().hex[:6]}"
        self.config = config or IngestionConfig()
        self.orchestrator = orchestrator or IngestionOrchestrator(config=self.config)
        self.client = client or IngestionClient(config=self.config)
        self.session_factory = session_factory or SessionLocal
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self.reaper_interval = reaper_interval
        self.lease_seconds = lease_seconds
        self.claim_backoff_seconds = 10.0
        self.is_running = False
        self._claim_failed = False
        self._last_heartbeat_time = 0.0
        self._last_reaper_time = 0.0
        self._execution_heartbeat_stop: threading.Event | None = None
        self._execution_heartbeat_thread: threading.Thread | None = None

    def start(self) -> None:
        self.is_running = True
        logger.info("Starting CrawlerWorker %s (PID: %d, Host: %s)", self.worker_id, self.pid, self.hostname)

        with self.session_factory() as db:
            register_worker_heartbeat(
                db=db,
                worker_id=self.worker_id,
                hostname=self.hostname,
                pid=self.pid,
                worker_type="crawler_worker",
                metadata={"scraper_source": self.orchestrator.scraper_source, "mode": self.config.ingestion_mode},
            )

        self._last_heartbeat_time = time.time()
        self._last_reaper_time = time.time()

        try:
            while self.is_running:
                self._tick()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutdown signal received by worker %s", self.worker_id)
        finally:
            self.stop()

    def stop(self) -> None:
        self.is_running = False
        self._stop_execution_heartbeat()
        try:
            with self.session_factory() as db:
                release_worker_leases(db, self.worker_id)
                retire_worker(db, self.worker_id)
            logger.info("Worker %s successfully retired", self.worker_id)
        except SQLAlchemyError:
            logger.exception("Worker shutdown cleanup failed for %s", self.worker_id)

    def _tick(self) -> None:
        now_ts = time.time()

        if now_ts - self._last_heartbeat_time >= self.heartbeat_interval:
            self._send_heartbeat()
            self._last_heartbeat_time = now_ts

        if now_ts - self._last_reaper_time >= self.reaper_interval:
            self._run_reaper()
            self._last_reaper_time = now_ts

        self._claim_failed = False
        job = self._claim_job()
        if self._claim_failed:
            time.sleep(self.claim_backoff_seconds)
            return
        if job:
            self._process_job(job)
        else:
            jitter = random.uniform(0.0, 0.5)
            time.sleep(self.poll_interval + jitter)

    def _send_heartbeat(self, current_job_id: str | None = None) -> None:
        try:
            with self.session_factory() as db:
                update_worker_heartbeat(db, self.worker_id, current_job_id=current_job_id)
        except Exception as exc:
            logger.warning("Worker %s heartbeat update failed: %s", self.worker_id, exc)

    def _run_reaper(self) -> None:
        try:
            with self.session_factory() as db:
                reap_stale_jobs(db)
        except Exception as exc:
            logger.warning("Reaper sweep failed: %s", exc)

    def _claim_job(self) -> CrawlerJob | None:
        try:
            with self.session_factory() as db:
                return claim_next_job(db, worker_id=self.worker_id, lease_seconds=self.lease_seconds)
        except SQLAlchemyError:
            logger.exception("Claim attempt failed for worker %s", self.worker_id)
            self._claim_failed = True
            return None

    def _refresh_while_executing(self, job_id: str, stop_event: threading.Event) -> None:
        while not stop_event.wait(self.heartbeat_interval):
            self._send_heartbeat(current_job_id=job_id)

    def _stop_execution_heartbeat(self) -> None:
        stop_event = self._execution_heartbeat_stop
        if stop_event is not None:
            stop_event.set()
        refresher = self._execution_heartbeat_thread
        if refresher is not None and refresher.is_alive() and threading.current_thread() is not refresher:
            refresher.join(timeout=self.heartbeat_interval + 1.0)
        self._execution_heartbeat_thread = None
        self._execution_heartbeat_stop = None

    def _resolve_routes(self, route_code: str | None) -> list[Route]:
        if not route_code or route_code.upper() in ("ALL", "ALL_ROUTES"):
            return list(DEFAULT_ROUTES)
        parts = route_code.strip().upper().replace("_", "-").split("-")
        orig, dest = (parts[0], parts[1]) if len(parts) >= 2 else ("DEL", "BOM")
        for r in DEFAULT_ROUTES:
            if r.origin == orig and r.destination == dest:
                return [r]
        return [Route(origin=orig, destination=dest, distance_km=1200, typical_duration_min=130, dgca_weight=0.05)]

    def _resolve_windows(self, window_code: str | None) -> list[BookingWindow]:
        if not window_code or window_code.upper() in ("ALL", "ALL_WINDOWS"):
            return list(BOOKING_WINDOWS)
        code = window_code.strip().upper()
        if code in BOOKING_WINDOW_MAP:
            return [BOOKING_WINDOW_MAP[code]]
        return [BOOKING_WINDOWS[0]]

    def _process_job(self, job: CrawlerJob) -> None:
        job_id_str = job.job_id
        job_pk = job.id
        lease_tok = job.lease_token or ""
        crawler = job.crawler_name
        route_str = job.route_code
        window_str = job.booking_window

        logger.info("Executing job %s (crawler=%s, route=%s, window=%s)", job_id_str, crawler, route_str, window_str)
        stop_event = threading.Event()
        self._execution_heartbeat_stop = stop_event
        refresher = threading.Thread(
            target=self._refresh_while_executing,
            args=(job_id_str, stop_event),
            name=f"{self.worker_id}-heartbeat",
            daemon=True,
        )
        self._execution_heartbeat_thread = refresher
        refresher.start()
        self._send_heartbeat(current_job_id=job_id_str)

        routes = self._resolve_routes(route_str)
        windows = self._resolve_windows(window_str)

        all_records: list[RawFareRecord] = []
        errors: list[str] = []
        start_time = time.time()
        slot_idx = 0
        captcha_hits = 0
        if self.config.ingestion_mode == "live":
            arm_orchestrator(self.orchestrator)

        try:
            for r in routes:
                for w in windows:
                    with self.session_factory() as db:
                        alive = heartbeat_job(db, job_pk, self.worker_id, lease_tok, lease_seconds=self.lease_seconds)
                        if not alive:
                            raise RuntimeError(f"Lease lost for job {job_id_str}")

                    scraper_override = crawler if crawler not in ("all", "default") else None
                    scrape_res = consume_challenge(
                        self.orchestrator.scrape_slot(
                            origin=r,
                            window_code=w,
                            scraper_source=scraper_override,
                        )
                    )
                    if scrape_res.metadata.get("outcome") == BLOCKED_BY_CAPTCHA:
                        captcha_hits += 1
                        errors.append(BLOCKED_BY_CAPTCHA)
                        logger.warning(
                            "job %s slot %s-%s %s blocked_by_captcha",
                            job_id_str,
                            r.origin,
                            r.destination,
                            w.code,
                        )
                    elif scrape_res.success and scrape_res.records:
                        all_records.extend(scrape_res.records)
                    if scrape_res.errors and scrape_res.metadata.get("outcome") != BLOCKED_BY_CAPTCHA:
                        errors.extend(scrape_res.errors)

                    slot_idx += 1

            dispatched_batches = 0
            if all_records:
                logger.info("[%s] Dispatching %d collected records to Ingestion API", job_id_str, len(all_records))
                batch_responses = self.client.post_records_chunked(
                    records=all_records,
                    source=f"worker_{crawler}",
                    chunk_size=self.config.batch_size,
                )
                dispatched_batches = len(batch_responses)

            elapsed_ms = round((time.time() - start_time) * 1000.0, 2)
            telemetry_status = telemetry_status_for(records=len(all_records), captcha_hits=captcha_hits)
            job_status = "FAILED" if telemetry_status == "CAPTCHA" else "COMPLETED"
            summary_dict = {
                "records_collected": len(all_records),
                "batches_dispatched": dispatched_batches,
                "duration_ms": elapsed_ms,
                "errors": errors,
                "slots_processed": slot_idx,
                "outcome": BLOCKED_BY_CAPTCHA if telemetry_status == "CAPTCHA" else telemetry_status,
                "captcha_hits": captcha_hits,
            }

            with self.session_factory() as db:
                log_scraper_telemetry(
                    db=db,
                    crawler_name=crawler,
                    route=route_str or "ALL",
                    booking_window=window_str or "T+1",
                    status=telemetry_status,
                    response_time_ms=elapsed_ms,
                    records_extracted=0 if telemetry_status == "CAPTCHA" else len(all_records),
                    error_details=BLOCKED_BY_CAPTCHA if telemetry_status == "CAPTCHA" else ("; ".join(errors) if errors else None),
                )

                completed = complete_job(
                    db=db,
                    job_id=job_pk,
                    worker_id=self.worker_id,
                    lease_token=lease_tok,
                    status=job_status,
                    result_summary=summary_dict,
                    error_message=BLOCKED_BY_CAPTCHA if telemetry_status == "CAPTCHA" else None,
                )
                if completed and job_status == "FAILED":
                    update_worker_heartbeat(db, self.worker_id, current_job_id=None, jobs_failed_increment=1)
                    logger.warning("Job %s blocked_by_captcha; no records ingested", job_id_str)
                elif completed:
                    update_worker_heartbeat(db, self.worker_id, current_job_id=None, jobs_completed_increment=1)
                    logger.info("Job %s completed successfully: %d fares in %.1fms", job_id_str, len(all_records), elapsed_ms)
                else:
                    logger.warning("Fenced completion rejected for job %s: lease was lost", job_id_str)

        except Exception as exc:
            elapsed_ms = round((time.time() - start_time) * 1000.0, 2)
            err_msg = str(exc)
            logger.error("Job %s failed: %s", job_id_str, exc, exc_info=True)

            try:
                with self.session_factory() as db:
                    log_scraper_telemetry(
                        db=db,
                        crawler_name=crawler,
                        route=route_str or "ALL",
                        booking_window=window_str or "T+1",
                        status="FAILED",
                        response_time_ms=elapsed_ms,
                        records_extracted=len(all_records),
                        error_details=err_msg,
                    )
                    complete_job(
                        db=db,
                        job_id=job_pk,
                        worker_id=self.worker_id,
                        lease_token=lease_tok,
                        status="FAILED",
                        error_message=err_msg,
                    )
                    update_worker_heartbeat(db, self.worker_id, current_job_id=None, jobs_failed_increment=1)
            except Exception as inner_exc:
                logger.error("Failed recording job error state: %s", inner_exc)
        finally:
            self._stop_execution_heartbeat()


def main() -> int:
    """CLI entrypoint for standalone worker daemon."""
    parser = argparse.ArgumentParser(description="APIx Ingestion Queue Worker Daemon")
    parser.add_argument("--worker-id", type=str, default=None, help="Explicit worker ID identifier")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Queue polling interval in seconds")
    parser.add_argument("--lease-seconds", type=int, default=90, help="Lease timeout duration in seconds")
    parser.add_argument(
        "--mode",
        choices=["live", "mock", "synthetic"],
        default=os.getenv("INGESTION_MODE", "synthetic"),
        help="Scraper operational mode",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    cfg = IngestionConfig(ingestion_mode=args.mode)
    worker = CrawlerWorker(
        worker_id=args.worker_id,
        config=cfg,
        poll_interval=args.poll_interval,
        lease_seconds=args.lease_seconds,
    )

    def handle_signal(sig: int, frame: Any) -> None:
        logger.info("Signal %d received, stopping worker...", sig)
        worker.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    worker.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
