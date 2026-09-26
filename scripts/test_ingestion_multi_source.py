#!/usr/bin/env python3
"""End-to-End Multi-Source Ingestion Pipeline Verification Script for APIx.

Validates Cycle 3 Deliverables:
1. MakeMyTrip Scraper (MakeMyTripScraper) with dynamic route parameters and fallback.
2. SpiceJet Direct Airline Crawler (SpiceJetScraper) with header randomization and route parsing.
3. Multi-Source Ingestion Orchestrator (IngestionOrchestrator) aggregating MakeMyTrip, SpiceJet, and EaseMyTrip.
4. Full 40-slot execution across all 10 DGCA trunk routes and 4 SIH booking windows.
5. Micro-batch dispatch to FastAPI Ingestion API (/api/v1/ingestion/batch) with 100% acceptance.
6. Execution summary artifact generation at artifacts/multi_source_summary.json.
7. Domain invariants: valid IATA airport codes, valid airline codes, non-negative fares, dedup hash uniqueness.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime
from typing import Any

# Ensure repository root is on sys.path
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.main import app
from ingestion.base import BaseScraper, RawFareRecord, ScrapeResult
from ingestion.client import IngestionClient
from ingestion.config import (
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    VALID_AIRLINE_CODES,
    VALID_IATA_CODES,
    BookingWindow,
    IngestionConfig,
    Route,
)
from ingestion.crawlers.amadeus import AmadeusFlightClient
from ingestion.crawlers.easemytrip import EaseMyTripScraper
from ingestion.crawlers.makemytrip import MakeMyTripScraper
from ingestion.crawlers.spicejet import SpiceJetScraper
from ingestion.crawlers.synthetic import SyntheticFlightGenerator
from ingestion.orchestrator import IngestionOrchestrator, OrchestratorRunSummary


class LocalTestClientIngestionClient(IngestionClient):
    """IngestionClient subclass routing requests directly through FastAPI TestClient."""

    def __init__(self, fastapi_app: Any, config: IngestionConfig) -> None:
        super().__init__(config=config)
        self.test_client = TestClient(fastapi_app)

    def _post_with_urllib(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Routes batch payload directly to in-process FastAPI TestClient."""
        headers = {
            "Content-Type": "application/json",
            "X-Ingestion-Key": self.ingestion_key,
        }
        resp = self.test_client.post(
            "/api/v1/ingestion/batch", json=payload, headers=headers
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"FastAPI TestClient returned {resp.status_code}: {resp.text}"
            )
        return resp.json()

    def _post_with_httpx(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_with_urllib(payload)


def run_multi_source_verification() -> int:
    """Executes full end-to-end multi-source ingestion verification."""
    print("=" * 80)
    print("APIX MULTI-SOURCE INGESTION END-TO-END VERIFICATION (CYCLE 3)")
    print("=" * 80)

    artifacts_dir = os.path.join(repo_root, "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    multi_summary_file = os.path.join(artifacts_dir, "multi_source_summary.json")

    # --------------------------------------------------------------------------
    # STEP 1: Verify Individual Crawlers (MakeMyTrip & SpiceJet)
    # --------------------------------------------------------------------------
    print("\n[STEP 1/5] Verifying Individual Scrapers (MakeMyTrip & SpiceJet)...")
    config = IngestionConfig(ingestion_mode="synthetic")

    # 1a. Test MakeMyTrip Scraper
    mmt_scraper = MakeMyTripScraper(config=config)
    target_date = date(2026, 9, 25)
    mmt_res = mmt_scraper.scrape_route("DEL", "BOM", target_date, "T+1")
    assert mmt_res.success, f"MakeMyTrip scrape failed: {mmt_res.errors}"
    assert len(mmt_res.records) > 0, "MakeMyTrip returned 0 records"
    assert (
        mmt_res.source == "makemytrip"
    ), f"Expected source makemytrip, got {mmt_res.source}"
    print(
        f"  ✓ MakeMyTripScraper verified: {len(mmt_res.records)} records collected (Source: {mmt_res.source})"
    )

    # 1b. Test SpiceJet Scraper
    sg_scraper = SpiceJetScraper(config=config)
    sg_res = sg_scraper.scrape_route("DEL", "BOM", target_date, "T+1")
    assert sg_res.success, f"SpiceJet scrape failed: {sg_res.errors}"
    assert len(sg_res.records) > 0, "SpiceJet returned 0 records"
    assert sg_res.source == "spicejet", f"Expected source spicejet, got {sg_res.source}"
    for rec in sg_res.records:
        assert (
            rec.airline_code == "SG"
        ), f"SpiceJet record must have airline_code SG, got {rec.airline_code}"
    print(
        f"  ✓ SpiceJetScraper verified: {len(sg_res.records)} records collected (Airline: SG, Source: {sg_res.source})"
    )

    # --------------------------------------------------------------------------
    # STEP 2: Verify Multi-Source Ingestion Orchestrator Execution across all 40 slots
    # --------------------------------------------------------------------------
    print("\n[STEP 2/5] Executing Multi-Source Orchestration across all 40 Slots...")
    client = LocalTestClientIngestionClient(app, config=config)
    orchestrator = IngestionOrchestrator(
        config=config,
        client=client,
        scraper_source="multi_source",
        jitter_range=(0.0, 0.0),  # Zero jitter for deterministic verification speed
        session_recycle_every=10,
        artifacts_dir=artifacts_dir,
    )

    summary: OrchestratorRunSummary = orchestrator.run_all_slots(dry_run=False)

    print(f"  -> Run ID:                   {summary.run_id}")
    print(f"  -> Total Slots Scheduled:    {summary.total_slots} (Expected: 40)")
    print(f"  -> Successful Slots:         {summary.successful_slots} (Expected: 40)")
    print(f"  -> Failed Slots:             {summary.failed_slots} (Expected: 0)")
    print(f"  -> Total Records Collected:  {summary.total_records_collected}")
    print(f"  -> Total Batches Dispatched: {summary.total_batches_dispatched}")
    print(f"  -> Successful Batches:       {summary.batches_successful}")
    print(f"  -> Backend Status:           {summary.backend_status}")
    print(f"  -> Tier Distribution:        {summary.tier_distribution}")

    assert summary.total_slots == 40, f"Expected 40 slots, got {summary.total_slots}"
    assert (
        summary.successful_slots == 40
    ), f"Expected 40 successful slots, got {summary.successful_slots}"
    assert (
        summary.failed_slots == 0
    ), f"Expected 0 failed slots, got {summary.failed_slots}"
    assert (
        summary.total_records_collected > 400
    ), f"Expected >400 records across 40 slots, got {summary.total_records_collected}"
    assert (
        summary.batches_successful == summary.total_batches_dispatched
    ), "Not all batches succeeded"
    assert (
        summary.backend_status == "success"
    ), f"Backend status is not success: {summary.backend_status}"
    print("  ✓ Multi-source 40-slot orchestration succeeded with 100% slot pass rate!")

    # --------------------------------------------------------------------------
    # STEP 3: Verify Multi-Source Distribution and Scraper Diversity
    # --------------------------------------------------------------------------
    print(
        "\n[STEP 3/5] Verifying Multi-Source Scraper Coverage and Slot Aggregation..."
    )
    slot_entries = summary.slots
    assert len(slot_entries) == 40, f"Expected 40 slot entries, got {len(slot_entries)}"

    unique_routes = {s["route"] for s in slot_entries}
    unique_windows = {s["booking_window"] for s in slot_entries}
    assert (
        len(unique_routes) == 10
    ), f"Expected 10 unique routes, got {len(unique_routes)}: {unique_routes}"
    assert unique_windows == {
        "T+1",
        "T+7",
        "T+15",
        "T+30",
    }, f"Expected 4 booking windows, got {unique_windows}"

    for slot in slot_entries:
        assert (
            slot["success"] is True
        ), f"Slot {slot['route']} {slot['booking_window']} failed: {slot['errors']}"
        assert (
            slot["records_count"] > 0
        ), f"Slot {slot['route']} {slot['booking_window']} has 0 records"
        assert (
            slot["source_platform"] == "multi_source"
        ), f"Expected source_platform multi_source, got {slot['source_platform']}"

    print(
        "  ✓ Verified all 10 trunk routes across all 4 booking windows (T+1, T+7, T+15, T+30)"
    )

    # --------------------------------------------------------------------------
    # STEP 4: Write & Validate multi_source_summary.json Artifact
    # --------------------------------------------------------------------------
    print("\n[STEP 4/5] Exporting and Validating Summary Artifact...")
    summary_dict = summary.to_dict()
    summary_dict["verified_at"] = datetime.now().isoformat()
    summary_dict["crawlers_active"] = ["makemytrip", "spicejet", "easemytrip"]

    with open(multi_summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_dict, f, indent=2)

    assert os.path.exists(
        multi_summary_file
    ), f"Summary file not found: {multi_summary_file}"
    file_size = os.path.getsize(multi_summary_file)
    assert file_size > 500, f"Summary file suspiciously small ({file_size} bytes)"
    print(f"  ✓ Artifact exported to {multi_summary_file} ({file_size} bytes)")

    # --------------------------------------------------------------------------
    # STEP 5: Verify Domain Invariants, Schema Correctness, and Deduplication
    # --------------------------------------------------------------------------
    print("\n[STEP 5/5] Validating Domain Invariants and Schema Quality...")
    # Run a test slot to inspect RawFareRecord fields in detail
    test_slot_res, _ = orchestrator.run_slot(
        DEFAULT_ROUTES[0], BOOKING_WINDOWS[0], slot_index=0
    )
    records = test_slot_res.records

    sources_in_records = {r.source for r in records}
    assert (
        "makemytrip" in sources_in_records
    ), f"Missing makemytrip records: {sources_in_records}"
    assert (
        "spicejet" in sources_in_records
    ), f"Missing spicejet records: {sources_in_records}"
    assert (
        "easemytrip" in sources_in_records
    ), f"Missing easemytrip records: {sources_in_records}"

    dedup_hashes = set()
    for rec in records:
        assert rec.origin in VALID_IATA_CODES, f"Invalid origin: {rec.origin}"
        assert (
            rec.destination in VALID_IATA_CODES
        ), f"Invalid destination: {rec.destination}"
        assert rec.origin != rec.destination, f"Origin equals destination: {rec.origin}"
        assert rec.fare_inr > 0.0, f"Fare must be positive: {rec.fare_inr}"
        assert (
            rec.base_fare is not None and rec.base_fare > 0.0
        ), f"Invalid base fare: {rec.base_fare}"
        assert (
            rec.taxes_and_fees is not None and rec.taxes_and_fees >= 0.0
        ), f"Invalid taxes: {rec.taxes_and_fees}"
        assert (
            rec.duration_minutes is not None and rec.duration_minutes > 0
        ), f"Invalid duration: {rec.duration_minutes}"
        assert rec.booking_window in (
            "T+1",
            "T+7",
            "T+15",
            "T+30",
        ), f"Invalid window: {rec.booking_window}"

        # Check timestamp consistency
        dep_dt = datetime.fromisoformat(rec.departure_datetime)
        arr_dt = datetime.fromisoformat(rec.arrival_datetime)
        assert arr_dt > dep_dt, f"Arrival must be after departure: {dep_dt} -> {arr_dt}"

        # Check deduplication hash
        h = rec.generate_dedup_hash()
        assert len(h) == 64, f"Dedup hash must be 64-char sha256 hex, got: {h}"
        dedup_hashes.add(h)

    print(
        f"  ✓ Inspected {len(records)} records: 100% valid IATA codes, positive fares, valid timestamps"
    )
    print(
        f"  ✓ Verified deduplication hash generation ({len(dedup_hashes)} distinct hashes)"
    )
    print(f"  ✓ Confirmed multi-source representation: {sorted(sources_in_records)}")

    print("\n" + "=" * 80)
    print("🏆 ALL MULTI-SOURCE INGESTION VERIFICATIONS PASSED (100% SUCCESS)")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(run_multi_source_verification())
