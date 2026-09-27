#!/usr/bin/env python3
"""Verification runner for Issue #11:
1. Verify 4 mandatory dashboard visuals:
   (1) Daily index & trends
   (2) Sector-wise heatmap (corridors x booking windows matrix including T+45)
   (3) Lead-time elasticity curves (including T+45)
   (4) Econometric comparisons (Fisher, Laspeyres, Paasche, CPI divergence)
2. Verify NSO/RBI consumable API contract:
   - OpenAPI schema URL (/api/v1/openapi.json)
   - Rate limit headers (120 req/60s)
   - CORS settings (reject wildcard '*')
   - Authentication boundaries
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Ensure worktree root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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


def run_verification() -> int:
    db_file = Path("/tmp/verify_visual_contract_runner.db")
    if db_file.exists():
        db_file.unlink()

    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)

    now = datetime.now(UTC)
    today = now.date()

    with Session(engine) as session:
        seed_routes(session)

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

        # 2. Route daily indices for active routes (Visual 1 & 2)
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

            # Advance booking window records including T+45 (Visual 2)
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
        with TestClient(app) as client:
            print("=================================================================")
            print("APIx Issue #11: Dashboard 4-Visual & NSO/RBI API Contract Runner")
            print("=================================================================\n")

            # Check 1: Visual 1 - Daily index & trends
            print("[CHECK 1] Visual 1: Daily National Index & Trends")
            r1 = client.get("/api/v1/indices/national/latest")
            assert r1.status_code == 200, f"Expected 200, got {r1.status_code}"
            d1 = r1.json()
            print(
                f"  ✓ /api/v1/indices/national/latest: index_value={d1['index_value']}, base_period={d1['base_period']}"
            )

            r1_hist = client.get("/api/v1/indices/national/history?days=30")
            assert r1_hist.status_code == 200
            d1_hist = r1_hist.json()
            print(
                f"  ✓ /api/v1/indices/national/history: points={len(d1_hist['points'])}, total_points={d1_hist['total_points']}"
            )

            r1_routes = client.get("/api/v1/indices/routes")
            assert r1_routes.status_code == 200
            d1_routes = r1_routes.json()
            print(
                f"  ✓ /api/v1/indices/routes: total_routes={d1_routes['total_routes']}, routes_count={len(d1_routes['routes'])}"
            )

            # Check 2: Visual 2 - Sector-wise heatmap (corridors x booking windows matrix including T+45)
            print(
                "\n[CHECK 2] Visual 2: Sector-Wise Heatmap Matrix (Routes x Booking Windows)"
            )
            r2 = client.get("/api/v1/analytics/sector-heatmap")
            assert r2.status_code == 200
            d2 = r2.json()
            assert d2["data_available"] is True
            assert "T+45" in d2["windows"]
            assert len(d2["sectors"]) >= 1
            s0 = d2["sectors"][0]
            print(
                f"  ✓ /api/v1/analytics/sector-heatmap: total_routes={d2['total_routes']}, windows={d2['windows']}"
            )
            print(
                f"    Corridor {s0['route_code']}: T+45={s0['windows'].get('T+45')} INR, T+30={s0['windows'].get('T+30')} INR, T+1={s0['windows'].get('T+1')} INR"
            )
            print(
                f"    Surge Multiplier={s0['surge_multiplier']}x, base_fare={s0['base_fare_inr']} INR, urgent_fare={s0['urgent_fare_inr']} INR"
            )

            r2_alias = client.get("/api/v1/indices/sector-heatmap")
            assert r2_alias.status_code == 200
            print("  ✓ /api/v1/indices/sector-heatmap (alias) verified")

            # Check 3: Visual 3 - Lead-time elasticity curves (including T+45)
            print("\n[CHECK 3] Visual 3: Lead-Time Elasticity Curves (Including T+45)")
            r3 = client.get("/api/v1/analytics/lead-time-curve?route_code=DEL-BOM")
            assert r3.status_code == 200
            d3 = r3.json()
            assert d3["data_available"] is True
            days_list = [pt["days_before_departure"] for pt in d3["curve_points"]]
            assert (
                45 in days_list
            ), f"Expected 45 (T+45) in curve points, got {days_list}"
            print(
                f"  ✓ /api/v1/analytics/lead-time-curve: route={d3['route_code']}, days={days_list}"
            )
            for pt in d3["curve_points"]:
                print(
                    f"    T+{pt['days_before_departure']:02d}: avg_fare={pt['avg_fare_inr']} INR, median={pt['median_fare_inr']} INR, elasticity={pt['elasticity_factor']}x"
                )

            r3_econ = client.get("/api/v1/econometrics/elasticity?route_code=DEL-BOM")
            assert r3_econ.status_code == 200
            d3_econ = r3_econ.json()
            print(
                f"  ✓ /api/v1/econometrics/elasticity: route={d3_econ['route_code']}, curves_count={len(d3_econ.get('curves', []))}"
            )

            # Check 4: Visual 4 - Econometric comparisons (Fisher, Laspeyres, Paasche, CPI Gap)
            print("\n[CHECK 4] Visual 4: Econometric Comparisons & MoSPI CPI Gap")
            r4 = client.get("/api/v1/econometrics/indices?route_code=NATIONAL")
            assert r4.status_code == 200
            d4 = r4.json()
            print(
                f"  ✓ /api/v1/econometrics/indices: Fisher={d4['fisher_index']}, Laspeyres={d4['laspeyres_index']}, Paasche={d4['paasche_index']}"
            )
            print(
                f"    Substitution Bias={d4['substitution_bias']} pts, Base Period={d4.get('base_period')}"
            )

            r4_cpi = client.get("/api/v1/econometrics/cpi-divergence")
            assert r4_cpi.status_code == 200
            d4_cpi = r4_cpi.json()
            assert len(d4_cpi["divergence_series"]) >= 1
            print(
                f"  ✓ /api/v1/econometrics/cpi-divergence: series_points={len(d4_cpi['divergence_series'])}, lead_days={d4_cpi.get('inflation_lead_days')}"
            )
            for p in d4_cpi["divergence_series"]:
                print(
                    f"    Month {p['date']}: APIx={p['apix_index']}, MoSPI Transport={p['mospi_cpi']}, Gap={p['gap']} pts"
                )

            # Check 5: Contract & Governance - OpenAPI, Rate Limits, CORS, Auth
            print("\n[CHECK 5] NSO/RBI API Contract & Governance")
            r5_open = client.get("/api/v1/openapi.json")
            assert r5_open.status_code == 200
            open_schema = r5_open.json()
            print(
                f"  ✓ OpenAPI Schema at /api/v1/openapi.json: version={open_schema['openapi']}, title='{open_schema['info']['title']}'"
            )
            print(f"    Endpoints cataloged: {len(open_schema['paths'])} routes")

            # Rate limit headers check
            assert "x-ratelimit-limit" in r1.headers
            assert "x-ratelimit-remaining" in r1.headers
            limit_val = int(r1.headers["x-ratelimit-limit"])
            assert limit_val == settings.API_RATE_LIMIT_REQUESTS
            print(
                f"  ✓ Rate limit headers: X-RateLimit-Limit={limit_val} (120 req/60s contract), X-RateLimit-Remaining={r1.headers['x-ratelimit-remaining']}"
            )

            # CORS check
            try:
                Settings(BACKEND_CORS_ORIGINS=["*"])
                print("  ✗ CORS wildcard '*' was incorrectly accepted")
                return 1
            except ValidationError:
                print("  ✓ CORS configuration strictly rejects wildcard '*' origin")

            # Auth boundary check
            r5_auth = client.post("/api/v1/econometrics/recalculate")
            assert r5_auth.status_code == 401
            print(
                f"  ✓ Protected administrative mutation rejected without key (HTTP {r5_auth.status_code} Unauthorized)"
            )

            print("\n=================================================================")
            print(
                "ALL CHECKS PASSED: 4-Visual Coverage & NSO/RBI API Contract Verified"
            )
            print("=================================================================")
            return 0
    finally:
        app.dependency_overrides.clear()
        if db_file.exists():
            db_file.unlink()


if __name__ == "__main__":
    sys.exit(run_verification())
