"""Master Ingestion Orchestrator for APIx Domestic Airfare Price Index.

Coordinates automated, rate-limited, and jittered airfare data collection across:
- 10 DGCA Domestic Trunk Routes (DEL, BOM, BLR, HYD, CCU)
- 4 SIH Mandatory Advance Booking Windows (T+1, T+7, T+15, T+30)
- Multi-Source Scrapers: the 11 PS portals, Amadeus GDS, and DGCA Synthetic Fallback. A registered scraper is not a live fare.
- Anti-bot jitter injection (randomized delays between requests)
- Periodic browser context and session recycling
- Micro-batch chunked network dispatch to APIx Backend Ingestion API
- Automated summary artifact generation for telemetry and auditability
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
from typing import Any, Dict, List, Optional, Tuple, Union

from ingestion.base import BaseScraper, RawFareRecord, ScrapeResult
from ingestion.client import IngestionClient
from ingestion.config import (
    BOOKING_WINDOW_MAP,
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    BookingWindow,
    IngestionConfig,
    Route,
)
from ingestion.crawlers.airindia import AirIndiaScraper
from ingestion.crawlers.airindia_express import AirIndiaExpressScraper
from ingestion.crawlers.akasa import AkasaScraper
from ingestion.crawlers.amadeus import AmadeusFlightClient
from ingestion.crawlers.cleartrip import CleartripScraper
from ingestion.crawlers.easemytrip import EaseMyTripScraper
from ingestion.crawlers.goibibo import GoibiboScraper
from ingestion.crawlers.indigo import IndiGoScraper
from ingestion.crawlers.ixigo import IxigoScraper
from ingestion.crawlers.makemytrip import MakeMyTripScraper
from ingestion.crawlers.spicejet import SpiceJetScraper
from ingestion.crawlers.synthetic import SyntheticFlightGenerator
from ingestion.crawlers.yatra import YatraScraper
from ingestion.sources import PS_SOURCE_TYPES

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("ingestion.orchestrator")

PS_PORTAL_SOURCES: Tuple[str, ...] = tuple(PS_SOURCE_TYPES)


def build_scraper_registry(config: IngestionConfig) -> Dict[str, BaseScraper]:
    """Every registered scraper. PS portals are implemented; live fares are not implied."""
    return {
        "easemytrip": EaseMyTripScraper(config=config),
        "makemytrip": MakeMyTripScraper(config=config),
        "spicejet": SpiceJetScraper(config=config),
        "indigo": IndiGoScraper(config=config),
        "airindia": AirIndiaScraper(config=config),
        "airindiaexpress": AirIndiaExpressScraper(config=config),
        "akasa": AkasaScraper(config=config),
        "yatra": YatraScraper(config=config),
        "cleartrip": CleartripScraper(config=config),
        "ixigo": IxigoScraper(config=config),
        "goibibo": GoibiboScraper(config=config),
        "amadeus": AmadeusFlightClient(config=config),
        "synthetic": SyntheticFlightGenerator(config=config),
    }

# Booking window alias map for scheduling compatibility
WINDOW_ALIAS_MAP: Dict[str, str] = {
    "1-3d": "T+1",
    "4-7d": "T+7",
    "8-14d": "T+15",
    "15-30d": "T+30",
    "t+1": "T+1",
    "t+7": "T+7",
    "t+15": "T+15",
    "t+30": "T+30",
}


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
        scraper_source: Optional[str] = None,
        jitter_range: Tuple[float, float] = (3.0, 6.0),
        session_recycle_every: int = 10,
        artifacts_dir: str = "artifacts",
        proxy_manager: Optional[Any] = None,
    ) -> None:
        self.config = config or IngestionConfig()
        self.client = client or IngestionClient(config=self.config)
        self.jitter_range = jitter_range
        self.session_recycle_every = session_recycle_every
        self.artifacts_dir = artifacts_dir
        self.proxy_manager = proxy_manager

        # Resolve scraper source
        self.scraper_source = (
            scraper_source
            or os.getenv("SCRAPER_SOURCE")
            or "easemytrip"
        )

        self.scrapers: Dict[str, BaseScraper] = build_scraper_registry(self.config)

        # Handle explicit single scraper injection
        if scraper is not None:
            self.scraper = scraper
            self.scrapers["custom"] = scraper
            self.scraper_source = "custom"
        elif self.scraper_source in self.scrapers:
            self.scraper = self.scrapers[self.scraper_source]
        else:
            self.scraper = self.scrapers["easemytrip"]

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
            "Recycling scraper sessions at slot %d (recycle interval: %d slots)",
            current_slot,
            self.session_recycle_every,
        )
        self.scrapers = build_scraper_registry(self.config)
        if self.scraper_source in self.scrapers:
            self.scraper = self.scrapers[self.scraper_source]
        elif self.scraper_source == "custom":
            pass
        else:
            self.scraper = self.scrapers["easemytrip"]

    def run_slot(
        self,
        route: Route,
        window: BookingWindow,
        slot_index: int,
        base_date: Optional[date] = None,
        proxy: Optional[str] = None,
    ) -> Tuple[ScrapeResult, SlotResultSummary]:
        """Executes a single route-window slot and returns the result with summary."""
        target_date = (base_date or date.today()) + timedelta(days=window.days_advance)
        route_str = f"{route.origin}-{route.destination}"

        logger.info(
            "Executing Slot #%02d: %s | Window: %s (%s) | Target Date: %s | Source: %s",
            slot_index + 1,
            route_str,
            window.code,
            f"+{window.days_advance}d",
            target_date.isoformat(),
            self.scraper_source,
        )

        # Multi-source aggregation execution
        if self.scraper_source in ("multi_source", "multi"):
            return self._run_slot_multi_source(route, window, slot_index, target_date)

        # Single designated scraper execution
        scraper_instance = self.scrapers.get(self.scraper_source, self.scraper)
        if proxy:
            # The slot loop is sequential, so binding the proxy to the instance for
            # this call is safe. Threading it as a scrape_route argument would be
            # cleaner but every crawler would need the signature change.
            scraper_instance.proxy = proxy
        scrape_res = scraper_instance.scrape_route(
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

    def _run_slot_multi_source(
        self,
        route: Route,
        window: BookingWindow,
        slot_index: int,
        target_date: date,
    ) -> Tuple[ScrapeResult, SlotResultSummary]:
        """Executes multi-source scraping across MakeMyTrip, SpiceJet, and EaseMyTrip for a slot."""
        route_str = f"{route.origin}-{route.destination}"
        start_time = time.time()

        # Primary sources to aggregate
        sources = list(PS_PORTAL_SOURCES)
        aggregated_records: List[RawFareRecord] = []
        collected_errors: List[str] = []
        source_counts: Dict[str, int] = {}
        highest_tier = 1

        for src_name in sources:
            scraper_inst = self.scrapers.get(src_name)
            if not scraper_inst:
                continue
            try:
                sub_res = scraper_inst.scrape_route(
                    origin=route.origin,
                    destination=route.destination,
                    target_date=target_date,
                    window_code=window.code,
                )
                if sub_res.success and sub_res.records:
                    for r in sub_res.records:
                        if r.source == "synthetic":
                            r.source = src_name
                            r.source_platform = src_name
                    aggregated_records.extend(sub_res.records)
                    source_counts[src_name] = len(sub_res.records)
                else:
                    source_counts[src_name] = 0
                    if sub_res.errors:
                        collected_errors.extend(sub_res.errors)

                tier_val = int(sub_res.metadata.get("tier", 1))
                if tier_val > highest_tier:
                    highest_tier = tier_val

            except Exception as src_exc:
                err = f"Scraper '{src_name}' failed on slot {route_str}: {src_exc}"
                logger.warning(err)
                collected_errors.append(err)
                source_counts[src_name] = 0

        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        success = len(aggregated_records) > 0

        # Build aggregated ScrapeResult
        scrape_res = ScrapeResult(
            source="multi_source",
            success=success,
            records=aggregated_records,
            errors=collected_errors,
            duration_ms=elapsed_ms,
            metadata={
                "tier": highest_tier,
                "source": "multi_source",
                "source_counts": source_counts,
                "records_count": len(aggregated_records),
                "origin": route.origin,
                "destination": route.destination,
                "target_date": target_date.isoformat(),
                "booking_window": window.code,
            },
        )

        summary = SlotResultSummary(
            slot_index=slot_index + 1,
            route=route_str,
            origin=route.origin,
            destination=route.destination,
            booking_window=window.code,
            target_date=target_date.isoformat(),
            records_count=len(aggregated_records),
            tier=highest_tier,
            source_platform="multi_source",
            duration_ms=elapsed_ms,
            success=success,
            errors=collected_errors,
        )

        return scrape_res, summary

    def scrape_slot(
        self,
        origin: Union[str, Route],
        destination: Optional[str] = None,
        window_code: Union[str, BookingWindow] = "T+1",
        target_date: Optional[date] = None,
        scraper_source: Optional[str] = None,
        proxy: Optional[str] = None,
    ) -> ScrapeResult:
        """Convenience method for scheduler and ad-hoc jobs to scrape a single slot.

        Supports both Route objects and (origin, destination) strings, as well as
        booking window aliases (e.g. '1-3d' -> 'T+1', '4-7d' -> 'T+7').
        """
        # Resolve route
        if isinstance(origin, Route):
            route_obj = origin
            orig_str = origin.origin
            dest_str = origin.destination
        else:
            orig_str = str(origin).upper().strip()
            dest_str = str(destination or "BOM").upper().strip()
            route_obj = Route(origin=orig_str, destination=dest_str, distance_km=1000, typical_duration_min=120, dgca_weight=0.10)

        # Resolve booking window
        if isinstance(window_code, BookingWindow):
            win_obj = window_code
            canon_window = window_code.code
        else:
            raw_code = str(window_code).lower().strip()
            canon_window = WINDOW_ALIAS_MAP.get(raw_code, raw_code.upper())
            win_obj = BOOKING_WINDOW_MAP.get(canon_window, BOOKING_WINDOWS[0])

        calc_date = target_date or (date.today() + timedelta(days=win_obj.days_advance))

        # Check scraper override
        active_source = scraper_source or self.scraper_source
        if active_source in ("multi_source", "multi"):
            scrape_res, _ = self._run_slot_multi_source(route_obj, win_obj, 0, calc_date)
            return scrape_res

        scraper_inst = self.scrapers.get(active_source, self.scraper)
        if proxy:
            # The slot loop is sequential, so binding the proxy to the instance for
            # this call is safe. Threading it as a scrape_route argument would be
            # cleaner but every crawler would need the signature change.
            scraper_inst.proxy = proxy
        return scraper_inst.scrape_route(
            origin=orig_str,
            destination=dest_str,
            target_date=calc_date,
            window_code=canon_window,
        )

    def scrape_all(
        self,
        routes: Optional[List[Route]] = None,
        windows: Optional[List[BookingWindow]] = None,
        base_date: Optional[date] = None,
        dry_run: bool = False,
    ) -> OrchestratorRunSummary:
        """Alias for run_all_slots to provide intuitive scheduling API."""
        return self.run_all_slots(routes=routes, windows=windows, base_date=base_date, dry_run=dry_run)

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
        logger.info(
            "Ingestion Mode: %s | Scraper Source: %s | Dry Run: %s",
            self.config.ingestion_mode,
            self.scraper_source,
            dry_run,
        )
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
                    logger.error(
                        "Error executing slot %d (%s-%s %s): %s",
                        slot_idx + 1,
                        route.origin,
                        route.destination,
                        window.code,
                        slot_exc,
                    )
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
                    source=f"orchestrator_{self.scraper_source}_{self.config.ingestion_mode}",
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
        "--scraper",
        choices=["multi_source", *PS_PORTAL_SOURCES, "amadeus", "synthetic"],
        default=os.getenv("SCRAPER_SOURCE", "multi_source"),
        help="Active scraper source or multi_source aggregation (default: multi_source)",
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
        scraper_source=args.scraper,
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
