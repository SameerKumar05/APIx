#!/usr/bin/env python3
"""Mathematical Verification Test Suite for APIx Statistical Engine.

Validates the four foundational mathematical invariants of SIH 2026 PS 26056:
- Invariant 1: Equal price distribution weighted median equals scalar price.
- Invariant 2: Base period prices yield national index = 100.00.
- Invariant 3: +20% uniform price increase yields national index = 120.00.
- Invariant 4: 3-sigma surge triggers CRITICAL anomaly alert.

Also verifies:
- Cross-platform flight deduplication (minimum consumer fare selection).
- Outlier filtering using Tukey's IQR rule [Q1 - 1.5*IQR, Q3 + 1.5*IQR].
- Booking window route composite fare weighting (0.20*T1 + 0.35*T7 + 0.30*T15 + 0.15*T30).
- Asymmetric airline market share weighted median.
- Non-uniform route price Laspeyres calculations.
- Stateful rolling 30-day anomaly detector.
"""

from __future__ import annotations

import math
import os
import sys
from typing import List

# Ensure repository root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.services.anomaly_detector import (
    AnomalyDetector,
    AnomalySeverity,
    calculate_dod_surge,
    calculate_z_score,
    classify_anomaly,
    compute_baseline_stats,
    detect_anomaly,
)
from backend.app.services.index_engine import (
    DEFAULT_AIRLINE_MARKET_SHARES,
    DEFAULT_BOOKING_WINDOW_WEIGHTS,
    DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
    FlightQuote,
    calculate_fisher_index,
    calculate_laspeyres_index,
    calculate_paasche_index,
    calculate_route_composite_fare,
    calculate_weighted_median,
    compute_tukey_bounds,
    deduplicate_quotes,
    filter_outliers_tukey,
    filter_quotes_tukey,
    weighted_median_values,
)


class MathVerificationError(AssertionError):
    """Raised when a mathematical invariant is violated."""


def test_invariant_1_equal_price_distribution_weighted_median() -> None:
    """Invariant 1: Equal price distribution weighted median equals scalar price."""
    test_scalar_prices = [3500.0, 5420.75, 8900.0, 15000.0]

    for scalar_price in test_scalar_prices:
        # Case A: Pure values with diverse arbitrary weights
        weights = [0.62, 0.20, 0.08, 0.05, 0.04]
        values = [scalar_price] * len(weights)
        med = weighted_median_values(values, weights)
        if not math.isclose(med, scalar_price, abs_tol=1e-9):
            raise MathVerificationError(
                f"Invariant 1 Failed: weighted_median_values({values}, {weights}) = {med}, "
                f"expected scalar price {scalar_price}"
            )

        # Case B: FlightQuote collection with all 5 DGCA domestic airlines at identical fare
        quotes = [
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-01",
                airline_code="6E",
                flight_number="6E-204",
                departure_time="08:00",
                fare=scalar_price,
            ),
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-01",
                airline_code="AI",
                flight_number="AI-805",
                departure_time="08:30",
                fare=scalar_price,
            ),
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-01",
                airline_code="IX",
                flight_number="IX-112",
                departure_time="09:00",
                fare=scalar_price,
            ),
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-01",
                airline_code="QP",
                flight_number="QP-1301",
                departure_time="09:30",
                fare=scalar_price,
            ),
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-01",
                airline_code="SG",
                flight_number="SG-8169",
                departure_time="10:00",
                fare=scalar_price,
            ),
        ]

        calc_med = calculate_weighted_median(quotes)
        if not math.isclose(calc_med, scalar_price, abs_tol=1e-9):
            raise MathVerificationError(
                f"Invariant 1 Failed: calculate_weighted_median quotes returned {calc_med}, "
                f"expected {scalar_price}"
            )

        # Case C: Multiple flights per airline with equal price
        expanded_quotes = quotes * 3
        calc_med_expanded = calculate_weighted_median(expanded_quotes)
        if not math.isclose(calc_med_expanded, scalar_price, abs_tol=1e-9):
            raise MathVerificationError(
                f"Invariant 1 Failed: expanded quotes returned {calc_med_expanded}, "
                f"expected {scalar_price}"
            )


