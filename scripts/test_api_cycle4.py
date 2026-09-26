#!/usr/bin/env python3
"""
APIx Airfare Price Index - Cycle 4 Econometrics & DGCA Surveillance Test Suite.
Verifies all Cycle 4 endpoints:
1. GET  /api/v1/econometrics/indices (Fisher, Paasche, Laspeyres, and substitution bias series)
2. GET  /api/v1/econometrics/cpi-divergence (APIx Index vs MoSPI CPI Transport Sub-Index & lead-lag)
3. GET  /api/v1/econometrics/cpi-gap (Alias endpoint for CPI divergence)
4. GET  /api/v1/econometrics/elasticity (Dynamic lead-time price elasticity curves T+1 -> T+30)
5. GET  /api/v1/econometrics/dgca-violations (Statutory tariff surveillance audit feed with filters)
6. GET  /api/v1/anomalies/dgca-violations (Cross-mounted anomaly alias endpoint)
7. POST /api/v1/econometrics/recalculate (Secured administrative recomputation trigger)
8. PATCH/POST /api/v1/econometrics/dgca-violations/{id}/status & /acknowledge (Secured review status)

Validates authentication rejection/acceptance, query parameter filtering, live DB persistence,
and calibrated mock fallback resilience.
"""

from __future__ import annotations

import os
import sys

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.econometrics_repo import (
    record_dgca_violation,
    upsert_econometric_index,
)
from backend.app.db.session import Base, SessionLocal, engine
from backend.app.main import app
from backend.app.models.econometrics import DgcaViolation, RouteElasticity
from backend.app.models.raw_fare import RawFare

# Ensure all database tables exist cleanly
Base.metadata.create_all(bind=engine)

# The elasticity curve is derived from stored fares, and this script runs against a
# freshly created database. Fares escalate toward departure so the gradient has the
# descending-demand shape the assertions below check.
with SessionLocal() as fare_db:
    for window, fare in (
        ("T+30", 4000.0),
        ("T+15", 4500.0),
        ("T+7", 5200.0),
        ("T+1", 6100.0),
    ):
        fare_db.add(
            RawFare(
                batch_id=1,
                origin="DEL",
                destination="BOM",
                flight_date=date.today() + timedelta(days=30),
                booking_window=window,
                airline_code="6E",
                flight_number=f"6E-el-{window}",
                stops=0,
                fare_class="ECONOMY",
                base_fare=fare - 500.0,
                taxes_and_fees=500.0,
                total_fare=fare,
                source_platform="synthetic",
                scraped_at=datetime.now(UTC),
                hash_id=f"cycle4-el-{window}",
                is_synthetic=True,
            )
        )
    for window, fare in (
        ("T+30", 4000.0),
        ("T+15", 4500.0),
        ("T+7", 5200.0),
        ("T+1", 6100.0),
    ):
        fare_db.add(
            RawFare(
                batch_id=1,
                origin="ELA",
                destination="STL",
                flight_date=date.today() + timedelta(days=30),
                booking_window=window,
                airline_code="6E",
                flight_number=f"6E-ela-{window}",
                stops=0,
                fare_class="ECONOMY",
                base_fare=fare - 500.0,
                taxes_and_fees=500.0,
                total_fare=fare,
                source_platform="synthetic",
                scraped_at=datetime.now(UTC),
                hash_id=f"cycle4-ela-{window}",
                is_synthetic=True,
            )
        )
    fare_db.commit()

# The elasticity endpoint returns an empty gradient when no RouteElasticity row
# exists, so the curve needs one. Elasticities are negative: demand slopes down.
with SessionLocal() as el_db:
    for target in ("NATIONAL", "BOM-BLR", "ELA-STL"):
        el_db.add(
            RouteElasticity(
                route_code=target,
                calculation_date=date.today(),
                t1_t7_elasticity=-0.42,
                t7_t15_elasticity=-0.38,
                t15_t30_elasticity=-0.31,
                avg_lead_time_decay=38.0,
                confidence_score=0.8,
                created_at=datetime.now(UTC),
            )
        )
    el_db.commit()

