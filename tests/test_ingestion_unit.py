"""Unit tests for APIx Ingestion framework."""

import os
import sys
import unittest
from datetime import date, datetime

worktree_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if worktree_root not in sys.path:
    sys.path.insert(0, worktree_root)

from ingestion.base import BaseScraper, RawFareRecord
from ingestion.client import IngestionClient
from ingestion.config import (
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    IngestionConfig,
    VALID_IATA_CODES,
)
from ingestion.crawlers.amadeus import AmadeusFlightClient, parse_iso_duration
from ingestion.crawlers.easemytrip import EaseMyTripScraper
from ingestion.crawlers.synthetic import SyntheticFlightGenerator
from ingestion.orchestrator import IngestionOrchestrator

class TestIngestionConfig(unittest.TestCase):
    def test_default_routes_count_and_properties(self):
        self.assertEqual(len(DEFAULT_ROUTES), 10)
        total_weight = sum(r.dgca_weight for r in DEFAULT_ROUTES)
        self.assertAlmostEqual(total_weight, 1.0, places=2)
        for route in DEFAULT_ROUTES:
            self.assertIn(route.origin, VALID_IATA_CODES)
            self.assertIn(route.destination, VALID_IATA_CODES)
            self.assertNotEqual(route.origin, route.destination)
            self.assertGreater(route.distance_km, 500)
            self.assertGreater(route.typical_duration_min, 60)

    def test_booking_windows(self):
        codes = [w.code for w in BOOKING_WINDOWS]
        self.assertEqual(codes, ["T+1", "T+7", "T+15", "T+30", "T+45"])
        advances = [w.days_advance for w in BOOKING_WINDOWS]
        self.assertEqual(advances, [1, 7, 15, 30, 45])


class TestBaseScraperNormalizers(unittest.TestCase):
    def test_normalize_iata(self):
        self.assertEqual(BaseScraper.normalize_iata("del"), "DEL")
        self.assertEqual(BaseScraper.normalize_iata(" BOM "), "BOM")
        with self.assertRaises(ValueError):
            BaseScraper.normalize_iata("DE")
        with self.assertRaises(ValueError):
            BaseScraper.normalize_iata("DEL1")
        with self.assertRaises(ValueError):
            BaseScraper.normalize_iata("")

    def test_normalize_airline_code(self):
        self.assertEqual(BaseScraper.normalize_airline_code("6e"), "6E")
        self.assertEqual(BaseScraper.normalize_airline_code(" ai "), "AI")
        with self.assertRaises(ValueError):
            BaseScraper.normalize_airline_code("INDIGO")
        with self.assertRaises(ValueError):
            BaseScraper.normalize_airline_code("6")

    def test_normalize_fare(self):
        self.assertEqual(BaseScraper.normalize_fare(5420), 5420.0)
        self.assertEqual(BaseScraper.normalize_fare("₹ 6,450.50"), 6450.50)
        self.assertEqual(BaseScraper.normalize_fare("Rs. 4,800"), 4800.0)
        self.assertEqual(BaseScraper.normalize_fare("3999"), 3999.0)
        with self.assertRaises(ValueError):
            BaseScraper.normalize_fare(None)
        with self.assertRaises(ValueError):
            BaseScraper.normalize_fare(0)
        with self.assertRaises(ValueError):
            BaseScraper.normalize_fare(-100)
        with self.assertRaises(ValueError):
            BaseScraper.normalize_fare("free")

    def test_normalize_datetime(self):
        dt = datetime(2026, 9, 25, 14, 30, 0)
        self.assertEqual(BaseScraper.normalize_datetime(dt), "2026-09-25T14:30:00")
        self.assertEqual(
            BaseScraper.normalize_datetime("2026-09-25 14:30:00"),
            "2026-09-25T14:30:00",
        )
        self.assertEqual(
            BaseScraper.normalize_datetime("2026-09-25T14:30:00Z"),
            "2026-09-25T14:30:00",
        )

    def test_validate_record(self):
        scraper = SyntheticFlightGenerator()
        valid_rec = RawFareRecord(
            airline_code="6E",
            flight_number="6E-205",
            origin="DEL",
            destination="BOM",
            departure_datetime="2026-09-25T06:00:00",
            arrival_datetime="2026-09-25T08:10:00",
            booking_datetime="2026-09-24T06:00:00",
            fare_inr=5400.0,
            cabin_class="economy",
            stops=0,
            source="synthetic",
        )
        is_valid, errors = scraper.validate_record(valid_rec)
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

        # Invalid: arrival before departure
        invalid_rec = RawFareRecord(
            airline_code="6E",
            flight_number="6E-205",
            origin="DEL",
            destination="BOM",
            departure_datetime="2026-09-25T10:00:00",
            arrival_datetime="2026-09-25T08:10:00",
            booking_datetime="2026-09-24T06:00:00",
            fare_inr=5400.0,
        )
        is_valid_inv, errors_inv = scraper.validate_record(invalid_rec)
        self.assertFalse(is_valid_inv)
        self.assertTrue(any("must be after departure" in e for e in errors_inv))