def test_invariant_2_base_period_prices_yield_national_index_100() -> None:
    """Invariant 2: Base period prices yield national index = 100.00."""
    base_fares = {
        "DEL-BOM": 5500.0,
        "BOM-DEL": 5450.0,
        "BLR-DEL": 6200.0,
        "DEL-BLR": 6150.0,
        "BOM-BLR": 4100.0,
        "BLR-BOM": 4050.0,
        "DEL-CCU": 4800.0,
        "DEL-HYD": 4500.0,
    }

    # Scenario A: Current fares are identical to base fares
    current_fares = dict(base_fares)

    # 1. With default DGCA route traffic share weights
    index_dgca = calculate_laspeyres_index(
        current_fares=current_fares,
        base_fares=base_fares,
        route_weights=DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
        base_value=100.0,
    )
    if not math.isclose(index_dgca, 100.00, abs_tol=1e-9):
        raise MathVerificationError(
            f"Invariant 2 Failed (DGCA weights): index = {index_dgca}, expected 100.00"
        )

    # 2. With equal route weights
    index_equal = calculate_laspeyres_index(
        current_fares=current_fares,
        base_fares=base_fares,
        route_weights=None,
        base_value=100.0,
    )
    if not math.isclose(index_equal, 100.00, abs_tol=1e-9):
        raise MathVerificationError(
            f"Invariant 2 Failed (Equal weights): index = {index_equal}, expected 100.00"
        )

    # 3. With arbitrary asymmetric weights
    custom_weights = {
        "DEL-BOM": 0.50,
        "BOM-DEL": 0.20,
        "BLR-DEL": 0.15,
        "DEL-BLR": 0.05,
        "BOM-BLR": 0.04,
        "BLR-BOM": 0.03,
        "DEL-CCU": 0.02,
        "DEL-HYD": 0.01,
    }
    index_custom = calculate_laspeyres_index(
        current_fares=current_fares,
        base_fares=base_fares,
        route_weights=custom_weights,
        base_value=100.0,
    )
    if not math.isclose(index_custom, 100.00, abs_tol=1e-9):
        raise MathVerificationError(
            f"Invariant 2 Failed (Custom weights): index = {index_custom}, expected 100.00"
        )


def test_invariant_3_uniform_20_percent_price_increase_yields_120() -> None:
    """Invariant 3: +20% uniform price increase yields national index = 120.00."""
    base_fares = {
        "DEL-BOM": 5000.0,
        "BOM-DEL": 5200.0,
        "BLR-DEL": 6000.0,
        "DEL-BLR": 6100.0,
        "BOM-BLR": 4000.0,
        "BLR-BOM": 4200.0,
        "DEL-CCU": 4500.0,
        "DEL-HYD": 4800.0,
    }

    # Exactly 20% increase across all monitored routes
    current_fares = {route: fare * 1.20 for route, fare in base_fares.items()}

    # 1. With default DGCA route traffic share weights
    index_dgca = calculate_laspeyres_index(
        current_fares=current_fares,
        base_fares=base_fares,
        route_weights=DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
        base_value=100.0,
    )
    if not math.isclose(index_dgca, 120.00, abs_tol=1e-9):
        raise MathVerificationError(
            f"Invariant 3 Failed (DGCA weights): index = {index_dgca}, expected 120.00"
        )

    # 2. With equal route weights
    index_equal = calculate_laspeyres_index(
        current_fares=current_fares,
        base_fares=base_fares,
        route_weights=None,
        base_value=100.0,
    )
    if not math.isclose(index_equal, 120.00, abs_tol=1e-9):
        raise MathVerificationError(
            f"Invariant 3 Failed (Equal weights): index = {index_equal}, expected 120.00"
        )

    # 3. With non-uniform random weights summing to 1.0
    custom_weights = {
        "DEL-BOM": 0.35,
        "BOM-DEL": 0.25,
        "BLR-DEL": 0.15,
        "DEL-BLR": 0.10,
        "BOM-BLR": 0.05,
        "BLR-BOM": 0.05,
        "DEL-CCU": 0.03,
        "DEL-HYD": 0.02,
    }
    index_custom = calculate_laspeyres_index(
        current_fares=current_fares,
        base_fares=base_fares,
        route_weights=custom_weights,
        base_value=100.0,
    )
    if not math.isclose(index_custom, 120.00, abs_tol=1e-9):
        raise MathVerificationError(
            f"Invariant 3 Failed (Custom weights): index = {index_custom}, expected 120.00"
        )