# The indices endpoint reads stored EconometricIndex rows; this script runs against a
# fresh database, so seed a short series. Laspeyres is held at or above Paasche to
# respect the substitution property the assertions below check.
with SessionLocal() as idx_db:
    for target in ("NATIONAL", "DEL-BOM"):
        for offset in range(3):
            upsert_econometric_index(
                db=idx_db,
                date=date.today() - timedelta(days=2 - offset),
                route_code=target,
                laspeyres_index=100.0 + offset,
                paasche_index=99.5 + offset,
                fisher_ideal_index=99.75 + offset,
                substitution_bias=0.5,
                calculation_method="chain_weighted",
                commit=False,
            )
    idx_db.commit()

# The DGCA feed reports stored violation rows; this script runs against a fresh
# database, so seed a couple of breaches above their statutory band cap.
with SessionLocal() as v_db:
    for target in ("DEL-BOM", "BOM-BLR"):
        v_db.add(
            DgcaViolation(
                route_code=target,
                airline_code="6E",
                flight_number=f"6E-v-{target}",
                flight_date=date.today(),
                window="T+7",
                fare_inr=10200.0,
                median_baseline_fare=5000.0,
                surge_multiple=2.04,
                severity="CRITICAL",
                violation_code="DGCA_CAP_EXCEEDED",
                detected_at=datetime.now(UTC),
                status="OPEN",
            )
        )
    # A SEVERE row is needed for the severity-filter test, and SEVERE is defined
    # as a 3.0x surge, so it cannot reuse the 2.04x CRITICAL value.
    v_db.add(
        DgcaViolation(
            route_code="DEL-BOM",
            airline_code="6E",
            flight_number="6E-v-severe",
            flight_date=date.today(),
            window="T+7",
            fare_inr=15500.0,
            median_baseline_fare=5000.0,
            surge_multiple=3.1,
            severity="SEVERE",
            violation_code="DGCA_CAP_EXCEEDED",
            detected_at=datetime.now(UTC),
            status="OPEN",
        )
    )
    v_db.commit()

# The API refuses compiled-in admin tokens and reads keys from APIX_API_KEYS at
# request time, so the script has to supply the key it then sends.
_ADMIN_KEY = "cycle4-verification-key"
os.environ["APIX_API_KEYS"] = _ADMIN_KEY

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": _ADMIN_KEY}
INVALID_AUTH_HEADERS = {"X-API-Key": "completely-invalid-key-xyz"}


def test_econometric_indices_default():
    print("[TEST 1/22] GET /api/v1/econometrics/indices (default)")
    res = client.get("/api/v1/econometrics/indices")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "base_period" in data
    assert "laspeyres_index" in data
    assert "paasche_index" in data
    assert "fisher_index" in data
    assert "substitution_bias" in data
    assert "series" in data
    assert len(data["series"]) >= 1, "Expected series points"
    assert "summary" in data and data["summary"] is not None

    latest_pt = data["series"][-1]
    assert "laspeyres" in latest_pt
    assert "paasche" in latest_pt
    assert "fisher" in latest_pt
    # Axiomatic economic property check: P_L >= P_P under typical substitution
    assert (
        latest_pt["laspeyres"] >= latest_pt["paasche"] - 1.0
    ), "Expected Laspeyres >= Paasche"
    print(
        f"  ✓ Verified: base={data['base_period']}, L={data['laspeyres_index']}, P={data['paasche_index']}, F={data['fisher_index']}, bias={data['substitution_bias']}"
    )


def test_econometric_indices_route_filtering():
    print("[TEST 2/22] GET /api/v1/econometrics/indices?route_code=DEL-BOM")
    res = client.get("/api/v1/econometrics/indices?route_code=DEL-BOM")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert all(
        pt["route_code"] == "DEL-BOM" for pt in data["series"]
    ), "All points must have route_code=DEL-BOM"
    print(f"  ✓ Route filtering verified: {len(data['series'])} points for DEL-BOM")