class TestEaseMyTripScraper(unittest.TestCase):
    def setUp(self):
        self.scraper = EaseMyTripScraper()

    def test_build_search_url(self):
        url = self.scraper.build_search_url("DEL", "BOM", date(2026, 9, 25))
        self.assertIn("DEL-BOM-25/09/2026", url)
        self.assertTrue(url.startswith("https://flight.easemytrip.com"))

    def test_url_pattern_matcher(self):
        self.assertTrue(
            self.scraper.is_flight_api_url(
                "https://flight.easemytrip.com/Flight/GetFlightList"
            )
        )
        self.assertTrue(
            self.scraper.is_flight_api_url(
                "https://flight.easemytrip.com/api/flight/search?src=DEL"
            )
        )
        self.assertFalse(
            self.scraper.is_flight_api_url(
                "https://flight.easemytrip.com/static/js/bundle.js"
            )
        )

    def test_parse_flight_json(self):
        raw_payload = {
            "FlightDetails": [
                {
                    "AirlineCode": "6E",
                    "FlightNo": "504",
                    "DepTime": "2026-09-25T07:00:00",
                    "ArrTime": "2026-09-25T09:15:00",
                    "TotalFare": "₹ 5,820",
                    "Duration": 135,
                    "Stops": 0,
                },
                {
                    "AirlineCode": "AI",
                    "FlightNo": "804",
                    "DepTime": "2026-09-25T08:30:00",
                    "ArrTime": "2026-09-25T10:40:00",
                    "TotalFare": 6450.0,
                    "Duration": 130,
                    "Stops": 0,
                },
            ]
        }
        records = self.scraper.parse_flight_json(
            payload=raw_payload,
            origin="DEL",
            destination="BOM",
            window_code="T+1",
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].flight_number, "6E-504")
        self.assertEqual(records[0].fare_inr, 5820.0)
        self.assertEqual(records[1].flight_number, "AI-804")
        self.assertEqual(records[1].fare_inr, 6450.0)


class TestIngestionClient(unittest.TestCase):
    def setUp(self):
        self.client = IngestionClient(
            base_url="http://localhost:8000",
            ingestion_key="test-key",
        )

    def test_payload_formatting(self):
        rec = RawFareRecord(
            airline_code="6E",
            flight_number="6E-205",
            origin="DEL",
            destination="BOM",
            departure_datetime="2026-09-25T06:00:00",
            arrival_datetime="2026-09-25T08:10:00",
            booking_datetime="2026-09-24T06:00:00",
            fare_inr=5400.0,
        )
        payload = self.client._format_payload(
            records=[rec],
            source="test_source",
            batch_id="test-batch-123",
        )
        self.assertEqual(payload["batch_id"], "test-batch-123")
        self.assertEqual(payload["source"], "test_source")
        self.assertEqual(len(payload["records"]), 1)
        self.assertEqual(payload["records"][0]["flight_number"], "6E-205")
        self.assertEqual(payload["records"][0]["origin_iata"], "DEL")
        self.assertIn("hash_id", payload["records"][0])



class TestAmadeusFlightClient(unittest.TestCase):
    def setUp(self):
        self.client = AmadeusFlightClient(mock_mode=True)

    def test_parse_iso_duration(self):
        self.assertEqual(parse_iso_duration("PT2H15M"), 135)
        self.assertEqual(parse_iso_duration("PT1H"), 60)
        self.assertEqual(parse_iso_duration("PT45M"), 45)
        self.assertEqual(parse_iso_duration(""), 120)

    def test_amadeus_mock_scrape(self):
        res = self.client.scrape_route("DEL", "BOM", date(2026, 9, 25), "T+1")
        self.assertTrue(res.success)
        self.assertEqual(len(res.records), 8)
        self.assertEqual(res.metadata["tier"], 2)
        self.assertEqual(res.source, "amadeus")
        self.assertEqual(res.records[0].origin, "DEL")
        self.assertEqual(res.records[0].destination, "BOM")
        self.assertEqual(res.records[0].booking_window, "T+1")
        self.assertGreater(res.records[0].fare_inr, 0)


class TestIngestionOrchestrator(unittest.TestCase):
    def setUp(self):
        self.config = IngestionConfig(ingestion_mode="synthetic")
        self.orchestrator = IngestionOrchestrator(
            config=self.config,
            jitter_range=(0.0, 0.0),
            session_recycle_every=5,
        )

    def test_single_slot_execution(self):
        route = DEFAULT_ROUTES[0]
        window = BOOKING_WINDOWS[0]
        scrape_res, summary = self.orchestrator.run_slot(route, window, slot_index=0)
        self.assertTrue(scrape_res.success)
        self.assertTrue(summary.success)
        self.assertEqual(summary.route, "DEL-BOM")
        self.assertEqual(summary.booking_window, "T+1")
        self.assertGreater(summary.records_count, 0)

    def test_orchestrator_dry_run_all_slots(self):
        summary = self.orchestrator.run_all_slots(dry_run=True)
        expected_slots = len(DEFAULT_ROUTES) * len(BOOKING_WINDOWS)
        self.assertEqual(summary.total_slots, expected_slots)
        self.assertEqual(summary.successful_slots, expected_slots)
        self.assertEqual(summary.failed_slots, 0)
        self.assertGreater(summary.total_records_collected, 150)
        self.assertEqual(summary.backend_status, "skipped_dry_run")
        self.assertEqual(len(summary.slots), len(DEFAULT_ROUTES) * len(BOOKING_WINDOWS))

if __name__ == "__main__":
    unittest.main()
