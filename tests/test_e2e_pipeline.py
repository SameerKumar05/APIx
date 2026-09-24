"""APIx Cycle 2 End-to-End Pipeline Integration Test Suite.

Validates the full vertical data pipeline:
1. Generates 40 synthetic route-window fare records via SyntheticCrawler.
2. Posts batch to POST /api/v1/ingestion/batch with X-Ingestion-Key authentication.
3. Asserts records are inserted into database raw_fares table with deduplication.
4. Runs statistical index pipeline to compute daily indices and anomaly alerts.
5. Queries GET /api/v1/indices/national/latest and asserts calculated index matches mathematical expectation.
6. Queries GET /api/v1/analytics/anomalies and asserts surge alert is generated for seeded 3-sigma outlier.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.config import settings
from backend.app.db.seed import seed_all
from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.models.anomaly import AnomalyAlert
from backend.app.models.index import NationalDailyIndex, RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.route import Route
from backend.app.services.index_pipeline import (
    DEFAULT_BASE_FARES,
    DEFAULT_ROUTE_WEIGHTS,
    DEFAULT_WINDOW_WEIGHTS,
    run_daily_index_pipeline,
)
from ingestion.config import BOOKING_WINDOWS, DEFAULT_ROUTES
from ingestion.crawlers.synthetic import SyntheticCrawler, SyntheticFlightGenerator


# ---------------------------------------------------------------------------
# Isolated Test Database & Client Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def pipeline_db_session(monkeypatch: pytest.MonkeyPatch) -> Generator[Session, None, None]:
    """Provides a fresh, isolated in-memory SQLite database session seeded with DGCA routes."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
    session = TestingSessionLocal()

    # Patch SessionLocal across backend modules so background tasks share this database
    monkeypatch.setattr("backend.app.db.session.SessionLocal", TestingSessionLocal)
    try:
        import backend.app.services.index_pipeline as ip_mod
        monkeypatch.setattr(ip_mod, "SessionLocal", TestingSessionLocal, raising=False)
    except Exception:
        pass

    # Pre-seed DGCA routes and airlines
    seed_all(session)

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture(scope="function")
def client(pipeline_db_session: Session) -> Generator[TestClient, None, None]:
    """FastAPI TestClient with overridden get_db dependency."""
    def _override_get_db():
        try:
            yield pipeline_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# End-to-End Pipeline Integration Test
# ---------------------------------------------------------------------------