def test_econometric_indices_limit_filtering():
    print("[TEST 3/22] GET /api/v1/econometrics/indices?limit=7")
    res = client.get("/api/v1/econometrics/indices?limit=7")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert len(data["series"]) <= 7, f"Expected <= 7 points, got {len(data['series'])}"
    print(
        f"  ✓ Limit filtering verified: received {len(data['series'])} points (requested 7)"
    )


def test_cpi_divergence_default():
    print("[TEST 4/22] GET /api/v1/econometrics/cpi-divergence (default)")
    res = client.get("/api/v1/econometrics/cpi-divergence")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "current_divergence_pts" in data
    assert "inflation_lead_days" in data
    assert "correlation_coefficient" in data
    assert "divergence_series" in data
    # No verified MoSPI series is bundled, so the endpoint must report no
    # comparison rather than emit a positive gap, lead and correlation.
    if data.get("data_available"):
        assert len(data["divergence_series"]) >= 1
        assert data["inflation_lead_days"] > 0, "Expected positive lead days"
        assert data["correlation_coefficient"] > 0.0, "Expected positive correlation"
        first_pt = data["divergence_series"][0]
        assert "date" in first_pt
        assert "apix_index" in first_pt
        assert "mospi_cpi" in first_pt
        assert "gap" in first_pt
        print(
            f"  ✓ CPI divergence verified: lead={data['inflation_lead_days']}d, "
            f"corr={data['correlation_coefficient']}, "
            f"spread={data['current_divergence_pts']} pts"
        )
    else:
        assert data["divergence_series"] == []
        assert data["current_divergence_pts"] is None
        assert data["inflation_lead_days"] is None
        assert data["correlation_coefficient"] is None
        print("  ✓ CPI divergence correctly reports no comparison (no verified series)")


def test_cpi_divergence_params_filtering():
    print("[TEST 5/22] GET /api/v1/econometrics/cpi-divergence?months=6&lag_days=45")
    res = client.get("/api/v1/econometrics/cpi-divergence?months=6&lag_days=45")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    # With no verified series there is no lead to report, so the endpoint returns
    # None rather than echoing the requested lag back as if it had been measured.
    if data.get("data_available"):
        assert (
            data["inflation_lead_days"] == 45
        ), f"Expected lag_days=45, got {data['inflation_lead_days']}"
        print("  ✓ Custom lag_days and lookback parameters accepted")
    else:
        assert data["inflation_lead_days"] is None
        print("  ✓ Parameters accepted; no lead reported without a verified series")


def test_cpi_gap_alias_endpoint():
    print("[TEST 6/22] GET /api/v1/econometrics/cpi-gap (alias endpoint)")
    res = client.get("/api/v1/econometrics/cpi-gap")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert "current_divergence_pts" in data
    assert "divergence_series" in data
    print("  ✓ /cpi-gap alias verified identically")


def test_elasticity_default():
    print("[TEST 7/22] GET /api/v1/econometrics/elasticity (default)")
    res = client.get("/api/v1/econometrics/elasticity?route_code=ELA-STL")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "route_code" in data
    assert "gradient_points" in data
    assert (
        len(data["gradient_points"]) == 4
    ), f"Expected 4 lead windows (T+30, T+15, T+7, T+1), got {len(data['gradient_points'])}"
    assert "segments" in data and data["segments"] is not None

    windows = [pt["lead_window"] for pt in data["gradient_points"]]
    assert windows == ["T+30", "T+15", "T+7", "T+1"], f"Unexpected windows: {windows}"

    # Price should increase as departure approaches (T+30 < T+15 < T+7 < T+1)
    fares = [pt["avg_fare_inr"] for pt in data["gradient_points"]]
    assert (
        fares[0] < fares[1] < fares[2] < fares[3]
    ), f"Expected monotonic price escalation: {fares}"

    # Elasticities should be negative where defined. T+30 is the baseline window and
    # has no preceding segment, so the endpoint reports no elasticity for it.
    for pt in data["gradient_points"]:
        if pt["price_elasticity"] is None:
            assert (
                pt["lead_window"] == "T+30"
            ), f"Only the T+30 baseline may omit elasticity, got {pt['lead_window']}"
            continue
        assert (
            pt["price_elasticity"] < 0
        ), f"Elasticity must be negative, got {pt['price_elasticity']}"
    print(
        f"  ✓ Elasticity curve verified: fares {fares[0]} -> {fares[-1]} INR, decay lambda={data['segments']['avg_lead_time_decay']}"
    )


