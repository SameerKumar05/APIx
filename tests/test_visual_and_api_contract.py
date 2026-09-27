"""Automated verification suite for Issue #11:
1. Dashboard 4-visual coverage:
   (1) Daily index & trends
   (2) Sector-wise heatmap (corridors x booking windows matrix including T+45)
   (3) Lead-time elasticity curves (including T+45)
   (4) Econometric comparisons (Fisher, Laspeyres, Paasche, CPI divergence)
2. NSO/RBI consumable API contract validation:
   - Endpoints availability and JSON schemas
   - OpenAPI schema URL (/api/v1/openapi.json)
   - Rate limit headers (120 req/60s)
   - CORS configuration rejecting wildcard origins
   - Authentication boundaries
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, settings
from backend.app.db.seed import seed_routes
from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.models.econometrics import (
    EconometricIndex,
    MospiCpiSeries,
    RouteElasticity,
)
from backend.app.models.index import NationalDailyIndex, RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.route import Route


@pytest.fixture
def api_client(tmp_path: Path):
    """Hermetic SQLite test client fixture with complete seeded test data."""
    db_file = tmp_path / "test_visual_contract.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        seed_routes(session)

        today = date.today()
        now = datetime.now(UTC)

        # 1. National daily index series (Visual 1)
        for days_ago, idx_val in [(2, 110.2), (1, 112.5), (0, 114.28)]:
            session.add(
                NationalDailyIndex(
                    index_date=today - timedelta(days=days_ago),
                    index_type="fisher",
                    booking_window="COMPOSITE",
                    index_value=idx_val,
                    total_samples=1500,
                    weighted_mean_fare=5400.0,
                    weighted_median_fare=5300.0,
                    base_period="2026-01-01",
                    calculation_timestamp=now - timedelta(days=days_ago),
                )
            )

        # 2. Route daily indices for active routes
        routes = session.query(Route).filter(Route.is_active.is_(True)).all()
        for r in routes:
            for days_ago in (1, 0):
                session.add(
                    RouteDailyIndex(
                        origin=r.origin,
                        destination=r.destination,
                        index_date=today - timedelta(days=days_ago),
                        booking_window="COMPOSITE",
                        index_type="composite",
                        sample_size=30,
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

            # Route daily index booking window records including T+45 (Visual 2)
            windows_data = [
                ("T+1", 8500.0, 8400.0, 7800.0, 9500.0, 20),
                ("T+7", 6200.0, 6100.0, 5600.0, 7000.0, 25),
                ("T+15", 5400.0, 5350.0, 4900.0, 6000.0, 30),
                ("T+30", 4800.0, 4750.0, 4300.0, 5500.0, 35),
                ("T+45", 4500.0, 4450.0, 4100.0, 5100.0, 25),
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

        # 3. Raw fares for lead-time elasticity curves including T+45 (Visual 3)
        lead_time_windows = [
            ("T+1", 1, 8500.0),
            ("T+7", 7, 6200.0),
            ("T+15", 15, 5400.0),
            ("T+30", 30, 4800.0),
            ("T+45", 45, 4500.0),
        ]
        for win, days, fare in lead_time_windows:
            for flight_idx in range(1, 4):
                f_date = today + timedelta(days=days)
                session.add(
                    RawFare(
                        batch_id="test-batch-contract",
                        airline_code="6E",
                        flight_number=f"6E-{200 + flight_idx}",
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
                        total_fare=fare + (flight_idx - 2) * 50.0,
                        source_platform="makemytrip",
                        scraped_at=now,
                        hash_id=f"test-del-bom-{win}-{flight_idx}",
                    )
                )

        # 4. Econometric indices (Visual 4)
        session.add(
            EconometricIndex(
                date=today,
                route_code="NATIONAL",
                laspeyres_index=122.40,
                paasche_index=115.01,
                fisher_ideal_index=118.65,
                substitution_bias=7.39,
                calculation_method="dgca_traffic_weighted",
                created_at=now,
            )
        )
        session.add(
            EconometricIndex(
                date=today,
                route_code="DEL-BOM",
                laspeyres_index=124.50,
                paasche_index=116.80,
                fisher_ideal_index=120.59,
                substitution_bias=7.70,
                calculation_method="route_level",
                created_at=now,
            )
        )

        # 5. MoSPI CPI Series & Matching Econometric Series (Visual 4)
        for ym, cpi_val in [
            ("2026-06", 105.8),
            ("2026-07", 106.5),
            ("2026-08", 107.4),
        ]:
            yr, mo = int(ym.split("-")[0]), int(ym.split("-")[1])
            session.add(
                MospiCpiSeries(
                    year_month=ym,
                    cpi_transport_index=cpi_val,
                    airfare_sub_index=cpi_val,
                    headline_cpi=cpi_val - 1.0,
                    published_at=date(yr, mo, 12),
                    source=f"https://mospi.gov.in/press-release-cpi-{ym}",
                    created_at=now,
                )
            )
            session.add(
                EconometricIndex(
                    date=date(yr, mo, 15),
                    route_code="NATIONAL",
                    laspeyres_index=cpi_val + 14.0,
                    paasche_index=cpi_val + 7.0,
                    fisher_ideal_index=round(
                        ((cpi_val + 14.0) * (cpi_val + 7.0)) ** 0.5, 2
                    ),
                    substitution_bias=7.0,
                    calculation_method="dgca_traffic_weighted",
                    created_at=now,
                )
            )

        session.add(
            RouteElasticity(
                route_code="DEL-BOM",
                calculation_date=today,
                t1_t7_elasticity=-0.38,
                t7_t15_elasticity=-0.72,
                t15_t30_elasticity=-1.15,
                avg_lead_time_decay=0.045,
                confidence_score=0.95,
                created_at=now,
            )
        )

        session.commit()

    app.dependency_overrides[get_db] = lambda: Session(engine)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


# =============================================================================
# Visual 1: Daily National Index and Historical Trends
# =============================================================================


def test_visual_1_national_latest(api_client: TestClient) -> None:
    """Visual 1: Latest national composite index returns valid payload and sub-indices."""
    response = api_client.get("/api/v1/indices/national/latest")
    assert response.status_code == 200
    data = response.json()

    assert "index_value" in data
    assert data["index_value"] > 0
    assert "base_period" in data
    assert "timestamp" in data
    assert "status" in data
    assert "weighted_median_fare_inr" in data


def test_visual_1_national_history(api_client: TestClient) -> None:
    """Visual 1: Historical daily series supports day duration queries."""
    response = api_client.get("/api/v1/indices/national/history?days=30")
    assert response.status_code == 200
    data = response.json()

    assert "points" in data
    assert len(data["points"]) >= 1
    point = data["points"][0]
    assert "timestamp" in point
    assert "index_value" in point


def test_visual_1_routes_overview(api_client: TestClient) -> None:
    """Visual 1: Trunk routes overview returns weighted corridor list."""
    response = api_client.get("/api/v1/indices/routes")
    assert response.status_code == 200
    data = response.json()

    assert "routes" in data
    assert len(data["routes"]) >= 10
    del_bom = next((r for r in data["routes"] if r["route_code"] == "DEL-BOM"), None)
    assert del_bom is not None
    assert del_bom["current_index"] > 0
    assert del_bom["avg_fare_inr"] > 0


# =============================================================================
# Visual 2: Sector-Wise Heatmap Matrix (Routes x Booking Windows)
# =============================================================================


def test_visual_2_sector_heatmap_coverage(api_client: TestClient) -> None:
    """Visual 2: Sector heatmap returns routes x booking windows matrix including T+45."""
    response = api_client.get("/api/v1/analytics/sector-heatmap")
    assert response.status_code == 200
    data = response.json()

    assert data["data_available"] is True
    assert data["total_routes"] >= 1
    assert "windows" in data
    # Ensure T+45 is included among canonical booking windows
    assert "T+45" in data["windows"]
    assert "T+30" in data["windows"]
    assert "T+1" in data["windows"]

    # Verify sector row attributes
    assert len(data["sectors"]) >= 1
    row = data["sectors"][0]
    assert "route_code" in row
    assert "windows" in row
    assert "surge_multiplier" in row
    assert "base_fare_inr" in row
    assert "urgent_fare_inr" in row
    assert "sample_size" in row

    # Verify DEL-BOM sector row has valid window fares
    del_bom = next((s for s in data["sectors"] if s["route_code"] == "DEL-BOM"), None)
    assert del_bom is not None
    assert "T+45" in del_bom["windows"]
    assert "T+30" in del_bom["windows"]
    assert "T+1" in del_bom["windows"]
    assert del_bom["windows"]["T+45"] is not None
    assert del_bom["windows"]["T+1"] > del_bom["windows"]["T+30"]
    assert del_bom["surge_multiplier"] >= 1.0

    # Verify flat matrix representation
    assert len(data["matrix"]) >= 1
    matrix_cell = data["matrix"][0]
    assert "route_code" in matrix_cell
    assert "booking_window" in matrix_cell
    assert "avg_fare_inr" in matrix_cell
    assert "fare_index" in matrix_cell


def test_visual_2_sector_heatmap_indices_alias(api_client: TestClient) -> None:
    """Visual 2: Alias endpoint /api/v1/indices/sector-heatmap returns matching matrix."""
    response = api_client.get("/api/v1/indices/sector-heatmap")
    assert response.status_code == 200
    data = response.json()
    assert data["data_available"] is True
    assert "T+45" in data["windows"]
    assert len(data["sectors"]) >= 1


# =============================================================================
# Visual 3: Lead-Time Elasticity Curves (Including T+45)
# =============================================================================


def test_visual_3_lead_time_curve_includes_t45(api_client: TestClient) -> None:
    """Visual 3: Lead-time elasticity curve includes T+45 advance purchase window."""
    response = api_client.get("/api/v1/analytics/lead-time-curve?route_code=DEL-BOM")
    assert response.status_code == 200
    data = response.json()

    assert data["data_available"] is True
    assert data["route_code"] == "DEL-BOM"
    assert len(data["curve_points"]) >= 4

    # Verify days_before_departure includes 45 (T+45)
    days_present = [pt["days_before_departure"] for pt in data["curve_points"]]
    assert 45 in days_present, f"Expected 45 in curve points, got: {days_present}"
    assert 30 in days_present
    assert 1 in days_present

    # Verify elasticity curve structure
    pt_t45 = next(
        (p for p in data["curve_points"] if p["days_before_departure"] == 45), None
    )
    assert pt_t45 is not None
    assert pt_t45["avg_fare_inr"] > 0
    assert pt_t45["median_fare_inr"] > 0
    assert pt_t45["elasticity_factor"] is not None

    # T+1 urgent should show higher fare than T+45 baseline
    pt_t1 = next(
        (p for p in data["curve_points"] if p["days_before_departure"] == 1), None
    )
    assert pt_t1 is not None
    assert pt_t1["median_fare_inr"] > pt_t45["median_fare_inr"]
    assert pt_t1["elasticity_factor"] > pt_t45["elasticity_factor"]


def test_visual_3_price_elasticity_endpoint(api_client: TestClient) -> None:
    """Visual 3: Econometrics price elasticity gradient endpoint."""
    response = api_client.get("/api/v1/econometrics/elasticity?route_code=DEL-BOM")
    assert response.status_code == 200
    data = response.json()
    assert data["route_code"] == "DEL-BOM"
    assert "curves" in data
    assert len(data["curves"]) >= 1


# =============================================================================
# Visual 4: Econometric Comparisons (Fisher, Laspeyres, Paasche, CPI Gap)
# =============================================================================


def test_visual_4_econometric_indices_decomposition(api_client: TestClient) -> None:
    """Visual 4: Axiomatic dual-index decomposition (Fisher, Laspeyres, Paasche)."""
    response = api_client.get("/api/v1/econometrics/indices?route_code=NATIONAL")
    assert response.status_code == 200
    data = response.json()

    assert "fisher_index" in data
    assert "laspeyres_index" in data
    assert "paasche_index" in data
    assert "substitution_bias" in data

    # Verify Fisher Ideal is approximately geometric mean: sqrt(L * P)
    laspeyres = data["laspeyres_index"]
    paasche = data["paasche_index"]
    fisher = data["fisher_index"]
    expected_fisher = (laspeyres * paasche) ** 0.5
    assert abs(fisher - expected_fisher) < 0.2

    # Verify substitution bias: Delta = L - P
    bias = data["substitution_bias"]
    assert abs(bias - (laspeyres - paasche)) < 0.2


def test_visual_4_cpi_divergence_series(api_client: TestClient) -> None:
    """Visual 4: MoSPI CPI Transport sub-index divergence series."""
    response = api_client.get("/api/v1/econometrics/cpi-divergence")
    assert response.status_code == 200
    data = response.json()

    assert "divergence_series" in data
    assert len(data["divergence_series"]) >= 1
    point = data["divergence_series"][0]
    assert "date" in point
    assert "apix_index" in point
    assert "mospi_cpi" in point
    assert "gap" in point


# =============================================================================
# Contract & Governance: OpenAPI, Rate Limits, CORS, Auth
# =============================================================================


def test_contract_openapi_schema_available(api_client: TestClient) -> None:
    """Contract: OpenAPI 3.1 JSON schema is discoverable at /api/v1/openapi.json."""
    response = api_client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    schema = response.json()

    assert schema["openapi"].startswith("3.")
    assert "info" in schema
    assert "paths" in schema
    assert "/api/v1/indices/national/latest" in schema["paths"]
    assert "/api/v1/analytics/sector-heatmap" in schema["paths"]
    assert "/api/v1/analytics/lead-time-curve" in schema["paths"]
    assert "/api/v1/econometrics/indices" in schema["paths"]
    assert "/api/v1/econometrics/cpi-divergence" in schema["paths"]


def test_contract_rate_limit_headers(api_client: TestClient) -> None:
    """Contract: Every response carries X-RateLimit-Limit and X-RateLimit-Remaining."""
    response = api_client.get("/api/v1/indices/national/latest")
    assert response.status_code == 200
    assert "x-ratelimit-limit" in response.headers
    assert "x-ratelimit-remaining" in response.headers
    assert (
        int(response.headers["x-ratelimit-limit"]) == settings.API_RATE_LIMIT_REQUESTS
    )
    assert int(response.headers["x-ratelimit-remaining"]) >= 0


def test_contract_cors_rejects_wildcard() -> None:
    """Contract: CORS startup validator strictly rejects wildcard '*' origin."""
    # Settings validates that wildcard '*' is disallowed

    with pytest.raises(ValidationError):
        Settings(BACKEND_CORS_ORIGINS=["*"])


def test_contract_protected_endpoint_requires_auth(api_client: TestClient) -> None:
    """Contract: Administrative mutation endpoints require authentication."""
    response = api_client.post("/api/v1/econometrics/recalculate")
    # Rejected with 401 when unauthenticated
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers
