"""Endpoints must not invent measurements when the database is empty."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.main import app
from backend.app.models.econometrics import (
    DgcaViolation,
    EconometricIndex,
    MospiCpiSeries,
)
from backend.app.models.raw_fare import RawFare


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Call the real app against an empty schema, not the process database."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_dgca_violations_empty_database_returns_zero_items(client: TestClient) -> None:
    """Given no violation rows, the audit feed is empty and evaluates nothing."""
    response = client.get("/api/v1/econometrics/dgca-violations")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["violations"] == []
    assert body["total_evaluated"] == 0
    assert body["total_violations"] == 0
    assert body["data_available"] is False
    assert body["carrier_distribution"] == []
    assert body["summary"]["top_violating_carriers"] == []
    assert "6E-205" not in response.text
    assert "18500" not in response.text


def test_cpi_divergence_empty_database_returns_null_correlation(
    client: TestClient,
) -> None:
    """Given no overlapping observations, correlation and lead are absent."""
    response = client.get("/api/v1/econometrics/cpi-divergence")

    assert response.status_code == 200
    body = response.json()
    assert body["correlation_coefficient"] is None
    assert body["summary"]["correlation"] is None
    assert body["summary"]["optimal_lead_days"] is None
    assert body["inflation_lead_days"] is None
    assert body["data_available"] is False
    assert body["divergence_series"] == []
    assert body["reason"] == "insufficient overlapping observations"
    assert "0.89" not in response.text


def test_cpi_gap_alias_empty_database_returns_null_correlation(
    client: TestClient,
) -> None:
    """The alias must fail closed the same way as /cpi-divergence."""
    response = client.get("/api/v1/econometrics/cpi-gap")

    assert response.status_code == 200
    assert response.json()["correlation_coefficient"] is None
    assert response.json()["summary"]["optimal_lead_days"] is None


def test_elasticity_empty_database_returns_empty_series(client: TestClient) -> None:
    """Given no route_elasticity rows, the curve is empty."""
    response = client.get("/api/v1/econometrics/elasticity?route_code=DEL-BOM")

    assert response.status_code == 200
    body = response.json()
    assert body["route_code"] == "DEL-BOM"
    assert body["gradient_points"] == []
    assert body["curves"] == []
    assert body["segments"] is None
    assert body["data_available"] is False
    assert "4850" not in response.text
    assert "12900" not in response.text


def test_indices_empty_database_returns_no_computed_values(client: TestClient) -> None:
    """Given no index rows, the series is empty rather than a generated path."""
    response = client.get("/api/v1/econometrics/indices")

    assert response.status_code == 200
    body = response.json()
    assert body["series"] == []
    assert body["items"] == []
    assert body["total"] == 0
    assert body["data_available"] is False
    assert body["fisher_index"] is None
    assert body["laspeyres_index"] is None
    assert body["paasche_index"] is None
    assert body["substitution_bias"] is None


def test_recalculate_without_raw_fares_fails(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recompute with no fares must not report success or write a constant index."""
    monkeypatch.setenv("APIX_API_KEYS", "test-observer-key")

    response = client.post(
        "/api/v1/econometrics/recalculate",
        headers={"X-API-Key": "test-observer-key"},
        json={"route_code": "NATIONAL", "calculation_method": "chain_weighted"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "no raw fares available to compute an index"
    stored = db_session.execute(
        select(func.count()).select_from(EconometricIndex)
    ).scalar_one()
    assert stored == 0


def test_compiled_admin_key_is_rejected(client: TestClient) -> None:
    """The previously compiled admin key is not a credential."""
    response = client.post(
        "/api/v1/econometrics/recalculate",
        headers={"X-API-Key": "apix-admin-key-2026"},
        json={"route_code": "NATIONAL"},
    )

    assert response.status_code == 401


def test_published_ingestion_key_is_rejected_outside_development(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside development, the published default is not accepted as a configured key."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("APIX_API_KEYS", raising=False)
    monkeypatch.delenv("INGESTION_API_KEY", raising=False)

    response = client.post(
        "/api/v1/econometrics/recalculate",
        headers={"X-API-Key": "apix-ingestion-secret-key-2026"},
        json={"route_code": "NATIONAL"},
    )

    assert response.status_code == 401


def test_recalculate_writes_the_index_computed_from_raw_fares(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fare that doubles from the base date produces an index of 200, not 118.50."""
    monkeypatch.setenv("APIX_API_KEYS", "test-observer-key")
    db_session.add_all(
        [
            RawFare(
                batch_id="recalc-base",
                origin="DEL",
                destination="BOM",
                flight_date=date(2026, 1, 15),
                booking_window="T+30",
                airline_code="6E",
                flight_number="6E-1",
                total_fare=4000.0,
                source_platform="verification",
                scraped_at=datetime(2026, 1, 1, tzinfo=UTC),
                hash_id="recalc-base",
            ),
            RawFare(
                batch_id="recalc-current",
                origin="DEL",
                destination="BOM",
                flight_date=date(2026, 2, 15),
                booking_window="T+30",
                airline_code="6E",
                flight_number="6E-1",
                total_fare=8000.0,
                source_platform="verification",
                scraped_at=datetime(2026, 2, 1, tzinfo=UTC),
                hash_id="recalc-current",
            ),
        ]
    )
    db_session.commit()

    response = client.post(
        "/api/v1/econometrics/recalculate",
        headers={"X-API-Key": "test-observer-key"},
        json={"route_code": "NATIONAL", "calculation_method": "chain_weighted"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["routes_processed"] == 1
    assert body["indices_generated"] == 1
    stored = db_session.execute(select(EconometricIndex)).scalar_one()
    assert stored.laspeyres_index == 200.0
    assert stored.paasche_index == 200.0
    assert stored.fisher_ideal_index == 200.0
    assert stored.substitution_bias == 0.0


def test_dgca_carrier_stats_follow_the_stored_row(
    client: TestClient,
    db_session: Session,
) -> None:
    """A stored violation replaces the hardcoded carrier table."""
    db_session.add(
        DgcaViolation(
            route_code="DEL-BOM",
            airline_code="SG",
            flight_number="SG-1",
            flight_date=date(2026, 3, 1),
            window="T+7",
            fare_inr=4321.0,
            median_baseline_fare=3000.0,
            surge_multiple=1.5,
            severity="WARNING",
            violation_code="PREDATORY-PRICING",
            detected_at=datetime(2026, 3, 1, tzinfo=UTC),
            status="OPEN",
        )
    )
    db_session.commit()

    response = client.get("/api/v1/econometrics/dgca-violations")

    assert response.status_code == 200
    body = response.json()
    assert body["total_evaluated"] == 1
    assert body["data_available"] is True
    assert body["items"][0]["observed_fare_inr"] == 4321.0
    assert body["items"][0]["flight_number"] == "SG-1"
    assert body["carrier_distribution"] == [
        {
            "carrier_code": "SG",
            "carrier_name": "SpiceJet",
            "avg_surge_multiplier": 1.5,
            "violations_count": 1,
            "compliance_rate": None,
        }
    ]
    assert body["summary"]["top_violating_carriers"] == [
        {"airline_code": "SG", "violations": 1}
    ]


def test_cpi_divergence_correlation_is_computed_from_overlapping_rows(
    client: TestClient,
    db_session: Session,
) -> None:
    """Perfectly aligned series correlate at 1 and do not report a 38-day lead."""
    for month, mospi, apix in (
        ("2026-01", 100.0, 110.0),
        ("2026-02", 110.0, 120.0),
        ("2026-03", 120.0, 130.0),
    ):
        db_session.add(
            MospiCpiSeries(
                year_month=month,
                cpi_transport_index=mospi,
                airfare_sub_index=mospi,
                headline_cpi=mospi,
                published_at=date.fromisoformat(f"{month}-12"),
                source="https://www.mospi.gov.in/press-note/cpi-example",
            )
        )
        db_session.add(
            EconometricIndex(
                date=date.fromisoformat(f"{month}-15"),
                route_code="NATIONAL",
                laspeyres_index=apix,
                paasche_index=apix,
                fisher_ideal_index=apix,
                substitution_bias=0.0,
                calculation_method="chain_weighted",
            )
        )
    db_session.commit()

    response = client.get("/api/v1/econometrics/cpi-divergence")

    assert response.status_code == 200
    body = response.json()
    assert body["correlation_coefficient"] == 1.0
    assert body["summary"]["correlation"] == 1.0
    assert body["summary"]["optimal_lead_days"] == 0
    assert body["inflation_lead_days"] == 0
    assert body["data_available"] is True
    assert [point["apix_index"] for point in body["divergence_series"]] == [
        110.0,
        120.0,
        130.0,
    ]