def test_elasticity_route_filtering():
    print("[TEST 8/22] GET /api/v1/econometrics/elasticity?route_code=BOM-BLR")
    res = client.get("/api/v1/econometrics/elasticity?route_code=BOM-BLR")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert data["route_code"] == "BOM-BLR"
    # segments.t1_t7 carries the T+1 to T+7 price elasticity, not a surge
    # multiplier, so it is negative. The point of this test is that the
    # corridor-specific lookup resolved at all.
    assert (
        data["segments"]["t1_t7"] < 0.0
    ), f"Expected negative T+1 to T+7 elasticity, got {data['segments']['t1_t7']}"
    print(
        f"  ✓ Corridor-specific elasticity verified for BOM-BLR: t1_t7={data['segments']['t1_t7']}"
    )


def test_dgca_violations_default():
    print("[TEST 9/22] GET /api/v1/econometrics/dgca-violations (default feed)")
    res = client.get("/api/v1/econometrics/dgca-violations")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert "violations" in data
    assert "carrier_distribution" in data
    assert "total_evaluated" in data
    assert "total_violations" in data
    assert len(data["violations"]) >= 1, "Expected flagged violations"
    assert len(data["carrier_distribution"]) >= 1, "Expected carrier breakdown"

    v = data["violations"][0]
    assert "id" in v
    assert "route_code" in v
    assert "carrier_code" in v
    assert "carrier_name" in v
    assert "flight_number" in v
    assert "observed_fare_inr" in v
    assert "statutory_band_cap_inr" in v
    assert "surge_multiplier" in v
    assert "severity" in v
    assert v["severity"] in ("WARNING", "CRITICAL", "SEVERE")
    assert v["surge_multiplier"] >= 2.0, "Violations must have surge >= 2.0x"
    print(
        f"  ✓ Violations feed verified: {len(data['violations'])} violations across {len(data['carrier_distribution'])} carriers"
    )


def test_dgca_violations_severity_filter():
    print("[TEST 10/22] GET /api/v1/econometrics/dgca-violations?severity=SEVERE")
    res = client.get("/api/v1/econometrics/dgca-violations?severity=SEVERE")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert len(data["violations"]) >= 1, "Expected at least 1 SEVERE violation"
    assert all(
        v["severity"] == "SEVERE" for v in data["violations"]
    ), "All returned violations must be SEVERE"
    assert all(
        v["surge_multiplier"] >= 3.0 for v in data["violations"]
    ), "SEVERE violations must have surge >= 3.0x"
    print(
        f"  ✓ Severity filter verified: {len(data['violations'])} SEVERE violations (all surge >= 3.0x)"
    )


def test_dgca_violations_airline_filter():
    print("[TEST 11/22] GET /api/v1/econometrics/dgca-violations?airline_code=6E")
    res = client.get("/api/v1/econometrics/dgca-violations?airline_code=6E")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert all(
        v["carrier_code"] == "6E" for v in data["violations"]
    ), "All returned violations must be 6E"
    assert all(
        c["carrier_code"] == "6E" for c in data["carrier_distribution"]
    ), "Distribution filtered to 6E"
    print(
        f"  ✓ Airline filter verified: {len(data['violations'])} violations for carrier 6E"
    )


def test_dgca_violations_route_filter():
    print("[TEST 12/22] GET /api/v1/econometrics/dgca-violations?route_code=DEL-BOM")
    res = client.get("/api/v1/econometrics/dgca-violations?route_code=DEL-BOM")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert all(
        v["route_code"] == "DEL-BOM" for v in data["violations"]
    ), "All returned violations must be DEL-BOM"
    print(
        f"  ✓ Corridor filter verified: {len(data['violations'])} violations on DEL-BOM"
    )


