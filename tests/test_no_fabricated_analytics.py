"""Endpoints must serve stored observations or an explicit empty flag, never a formula."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import backend.app.models  # noqa: F401
from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.models.econometrics import DgcaViolation
from backend.app.models.index import NationalDailyIndex, RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.route import Route


def _open_session(tmp_path: Path, name: str) -> tuple[Session, Engine]:
    engine = create_engine(
        f"sqlite:///{tmp_path / name}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    return Session(engine), engine


def _fare(
    *,
    origin: str,
    destination: str,
    window: str,
    total: float,
    flight_date: date,
    hash_id: str,
    departure: datetime | None = None,
) -> RawFare:
    return RawFare(
        batch_id="fail-closed",
        origin=origin,
        destination=destination,
        flight_date=flight_date,
        booking_window=window,
        airline_code="6E",
        flight_number=f"6E-{hash_id[-4:]}",
        departure_time=departure,
        stops=0,
        fare_class="Economy",
        base_fare=total,
        taxes_and_fees=0.0,
        total_fare=total,
        source_platform="verification",
        scraped_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        hash_id=hash_id,
        is_synthetic=False,
    )


def test_lead_time_curve_is_empty_when_no_fares_are_stored(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "lead-empty.db")
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/lead-time-curve", params={"route_code": "DEL-BOM"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["curve_points"] == []
        assert body["data_available"] is False
        assert body["route_code"] == "DEL-BOM"
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_lead_time_curve_returns_stored_window_fares(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "lead-seeded.db")
    session.add_all(
        [
            _fare(origin="DEL", destination="BOM", window="T+30", total=4000.0, flight_date=date(2026, 10, 1), hash_id="a" * 64),
            _fare(origin="DEL", destination="BOM", window="T+30", total=5000.0, flight_date=date(2026, 10, 2), hash_id="b" * 64),
            _fare(origin="DEL", destination="BOM", window="T+30", total=6000.0, flight_date=date(2026, 10, 3), hash_id="c" * 64),
            _fare(origin="DEL", destination="BOM", window="T+7", total=8000.0, flight_date=date(2026, 9, 8), hash_id="d" * 64),
            _fare(origin="DEL", destination="BOM", window="T+7", total=9000.0, flight_date=date(2026, 9, 9), hash_id="e" * 64),
            _fare(origin="BOM", destination="DEL", window="T+7", total=20000.0, flight_date=date(2026, 9, 9), hash_id="f" * 64),
        ]
    )
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/lead-time-curve", params={"route_code": "DEL-BOM"})
        assert response.status_code == 200, response.text
        points = response.json()["curve_points"]
        assert response.json()["data_available"] is True
        assert [point["days_before_departure"] for point in points] == [30, 7]
        assert points[0]["avg_fare_inr"] == 5000.0
        assert points[0]["median_fare_inr"] == 5000.0
        assert points[0]["p10_fare_inr"] == 4200.0
        assert points[0]["p90_fare_inr"] == 5800.0
        assert points[0]["elasticity_factor"] == 1.0
        assert points[1]["avg_fare_inr"] == 8500.0
        assert points[1]["median_fare_inr"] == 8500.0
        assert points[1]["p10_fare_inr"] == 8100.0
        assert points[1]["p90_fare_inr"] == 8900.0
        assert points[1]["elasticity_factor"] == 1.7
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_heatmap_is_empty_when_no_departure_times_are_stored(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "heat-empty.db")
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/heatmap")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["matrix"] == []
        assert body["data_available"] is False
        assert body["min_val"] is None
        assert body["max_val"] is None
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_heatmap_returns_observed_departure_slots(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "heat-seeded.db")
    session.add_all(
        [
            _fare(
                origin="DEL",
                destination="BOM",
                window="T+7",
                total=6200.0,
                flight_date=date(2026, 9, 7),
                hash_id="1" * 64,
                departure=datetime(2026, 9, 7, 8, 0),
            ),
            _fare(
                origin="DEL",
                destination="BOM",
                window="T+7",
                total=6400.0,
                flight_date=date(2026, 9, 7),
                hash_id="2" * 64,
                departure=datetime(2026, 9, 7, 8, 30),
            ),
            _fare(
                origin="DEL",
                destination="BOM",
                window="T+7",
                total=5000.0,
                flight_date=date(2026, 9, 8),
                hash_id="3" * 64,
                departure=datetime(2026, 9, 8, 9, 0),
            ),
            _fare(
                origin="DEL",
                destination="BOM",
                window="T+7",
                total=99000.0,
                flight_date=date(2026, 9, 9),
                hash_id="4" * 64,
                departure=None,
            ),
        ]
    )
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/heatmap", params={"route_code": "DEL-BOM"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["data_available"] is True
        assert body["min_val"] == 5000.0
        assert body["max_val"] == 6300.0
        assert len(body["matrix"]) == 2
        monday = body["matrix"][0]
        tuesday = body["matrix"][1]
        assert monday["day_of_week"] == 0
        assert monday["hour_of_day"] == 8
        assert monday["avg_fare_inr"] == 6300.0
        assert monday["fare_index"] == 107.39
        assert tuesday["day_of_week"] == 1
        assert tuesday["hour_of_day"] == 9
        assert tuesday["avg_fare_inr"] == 5000.0
        assert tuesday["fare_index"] == 85.23
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_dgca_validation_is_not_evaluated_when_the_ledger_is_empty(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "dgca-empty.db")
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/dgca-validation")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["violations"] == []
        assert body["total_violations"] == 0
        assert body["total_routes_evaluated"] == 0
        assert body["data_available"] is False
        assert body["evaluation_status"] == "not_evaluated"
        assert "BREACH_DETECTED" not in response.text
        assert "24500" not in response.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_dgca_validation_reports_only_stored_violation_rows(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "dgca-seeded.db")
    session.add_all(
        [
            DgcaViolation(
                route_code="DEL-BOM",
                airline_code="6E",
                flight_number="6E-201",
                flight_date=date(2026, 9, 7),
                window="T+1",
                fare_inr=18450.0,
                median_baseline_fare=16000.0,
                surge_multiple=1.15,
                severity="CRITICAL",
                violation_code="DGCA-CAP-BREACH",
                status="OPEN",
            ),
            DgcaViolation(
                route_code="DEL-BOM",
                airline_code="6E",
                flight_number="6E-202",
                flight_date=date(2026, 9, 8),
                window="T+1",
                fare_inr=12000.0,
                median_baseline_fare=15000.0,
                surge_multiple=0.8,
                severity="WARNING",
                violation_code="DGCA-CAP-BREACH",
                status="CONFIRMED",
            ),
            DgcaViolation(
                route_code="DEL-BLR",
                airline_code="AI",
                flight_number="AI-501",
                flight_date=date(2026, 9, 8),
                window="T+1",
                fare_inr=30000.0,
                median_baseline_fare=11000.0,
                surge_multiple=2.7,
                severity="CRITICAL",
                violation_code="DGCA-CAP-BREACH",
                status="DISMISSED",
            ),
            DgcaViolation(
                route_code="BOM-GOI",
                airline_code="SG",
                flight_number="SG-815",
                flight_date=date(2026, 9, 9),
                window="T+7",
                fare_inr=9000.0,
                median_baseline_fare=8000.0,
                surge_multiple=1.125,
                severity="WARNING",
                violation_code="DGCA-CAP-BREACH",
                status="OPEN",
            ),
        ]
    )
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/dgca-validation")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["data_available"] is True
        assert body["evaluation_status"] == "evaluated"
        assert body["total_violations"] == 3
        assert body["total_routes_evaluated"] == 2
        assert [item["route_code"] for item in body["violations"]] == ["BOM-GOI", "DEL-BOM"]
        goi, bom = body["violations"]
        assert goi["observed_max_fare_inr"] == 9000.0
        assert goi["statutory_band_cap_inr"] == 8000.0
        assert goi["violations_count"] == 1
        assert goi["compliance_status"] == "BREACH_DETECTED"
        assert bom["observed_max_fare_inr"] == 18450.0
        assert bom["statutory_band_cap_inr"] == 16000.0
        assert bom["violations_count"] == 2
        assert bom["compliance_status"] == "BREACH_DETECTED"
        assert "24500" not in response.text
        assert "DEL-BLR" not in response.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_routes_overview_omits_a_route_with_no_index(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "routes-empty.db")
    session.add(Route(origin="DEL", destination="BOM", distance_km=1148.0, is_active=True))
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/indices/routes")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["routes"] == []
        assert body["total_routes"] == 0
        assert body["data_available"] is False
        assert "6850" not in response.text
        assert "5000" not in response.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_routes_overview_returns_the_stored_index(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "routes-seeded.db")
    session.add_all(
        [
            Route(origin="DEL", destination="BOM", distance_km=1148.0, is_active=True),
            Route(origin="BOM", destination="BLR", distance_km=842.0, is_active=True),
            RouteDailyIndex(
                origin="DEL",
                destination="BOM",
                index_date=date(2026, 9, 7),
                index_value=100.0,
                mean_fare=5000.0,
                min_fare=4000.0,
                sample_size=8,
                std_dev=400.0,
            ),
            RouteDailyIndex(
                origin="DEL",
                destination="BOM",
                index_date=date(2026, 9, 8),
                index_value=110.0,
                mean_fare=5500.0,
                min_fare=4000.0,
                sample_size=12,
                std_dev=550.0,
            ),
        ]
    )
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/indices/routes")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["data_available"] is True
        assert body["total_routes"] == 1
        item = body["routes"][0]
        assert item["route_code"] == "DEL-BOM"
        assert item["current_index"] == 110.0
        assert item["change_24h"] == 10.0
        assert item["avg_fare_inr"] == 5500.0
        assert item["min_fare_inr"] == 4000.0
        assert item["active_flights_tracked"] == 12
        assert item["volatility_score"] == 0.1
        assert "BOM-BLR" not in response.text
        assert "6850" not in response.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_route_history_is_empty_when_no_index_is_stored(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "history-empty.db")
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/indices/routes/DEL-BOM/history")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["points"] == []
        assert body["data_available"] is False
        assert "1800" not in response.text
        assert "108.0" not in response.text
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_route_history_returns_stored_points_and_a_real_week_change(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "history-seeded.db")
    session.add_all(
        [
            RouteDailyIndex(
                origin="DEL",
                destination="BOM",
                index_date=date(2026, 9, 1),
                index_value=100.0,
                sample_size=10,
                mean_fare=5000.0,
            ),
            RouteDailyIndex(
                origin="DEL",
                destination="BOM",
                index_date=date(2026, 9, 8),
                index_value=110.0,
                sample_size=12,
                mean_fare=5500.0,
            ),
        ]
    )
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/indices/routes/DEL-BOM/history", params={"days": 30})
        assert response.status_code == 200, response.text
        points = response.json()["points"]
        assert response.json()["data_available"] is True
        assert len(points) == 2
        assert points[0]["index_value"] == 100.0
        assert points[0]["sample_size"] == 10
        assert points[0]["change_24h"] is None
        assert points[0]["change_7d"] is None
        assert points[1]["index_value"] == 110.0
        assert points[1]["sample_size"] == 12
        assert points[1]["change_24h"] == 10.0
        assert points[1]["change_7d"] == 10.0
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_national_latest_omits_interval_and_week_change_it_cannot_compute(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "latest-no-prior.db")
    session.add(
        NationalDailyIndex(
            index_date=date(2026, 9, 8),
            booking_window="COMPOSITE",
            index_type="laspeyres",
            index_value=110.0,
            inflation_dod_pct=1.5,
            inflation_mom_pct=9.9,
            total_samples=40,
        )
    )
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/indices/national/latest")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["index_value"] == 110.0
        assert body["change_24h"] == 1.5
        assert body["change_7d"] is None
        assert body["confidence_interval_lower"] is None
        assert body["confidence_interval_upper"] is None
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def test_national_latest_week_change_uses_the_index_seven_days_earlier(tmp_path: Path) -> None:
    session, engine = _open_session(tmp_path, "latest-prior.db")
    session.add_all(
        [
            NationalDailyIndex(
                index_date=date(2026, 9, 1),
                booking_window="COMPOSITE",
                index_type="laspeyres",
                index_value=100.0,
                inflation_dod_pct=0.0,
                total_samples=40,
            ),
            NationalDailyIndex(
                index_date=date(2026, 9, 8),
                booking_window="COMPOSITE",
                index_type="laspeyres",
                index_value=110.0,
                inflation_dod_pct=1.5,
                inflation_mom_pct=9.9,
                total_samples=40,
            ),
        ]
    )
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/indices/national/latest")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["change_24h"] == 1.5
        assert body["change_7d"] == 10.0
        assert body["confidence_interval_lower"] is None
        assert body["confidence_interval_upper"] is None
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()