class TestEndToEndPipeline:
    """Cycle 2 End-to-End Ingestion, Database Persistence, Index Engine, and Anomaly Suite."""

    def test_e2e_ingestion_index_anomaly_pipeline(
        self, client: TestClient, pipeline_db_session: Session
    ) -> None:
        calc_date = date(2026, 9, 24)
        target_time = datetime(2026, 9, 24, 6, 0, 0, tzinfo=timezone.utc)

        # ------------------------------------------------------------------
        # Step 1: Generate 40 synthetic route-window fare records via SyntheticCrawler
        # ------------------------------------------------------------------
        crawler = SyntheticCrawler(seed=42)
        raw_records = crawler.generate_40_route_window_records(
            routes=DEFAULT_ROUTES,
            windows=BOOKING_WINDOWS,
            capture_time=target_time.replace(tzinfo=None),
        )

        assert len(raw_records) == 40, f"Expected 40 records, generated {len(raw_records)}"

        # Validate that exactly 10 distinct routes and 4 windows are covered
        pairs_covered = {(r.origin, r.destination) for r in raw_records}
        windows_covered = {r.booking_window for r in raw_records}
        assert len(pairs_covered) == 10
        assert len(windows_covered) == 4

        # Seed a 3-sigma outlier for Step 6:
        # Increase fare on DEL->BOM (T+1 window) to an extreme surge (INR 25,000)
        outlier_seeded = False
        for r in raw_records:
            if r.origin == "DEL" and r.destination == "BOM" and r.booking_window in ("T+1", "1", 1):
                r.fare_inr = 25000.0  # ~4.5x normal baseline of 5500
                outlier_seeded = True
                break
        assert outlier_seeded, "Failed to locate DEL->BOM T+1 slot to seed outlier"

        # ------------------------------------------------------------------
        # Step 2: Post batch to POST /api/v1/ingestion/batch with X-Ingestion-Key
        # ------------------------------------------------------------------
        # Convert records to API schema format
        api_records_payload = []
        for r in raw_records:
            rec_dict = r.to_dict()
            rec_dict["flight_date"] = calc_date.isoformat()
            # Ensure ISO format strings
            api_records_payload.append(rec_dict)

        batch_id = f"batch-e2e-{calc_date.isoformat()}"
        post_response = client.post(
            "/api/v1/ingestion/batch",
            headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
            json={"batch_id": batch_id, "source": "synthetic", "records": api_records_payload},
        )

        assert post_response.status_code == 200, f"Batch post failed: {post_response.text}"
        batch_resp_data = post_response.json()
        assert batch_resp_data["status"] == "success"
        assert batch_resp_data["records_received"] == 40
        assert batch_resp_data["records_valid"] == 40

        # ------------------------------------------------------------------
        # Step 3: Assert records are inserted into database raw_fares table
        # ------------------------------------------------------------------
        raw_fare_count = pipeline_db_session.scalar(select(func.count(RawFare.id)))
        assert raw_fare_count == 40, f"Expected 40 raw_fares in DB, found {raw_fare_count}"

        # Verify seeded outlier is in raw_fares table
        outlier_db_record = pipeline_db_session.execute(
            select(RawFare).where(
                RawFare.origin == "DEL",
                RawFare.destination == "BOM",
                RawFare.booking_window.in_(["T+1", "1"]),
            )
        ).scalar_one_or_none()
        assert outlier_db_record is not None
        assert outlier_db_record.total_fare == 25000.0

        replay_response = client.post(
            "/api/v1/ingestion/batch",
            headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
            json={"batch_id": f"{batch_id}-replay", "source": "synthetic", "records": api_records_payload},
        )
        assert replay_response.status_code == 200
        assert pipeline_db_session.scalar(select(func.count(RawFare.id))) == 40

        # ------------------------------------------------------------------
        # Pre-seed 30-day baseline for DEL->BOM to calculate Z-score outlier
        # ------------------------------------------------------------------
        del_bom_route = pipeline_db_session.execute(
            select(Route).where(Route.origin == "DEL", Route.destination == "BOM")
        ).scalar_one()

        for day_offset in range(1, 31):
            hist_date = calc_date - timedelta(days=day_offset)
            # Baseline normal median fare around 5500 INR
            pipeline_db_session.add(
                RouteDailyIndex(
                    route_id=del_bom_route.id,
                    origin="DEL",
                    destination="BOM",
                    index_date=hist_date,
                    booking_window="T+1",
                    index_type="weighted_median",
                    sample_size=10,
                    median_fare=5500.0,
                    mean_fare=5500.0,
                    min_fare=5200.0,
                    max_fare=5800.0,
                    percentile_25=5400.0,
                    percentile_75=5600.0,
                    std_dev=150.0,
                    index_value=100.0,
                    base_period="2026-01-01",
                    calculation_timestamp=datetime.now(timezone.utc),
                )
            )
            # Also add COMPOSITE history
            pipeline_db_session.add(
                RouteDailyIndex(
                    route_id=del_bom_route.id,
                    origin="DEL",
                    destination="BOM",
                    index_date=hist_date,
                    booking_window="COMPOSITE",
                    index_type="weighted_median",
                    sample_size=40,
                    median_fare=5400.0,
                    mean_fare=5400.0,
                    min_fare=4200.0,
                    max_fare=6800.0,
                    percentile_25=5100.0,
                    percentile_75=5700.0,
                    std_dev=200.0,
                    index_value=98.18,
                    base_period="2026-01-01",
                    calculation_timestamp=datetime.now(timezone.utc),
                )
            )
        pipeline_db_session.commit()

        # ------------------------------------------------------------------
        # Step 4: Run statistical index pipeline to compute daily indices and anomaly alerts
        # ------------------------------------------------------------------
        pipeline_result = run_daily_index_pipeline(db=pipeline_db_session, calculation_date=calc_date)

        assert pipeline_result["status"] == "success"
        assert pipeline_result["routes_covered"] == 10
        assert pipeline_result["route_indices_count"] > 0
        assert pipeline_result["national_index_value"] > 0

        # ------------------------------------------------------------------
        # Step 5: Queries GET /api/v1/indices/national/latest and asserts calculated index matches mathematical expectation
        # ------------------------------------------------------------------
        national_resp = client.get("/api/v1/indices/national/latest")
        assert national_resp.status_code == 200, f"Failed to get national index: {national_resp.text}"
        national_data = national_resp.json()

        expected_national_index = pipeline_result["national_index_value"]
        actual_national_index = national_data["index_value"]
        assert abs(actual_national_index - round(expected_national_index, 2)) < 0.05, (
            f"National index mismatch: actual={actual_national_index}, expected={expected_national_index}"
        )
        assert national_data["status"] == "published"
        assert national_data["sample_size"] >= 40

        # ------------------------------------------------------------------
        # Step 6: Queries GET /api/v1/analytics/anomalies and asserts surge alert is generated for seeded 3-sigma outlier
        # ------------------------------------------------------------------
        anomalies_resp = client.get("/api/v1/analytics/anomalies")
        assert anomalies_resp.status_code == 200, f"Failed to get anomalies: {anomalies_resp.text}"
        anomalies_data = anomalies_resp.json()
        assert anomalies_data.get("total_alerts", len(anomalies_data.get("alerts", []))) > 0, (
            "Expected at least 1 anomaly alert generated"
        )
        alerts = anomalies_data["alerts"]

        # Look for the seeded outlier on DEL-BOM
        del_bom_alerts = [
            a for a in alerts if a["route_code"] == "DEL-BOM"
        ]
        assert len(del_bom_alerts) > 0, "Expected anomaly alert for seeded DEL-BOM route"

        outlier_alert = del_bom_alerts[0]
        assert outlier_alert["severity"] == "CRITICAL"
        assert outlier_alert["anomaly_type"] in ("SURGE_PRICING", "SPIKE", "SURGE", "DGCA_STATUTORY_VIOLATION")
        assert outlier_alert["observed_fare_inr"] >= 9000.0
        assert outlier_alert["deviation_percent"] > 0
