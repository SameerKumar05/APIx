"""Integration tests for fare ingestion database persistence plumbing.

Verifies:
1. Ingestion batch API endpoint persists fare records with base_fare and taxes_and_fees.
2. Deduplication logic correctly detects duplicate records idempotently.
3. Conditional upsert updates synthetic records on price revision without errors.
4. Crawler honestly operates in fallback mode without fabricating live quotes.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.ingestion_repo import bulk_insert_raw_fares
from backend.app.db.session import Base
from backend.app.main import app
from backend.app.models.raw_fare import RawFare
from backend.app.schemas.ingestion import RawFareRecord
from ingestion.client import IngestionClient
from ingestion.config import BOOKING_WINDOWS, IngestionConfig, Route
from ingestion.crawlers.spicejet import SpiceJetScraper
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
            "/api/v1/ingestion/batch",
            headers=headers,
            json=payload,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"FastAPI TestClient returned {resp.status_code}: {resp.text}")
        return resp.json()

    def _post_with_httpx(self, payload: dict) -> dict:
        return self._post_with_urllib(payload)


@pytest.fixture(autouse=True)
def setup_test_db():
    """Ensures database tables exist and cleans up test rows afterward."""
    db_path = os.path.abspath("apix.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    yield
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("DELETE FROM raw_fares WHERE batch_id LIKE 'test-plumbing-%'")
        cur.execute("DELETE FROM scraping_runs WHERE batch_id LIKE 'test-plumbing-%'")
        con.commit()


def test_batch_ingestion_persists_fare_records_with_component_splits() -> None:
    """Verifies that batch ingestion stores component splits and staged fixtures accurately."""
    db_path = os.path.abspath("apix.db")
    config = IngestionConfig(
        ingestion_mode="mock",
        ingestion_key=settings.INGESTION_API_KEY,
    )
    client = LocalTestClientIngestionClient(app, config=config)

    scraper = SpiceJetScraper(config=config)
    target_date = datetime.now(UTC).date() + timedelta(days=7)
    fixtures = scraper.get_staged_fixtures(
        origin="DEL",
        destination="BOM",
        target_date=target_date,
        window_code="T+7",
    )

    assert len(fixtures) > 0
    first = fixtures[0]
    assert first.is_synthetic is True
    assert first.source_platform == "staged_fixture"
    assert first.base_fare is not None and first.base_fare > 0
    assert first.taxes_and_fees is not None and first.taxes_and_fees > 0
    assert round(first.base_fare + first.taxes_and_fees, 2) == first.total_fare

    batch_id = f"test-plumbing-split-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
    resp = client.post_batch(fixtures, source="spicejet", batch_id=batch_id)

    assert resp.get("status") in ("success", "partial")
    assert resp.get("inserted_count") == len(fixtures)
    assert resp.get("duplicate_count") == 0

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute(
            "SELECT flight_number, base_fare, taxes_and_fees, total_fare, is_synthetic, source_platform "
            "FROM raw_fares WHERE batch_id = ? ORDER BY flight_number",
            (batch_id,),
        )
        rows = cur.fetchall()

    assert len(rows) == len(fixtures)
    row_flight, row_base, row_tax, row_total, row_synthetic, row_platform = rows[0]
    fixture_map = {f.flight_number: f for f in fixtures}
    matched_fixture = fixture_map[row_flight]

    assert row_base == matched_fixture.base_fare
    assert row_tax == matched_fixture.taxes_and_fees
    assert row_total == matched_fixture.total_fare
    assert row_synthetic == 1
    assert row_platform == "staged_fixture"


def test_batch_ingestion_deduplication_is_idempotent() -> None:
    """Verifies that re-ingesting identical fare records is idempotent and does not create duplicate rows."""
    db_path = os.path.abspath("apix.db")
    config = IngestionConfig(
        ingestion_mode="mock",
        ingestion_key=settings.INGESTION_API_KEY,
    )
    client = LocalTestClientIngestionClient(app, config=config)

    scraper = SpiceJetScraper(config=config)
    target_date = datetime.now(UTC).date() + timedelta(days=1)
    fixtures = scraper.get_staged_fixtures(
        origin="BOM",
        destination="DEL",
        target_date=target_date,
        window_code="T+1",
    )

    batch_id_first = f"test-plumbing-dedup-1-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
    resp1 = client.post_batch(fixtures, source="spicejet", batch_id=batch_id_first)
    assert resp1.get("status") in ("success", "partial")
    assert resp1.get("inserted_count") == len(fixtures)

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("SELECT count(*) FROM raw_fares WHERE origin = 'BOM' AND destination = 'DEL'")
        count_first = cur.fetchone()[0]

    batch_id_second = f"test-plumbing-dedup-2-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
    resp2 = client.post_batch(fixtures, source="spicejet", batch_id=batch_id_second)
    assert resp2.get("status") in ("success", "partial")

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute("SELECT count(*) FROM raw_fares WHERE origin = 'BOM' AND destination = 'DEL'")
        count_second = cur.fetchone()[0]

    assert count_second == count_first, f"Expected idempotent storage without row duplication, got {count_second} vs {count_first}"

def test_upsert_raw_fares_conditional_update() -> None:
    """Verifies that conditional upsert logic updates synthetic fares upon fare revision."""
    db_path = os.path.abspath("apix.db")
    engine = create_engine(f"sqlite:///{db_path}")

    now_dt = datetime.now(UTC)
    now_str = now_dt.strftime("%Y-%m-%dT%H:%M:%S")
    flight_date_str = (now_dt.date() + timedelta(days=15)).strftime("%Y-%m-%d")
    batch_id = f"test-plumbing-upsert-{now_dt.strftime('%Y%m%d%H%M%S%f')}"

    initial_record = RawFareRecord(
        airline_code="SG",
        flight_number="SG-8999",
        origin="DEL",
        destination="BOM",
        departure_datetime=f"{flight_date_str}T08:00:00",
        arrival_datetime=f"{flight_date_str}T10:15:00",
        booking_datetime=now_str,
        fare_inr=5000.0,
        cabin_class="economy",
        stops=0,
        source="spicejet",
        booking_window="T+15",
        flight_date=flight_date_str,
        duration_minutes=135,
        base_fare=4100.0,
        taxes_and_fees=900.0,
        total_fare=5000.0,
        flight_status="scheduled",
        is_synthetic=True,
        source_platform="staged_fixture",
    )

    with Session(engine) as session:
        stats1 = bulk_insert_raw_fares(session, [initial_record], batch_id=batch_id, commit=True)
        assert stats1.get("inserted") == 1

        revised_record = RawFareRecord(
            airline_code="SG",
            flight_number="SG-8999",
            origin="DEL",
            destination="BOM",
            departure_datetime=f"{flight_date_str}T08:00:00",
            arrival_datetime=f"{flight_date_str}T10:15:00",
            booking_datetime=now_str,
            fare_inr=5250.0,
            cabin_class="economy",
            stops=0,
            source="spicejet",
            booking_window="T+15",
            flight_date=flight_date_str,
            duration_minutes=135,
            base_fare=4350.0,
            taxes_and_fees=900.0,
            total_fare=5250.0,
            flight_status="scheduled",
            is_synthetic=True,
            source_platform="staged_fixture",
        )

        stats2 = bulk_insert_raw_fares(session, [revised_record], batch_id=batch_id, commit=True)
        assert stats2.get("received") == 1

        stmt = select(RawFare).where(RawFare.flight_number == "SG-8999", RawFare.batch_id == batch_id)
        updated_row = session.scalars(stmt).first()
        assert updated_row is not None
        assert updated_row.total_fare == 5250.0
        assert updated_row.base_fare == 4350.0
        assert updated_row.taxes_and_fees == 900.0
        assert updated_row.is_synthetic is True


def test_crawler_honestly_reports_fallback_without_fabricating_live_quotes() -> None:
    """Verifies that scraper fallback sets is_synthetic=True and produces zero fake live quotes."""
    config = IngestionConfig(
        ingestion_mode="mock",
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

    res = orchestrator.scrape_slot(
        route,
        window_code=window,
        target_date=target_date,
        scraper_source="spicejet",
    )

    assert res.success is True
    assert len(res.records) > 0

    fake_live_quotes = [r for r in res.records if not r.is_synthetic]
    assert len(fake_live_quotes) == 0, f"Found {len(fake_live_quotes)} records claiming is_synthetic=False in fallback"

    for r in res.records:
        assert r.is_synthetic is True
        assert r.source_platform in ("staged_fixture", "synthetic_dgca", "synthetic", "amadeus")
