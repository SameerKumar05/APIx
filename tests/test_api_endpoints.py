"""Integration test suite for APIx FastAPI endpoints.

Covers:
- System health and root endpoints
- Ingestion pipeline with API key authentication
- National daily index (latest and historical series)
- Route catalog and corridor index history (filtering by COMPOSITE booking window)
- Analytics endpoints (lead time curve, 7x24 heatmap, anomalies, DGCA validation)
- Sector heatmap matrix with advance booking window pricing and surge multipliers
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.seed import seed_routes
from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.models.anomaly import AnomalyAlert
from backend.app.models.econometrics import DgcaViolation
from backend.app.models.index import NationalDailyIndex, RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.route import Route


@pytest.fixture
def api_client(tmp_path: Path):
    """Hermetic SQLite test client fixture with complete seeded test data."""
    db_file = tmp_path / "test_api_endpoints.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        # 1. Active routes
        seed_routes(session)

        today = date.today()
        now = datetime.now(UTC)

        # 2. National indices
        for days_ago, idx_val in [(1, 112.5), (0, 114.28)]:
            session.add(
                NationalDailyIndex(
                    index_date=today - timedelta(days=days_ago),
                    index_type="fisher",
                    booking_window="COMPOSITE",
                    index_value=idx_val,
                    total_samples=1200,
                    weighted_mean_fare=5400.0,
                    weighted_median_fare=5300.0,
                    base_period="2026-01-01",
                    calculation_timestamp=now - timedelta(days=days_ago),
                )
            )

        # 3. Route daily indices for active routes
        routes = session.query(Route).filter(Route.is_active.is_(True)).all()
        for r in routes:
            for days_ago in (1, 0):
                # Composite record (primary index series)
                session.add(
                    RouteDailyIndex(
                        origin=r.origin,
                        destination=r.destination,
                        index_date=today - timedelta(days=days_ago),
                        booking_window="COMPOSITE",
                        index_type="composite",
                        sample_size=20,
                        median_fare=5100.0 + days_ago * 50,
                        mean_fare=5200.0 + days_ago * 50,
                        min_fare=4200.0,
                        max_fare=6500.0,
                        percentile_25=4800.0,
                        percentile_75=5600.0,
                        std_dev=380.0,
                        index_value=105.0 + days_ago * 1.5,
                        base_period="2026-01-01",
                        calculation_timestamp=now - timedelta(days=days_ago),
                    )
                )

            # Advance booking window records for DEL-BOM sector heatmap
            if r.route_code == "DEL-BOM":
                windows_data = [
                    ("T+1", 8500.0, 8400.0, 7800.0, 9500.0, 15),
                    ("T+7", 6200.0, 6100.0, 5600.0, 7000.0, 25),
                    ("T+15", 5400.0, 5350.0, 4900.0, 6000.0, 30),
                    ("T+30", 4800.0, 4750.0, 4300.0, 5500.0, 35),
                    ("T+45", 4500.0, 4450.0, 4100.0, 5100.0, 20),
                ]
                for win, mean_f, med_f, min_f, max_f, smp in windows_data:
                    session.add(
                        RouteDailyIndex(
                            origin=r.origin,
                            destination=r.destination,
                            index_date=today,
                            booking_window=win,
                            index_type="weighted_median",
                            sample_size=smp,
                            median_fare=med_f,
                            mean_fare=mean_f,
                            min_fare=min_f,
                            max_fare=max_f,
                            percentile_25=min_f + 200,
                            percentile_75=max_f - 200,
                            std_dev=300.0,
                            index_value=round((mean_f / 4800.0) * 100.0, 2),
                            base_period="2026-01-01",
                            calculation_timestamp=now,
                        )
                    )

        # 4. Raw fares for lead-time curve (DEL-BOM)
        windows = [
            ("T+0", 0, 8900.0),
            ("T+1", 1, 8500.0),
            ("T+3", 3, 7400.0),
            ("T+7", 7, 6200.0),
            ("T+14", 14, 5600.0),
            ("T+21", 21, 5100.0),
            ("T+30", 30, 4800.0),
            ("T+45", 45, 4500.0),
            ("T+60", 60, 4300.0),
            ("T+75", 75, 4200.0),
            ("T+90", 90, 4100.0),
        ]
        for win, days, fare in windows:
            for flight_idx in range(1, 4):
                f_date = today + timedelta(days=days)
                session.add(
                    RawFare(
                        batch_id="test-batch-001",
                        airline_code="6E",
                        flight_number=f"6E-{100 + flight_idx}",
                        origin="DEL",
                        destination="BOM",
                        flight_date=f_date,
                        departure_time=datetime.combine(
                            f_date, datetime.min.time(), tzinfo=UTC
                        )
                        + timedelta(hours=6 * flight_idx),
                        booking_window=win,
                        cabin_class="economy",
                        base_fare=fare - 300.0,
                        taxes_and_fees=300.0,
                        total_fare=fare + (flight_idx - 2) * 100.0,
                        source_platform="makemytrip",
                        scraped_at=now,
                        hash_id=f"test-del-bom-{win}-{flight_idx}",
                    )
                )

        # 5. Raw fares for 7x24 heatmap (BOM-DEL)
        for dow in range(7):
            for hod in [2, 8, 14, 20]:
                target_dt = now - timedelta(days=now.weekday() - dow)
                target_dt = target_dt.replace(
                    hour=hod, minute=0, second=0, microsecond=0
                )
                session.add(
                    RawFare(
                        batch_id="test-heatmap-batch",
                        airline_code="6E",
                        flight_number=f"6E-{300 + dow}",
                        origin="BOM",
                        destination="DEL",
                        flight_date=target_dt.date(),
                        departure_time=target_dt,
                        booking_window="T+7",
                        cabin_class="economy",
                        base_fare=5200.0,
                        taxes_and_fees=300.0,
                        total_fare=5500.0 + dow * 50.0 + hod * 20.0,
                        source_platform="easemytrip",
                        scraped_at=now,
                        hash_id=f"test-heat-{dow}-{hod}",
                    )
                )

        # 6. Anomaly alerts
        session.add(
            AnomalyAlert(
                origin="DEL",
                destination="BOM",
                booking_window="T+1",
                airline_code="6E",
                alert_type="SPIKE",
                severity="CRITICAL",
                detected_fare=14500.0,
                baseline_fare=6200.0,
                pct_change=133.87,
                status="ACTIVE",
                created_at=now,
            )
        )

        # 7. DGCA Violations
        for idx, route_code in enumerate(
            ["DEL-BOM", "BOM-DEL", "DEL-BLR", "BLR-DEL", "BOM-BLR"]
        ):
            session.add(
                DgcaViolation(
                    route_code=route_code,
                    airline_code="6E",
                    flight_number=f"6E-dgca{idx}",
                    flight_date=today + timedelta(days=30),
                    window="T+7",
                    fare_inr=9500.0 + idx * 100,
                    median_baseline_fare=5000.0,
                    surge_multiple=1.9 + idx * 0.05,
                    severity="CRITICAL",
                    violation_code="DGCA_CAP_EXCEEDED",
                    detected_at=now,
                    status="OPEN",
                )
            )

        session.commit()

    app.dependency_overrides[get_db] = lambda: Session(engine)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_health_endpoint(api_client: TestClient) -> None:
    response = api_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "apix-backend-api"
    assert "timestamp" in data


def test_root_endpoint(api_client: TestClient) -> None:
    response = api_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "operational"
    assert "/docs" in data["docs"]


def test_ingestion_batch_unauthorized_missing_header(api_client: TestClient) -> None:
    payload = {
        "source": "easemytrip_scraper",
        "scraped_at": datetime.now(UTC).isoformat(),
        "records": [
            {
                "airline_code": "6E",
                "flight_number": "6E-205",
                "origin": "DEL",
                "destination": "BOM",
                "departure_datetime": (
                    datetime.now(UTC) + timedelta(days=7)
                ).isoformat(),
                "booking_datetime": datetime.now(UTC).isoformat(),
                "fare_inr": 6250.0,
            }
        ],
    }
    response = api_client.post("/api/v1/ingestion/batch", json=payload)
    assert response.status_code == 401
    assert "Missing required authentication header" in response.json()["detail"]


def test_ingestion_batch_unauthorized_invalid_key(api_client: TestClient) -> None:
    payload = {
        "source": "easemytrip_scraper",
        "scraped_at": datetime.now(UTC).isoformat(),
        "records": [
            {
                "airline_code": "6E",
                "flight_number": "6E-205",
                "origin": "DEL",
                "destination": "BOM",
                "departure_datetime": (
                    datetime.now(UTC) + timedelta(days=7)
                ).isoformat(),
                "booking_datetime": datetime.now(UTC).isoformat(),
                "fare_inr": 6250.0,
            }
        ],
    }
    response = api_client.post(
        "/api/v1/ingestion/batch",
        json=payload,
        headers={"X-Ingestion-Key": "invalid-key-xyz"},
    )
    assert response.status_code == 401
    assert "Invalid X-Ingestion-Key" in response.json()["detail"]


def test_ingestion_batch_authorized_valid(api_client: TestClient) -> None:
    now_str = datetime.now(UTC).isoformat()
    dep1 = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    dep2 = (datetime.now(UTC) + timedelta(days=12)).isoformat()

    payload = {
        "batch_id": "test-batch-001",
        "source": "makemytrip_pipeline",
        "scraped_at": now_str,
        "records": [
            {
                "airline_code": "6E",
                "flight_number": "6E-205",
                "origin": "DEL",
                "destination": "BOM",
                "departure_datetime": dep1,
                "arrival_datetime": (
                    datetime.now(UTC) + timedelta(days=5, hours=2)
                ).isoformat(),
                "booking_datetime": now_str,
                "fare_inr": 5800.0,
                "cabin_class": "economy",
                "stops": 0,
                "source": "makemytrip_pipeline",
                "booking_window": 5,
            },
            {
                "airline_code": "AI",
                "flight_number": "AI-806",
                "origin": "BOM",
                "destination": "BLR",
                "departure_datetime": dep2,
                "booking_datetime": now_str,
                "fare_inr": 4200.0,
                "cabin_class": "economy",
                "stops": 0,
                "source": "makemytrip_pipeline",
                "booking_window": 12,
            },
        ],
    }
    response = api_client.post(
        "/api/v1/ingestion/batch",
        json=payload,
        headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["batch_id"] == "test-batch-001"
    assert data["records_valid"] == 2


def test_national_index_latest(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/indices/national/latest")
    assert response.status_code == 200
    data = response.json()
    assert data["index_value"] > 0
    assert data["status"] == "published"
    assert data["base_period"] == "2026-01-01"


def test_national_index_history(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/indices/national/history?days=14")
    assert response.status_code == 200
    data = response.json()
    assert "points" in data
    assert len(data["points"]) >= 1


def test_routes_overview(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/indices/routes")
    assert response.status_code == 200
    data = response.json()
    assert "routes" in data
    assert len(data["routes"]) >= 5
    codes = [r["route_code"] for r in data["routes"]]
    assert "DEL-BOM" in codes
    assert "BOM-BLR" in codes


def test_route_history_filtering_composite(api_client: TestClient) -> None:
    # 1. Default request should filter RouteDailyIndex.booking_window == 'COMPOSITE'
    response_default = api_client.get("/api/v1/indices/routes/DEL-BOM/history?days=7")
    assert response_default.status_code == 200
    data_default = response_default.json()
    assert data_default["route_code"] == "DEL-BOM"
    assert len(data_default["points"]) >= 1

    # 2. Explicit booking_window query parameter
    response_win = api_client.get(
        "/api/v1/indices/routes/DEL-BOM/history?days=7&booking_window=T%2B7"
    )
    assert response_win.status_code == 200
    data_win = response_win.json()
    assert len(data_win["points"]) >= 1

    # 3. Non-existent booking window returns empty series
    response_none = api_client.get(
        "/api/v1/indices/routes/DEL-BOM/history?days=7&booking_window=T%2B999"
    )
    assert response_none.status_code == 200
    assert response_none.json()["data_available"] is False
    assert len(response_none.json()["points"]) == 0


def test_route_history_frequency_aggregation(api_client: TestClient) -> None:
    res_daily = api_client.get(
        "/api/v1/indices/routes/DEL-BOM/history?days=30&frequency=daily"
    )
    assert res_daily.status_code == 200
    data_daily = res_daily.json()
    assert data_daily["frequency"] == "daily"

    res_weekly = api_client.get(
        "/api/v1/indices/routes/DEL-BOM/history?days=30&frequency=weekly"
    )
    assert res_weekly.status_code == 200
    data_weekly = res_weekly.json()
    assert data_weekly["frequency"] == "weekly"

    res_monthly = api_client.get(
        "/api/v1/indices/routes/DEL-BOM/history?days=30&frequency=monthly"
    )
    assert res_monthly.status_code == 200
    data_monthly = res_monthly.json()
    assert data_monthly["frequency"] == "monthly"

    res_invalid = api_client.get(
        "/api/v1/indices/routes/DEL-BOM/history?days=30&frequency=hourly"
    )
    assert res_invalid.status_code == 422


def test_lead_time_curve(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/analytics/lead-time-curve?route_code=DEL-BOM")
    assert response.status_code == 200
    data = response.json()
    assert data["route_code"] == "DEL-BOM"
    assert len(data["curve_points"]) >= 5
    days = [pt["days_before_departure"] for pt in data["curve_points"]]
    assert 1 in days
    assert 30 in days


def test_heatmap_matrix(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/analytics/heatmap?route_code=NATIONAL")
    assert response.status_code == 200
    data = response.json()
    assert len(data["matrix"]) > 0


def test_anomalies(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/analytics/anomalies")
    assert response.status_code == 200
    data = response.json()
    assert data["total_alerts"] >= 1
    assert data["alerts"][0]["severity"] == "CRITICAL"


def test_dgca_validation(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/analytics/dgca-validation")
    assert response.status_code == 200
    data = response.json()
    assert data["total_routes_evaluated"] >= 1
    assert data["total_violations"] >= 1
    assert data["evaluation_status"] == "evaluated"


def test_sector_heatmap_live(api_client: TestClient) -> None:
    # 1. Full sector heatmap
    response = api_client.get("/api/v1/analytics/sector-heatmap")
    assert response.status_code == 200
    data = response.json()
    assert data["data_available"] is True
    assert data["total_routes"] >= 1
    assert len(data["sectors"]) >= 1

    # Verify DEL-BOM sector row
    del_bom = next((s for s in data["sectors"] if s["route_code"] == "DEL-BOM"), None)
    assert del_bom is not None
    assert del_bom["origin"] == "DEL"
    assert del_bom["destination"] == "BOM"
    # Booking window fares
    assert "T+1" in del_bom["windows"]
    assert "T+7" in del_bom["windows"]
    assert "T+15" in del_bom["windows"]
    assert "T+30" in del_bom["windows"]
    assert "T+45" in del_bom["windows"]
    assert del_bom["windows"]["T+1"] == 8500.0
    assert del_bom["windows"]["T+30"] == 4800.0
    assert del_bom["surge_multiplier"] == round(8500.0 / 4800.0, 2)

    # Verify flat matrix
    assert len(data["matrix"]) >= 5
    cell_t1 = next(
        (
            c
            for c in data["matrix"]
            if c["route_code"] == "DEL-BOM" and c["booking_window"] == "T+1"
        ),
        None,
    )
    assert cell_t1 is not None
    assert cell_t1["days_before_departure"] == 1
    assert cell_t1["avg_fare_inr"] == 8500.0

    # Verify windows list contains advance windows
    assert "T+1" in data["windows"]
    assert "T+30" in data["windows"]
    assert "T+45" in data["windows"]

    # 2. Filtered sector heatmap by route_code
    filtered_resp = api_client.get(
        "/api/v1/analytics/sector-heatmap?route_code=DEL-BOM"
    )
    assert filtered_resp.status_code == 200
    filtered_data = filtered_resp.json()
    assert filtered_data["total_routes"] == 1
    assert filtered_data["sectors"][0]["route_code"] == "DEL-BOM"

    # 3. Also verify alias on /indices/sector-heatmap
    alias_resp = api_client.get("/api/v1/indices/sector-heatmap")
    assert alias_resp.status_code == 200
    assert alias_resp.json()["data_available"] is True


def test_sector_heatmap_empty_database(tmp_path: Path) -> None:
    empty_db = tmp_path / "empty.db"
    engine = create_engine(
        f"sqlite:///{empty_db}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = lambda: Session(engine)
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/sector-heatmap")
            assert response.status_code == 200
            data = response.json()
            assert data["data_available"] is False
            assert data["total_routes"] == 0
            assert len(data["sectors"]) == 0
            assert len(data["matrix"]) == 0
    finally:
        app.dependency_overrides.clear()