def test_dgca_violations_anomalies_alias():
    print("[TEST 13/22] GET /api/v1/anomalies/dgca-violations (cross-mount alias)")
    res = client.get("/api/v1/anomalies/dgca-violations")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.json()
    assert "violations" in data and len(data["violations"]) >= 1
    print("  ✓ Anomaly cross-mounted alias /anomalies/dgca-violations verified")


def test_authentication_rejection_invalid_token():
    print("[TEST 14/22] Authentication security: invalid key rejection")
    res = client.get("/api/v1/econometrics/indices", headers=INVALID_AUTH_HEADERS)
    assert (
        res.status_code == 401
    ), f"Expected 401 for invalid auth, got {res.status_code}"
    assert "Invalid API key" in res.text
    print("  ✓ Invalid API key rejected with 401 Unauthorized")


def test_authentication_acceptance_valid_tokens():
    print("[TEST 15/22] Authentication security: valid credentials accepted")
    # 1. X-API-Key
    res1 = client.get("/api/v1/econometrics/indices", headers={"X-API-Key": _ADMIN_KEY})
    assert res1.status_code == 200, f"Expected 200, got {res1.status_code}"

    # 2. X-Ingestion-Key
    res2 = client.get(
        "/api/v1/econometrics/indices",
        headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
    )
    assert res2.status_code == 200, f"Expected 200, got {res2.status_code}"

    # 3. Bearer Authorization
    res3 = client.get(
        "/api/v1/econometrics/indices",
        headers={"Authorization": f"Bearer {_ADMIN_KEY}"},
    )
    assert res3.status_code == 200, f"Expected 200, got {res3.status_code}"
    print(
        "  ✓ Valid X-API-Key, X-Ingestion-Key, and Bearer token authorized successfully"
    )


def test_recalculate_unauthenticated_rejection():
    print("[TEST 16/22] POST /api/v1/econometrics/recalculate without auth")
    res = client.post("/api/v1/econometrics/recalculate", json={})
    assert (
        res.status_code == 401
    ), f"Expected 401 for unauthenticated recalculate, got {res.status_code}"
    print("  ✓ Unauthenticated recalculation request rejected with 401")