def test_invariant_4_three_sigma_surge_triggers_critical_alert() -> None:
    """Invariant 4: 3-sigma surge triggers CRITICAL anomaly alert."""
    mu_30 = 5000.0
    sigma_30 = 400.0

    # 1. Exact 3-sigma price: P = mu + 3.0 * sigma = 6200.0
    fare_3_sigma = mu_30 + 3.0 * sigma_30
    z_3 = calculate_z_score(fare_3_sigma, mu_30, sigma_30)
    if not math.isclose(z_3, 3.0, abs_tol=1e-9):
        raise MathVerificationError(f"Z-score calculation mismatch: {z_3} != 3.0")

    result_3 = detect_anomaly(
        observed_fare=fare_3_sigma,
        baseline_mean=mu_30,
        baseline_std=sigma_30,
        previous_fare=5200.0,  # modest prior fare (no DoD surge)
    )
    if result_3.severity != AnomalySeverity.CRITICAL:
        raise MathVerificationError(
            f"Invariant 4 Failed: Fare at exact 3-sigma resulted in {result_3.severity}, "
            "expected CRITICAL"
        )
    if not result_3.is_anomaly:
        raise MathVerificationError("Invariant 4 Failed: is_anomaly must be True")

    # 2. Greater than 3-sigma price (e.g. 3.5-sigma, P = 6400.0)
    fare_3_5_sigma = mu_30 + 3.5 * sigma_30
    result_3_5 = detect_anomaly(
        observed_fare=fare_3_5_sigma,
        baseline_mean=mu_30,
        baseline_std=sigma_30,
    )
    if result_3_5.severity != AnomalySeverity.CRITICAL:
        raise MathVerificationError(
            f"Invariant 4 Failed: Fare at 3.5-sigma resulted in {result_3_5.severity}, "
            "expected CRITICAL"
        )

    # 3. DoD surge >= 40% triggers CRITICAL even if Z < 3.0
    # e.g., previous = 4000.0, current = 5650.0 (+41.25% surge, Z = 1.625 < 2.0)
    result_dod = detect_anomaly(
        observed_fare=5650.0,
        baseline_mean=mu_30,
        baseline_std=sigma_30,
        previous_fare=4000.0,
    )
    if result_dod.severity != AnomalySeverity.CRITICAL:
        raise MathVerificationError(
            f"Invariant 4 Failed: DoD surge of 41.25% resulted in {result_dod.severity}, "
            "expected CRITICAL"
        )

    # 4. Verify boundary for WARNING: 2.0 <= Z < 3.0 (and DoD < 40%)
    fare_warning = mu_30 + 2.5 * sigma_30  # Z = 2.5
    result_warning = detect_anomaly(
        observed_fare=fare_warning,
        baseline_mean=mu_30,
        baseline_std=sigma_30,
        previous_fare=fare_warning * 0.95,  # modest DoD ~ 5.2%
    )
    if result_warning.severity != AnomalySeverity.WARNING:
        raise MathVerificationError(
            f"Expected WARNING for Z=2.5, got {result_warning.severity}"
        )

    # 5. Verify boundary for NORMAL: Z < 2.0 (and DoD < 40%)
    fare_normal = mu_30 + 1.2 * sigma_30  # Z = 1.2
    result_normal = detect_anomaly(
        observed_fare=fare_normal,
        baseline_mean=mu_30,
        baseline_std=sigma_30,
        previous_fare=fare_normal * 0.98,
    )
    if result_normal.severity != AnomalySeverity.NORMAL:
        raise MathVerificationError(
            f"Expected NORMAL for Z=1.2, got {result_normal.severity}"
        )


