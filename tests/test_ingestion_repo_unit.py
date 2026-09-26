"""Unit tests for APIx Ingestion Repository."""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.ingestion_repo import (
    IngestionRepo,
    bulk_insert_raw_fares,
    cleanup_old_raw_fares,
    compute_dedup_hash,
    count_raw_fares,
    create_scraping_run,
    get_raw_fares,
    get_raw_fares_for_calculation,
    get_scraping_run,
    update_scraping_run,
)
from backend.app.db.session import Base
from backend.app.models.index import NationalDailyIndex, RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.scraping import ScrapingRun


class TestIngestionRepo(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.repo = IngestionRepo(self.db)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_compute_dedup_hash(self):
        h1 = compute_dedup_hash(
            "6E", "6E-205", "DEL", "BOM", "2026-10-01T06:00:00", "T+7"
        )
        h2 = compute_dedup_hash(
            "6e", "6E-205", "del", "bom", "2026-10-01T06:00:00", "T+7"
        )
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_bulk_insert_and_idempotency(self):
        records = [
            {
                "batch_id": "b1",
                "origin": "DEL",
                "destination": "BOM",
                "flight_date": date(2026, 10, 1),
                "booking_window": "T+7",
                "airline_code": "6E",
                "flight_number": "6E-101",
                "total_fare": 4500.0,
                "source_platform": "synthetic",
            },
            {
                "batch_id": "b1",
                "origin": "BOM",
                "destination": "DEL",
                "flight_date": date(2026, 10, 1),
                "booking_window": "T+7",
                "airline_code": "AI",
                "flight_number": "AI-202",
                "total_fare": 5200.0,
                "source_platform": "synthetic",
            },
        ]

        # Initial insert
        res1 = self.repo.bulk_insert(records)
        self.assertEqual(res1["received"], 2)
        self.assertEqual(res1["inserted"], 2)
        self.assertEqual(res1["duplicates"], 0)
        self.assertEqual(self.repo.count(), 2)

        # Re-insert should be 100% idempotent
        res2 = self.repo.bulk_insert(records)
        self.assertEqual(res2["received"], 2)
        self.assertEqual(res2["inserted"], 0)
        self.assertEqual(res2["duplicates"], 2)
        self.assertEqual(self.repo.count(), 2)

    def test_scraping_run_telemetry(self):
        run = self.repo.create_run(
            batch_id="run-test-1",
            source_platform="synthetic",
            status="RUNNING",
            routes_attempted=5,
        )
        self.assertEqual(run.batch_id, "run-test-1")
        self.assertEqual(run.status, "RUNNING")

        updated = self.repo.update_run(
            batch_id="run-test-1",
            status="COMPLETED",
            routes_succeeded=5,
            fares_collected=100,
            fares_deduplicated=95,
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, "COMPLETED")
        self.assertEqual(updated.fares_collected, 100)
        self.assertEqual(updated.fares_deduplicated, 95)
        self.assertIsNotNone(updated.duration_seconds)

    def test_cleanup_retention_and_index_preservation(self):
        now = datetime.now(UTC)
        today = date.today()

        # Add recent record
        self.repo.bulk_insert(
            [
                {
                    "origin": "DEL",
                    "destination": "BOM",
                    "flight_date": today,
                    "booking_window": "T+1",
                    "airline_code": "6E",
                    "flight_number": "6E-500",
                    "total_fare": 4000.0,
                    "scraped_at": now,
                }
            ]
        )

        # Add old record (120 days old)
        self.repo.bulk_insert(
            [
                {
                    "origin": "DEL",
                    "destination": "BOM",
                    "flight_date": today - timedelta(days=120),
                    "booking_window": "T+1",
                    "airline_code": "6E",
                    "flight_number": "6E-501",
                    "total_fare": 4200.0,
                    "scraped_at": now - timedelta(days=120),
                }
            ]
        )

        # Add route daily index
        route_idx = RouteDailyIndex(
            origin="DEL",
            destination="BOM",
            index_date=today - timedelta(days=120),
            booking_window="T+1",
            index_type="geometric_mean",
            index_value=105.0,
            mean_fare=4200.0,
            sample_size=10,
        )
        self.db.add(route_idx)
        self.db.commit()

        self.assertEqual(self.repo.count(), 2)
        pruned = self.repo.cleanup_old_fares(days=90)
        self.assertEqual(pruned, 1)
        self.assertEqual(self.repo.count(), 1)

        # Assert RouteDailyIndex was not deleted
        idx_count = self.db.scalar(select(func.count(RouteDailyIndex.id)))
        self.assertEqual(idx_count, 1)

    def test_get_fares_for_calculation(self):
        flight_date = date(2026, 11, 15)
        records = [
            {
                "origin": "DEL",
                "destination": "BOM",
                "flight_date": flight_date,
                "booking_window": "T+7",
                "airline_code": "6E",
                "flight_number": "6E-101",
                "total_fare": 4800.0,
            },
            {
                "origin": "DEL",
                "destination": "BOM",
                "flight_date": flight_date,
                "booking_window": "T+7",
                "airline_code": "AI",
                "flight_number": "AI-202",
                "total_fare": 4200.0,
            },
            {
                "origin": "BLR",
                "destination": "DEL",
                "flight_date": flight_date,
                "booking_window": "T+7",
                "airline_code": "QP",
                "flight_number": "QP-303",
                "total_fare": 3900.0,
            },
        ]
        self.repo.bulk_insert(records)

        calc_fares = self.repo.get_fares_for_calculation(
            origin="DEL",
            destination="BOM",
            booking_window="T+7",
            calculation_date=flight_date,
        )
        self.assertEqual(len(calc_fares), 2)
        # Verify sorted ascending by total_fare
        self.assertEqual(calc_fares[0].total_fare, 4200.0)
        self.assertEqual(calc_fares[1].total_fare, 4800.0)


if __name__ == "__main__":
    unittest.main()
