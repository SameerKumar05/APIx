"""Unit test suite for APIx Cycle 3 Multi-Source Crawlers and Orchestrator.

Validates:
1. MakeMyTripScraper:
   - Dynamic route URL construction
   - API endpoint detection (is_flight_api_url)
   - Stealth browser context generation
   - JSON response parsing into RawFareRecord
   - Fallback hierarchy (Tier 1 -> Tier 2 -> Tier 3)
2. SpiceJetScraper:
   - Dynamic route URL construction
   - Header randomization and browser spoofing
   - Navitaire and standard JSON availability parsing
   - Fallback hierarchy calibrated to SpiceJet (SG)
3. IngestionOrchestrator:
   - Multi-source scraper coordination (MakeMyTrip, SpiceJet, EaseMyTrip)
   - Route and booking window alias resolution (e.g. '1-3d' -> 'T+1')
   - Aggregated multi-source slot execution
   - Summary telemetry artifact generation
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from typing import Any

worktree_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if worktree_root not in sys.path:
    sys.path.insert(0, worktree_root)

from ingestion.base import (
    SYSTEM_CHROMIUM_CANDIDATES,
    BaseScraper,
    RawFareRecord,
    ScrapeResult,
)
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
from ingestion.orchestrator import (
    IngestionOrchestrator,
    OrchestratorRunSummary,
    SlotResultSummary,
)


class TestMakeMyTripScraper(unittest.TestCase):
    """Unit tests for MakeMyTrip scraper implementation."""

    def setUp(self) -> None:
        self.config = IngestionConfig(ingestion_mode="synthetic")
        self.scraper = MakeMyTripScraper(config=self.config)
        self.target_date = date(2026, 9, 25)

    def test_build_search_url_dynamic_parameters(self) -> None:
        """Verifies dynamic route parameter formatting for MakeMyTrip search URL."""
        url = self.scraper.build_search_url(
            origin="del",
            destination="bom",
            flight_date=self.target_date,
            cabin_class="E",
            adults=1,
        )
        self.assertIn("makemytrip.com/flight/search", url)
        self.assertIn("itinerary=DEL-BOM-25/09/2026", url)
        self.assertIn("tripType=O", url)
        self.assertIn("paxType=A-1_C-0_I-0", url)
        self.assertIn("cabinClass=E", url)

    def test_is_flight_api_url_matching(self) -> None:
        """Verifies accurate detection of MakeMyTrip flight pricing API endpoints."""
        valid_urls = [
            "https://www.makemytrip.com/flight/search/v2/flights",
            "https://www.makemytrip.com/air-search-service/search",
            "https://www.makemytrip.com/api/flight/search/DEL-BOM",
            "https://www.makemytrip.com/search-summary/flightList",
            "https://www.makemytrip.com/get-flight-details?id=123",
            "https://www.makemytrip.com/flights/v1/search",
        ]
        invalid_urls = [
            "https://www.makemytrip.com/hotel/listing",
            "https://www.makemytrip.com/static/js/bundle.js",
            "https://www.makemytrip.com/images/logo.png",
            "https://google-analytics.com/collect",
        ]
        for url in valid_urls:
            self.assertTrue(self.scraper.is_flight_api_url(url), f"Should match: {url}")
        for url in invalid_urls:
            self.assertFalse(
                self.scraper.is_flight_api_url(url), f"Should not match: {url}"
            )

    def test_stealth_playwright_context_options(self) -> None:
        """Verifies stealth browser context options for MakeMyTrip."""
        opts = self.scraper.get_playwright_context_options()
        self.assertEqual(opts["locale"], "en-IN")
        self.assertEqual(opts["timezone_id"], "Asia/Kolkata")
        self.assertEqual(opts["geolocation"]["latitude"], 28.6139)
        self.assertTrue(opts["java_script_enabled"])
        self.assertTrue(opts["ignore_https_errors"])
        self.assertIn("viewport", opts)
        self.assertIn("user_agent", opts)
        self.assertIn("Accept-Language", opts["extra_http_headers"])

    def test_parse_flight_json_various_payload_structures(self) -> None:
        """Tests parsing realistic MakeMyTrip flight search JSON payloads."""
        mock_payload = {
            "flights": [
                {
                    "airlineCode": "6E",
                    "flightNumber": "6E-532",
                    "departureTime": "2026-09-25T06:00:00",
                    "arrivalTime": "2026-09-25T08:15:00",
                    "totalFare": 4500.0,
                    "duration": 135,
                    "stops": 0,
                    "fareDetails": {"baseFare": 3510.0, "tax": 990.0},
                },
                {
                    "airline": {"code": "AI"},
                    "flightNo": "804",
                    "depTime": "2026-09-25T09:30:00",
                    "arrTime": "2026-09-25T11:45:00",
                    "fare": 5200.0,
                    "durationMinutes": 135,
                    "stops": 0,
                },
            ]
        }

        records = self.scraper.parse_flight_json(
            payload=mock_payload,
            origin="DEL",
            destination="BOM",
            window_code="T+1",
        )

        self.assertEqual(len(records), 2)

        # Check record 1
        rec1 = records[0]
        self.assertEqual(rec1.airline_code, "6E")
        self.assertEqual(rec1.flight_number, "6E-532")
        self.assertEqual(rec1.origin, "DEL")
        self.assertEqual(rec1.destination, "BOM")
        self.assertEqual(rec1.fare_inr, 4500.0)
        self.assertEqual(rec1.source, "makemytrip")
        self.assertEqual(rec1.booking_window, "T+1")
        self.assertEqual(rec1.duration_minutes, 135)
        self.assertEqual(rec1.stops, 0)
        self.assertFalse(rec1.is_synthetic)
        self.assertIsNotNone(rec1.generate_dedup_hash())

        # Check record 2
        rec2 = records[1]
        self.assertEqual(rec2.airline_code, "AI")
        self.assertEqual(rec2.flight_number, "AI-804")
        self.assertEqual(rec2.fare_inr, 5200.0)
        self.assertEqual(rec2.source, "makemytrip")

    def test_parse_flight_json_empty_and_malformed(self) -> None:
        """Verifies graceful handling of empty or malformed payloads."""
        self.assertEqual(self.scraper.parse_flight_json({}, "DEL", "BOM", "T+1"), [])
        self.assertEqual(
            self.scraper.parse_flight_json(
                {"flights": "not-a-list"}, "DEL", "BOM", "T+1"
            ),
            [],
        )
        self.assertEqual(
            self.scraper.parse_flight_json({"flights": [{}]}, "DEL", "BOM", "T+1"), []
        )

    def test_scrape_route_fallback_synthetic_mode(self) -> None:
        """Tests that synthetic mode returns DGCA synthetic records for MakeMyTrip."""
        result = self.scraper.scrape_route(
            origin="DEL",
            destination="BOM",
            target_date=self.target_date,
            window_code="T+7",
        )
        self.assertTrue(result.success)
        self.assertGreater(len(result.records), 0)
        self.assertEqual(result.metadata["tier"], 3)
        self.assertEqual(result.metadata["source"], "makemytrip_tier3_synthetic")
        for rec in result.records:
            self.assertEqual(rec.origin, "DEL")
            self.assertEqual(rec.destination, "BOM")
            self.assertGreater(rec.fare_inr, 0.0)

    def test_scrape_all_returns_all_slots(self) -> None:
        """Tests scrape_all across routes and windows."""
        results = self.scraper.scrape_all(
            routes=[DEFAULT_ROUTES[0]],
            windows=[BOOKING_WINDOWS[0]],
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)


class TestSpiceJetScraper(unittest.TestCase):
    """Unit tests for SpiceJet direct airline crawler implementation."""

    def setUp(self) -> None:
        self.config = IngestionConfig(ingestion_mode="synthetic")
        self.scraper = SpiceJetScraper(config=self.config)
        self.target_date = date(2026, 9, 25)

    def test_build_search_url_dynamic_parameters(self) -> None:
        """Verifies SpiceJet search URL generation."""
        url = self.scraper.build_search_url(
            origin="del",
            destination="bom",
            flight_date=self.target_date,
            adults=1,
        )
        self.assertIn("spicejet.com/search", url)
        self.assertIn("from=DEL", url)
        self.assertIn("to=BOM", url)
        self.assertIn("departure=2026-09-25", url)
        self.assertIn("tripType=1", url)

    def test_is_flight_api_url_matching(self) -> None:
        """Verifies SpiceJet API pattern detection."""
        valid_urls = [
            "https://api.spicejet.com/v1/flight/search",
            "https://www.spicejet.com/api/v2/flight/availability",
            "https://booking.spicejet.com/api/searchFlight",
            "https://www.spicejet.com/getAvailability",
        ]
        invalid_urls = [
            "https://www.spicejet.com/deals",
            "https://www.spicejet.com/assets/img/logo.svg",
            "https://google-analytics.com/analytics.js",
        ]
        for url in valid_urls:
            self.assertTrue(self.scraper.is_flight_api_url(url), f"Should match: {url}")
        for url in invalid_urls:
            self.assertFalse(
                self.scraper.is_flight_api_url(url), f"Should not match: {url}"
            )

    def test_get_randomized_headers(self) -> None:
        """Verifies randomized headers contain realistic browser headers."""
        headers = self.scraper.get_randomized_headers()
        self.assertIn("User-Agent", headers)
        self.assertIn("Accept", headers)
        self.assertIn("Accept-Language", headers)
        self.assertIn("Sec-Ch-Ua", headers)
        self.assertEqual(headers["Referer"], "https://www.spicejet.com/")
        self.assertEqual(headers["Origin"], "https://www.spicejet.com")
        self.assertEqual(headers["X-Channel"], "WEB")

    def test_parse_flight_json_navitaire_and_standard_formats(self) -> None:
        """Tests parsing SpiceJet Navitaire/NewSkies structure."""
        navitaire_payload = {
            "trips": [
                {
                    "journeys": [
                        {
                            "segments": [
                                {
                                    "airlineCode": "SG",
                                    "flightNumber": "8169",
                                    "departureTime": "2026-09-25T07:15:00",
                                    "arrivalTime": "2026-09-25T09:30:00",
                                    "fare": 3890.0,
                                    "duration": 135,
                                }
                            ],
                            "totalFare": 3890.0,
                            "stops": 0,
                        }
                    ]
                }
            ]
        }

        records = self.scraper.parse_flight_json(
            payload=navitaire_payload,
            origin="DEL",
            destination="BOM",
            window_code="T+1",
        )

        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec.airline_code, "SG")
        self.assertEqual(rec.flight_number, "SG-8169")
        self.assertEqual(rec.origin, "DEL")
        self.assertEqual(rec.destination, "BOM")
        self.assertEqual(rec.fare_inr, 3890.0)
        self.assertEqual(rec.source, "spicejet")
        self.assertEqual(rec.booking_window, "T+1")
        self.assertEqual(rec.duration_minutes, 135)
        self.assertEqual(rec.stops, 0)

    def test_parse_flight_json_live_availability_shape(self) -> None:
        """The live /api/v3/search/availability payload must yield real records.

        The itinerary lives under data.trips[].journeysAvailable and the money
        under data.faresAvailable keyed by the journey's opaque fare keys; the
        generic branches do not look there, so this shape is read explicitly.
        """
        fare_key = "opaque-fare-key"
        payload = {
            "data": {
                "currencyCode": "INR",
                "trips": [
                    {
                        "journeysAvailable": [
                            {
                                "designator": {
                                    "origin": "DEL",
                                    "destination": "BOM",
                                    "departure": "2026-10-05T19:55:00",
                                    "arrival": "2026-10-05T22:40:00",
                                },
                                "carrierString": "SG 162",
                                "stops": 0,
                                "segments": [
                                    {
                                        "identifier": {
                                            "carrierCode": "SG",
                                            "identifier": "162",
                                        }
                                    }
                                ],
                                "fares": {
                                    fare_key: {
                                        "classOfService": "U",
                                        "availableCount": 1,
                                    }
                                },
                            }
                        ]
                    }
                ],
                "faresAvailable": {
                    fare_key: {
                        "passengerFares": [
                            {
                                "passengerType": "ADT",
                                "fareAmount": 6447,
                                "publishedFare": 4900,
                                "revenueFare": 4900,
                                "serviceCharges": [
                                    {"amount": 4900, "code": None, "type": 0},
                                    {"amount": 100, "code": "RCS", "type": 4},
                                    {"amount": 85, "code": "TRF", "type": 4},
                                    {"amount": 599, "code": "YQ", "type": 4},
                                    {"amount": 236, "code": "ASF", "type": 4},
                                    {"amount": 152, "code": "UDF", "type": 4},
                                    {"amount": 89, "code": "AAT", "type": 4},
                                    {"amount": 286, "code": None, "type": 5},
                                ],
                            }
                        ]
                    }
                },
            }
        }

        records = self.scraper.parse_flight_json(
            payload=payload,
            origin="DEL",
            destination="BOM",
            window_code="T+7",
        )

        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertFalse(rec.is_synthetic)
        self.assertEqual(rec.source_platform, "spicejet")
        self.assertEqual(rec.source, "spicejet")
        self.assertEqual(rec.flight_number, "SG-162")
        self.assertEqual(rec.origin, "DEL")
        self.assertEqual(rec.destination, "BOM")
        self.assertEqual(rec.departure_datetime, "2026-10-05T19:55:00")
        self.assertEqual(rec.arrival_datetime, "2026-10-05T22:40:00")
        self.assertEqual(rec.fare_inr, 6447.0)
        self.assertEqual(rec.base_fare, 4900.0)
        self.assertEqual(rec.taxes_and_fees, 1395.0)
        self.assertEqual(rec.fare_split_basis, "measured")
        self.assertEqual(rec.booking_class, "U")
        self.assertEqual(rec.udf_fee, 152.0)
        self.assertEqual(rec.base_fare + rec.taxes_and_fees + rec.udf_fee, rec.fare_inr)
        self.assertEqual(rec.booking_window, "T+7")
        self.assertEqual(rec.duration_minutes, 165)
        is_valid, errors = self.scraper.validate_record(rec)
        self.assertTrue(is_valid, errors)

    def test_parse_flight_json_availability_rejects_non_inr(self) -> None:
        """A non-INR availability payload must not be recorded as INR fares."""
        payload = {
            "data": {
                "currencyCode": "USD",
                "trips": [],
                "faresAvailable": {},
            }
        }
        records = self.scraper.parse_flight_json(
            payload=payload,
            origin="DEL",
            destination="BOM",
            window_code="T+7",
        )
        self.assertEqual(records, [])

    def test_scrape_route_fallback_synthetic_spicejet(self) -> None:
        """Tests that synthetic mode generates SpiceJet (SG) calibrated records."""
        result = self.scraper.scrape_route(
            origin="DEL",
            destination="BOM",
            target_date=self.target_date,
            window_code="T+7",
        )
        self.assertTrue(result.success)
        self.assertGreater(len(result.records), 0)
        self.assertEqual(result.metadata["tier"], 3)
        self.assertEqual(result.metadata["source"], "spicejet_tier3_synthetic")
        for rec in result.records:
            self.assertEqual(rec.airline_code, "SG")
            self.assertTrue(rec.flight_number.startswith("SG-"))
            self.assertEqual(rec.source, "spicejet")
            self.assertGreater(rec.fare_inr, 0.0)

    def test_scrape_all_returns_all_slots(self) -> None:
        """Tests scrape_all across routes and windows."""
        results = self.scraper.scrape_all(
            routes=[DEFAULT_ROUTES[0]],
            windows=[BOOKING_WINDOWS[0]],
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success)


class TestIngestionOrchestratorMultiSource(unittest.TestCase):
    """Unit tests for IngestionOrchestrator multi-source aggregation and slot coordination."""

    def setUp(self) -> None:
        self.config = IngestionConfig(ingestion_mode="synthetic")
        self.orchestrator = IngestionOrchestrator(
            config=self.config,
            scraper_source="multi_source",
            jitter_range=(0.0, 0.0),
            session_recycle_every=5,
        )

    def test_crawler_registry_initialized(self) -> None:
        """Verifies all scrapers are present in the crawler registry."""
        registry = self.orchestrator.scrapers
        self.assertIn("easemytrip", registry)
        self.assertIn("makemytrip", registry)
        self.assertIn("spicejet", registry)
        self.assertIn("amadeus", registry)
        self.assertIn("synthetic", registry)
        self.assertIsInstance(registry["makemytrip"], MakeMyTripScraper)
        self.assertIsInstance(registry["spicejet"], SpiceJetScraper)
        self.assertIsInstance(registry["easemytrip"], EaseMyTripScraper)

    def test_run_slot_multi_source_aggregates_records(self) -> None:
        """Tests that run_slot in multi_source mode aggregates records across scrapers."""
        route = DEFAULT_ROUTES[0]
        window = BOOKING_WINDOWS[0]
        scrape_res, summary = self.orchestrator.run_slot(route, window, slot_index=0)

        self.assertTrue(scrape_res.success)
        self.assertTrue(summary.success)
        self.assertEqual(summary.route, "DEL-BOM")
        self.assertEqual(summary.booking_window, "T+1")
        self.assertEqual(summary.source_platform, "multi_source")
        self.assertGreater(summary.records_count, 0)

        # Verify records come from multiple sources
        sources_found = {r.source for r in scrape_res.records}
        self.assertIn("makemytrip", sources_found)
        self.assertIn("spicejet", sources_found)
        self.assertIn("easemytrip", sources_found)

    def test_scrape_slot_with_string_inputs_and_window_alias(self) -> None:
        """Tests scrape_slot convenience method with origin-destination strings and window aliases."""
        # Test alias '1-3d' -> T+1
        res1 = self.orchestrator.scrape_slot(
            origin="DEL",
            destination="BOM",
            window_code="1-3d",
        )
        self.assertTrue(res1.success)
        self.assertGreater(len(res1.records), 0)

        # Test alias '4-7d' -> T+7
        res2 = self.orchestrator.scrape_slot(
            origin="BOM",
            destination="DEL",
            window_code="4-7d",
        )
        self.assertTrue(res2.success)
        self.assertGreater(len(res2.records), 0)

    def test_scrape_slot_with_route_object(self) -> None:
        """Tests scrape_slot with Route and BookingWindow objects."""
        route = DEFAULT_ROUTES[1]
        window = BOOKING_WINDOWS[1]
        res = self.orchestrator.scrape_slot(
            origin=route,
            window_code=window,
        )
        self.assertTrue(res.success)
        self.assertGreater(len(res.records), 0)

    def test_single_source_scraper_override(self) -> None:
        """Tests that specifying a single source (e.g. makemytrip) routes only to that scraper."""
        orch = IngestionOrchestrator(
            config=self.config,
            scraper_source="makemytrip",
            jitter_range=(0.0, 0.0),
        )
        route = DEFAULT_ROUTES[0]
        window = BOOKING_WINDOWS[0]
        scrape_res, summary = orch.run_slot(route, window, slot_index=0)

        self.assertTrue(scrape_res.success)
        self.assertEqual(summary.source_platform, "makemytrip_tier3_synthetic")
        for rec in scrape_res.records:
            self.assertEqual(rec.source, "makemytrip")

    def test_orchestrator_dry_run_multi_source_all_slots(self) -> None:
        """Tests a full routes x windows dry run in multi-source mode."""
        summary = self.orchestrator.run_all_slots(dry_run=True)
        expected_slots = len(DEFAULT_ROUTES) * len(BOOKING_WINDOWS)
        self.assertEqual(summary.total_slots, expected_slots)
        self.assertEqual(summary.successful_slots, expected_slots)
        self.assertEqual(summary.failed_slots, 0)
        self.assertEqual(summary.backend_status, "skipped_dry_run")
        self.assertEqual(len(summary.slots), len(DEFAULT_ROUTES) * len(BOOKING_WINDOWS))
        self.assertGreater(summary.total_records_collected, 400)


if __name__ == "__main__":
    unittest.main()


def test_resolve_launch_kwargs_prefers_executable_system_chromium():
    """Akamai resets the bundled Playwright Chromium over HTTP/2 but accepts the distro build."""
    import os

    from ingestion.config import IngestionConfig
    from ingestion.crawlers.makemytrip import resolve_launch_kwargs

    cfg = IngestionConfig(ingestion_mode="live", playwright_headless=True)
    kwargs = resolve_launch_kwargs(cfg)
    assert "headless" in kwargs and "args" in kwargs

    picked = kwargs.get("executable_path")
    if picked is not None:
        assert os.path.isfile(picked) and os.access(picked, os.X_OK), picked
    else:
        for candidate in SYSTEM_CHROMIUM_CANDIDATES:
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                raise AssertionError(
                    f"executable {candidate} exists but was not selected"
                )


def test_resolve_launch_kwargs_honours_explicit_override():
    import os
    import tempfile

    from ingestion.config import IngestionConfig
    from ingestion.crawlers.makemytrip import resolve_launch_kwargs

    with tempfile.NamedTemporaryFile(suffix=".chromium") as fake:
        os.chmod(fake.name, 0o755)
        cfg = IngestionConfig(
            ingestion_mode="live", playwright_browser_executable=fake.name
        )
        assert resolve_launch_kwargs(cfg)["executable_path"] == fake.name

    cfg = IngestionConfig(
        ingestion_mode="live", playwright_browser_executable="/nonexistent/chromium"
    )
    assert "executable_path" not in resolve_launch_kwargs(cfg)