def test_cross_platform_flight_deduplication() -> None:
    """Verifies that quotes for the same flight across platforms select the minimum fare."""
    quotes = [
        # Flight 1: 6E-204 from 3 different sources
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-01",
            airline_code="6E",
            flight_number="6E 204",
            departure_time="08:00",
            fare=5250.0,
            source_portal="makemytrip",
        ),
        FlightQuote(
            origin="del",
            destination="bom",
            flight_date="2026-10-01T00:00:00",
            airline_code="6e",
            flight_number="6E-204",
            departure_time="08:00:00",
            fare=4950.0,  # CHEAPEST
            source_portal="easemytrip",
        ),
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-01",
            airline_code="6E",
            flight_number="204",
            departure_time="08:00",
            fare=5100.0,
            source_portal="indigo_direct",
        ),
        # Flight 2: AI-805
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-01",
            airline_code="AI",
            flight_number="AI-805",
            departure_time="09:15",
            fare=6200.0,
            source_portal="makemytrip",
        ),
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-01",
            airline_code="AI",
            flight_number="AI-805",
            departure_time="09:15",
            fare=5900.0,  # CHEAPEST
            source_portal="amadeus",
        ),
    ]

    deduped = deduplicate_quotes(quotes)
    if len(deduped) != 2:
        raise MathVerificationError(f"Expected 2 deduplicated flights, got {len(deduped)}")

    # Check that 6E-204 chose 4950.0 from EaseMyTrip
    f1 = next(q for q in deduped if q.airline_code == "6E")
    if not math.isclose(f1.fare, 4950.0, abs_tol=1e-9):
        raise MathVerificationError(f"6E-204 fare mismatch: {f1.fare} != 4950.0")
    if f1.source_portal != "easemytrip":
        raise MathVerificationError(f"6E-204 portal mismatch: {f1.source_portal}")

    # Check that AI-805 chose 5900.0 from Amadeus
    f2 = next(q for q in deduped if q.airline_code == "AI")
    if not math.isclose(f2.fare, 5900.0, abs_tol=1e-9):
        raise MathVerificationError(f"AI-805 fare mismatch: {f2.fare} != 5900.0")


def test_tukey_iqr_outlier_filtering() -> None:
    """Verifies Tukey IQR bounds [Q1 - 1.5*IQR, Q3 + 1.5*IQR]."""
    # Distribution of 8 normal fares and 2 severe outliers
    normal_fares = [4000.0, 4200.0, 4400.0, 4600.0, 4800.0, 5000.0, 5200.0, 5400.0]
    outlier_low = 500.0     # extreme scraping error / voucher artifact
    outlier_high = 25000.0  # mistaken business class or currency conversion error

    all_fares = sorted(normal_fares + [outlier_low, outlier_high])
    bounds = compute_tukey_bounds(all_fares, k=1.5)

    if bounds.outlier_count < 2:
        raise MathVerificationError(
            f"Expected at least 2 outliers, got {bounds.outlier_count} (bounds: {bounds})"
        )

    filtered = filter_outliers_tukey(all_fares, k=1.5)
    if outlier_low in filtered:
        raise MathVerificationError(f"Low outlier {outlier_low} was not filtered out")
    if outlier_high in filtered:
        raise MathVerificationError(f"High outlier {outlier_high} was not filtered out")

    # All regular fares should be retained
    for f in normal_fares:
        if f not in filtered:
            raise MathVerificationError(f"Normal fare {f} was incorrectly filtered out")


def test_asymmetric_weighted_median() -> None:
    """Verifies exact weighted median calculation with asymmetric market shares."""
    # 6E has 62% market share; if 6E has price 5000, and other carriers have higher prices,
    # the 50% cumulative weight threshold is reached strictly within 6E!
    quotes = [
        FlightQuote("DEL", "BOM", "2026-10-01", "6E", "6E-101", "06:00", 5000.0),
        FlightQuote("DEL", "BOM", "2026-10-01", "AI", "AI-201", "07:00", 8000.0),
        FlightQuote("DEL", "BOM", "2026-10-01", "IX", "IX-301", "08:00", 8500.0),
        FlightQuote("DEL", "BOM", "2026-10-01", "QP", "QP-401", "09:00", 9000.0),
        FlightQuote("DEL", "BOM", "2026-10-01", "SG", "SG-501", "10:00", 9500.0),
    ]

    med = calculate_weighted_median(quotes)
    if not math.isclose(med, 5000.0, abs_tol=1e-9):
        raise MathVerificationError(
            f"Expected weighted median 5000.0 due to 6E's 62% dominance, got {med}"
        )


def test_route_composite_fare_formula() -> None:
    """Verifies route composite fare formula: P_r,t = 0.20*T1 + 0.35*T7 + 0.30*T15 + 0.15*T30."""
    window_fares = {
        "T1": 8000.0,
        "T7": 6000.0,
        "T15": 5000.0,
        "T30": 4000.0,
    }

    # Expected: 0.20*8000 + 0.35*6000 + 0.30*5000 + 0.15*4000
    # = 1600 + 2100 + 1500 + 600 = 5800.0
    expected = 5800.0
    composite = calculate_route_composite_fare(window_fares)

    if not math.isclose(composite, expected, abs_tol=1e-9):
        raise MathVerificationError(
            f"Route composite fare mismatch: got {composite}, expected {expected}"
        )


