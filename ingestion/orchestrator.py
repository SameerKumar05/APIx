"""Master Ingestion Orchestrator for APIx Domestic Airfare Price Index.

Coordinates automated, scheduled, and on-demand scraping across all 40 domestic flight
slots (10 top DGCA trunk routes x 4 advance booking windows: T+1, T+7, T+15, T+30).

Implements:
1. Systematic slot traversal with human-like jitter delays (3-6s).
2. Browser session recycling every N slots to eliminate memory buildup and fingerprinting.
3. Automated 3-tier crawler fallback (EaseMyTrip Playwright -> Amadeus API -> DGCA Synthetic).
4. Chunked batch submission to APIx backend endpoint (POST /api/v1/ingestion/batch).
5. Comprehensive audit logging and execution summary artifact generation (artifacts/run_summary.json).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ingestion.base import BaseScraper, RawFareRecord, ScrapeResult
from ingestion.client import IngestionClient
from ingestion.config import (
    BOOKING_WINDOW_MAP,
    BOOKING_WINDOWS,
    BookingWindow,
    DEFAULT_ROUTES,
    IngestionConfig,
    Route,
)
from ingestion.crawlers.amadeus import AmadeusFlightClient
from ingestion.crawlers.easemytrip import EaseMyTripScraper
from ingestion.crawlers.synthetic import SyntheticFlightGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ingestion.orchestrator")


@dataclass
class SlotResultSummary:
    """Summary of an individual slot scrape execution."""

    slot_index: int
    route: str
    origin: str
    destination: str
    booking_window: str
    target_date: str
    records_count: int
    tier: int
    source_platform: str
    duration_ms: float
    success: bool
    errors: List[str] = field(default_factory=list)


@dataclass
class OrchestratorRunSummary:
    """Consolidated summary artifact for an entire orchestrator execution run."""

    run_id: str
    mode: str
    started_at: str
    completed_at: str
    duration_seconds: float
    total_slots: int
    successful_slots: int
    failed_slots: int
    total_records_collected: int
    total_batches_dispatched: int
    batches_successful: int
    tier_distribution: Dict[str, int]
    slots: List[Dict[str, Any]]
    backend_status: Optional[str] = None
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IngestionOrchestrator:
    """Master scraper coordinator executing all 40 slots with jitter, recycling, and batching."""

    def __init__(
        self,
        config: Optional[IngestionConfig] = None,
        client: Optional[IngestionClient] = None,
        scraper: Optional[BaseScraper] = None,
        jitter_range: Tuple[float, float] = (3.0, 6.0),
        session_recycle_every: int = 10,
        artifacts_dir: str = "artifacts",
    ) -> None:
        self.config = config or IngestionConfig()
        self.client = client or IngestionClient(config=self.config)
        self.scraper = scraper or EaseMyTripScraper(config=self.config)
        self.jitter_range = jitter_range
        self.session_recycle_every = session_recycle_every
        self.artifacts_dir = artifacts_dir

    def _apply_jitter(self, slot_index: int, total_slots: int) -> None:
        """Applies randomized human-like jitter between scraping operations."""
        min_j, max_j = self.jitter_range
        if max_j <= 0.0 or slot_index == 0:
            return

        jitter = random.uniform(min_j, max_j)
        logger.info(
            "Applying anti-bot jitter: sleeping %.2fs before slot %d/%d",
            jitter,
            slot_index + 1,
            total_slots,
        )
        time.sleep(jitter)

    def _recycle_session(self, current_slot: int) -> None:
        """Recycles scraper session/context to prevent memory bloat and evasive pattern profiling."""
        logger.info(
            "Recycling scraper session at slot %d (recycle interval: %d slots)",
            current_slot,
            self.session_recycle_every,
        )
        # Re-initialize primary scraper instance
        self.scraper = EaseMyTripScraper(config=self.config)

    def run_slot(
        self,
        route: Route,
        window: BookingWindow,
        slot_index: int,
        base_date: Optional[date] = None,
    ) -> Tuple[ScrapeResult, SlotResultSummary]:
        """Executes a single route-window slot and returns the result with summary."""
        target_date = (base_date or date.today()) + timedelta(days=window.days_advance)
        route_str = f"{route.origin}-{route.destination}"

        logger.info(
            "Executing Slot #%02d: %s | Window: %s (%s) | Target Date: %s",
            slot_index + 1,
            route_str,
            window.code,
            f"+{window.days_advance}d",
            target_date.isoformat(),
        )

        scrape_res = self.scraper.scrape_route(
            origin=route.origin,
            destination=route.destination,
            target_date=target_date,
            window_code=window.code,
        )

        tier = int(scrape_res.metadata.get("tier", 1))
        source_plat = str(scrape_res.metadata.get("source", scrape_res.source))

        summary = SlotResultSummary(
            slot_index=slot_index + 1,
            route=route_str,
            origin=route.origin,
            destination=route.destination,
            booking_window=window.code,
            target_date=target_date.isoformat(),
            records_count=len(scrape_res.records),
            tier=tier,
            source_platform=source_plat,
            duration_ms=scrape_res.duration_ms,
            success=scrape_res.success and len(scrape_res.records) > 0,
            errors=list(scrape_res.errors),
        )

        return scrape_res, summary

    def run_all_slots(
        self,
        routes: Optional[List[Route]] = None,
        windows: Optional[List[BookingWindow]] = None,
        base_date: Optional[date] = None,
        dry_run: bool = False,
    ) -> OrchestratorRunSummary:
        """Runs all 40 slots, chunks batches, dispatches to backend, and exports summary."""
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        start_dt = datetime.now(timezone.utc)
        start_time = time.time()

        target_routes = routes or DEFAULT_ROUTES
        target_windows = windows or BOOKING_WINDOWS
        total_slots = len(target_routes) * len(target_windows)

        logger.info("=" * 80)
        logger.info("STARTING MASTER INGESTION ORCHESTRATION: RUN ID %s", run_id)
        logger.info(
            "Routes: %d | Windows: %d | Total Scheduled Slots: %d",
            len(target_routes),
            len(target_windows),
            total_slots,
        )
        logger.info("Ingestion Mode: %s | Dry Run: %s", self.config.ingestion_mode, dry_run)
        logger.info("=" * 80)

        all_records: List[RawFareRecord] = []
        slot_summaries: List[Dict[str, Any]] = []
        tier_counts = {"tier_1": 0, "tier_2": 0, "tier_3": 0}
        successful_slots = 0
        failed_slots = 0
        orchestrator_errors: List[str] = []

        slot_idx = 0
        for route in target_routes:
            for window in target_windows:
                # 1. Apply anti-bot human-like jitter
                self._apply_jitter(slot_idx, total_slots)

                # 2. Check session recycling threshold
                if slot_idx > 0 and self.session_recycle_every > 0 and slot_idx % self.session_recycle_every == 0:
                    self._recycle_session(slot_idx)

                # 3. Execute slot scrape
                try:
                    scrape_res, summary = self.run_slot(
                        route=route,
                        window=window,
                        slot_index=slot_idx,
                        base_date=base_date,
                    )

                    all_records.extend(scrape_res.records)
                    slot_summaries.append(asdict(summary))

                    tier_key = f"tier_{summary.tier}"
                    tier_counts[tier_key] = tier_counts.get(tier_key, 0) + 1

                    if summary.success:
                        successful_slots += 1
                    else:
                        failed_slots += 1

                except Exception as slot_exc:
                    logger.error("Error executing slot %d (%s-%s %s): %s", slot_idx + 1, route.origin, route.destination, window.code, slot_exc)
                    failed_slots += 1
                    orchestrator_errors.append(f"Slot #{slot_idx + 1} ({route.origin}-{route.destination}) failed: {slot_exc}")
                    slot_summaries.append(
                        asdict(
                            SlotResultSummary(
                                slot_index=slot_idx + 1,
                                route=f"{route.origin}-{route.destination}",
                                origin=route.origin,
                                destination=route.destination,
                                booking_window=window.code,
                                target_date=((base_date or date.today()) + timedelta(days=window.days_advance)).isoformat(),
                                records_count=0,
                                tier=0,
                                source_platform="error",
                                duration_ms=0.0,
                                success=False,
                                errors=[str(slot_exc)],
                            )
                        )
                    )

                slot_idx += 1

        # 4. Chunk records into batches and dispatch to Backend API
        total_batches = 0
        successful_batches = 0
        backend_status = "skipped_dry_run" if dry_run else "no_records"

        if all_records and not dry_run:
            logger.info("=" * 80)
            logger.info("DISPATCHING %d RECORDS TO INGESTION API", len(all_records))
            logger.info("=" * 80)

            try:
                batch_responses = self.client.post_records_chunked(
                    records=all_records,
                    source=f"orchestrator_{self.config.ingestion_mode}",
                    chunk_size=self.config.batch_size,
                )
                total_batches = len(batch_responses)
                successful_batches = sum(1 for resp in batch_responses if resp.get("status") in ("success", "partial"))
                backend_status = "success" if successful_batches == total_batches else "partial_or_failed"
                logger.info("Dispatched %d batches: %d succeeded", total_batches, successful_batches)
            except Exception as dispatch_exc:
                err_msg = f"Failed to dispatch records to API: {dispatch_exc}"
                logger.error(err_msg)
                orchestrator_errors.append(err_msg)
                backend_status = "dispatch_error"
        elif dry_run:
            logger.info("Dry-run active: skipping network batch dispatch to API")
            # Calculate mock batches
            total_batches = (len(all_records) + self.config.batch_size - 1) // max(1, self.config.batch_size)
            successful_batches = total_batches

        end_dt = datetime.now(timezone.utc)
        elapsed_sec = round(time.time() - start_time, 2)

        summary_artifact = OrchestratorRunSummary(
            run_id=run_id,
            mode=self.config.ingestion_mode,
            started_at=start_dt.isoformat(),
            completed_at=end_dt.isoformat(),
            duration_seconds=elapsed_sec,
            total_slots=total_slots,
            successful_slots=successful_slots,
            failed_slots=failed_slots,
            total_records_collected=len(all_records),
            total_batches_dispatched=total_batches,
            batches_successful=successful_batches,
            tier_distribution=tier_counts,
            slots=slot_summaries,
            backend_status=backend_status,
            errors=orchestrator_errors,
        )

        # 5. Write execution summary artifact to artifacts/run_summary.json
        self._write_summary_artifact(summary_artifact)

        logger.info("=" * 80)
        logger.info("ORCHESTRATION COMPLETED: %d/%d SLOTS SUCCESSFUL", successful_slots, total_slots)
        logger.info("Total Records: %d | Duration: %.2fs", len(all_records), elapsed_sec)
        logger.info("Tier Breakdown: %s", tier_counts)
        logger.info("=" * 80)

        return summary_artifact

    def _write_summary_artifact(self, summary: OrchestratorRunSummary) -> str:
        """Writes the run summary dictionary to artifacts/run_summary.json."""
        try:
            os.makedirs(self.artifacts_dir, exist_ok=True)
            output_path = os.path.join(self.artifacts_dir, "run_summary.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(summary.to_dict(), f, indent=2)
            logger.info("Saved run summary artifact to %s", output_path)
            return output_path
        except Exception as exc:
            logger.error("Failed writing run summary artifact: %s", exc)
            return ""


def main() -> int:
    """CLI entrypoint for running ingestion orchestrator directly."""
    parser = argparse.ArgumentParser(description="APIx Master Airfare Ingestion Orchestrator")
    parser.add_argument(
        "--mode",
        choices=["live", "mock", "synthetic"],
        default=os.getenv("INGESTION_MODE", "synthetic"),
        help="Scraper operational mode (default: synthetic or INGESTION_MODE)",
    )
    parser.add_argument(
        "--no-jitter",
        action="store_true",
        help="Disable inter-slot anti-bot jitter delays for testing and benchmarking",
    )
    parser.add_argument(
        "--jitter-min",
        type=float,
        default=3.0,
        help="Minimum jitter delay in seconds (default: 3.0)",
    )
    parser.add_argument(
        "--jitter-max",
        type=float,
        default=6.0,
        help="Maximum jitter delay in seconds (default: 6.0)",
    )
    parser.add_argument(
        "--recycle-every",
        type=int,
        default=10,
        help="Recycle scraper session every N slots (default: 10)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("INGESTION_BATCH_SIZE", "100")),
        help="API submission batch chunk size (default: 100)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run scraping without posting records to backend API",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts",
        help="Directory to save run_summary.json (default: artifacts)",
    )
    parser.add_argument(
        "--endpoint",
        default=None,
        help="Override backend API endpoint URL",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Override backend ingestion API key",
    )

    args = parser.parse_args()

    # Build config
    config = IngestionConfig(
        ingestion_mode=args.mode,
        batch_size=args.batch_size,
    )
    if args.endpoint:
        config.api_base_url = args.endpoint
    if args.api_key:
        config.ingestion_key = args.api_key

    jitter_range = (0.0, 0.0) if args.no_jitter else (args.jitter_min, args.jitter_max)

    orchestrator = IngestionOrchestrator(
        config=config,
        jitter_range=jitter_range,
        session_recycle_every=args.recycle_every,
        artifacts_dir=args.output_dir,
    )

    summary = orchestrator.run_all_slots(dry_run=args.dry_run)

    if summary.failed_slots > 0:
        logger.warning("%d slots failed during execution", summary.failed_slots)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
