"""Integration test for live airfare ingestion into apix.db.

Verifies:
1. Live fare extraction runs and produces genuine flight fare records.
2. Verified live quotes are inserted into apix.db.
3. Database query confirms at least one row with is_synthetic == 0 exists.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend.app.core.config import settings
from backend.app.db.session import Base
from backend.app.main import app
from ingestion.client import IngestionClient
from ingestion.config import BOOKING_WINDOWS, IngestionConfig, Route
from ingestion.orchestrator import IngestionOrchestrator


class LocalTestClientIngestionClient(IngestionClient):
    """Routes requests directly through FastAPI TestClient."""

    def __init__(self, test_app, config=None) -> None:
        super().__init__(config=config)
        self._test_client = TestClient(test_app)

    def _post_with_urllib(self, payload: dict) -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-Ingestion-Key": self.ingestion_key,
        }
        resp = self._test_client.post(
            "/api/v1/ingestion/batch", json=payload, headers=headers
        )
        if resp.status_code != 200:
            raise RuntimeError(f"FastAPI TestClient returned {resp.status_code}: {resp.text}")
        return resp.json()

    def _post_with_httpx(self, payload: dict) -> dict:
        return self._post_with_urllib(payload)


def test_live_fare_ingestion_stores_non_synthetic_record_in_db() -> None:
    """Verifies that running live ingestion stores at least one is_synthetic == 0 row in apix.db."""
    db_path = os.path.abspath("apix.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)

    config = IngestionConfig(
        ingestion_mode="live",
        ingestion_key=settings.INGESTION_API_KEY,
    )
    client = LocalTestClientIngestionClient(app, config=config)
    orchestrator = IngestionOrchestrator(
        config=config,
        client=client,
        scraper_source="spicejet",
        jitter_range=(0.0, 0.0),
    )

    route = Route(
        origin="DEL",
        destination="BOM",
        distance_km=1148,
        typical_duration_min=135,
        dgca_weight=0.18,
    )
    window = BOOKING_WINDOWS[0]
    target_date = datetime.now(UTC).date() + timedelta(days=1)

    # Execute scrape for slot in live mode
    res = orchestrator.scrape_slot(
        route,
        window_code=window,
        target_date=target_date,
        scraper_source="spicejet",
    )
    assert res.success, f"Live scrape failed: {res.errors}"
    assert len(res.records) > 0, "No records returned from live scrape"

    # Verify at least one record has is_synthetic is False
    live_records = [r for r in res.records if not r.is_synthetic]
    assert len(live_records) > 0, "All scraped records were marked synthetic"

    # Post batch to database via backend ingestion API
    batch_id = f"batch-live-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    resp = client.post_batch(live_records, source="spicejet", batch_id=batch_id)
    assert resp.get("status") in ("success", "partial"), f"Batch post failed: {resp}"

    # Query apix.db directly via sqlite3 to confirm is_synthetic == 0 in persistent storage
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT count(*) FROM raw_fares WHERE is_synthetic = 0")
    row_count = cur.fetchone()[0]
    con.close()

    assert row_count >= 1, (
        f"Expected at least one row in apix.db with is_synthetic == 0, got {row_count}"
    )


def test_apix_db_has_at_least_one_non_synthetic_row() -> None:
    """Acceptance criterion query: apix.db must contain at least one is_synthetic == 0 record."""
    db_path = os.path.abspath("apix.db")
    assert os.path.exists(db_path), f"Database file does not exist at {db_path}"

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        "SELECT id, airline_code, flight_number, origin, destination, total_fare, source_platform, is_synthetic FROM raw_fares WHERE is_synthetic = 0 LIMIT 5"
    )
    rows = cur.fetchall()
    con.close()

    assert len(rows) >= 1, (
        f"Expected at least one row with is_synthetic == 0 in {db_path}, found {len(rows)}"
    )