def test_recalculate_authenticated_execution():
    print("[TEST 17/22] POST /api/v1/econometrics/recalculate with valid auth")
    payload = {"route_code": "DEL-BOM", "calculation_method": "chain_weighted"}
    res = client.post(
        "/api/v1/econometrics/recalculate", json=payload, headers=AUTH_HEADERS
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "DEL-BOM" in data["message"]
    assert data["indices_generated"] >= 1
    assert "timestamp" in data
    print(f"  ✓ Recomputation executed successfully: {data['message']}")


def test_violation_status_patch_unauthenticated():
    print(
        "[TEST 18/22] PATCH /api/v1/econometrics/dgca-violations/{id}/status without auth"
    )
    res = client.patch(
        "/api/v1/econometrics/dgca-violations/dgca-v-001/status",
        json={"status": "CONFIRMED", "notes": "Unauthenticated test"},
    )
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"
    print("  ✓ Unauthenticated violation status modification rejected with 401")


def test_violation_status_patch_authenticated():
    print(
        "[TEST 19/22] PATCH /api/v1/econometrics/dgca-violations/{id}/status with valid auth"
    )
    res = client.patch(
        "/api/v1/econometrics/dgca-violations/dgca-v-001/status",
        json={"status": "CONFIRMED", "notes": "Auditor confirmed tariff gouging"},
        headers=AUTH_HEADERS,
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["id"] == "dgca-v-001"
    assert data["status"] == "CONFIRMED"
    assert data["notes"] == "Auditor confirmed tariff gouging"
    print(f"  ✓ Violation review status patched to CONFIRMED for id={data['id']}")


def test_violation_acknowledge_authenticated():
    print(
        "[TEST 20/22] POST /api/v1/econometrics/dgca-violations/{id}/acknowledge with valid auth"
    )
    res = client.post(
        "/api/v1/econometrics/dgca-violations/dgca-v-002/acknowledge",
        headers=AUTH_HEADERS,
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["status"] == "UNDER_REVIEW"
    print(f"  ✓ Violation {data['id']} acknowledged to status=UNDER_REVIEW")


def test_database_persistence_and_live_query():
    print("[TEST 21/22] Database persistence and live repository integration")
    db = SessionLocal()
    unique_route = "HYD-BLR"
    today_str = date.today().isoformat()

    # 1. Upsert live econometric index
    upsert_econometric_index(
        db=db,
        date=today_str,
        route_code=unique_route,
        laspeyres_index=124.80,
        paasche_index=119.20,
        fisher_ideal_index=121.98,
        substitution_bias=5.60,
        calculation_method="chain_weighted",
        commit=True,
    )

    # 2. Record live dgca violation
    record_dgca_violation(
        db=db,
        route_code=unique_route,
        airline_code="AI",
        flight_number="AI-543",
        flight_date=today_str,
        window="T+1",
        fare_inr=24500.0,
        median_baseline_fare=7000.0,
        surge_multiple=3.50,
        severity="SEVERE",
        violation_code="DGCA-SURGE-3X",
        commit=True,
    )

    # 3. Query API for this exact route
    res_idx = client.get(f"/api/v1/econometrics/indices?route_code={unique_route}")
    assert res_idx.status_code == 200
    idx_data = res_idx.json()
    assert (
        idx_data["fisher_index"] == 121.98
    ), f"Expected 121.98, got {idx_data['fisher_index']}"

    res_v = client.get(
        f"/api/v1/econometrics/dgca-violations?route_code={unique_route}"
    )
    assert res_v.status_code == 200
    v_data = res_v.json()
    assert any(
        v["flight_number"] == "AI-543" for v in v_data["violations"]
    ), "Expected AI-543 in violations"
    print(
        f"  ✓ Live DB write and query verified: {unique_route} Fisher={idx_data['fisher_index']}, violation AI-543 recorded"
    )


def test_mock_fallback_on_unseeded_route():
    print("[TEST 22/22] Calibrated mock fallback resilience for unseeded route")
    unseeded_route = "IXZ-MAA"
    res = client.get(f"/api/v1/econometrics/indices?route_code={unseeded_route}")
    assert res.status_code == 200
    data = res.json()
    # No calibrated fallback exists, and there must not be one: synthesising a
    # plausible index series for a corridor with no data is exactly the fabrication
    # this project exists to avoid. An unseeded route reports no data instead.
    assert data["data_available"] is False
    assert data["series"] == []
    assert data["base_period"] is None
    print(
        f"  ✓ Unseeded route {unseeded_route} correctly reports no data rather than a synthetic series"
    )


def main():
    print("=" * 72)
    print("APIx Master Mission Cycle 4 - Econometrics & DGCA API Test Suite")
    print("=" * 72)
    tests = [
        test_econometric_indices_default,
        test_econometric_indices_route_filtering,
        test_econometric_indices_limit_filtering,
        test_cpi_divergence_default,
        test_cpi_divergence_params_filtering,
        test_cpi_gap_alias_endpoint,
        test_elasticity_default,
        test_elasticity_route_filtering,
        test_dgca_violations_default,
        test_dgca_violations_severity_filter,
        test_dgca_violations_airline_filter,
        test_dgca_violations_route_filter,
        test_dgca_violations_anomalies_alias,
        test_authentication_rejection_invalid_token,
        test_authentication_acceptance_valid_tokens,
        test_recalculate_unauthenticated_rejection,
        test_recalculate_authenticated_execution,
        test_violation_status_patch_unauthenticated,
        test_violation_status_patch_authenticated,
        test_violation_acknowledge_authenticated,
        test_database_persistence_and_live_query,
        test_mock_fallback_on_unseeded_route,
    ]

    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            raise

    print("=" * 72)
    print(f"ALL {passed}/{len(tests)} CYCLE 4 API TESTS PASSED SUCCESSFULLY!")
    print("=" * 72)


if __name__ == "__main__":
    main()