def test_non_uniform_laspeyres_index() -> None:
    """Verifies Laspeyres index with non-uniform route price changes."""
    base_fares = {
        "ROUTE_A": 5000.0,
        "ROUTE_B": 4000.0,
    }
    # Route A increases by 10% (5500.0), Route B increases by 30% (5200.0)
    current_fares = {
        "ROUTE_A": 5500.0,
        "ROUTE_B": 5200.0,
    }
    route_weights = {
        "ROUTE_A": 0.60,
        "ROUTE_B": 0.40,
    }

    # Expected Index = (0.60 * (5500/5000) + 0.40 * (5200/4000)) * 100
    # = (0.60 * 1.10 + 0.40 * 1.30) * 100
    # = (0.66 + 0.52) * 100 = 1.18 * 100 = 118.00
    expected_index = 118.00
    calculated_index = calculate_laspeyres_index(
        current_fares=current_fares,
        base_fares=base_fares,
        route_weights=route_weights,
        base_value=100.0,
    )

    if not math.isclose(calculated_index, expected_index, abs_tol=1e-9):
        raise MathVerificationError(
            f"Non-uniform Laspeyres index mismatch: got {calculated_index}, expected {expected_index}"
        )


def test_stateful_anomaly_detector_simulation() -> None:
    """Simulates 35 days of pricing to verify rolling 30-day baseline and anomaly detection."""
    detector = AnomalyDetector(window_size=30)
    route = "DEL-BOM"
    window = "T7"

    # Days 1 to 30: baseline prices fluctuating normally around 5000 with std ~ 200
    # e.g., alternating between 4800, 5000, 5200
    for day in range(1, 31):
        fare = 5000.0 + (100.0 if day % 2 == 0 else -100.0)
        res = detector.evaluate(route, window, fare)
        if res.severity != AnomalySeverity.NORMAL and day > 3:
            raise MathVerificationError(f"Day {day} falsely flagged: {res}")

    # Day 31: Sudden surge to 8000.0 (+60% surge, Z >> 3.0)
    surge_fare = 8000.0
    res_surge = detector.evaluate(route, window, surge_fare)
    if res_surge.severity != AnomalySeverity.CRITICAL:
        raise MathVerificationError(
            f"Day 31 severe surge should be CRITICAL, got {res_surge.severity} (Z={res_surge.z_score})"
        )


def run_all_verifications() -> None:
    """Executes all mathematical invariant and statistical engine verification tests."""
    print("=" * 80)
    print("APIx Mathematical & Statistical Quant Engine Verification Suite")
    print("SIH 2026 Problem Statement 26056 - Real-time Airfare Price Index")
    print("=" * 80)

    tests = [
        ("Invariant 1: Equal price distribution weighted median equals scalar price", test_invariant_1_equal_price_distribution_weighted_median),
        ("Invariant 2: Base period prices yield national index = 100.00", test_invariant_2_base_period_prices_yield_national_index_100),
        ("Invariant 3: +20% uniform price increase yields national index = 120.00", test_invariant_3_uniform_20_percent_price_increase_yields_120),
        ("Invariant 4: 3-sigma surge triggers CRITICAL anomaly alert", test_invariant_4_three_sigma_surge_triggers_critical_alert),
        ("Cross-Platform Flight Deduplication (Minimum consumer fare selection)", test_cross_platform_flight_deduplication),
        ("Tukey IQR Outlier Filtering [Q1 - 1.5*IQR, Q3 + 1.5*IQR]", test_tukey_iqr_outlier_filtering),
        ("Asymmetric Market Share Weighted Median Calculation", test_asymmetric_weighted_median),
        ("Route Composite Fare (0.20*T1 + 0.35*T7 + 0.30*T15 + 0.15*T30)", test_route_composite_fare_formula),
        ("Non-uniform Laspeyres Price Index Computation", test_non_uniform_laspeyres_index),
        ("Stateful Rolling 30-Day Anomaly Detection Engine", test_stateful_anomaly_detector_simulation),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            test_fn()
            print(f"  [PASS] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}")
            print(f"         Error: {e}")
            failed += 1

    print("-" * 80)
    print(f"Verification Summary: {passed}/{len(tests)} tests PASSED, {failed} FAILED")
    print("=" * 80)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_all_verifications()
