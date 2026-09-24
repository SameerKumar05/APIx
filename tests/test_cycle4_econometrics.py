"""Integration test suite for APIx Cycle 4 econometrics, CPI gap analytics,
lead-time elasticity, and DGCA tariff surveillance APIs.

SIH 2026 Problem Statement 26056 - Real-time Airfare Price Index for CPI Augmentation
"""

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.session import Base, engine
from backend.app.main import app
from backend.app.schemas.econometrics import (
    CpiDivergenceResponse,
    DgcaViolationsResponse,
    EconometricIndicesResponse,
    ElasticityResponse,
)

# Ensure database schema exists
Base.metadata.create_all(bind=engine)

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "apix-admin-key-2026"}


class TestEconometricIndicesEndpoint:
    """Tests for GET /api/v1/econometrics/indices."""

    def test_default_indices(self):
        res = client.get("/api/v1/econometrics/indices")
        assert res.status_code == 200
        data = res.json()
        validated = EconometricIndicesResponse.model_validate(data)
        assert validated.base_period == "2024-Q1"
        assert len(validated.series) >= 1
        assert validated.summary is not None
        assert validated.laspeyres_index >= validated.paasche_index - 1.0

    def test_route_filter(self):
        res = client.get("/api/v1/econometrics/indices?route_code=DEL-BOM")
        assert res.status_code == 200
        data = res.json()
        assert all(pt["route_code"] == "DEL-BOM" for pt in data["series"])

    def test_limit_filter(self):
        res = client.get("/api/v1/econometrics/indices?limit=5")
        assert res.status_code == 200
        data = res.json()
        assert len(data["series"]) <= 5


class TestCpiDivergenceEndpoint:
    """Tests for GET /api/v1/econometrics/cpi-divergence and /cpi-gap."""

    def test_default_cpi_divergence(self):
        res = client.get("/api/v1/econometrics/cpi-divergence")
        assert res.status_code == 200
        data = res.json()
        validated = CpiDivergenceResponse.model_validate(data)
        assert validated.inflation_lead_days > 0
        assert validated.correlation_coefficient > 0.0
        assert len(validated.divergence_series) >= 1

    def test_cpi_gap_alias(self):
        res = client.get("/api/v1/econometrics/cpi-gap")
        assert res.status_code == 200
        data = res.json()
        validated = CpiDivergenceResponse.model_validate(data)
        assert validated.current_divergence_pts is not None

    def test_custom_lag_and_months(self):
        res = client.get("/api/v1/econometrics/cpi-divergence?months=6&lag_days=45")
        assert res.status_code == 200
        data = res.json()
        assert data["inflation_lead_days"] == 45


class TestElasticityEndpoint:
    """Tests for GET /api/v1/econometrics/elasticity."""

    def test_default_elasticity(self):
        res = client.get("/api/v1/econometrics/elasticity")
        assert res.status_code == 200
        data = res.json()
        validated = ElasticityResponse.model_validate(data)
        assert validated.route_code == "NATIONAL"
        assert len(validated.gradient_points) == 4
        assert validated.segments is not None
        assert validated.segments.avg_lead_time_decay > 0

        # Monotonic price progression
        fares = [pt.avg_fare_inr for pt in validated.gradient_points]
        assert fares[0] < fares[1] < fares[2] < fares[3]

    def test_corridor_elasticity(self):
        res = client.get("/api/v1/econometrics/elasticity?route_code=BOM-BLR")
        assert res.status_code == 200
        data = res.json()
        assert data["route_code"] == "BOM-BLR"
        assert data["segments"]["t1_t7"] > 1.0


class TestDgcaSurveillanceEndpoint:
    """Tests for GET /api/v1/econometrics/dgca-violations."""

    def test_default_violations_feed(self):
        res = client.get("/api/v1/econometrics/dgca-violations")
        assert res.status_code == 200
        data = res.json()
        validated = DgcaViolationsResponse.model_validate(data)
        assert validated.total_violations >= 1
        assert len(validated.carrier_distribution) >= 1

    def test_severity_filter(self):
        res = client.get("/api/v1/econometrics/dgca-violations?severity=SEVERE")
        assert res.status_code == 200
        data = res.json()
        assert all(v["severity"] == "SEVERE" for v in data["violations"])

    def test_airline_filter(self):
        res = client.get("/api/v1/econometrics/dgca-violations?airline_code=6E")
        assert res.status_code == 200
        data = res.json()
        assert all(v["carrier_code"] == "6E" for v in data["violations"])

    def test_anomalies_alias(self):
        res = client.get("/api/v1/anomalies/dgca-violations")
        assert res.status_code == 200
        data = res.json()
        assert "violations" in data


class TestAuthenticationAndMutations:
    """Tests for security, authentication, and mutation endpoints."""

    def test_invalid_key_rejection(self):
        res = client.get("/api/v1/econometrics/indices", headers={"X-API-Key": "invalid-xyz"})
        assert res.status_code == 401

    def test_valid_keys_accepted(self):
        res = client.get("/api/v1/econometrics/indices", headers=AUTH_HEADERS)
        assert res.status_code == 200

        res2 = client.get("/api/v1/econometrics/indices", headers={"X-Ingestion-Key": settings.INGESTION_API_KEY})
        assert res2.status_code == 200

    def test_recalculate_security(self):
        # Unauthenticated
        res1 = client.post("/api/v1/econometrics/recalculate", json={})
        assert res1.status_code == 401

        # Authenticated
        res2 = client.post(
            "/api/v1/econometrics/recalculate",
            json={"route_code": "DEL-BOM"},
            headers=AUTH_HEADERS,
        )
        assert res2.status_code == 200
        assert res2.json()["status"] == "SUCCESS"

    def test_violation_status_patch(self):
        # Unauthenticated
        res1 = client.patch(
            "/api/v1/econometrics/dgca-violations/dgca-v-001/status",
            json={"status": "CONFIRMED"},
        )
        assert res1.status_code == 401

        # Authenticated
        res2 = client.patch(
            "/api/v1/econometrics/dgca-violations/dgca-v-001/status",
            json={"status": "CONFIRMED", "notes": "Auditor checked"},
            headers=AUTH_HEADERS,
        )
        assert res2.status_code == 200
        assert res2.json()["status"] == "CONFIRMED"

    def test_violation_acknowledge(self):
        res = client.post(
            "/api/v1/econometrics/dgca-violations/dgca-v-002/acknowledge",
            headers=AUTH_HEADERS,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "UNDER_REVIEW"
