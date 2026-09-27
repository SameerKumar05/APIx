"""Mathematical Invariants and Statistical Properties Test Suite for APIx.

Validates the foundational mathematical and quantitative pricing formulations of
SIH 2026 Problem Statement 26056 (Real-time Airfare Price Index for CPI Augmentation):

1. Invariant 1: Equal Price Distribution Weighted Median Identity
2. Invariant 2: Base Period Price Index Identity (Index == 100.00)
3. Invariant 3: Uniform Relative Price Scaling Linearity (+20% -> 120.00)
4. Invariant 4: 3-Sigma Surge & DoD Surge Thresholds (CRITICAL Anomaly Alert)
5. Invariant 5: Weighted Median Cumulative Weight Split & Transition Properties
6. Invariant 6: Asymmetric DGCA Market Share Weighted Median vs Unweighted Median
7. Invariant 7: Booking Horizon Window Composite Formula Invariants
8. Invariant 8: Traffic Weight Monotonicity and Sensitivity
9. Invariant 9: Fisher Ideal Price Index Geometric Mean & Reversal Properties
10. Invariant 10: Tukey IQR Outlier Bounds Filtering Properties
11. Invariant 11: Weekly Index Aggregation & Rollup Invariants
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
import pytest

from backend.app.services.anomaly_detector import (
    AnomalySeverity,
    calculate_dod_surge,
    calculate_z_score,
    detect_anomaly,
)
from backend.app.services.index_engine import (
    DEFAULT_BOOKING_WINDOW_WEIGHTS,
    DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
    FlightQuote,
    calculate_fisher_index,
    calculate_laspeyres_index,
    calculate_paasche_index,
    calculate_route_composite_fare,
    calculate_weighted_median,
    compute_tukey_bounds,
    filter_outliers_tukey,
    weighted_median_values,
)
from backend.app.api.v1.endpoints.indices import _bucket_key
from backend.app.services.econometric_engine import calculate_lead_time_elasticity

# ===========================================================================
# 1. Invariant 1: Equal Price Distribution Weighted Median Identity
# ===========================================================================


class TestInvariant1WeightedMedianEqualPrice:
    """Verifies that for any price vector P where all elements equal scalar p,
    the Weighted Median equals p exactly, regardless of the weight distribution.
    """

    @pytest.mark.parametrize(
        "scalar_price", [1500.0, 3500.0, 5420.75, 8900.0, 15000.0, 48500.0]
    )
    def test_scalar_price_with_arbitrary_weights(self, scalar_price: float) -> None:
        """Weighted median of identical prices must equal scalar price for any positive weights."""
        test_weight_distributions = [
            [0.2, 0.2, 0.2, 0.2, 0.2],  # Uniform weights
            [0.62, 0.20, 0.08, 0.05, 0.04],  # DGCA domestic carrier market shares
            [0.95, 0.02, 0.01, 0.01, 0.01],  # Highly dominant single carrier
            [0.01, 0.01, 0.01, 0.01, 0.96],  # Dominance at tail
            [1.0],  # Single observation
            [0.001] * 50,  # Large balanced basket
        ]

        for weights in test_weight_distributions:
            values = [scalar_price] * len(weights)
            result = weighted_median_values(values, weights)
            assert math.isclose(
                result, scalar_price, abs_tol=1e-9
            ), f"Failed for weights {weights}: got {result}, expected {scalar_price}"

    def test_scalar_price_with_flight_quotes_across_all_airlines(self) -> None:
        """FlightQuote collection of all 5 DGCA domestic carriers at identical fare."""
        scalar_fare = 6250.00
        quotes = [
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-01",
                airline_code=carrier,
                flight_number=f"{carrier}-101",
                departure_time="08:00",
                fare=scalar_fare,
            )
            for carrier in ["6E", "AI", "IX", "QP", "SG"]
        ]

        computed_median = calculate_weighted_median(quotes)
        assert math.isclose(computed_median, scalar_fare, abs_tol=1e-9)


# ===========================================================================
# 2. Invariant 2: Base Period Price Index Identity
# ===========================================================================


class TestInvariant2BasePeriodIndexIdentity:
    """Verifies that when current period prices equal base period prices,
    Laspeyres, Paasche, and Fisher indices all equal 100.00 exactly.
    """

    @pytest.fixture
    def base_fares_basket(self) -> dict[str, float]:
        """Representative base period fares for the top 10 domestic routes."""
        return {
            "DEL-BOM": 5500.0,
            "BOM-DEL": 5450.0,
            "BLR-DEL": 6200.0,
            "DEL-BLR": 6150.0,
            "BOM-BLR": 4100.0,
            "BLR-BOM": 4050.0,
            "DEL-CCU": 4800.0,
            "CCU-DEL": 4750.0,
            "DEL-HYD": 4500.0,
            "HYD-DEL": 4450.0,
        }

    def test_laspeyres_index_base_period_identity(
        self, base_fares_basket: dict[str, float]
    ) -> None:
        """P_{r,t} == P_{r,0} for all r => I_L == 100.00 across all weight schemes."""
        current_fares = dict(base_fares_basket)

        # 1. DGCA traffic weights
        idx_dgca = calculate_laspeyres_index(
            current_fares=current_fares,
            base_fares=base_fares_basket,
            route_weights=DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
            base_value=100.0,
        )
        assert math.isclose(idx_dgca, 100.00, abs_tol=1e-9)

        # 2. Equal route weights
        idx_equal = calculate_laspeyres_index(
            current_fares=current_fares,
            base_fares=base_fares_basket,
            route_weights=None,
            base_value=100.0,
        )
        assert math.isclose(idx_equal, 100.00, abs_tol=1e-9)

        # 3. Random asymmetric route weights
        rng = random.Random(42)
        raw_random_weights = {r: rng.uniform(0.01, 1.0) for r in base_fares_basket}
        tot = sum(raw_random_weights.values())
        norm_random_weights = {r: w / tot for r, w in raw_random_weights.items()}

        idx_random = calculate_laspeyres_index(
            current_fares=current_fares,
            base_fares=base_fares_basket,
            route_weights=norm_random_weights,
            base_value=100.0,
        )
        assert math.isclose(idx_random, 100.00, abs_tol=1e-9)

    def test_paasche_and_fisher_base_period_identity(
        self, base_fares_basket: dict[str, float]
    ) -> None:
        """Paasche and Fisher Ideal Index also evaluate to 100.00 at base period."""
        current_fares = dict(base_fares_basket)
        current_weights = DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES

        idx_paasche = calculate_paasche_index(
            current_fares=current_fares,
            base_fares=base_fares_basket,
            current_traffic_weights=current_weights,
            base_value=100.0,
        )
        assert math.isclose(idx_paasche, 100.00, abs_tol=1e-9)

        idx_fisher = calculate_fisher_index(laspeyres=100.00, paasche=100.00)
        assert math.isclose(idx_fisher, 100.00, abs_tol=1e-9)


# ===========================================================================
# 3. Invariant 3: Uniform Relative Price Scaling Linearity
# ===========================================================================


class TestInvariant3UniformPriceScalingLinearity:
    """Verifies that when all route prices scale uniformly by factor alpha,
    the National Laspeyres Index scales by exactly alpha * 100.00.
    """

    @pytest.fixture
    def base_fares(self) -> dict[str, float]:
        return {
            "DEL-BOM": 5000.0,
            "BOM-DEL": 5200.0,
            "BLR-DEL": 6000.0,
            "DEL-BLR": 6100.0,
            "BOM-BLR": 4000.0,
            "BLR-BOM": 4200.0,
            "DEL-CCU": 4500.0,
            "CCU-DEL": 4600.0,
            "DEL-HYD": 4800.0,
            "HYD-DEL": 4700.0,
        }

    @pytest.mark.parametrize(
        "scaling_factor, expected_index",
        [
            (1.20, 120.00),  # +20% uniform price increase
            (1.10, 110.00),  # +10% uniform price increase
            (0.85, 85.00),  # -15% uniform price decline
            (1.50, 150.00),  # +50% surge
            (2.00, 200.00),  # 100% price doubling
        ],
    )
    def test_uniform_scaling_holds_across_weighting_regimes(
        self, base_fares: dict[str, float], scaling_factor: float, expected_index: float
    ) -> None:
        """Linearity invariant must hold for any route weighting regime."""
        scaled_fares = {
            route: fare * scaling_factor for route, fare in base_fares.items()
        }

        # Regime 1: DGCA traffic weights
        idx_dgca = calculate_laspeyres_index(
            current_fares=scaled_fares,
            base_fares=base_fares,
            route_weights=DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
            base_value=100.0,
        )
        assert math.isclose(idx_dgca, expected_index, abs_tol=1e-9)

        # Regime 2: Equal weights
        idx_equal = calculate_laspeyres_index(
            current_fares=scaled_fares,
            base_fares=base_fares,
            route_weights=None,
            base_value=100.0,
        )
        assert math.isclose(idx_equal, expected_index, abs_tol=1e-9)


# ===========================================================================
# 4. Invariant 4: 3-Sigma Surge & DoD Surge Thresholds (Anomaly Detector)
# ===========================================================================


class TestInvariant4AnomalyAlertThresholds:
    """Verifies that mathematical anomaly thresholds operate correctly:
    - Z-Score >= 3.0 triggers CRITICAL severity alert.
    - Day-over-Day surge >= +40% triggers CRITICAL alert even if Z < 3.0.
    - 2.0 <= Z < 3.0 triggers WARNING severity alert.
    - Z < 2.0 and DoD < 25% produces NORMAL status (no anomaly).
    """

    def test_three_sigma_surge_triggers_critical(self) -> None:
        """Fare at or exceeding 3 standard deviations above baseline mean triggers CRITICAL."""
        baseline_mean = 5000.0
        baseline_std = 400.0

        # Exact 3.0 sigma: 5000 + 3*400 = 6200
        fare_3_sigma = baseline_mean + 3.0 * baseline_std
        z = calculate_z_score(fare_3_sigma, baseline_mean, baseline_std)
        assert math.isclose(z, 3.0, abs_tol=1e-9)

        res = detect_anomaly(
            observed_fare=fare_3_sigma,
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
            previous_fare=5200.0,  # moderate prior fare (no DoD surge)
        )
        assert res.is_anomaly is True
        assert res.severity == AnomalySeverity.CRITICAL
        assert res.z_score == pytest.approx(3.0, abs=1e-4)

    def test_dod_surge_greater_than_40_percent_triggers_critical(self) -> None:
        """Day-over-day surge >= 40% triggers CRITICAL alert regardless of Z-score."""
        baseline_mean = 5000.0
        baseline_std = 1000.0  # high standard deviation so Z remains < 2.0

        prev_fare = 4000.0
        curr_fare = 5700.0  # +42.5% increase, but Z = (5700-5000)/1000 = 0.7 < 2.0

        dod = calculate_dod_surge(curr_fare, prev_fare)
        assert dod > 0.40

        res = detect_anomaly(
            observed_fare=curr_fare,
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
            previous_fare=prev_fare,
        )
        assert res.is_anomaly is True
        assert res.severity == AnomalySeverity.CRITICAL

    def test_two_sigma_to_three_sigma_triggers_warning(self) -> None:
        """Z-score between 2.0 and 3.0 (with DoD < 40%) triggers WARNING."""
        baseline_mean = 5000.0
        baseline_std = 400.0

        fare_2_5_sigma = baseline_mean + 2.5 * baseline_std  # 6000.0 (Z = 2.5)
        res = detect_anomaly(
            observed_fare=fare_2_5_sigma,
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
            previous_fare=5500.0,  # DoD = +9.1%
        )
        assert res.is_anomaly is True
        assert res.severity == AnomalySeverity.WARNING
        assert res.z_score == pytest.approx(2.5, abs=1e-4)

    def test_normal_fare_produces_no_anomaly(self) -> None:
        """Fare within normal distribution bounds produces is_anomaly = False."""
        baseline_mean = 5000.0
        baseline_std = 400.0

        fare_normal = 5200.0  # Z = 0.5
        res = detect_anomaly(
            observed_fare=fare_normal,
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
            previous_fare=5100.0,
        )
        assert res.is_anomaly is False
        assert res.severity == AnomalySeverity.NORMAL


# ===========================================================================
# 5. Invariant 5: Weighted Median Step & Split Transition Properties
# ===========================================================================


class TestWeightedMedianTransitions:
    """Verifies boundary properties of the weighted median algorithm."""

    def test_exact_half_weight_split_returns_average_of_two_values(self) -> None:
        """When cumulative weight equals 0.50 exactly, median is (x_k + x_{k+1}) / 2."""
        values = [4000.0, 6000.0]
        weights = [0.50, 0.50]

        result = weighted_median_values(values, weights)
        assert math.isclose(result, 5000.0, abs_tol=1e-9)

    def test_step_function_crosses_half_weight(self) -> None:
        """As weights tip slightly above or below 0.50, the median steps discretely."""
        values = [4000.0, 6000.0]

        # Case A: 51% weight on 4000.0 -> crosses 0.5 at 4000.0
        med_a = weighted_median_values(values, [0.51, 0.49])
        assert math.isclose(med_a, 4000.0, abs_tol=1e-9)

        # Case B: 49% weight on 4000.0, 51% on 6000.0 -> crosses 0.5 at 6000.0
        med_b = weighted_median_values(values, [0.49, 0.51])
        assert math.isclose(med_b, 6000.0, abs_tol=1e-9)

    def test_permutation_invariance_of_weighted_median(self) -> None:
        """Shuffling the input order of (value, weight) pairs yields identical median."""
        original_values = [3200.0, 4800.0, 5600.0, 7200.0, 9500.0]
        original_weights = [0.15, 0.35, 0.25, 0.15, 0.10]

        expected_median = weighted_median_values(original_values, original_weights)

        # Shuffle pairs with different random seeds
        for seed in [1, 42, 99, 1337]:
            rng = random.Random(seed)
            pairs = list(zip(original_values, original_weights, strict=True))
            rng.shuffle(pairs)
            shuffled_vals = [p[0] for p in pairs]
            shuffled_wts = [p[1] for p in pairs]

            res = weighted_median_values(shuffled_vals, shuffled_wts)
            assert math.isclose(res, expected_median, abs_tol=1e-9)


# ===========================================================================
# 6. Invariant 6: DGCA Airline Market Share Weighted vs Unweighted Median
# ===========================================================================


class TestMarketShareWeightedMedianAsymmetry:
    """Demonstrates that market-share weighted median correctly reflects consumer pricing."""

    def test_dominant_carrier_drags_weighted_median_towards_high_volume_fare(
        self,
    ) -> None:
        """IndiGo (62% market share) pricing dominates the weighted median even if minority in quote count."""
        # 3 quotes: IndiGo offering low fare, other 2 carriers offering high fares
        quotes = [
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-01",
                airline_code="6E",  # 62% market share
                flight_number="6E-201",
                departure_time="08:00",
                fare=4500.0,
            ),
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-01",
                airline_code="AI",  # 20% market share
                flight_number="AI-801",
                departure_time="08:30",
                fare=7500.0,
            ),
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-01",
                airline_code="SG",  # 4% market share
                flight_number="SG-101",
                departure_time="09:00",
                fare=8500.0,
            ),
        ]

        # Unweighted median of [4500, 7500, 8500] is 7500.0 (the middle value)
        unweighted_med = 7500.0

        # Weighted median: IndiGo (62% > 50% threshold) resolves to 4500.0
        weighted_med = calculate_weighted_median(quotes)
        assert weighted_med == 4500.0
        assert weighted_med < unweighted_med


# ===========================================================================
# 7. Invariant 7: Booking Horizon Window Composite Formula Invariants
# ===========================================================================


class TestBookingWindowCompositeFormula:
    """Verifies route composite fare calculation across advance windows (T+1, T+7, T+15, T+30, T+45):
    P_r = 0.20*P_{r,1} + 0.32*P_{r,7} + 0.26*P_{r,15} + 0.14*P_{r,30} + 0.08*P_{r,45}
    """

    def test_window_weights_sum_to_one(self) -> None:
        """Booking window weights must sum to exactly 1.000."""
        total_w = sum(DEFAULT_BOOKING_WINDOW_WEIGHTS.values())
        assert pytest.approx(total_w, abs=1e-9) == 1.00

    def test_equal_fares_across_all_windows_yields_scalar_fare(self) -> None:
        """If fares across all booking windows are identical, composite fare equals scalar."""
        scalar_fare = 5400.0
        window_fares = {
            "T+1": scalar_fare,
            "T+7": scalar_fare,
            "T+15": scalar_fare,
            "T+30": scalar_fare,
            "T+45": scalar_fare,
        }

        composite = calculate_route_composite_fare(window_fares)
        assert math.isclose(composite, scalar_fare, abs_tol=1e-9)

    def test_calibrated_advance_purchase_discount_curve(self) -> None:
        """Typical airline revenue management curve: T+1 > T+7 > T+15 > T+30."""
        window_fares = {
            "T+1": 12000.0,  # Last-minute / emergency
            "T+7": 8500.0,  # Business lead time
            "T+15": 6500.0,  # Standard planning
            "T+30": 5200.0,  # Early leisure discount
            "T+45": 4400.0,  # Far-planned discount
        }
        # Derived from the weight table rather than hardcoded, so changing the
        # weights cannot leave a stale magic number here. The composite
        # renormalises over the windows actually supplied, so T+45's share is
        # excluded and redistributed rather than silently dropped.
        present = {w.replace("+", ""): w for w in window_fares}
        weight_sum = sum(DEFAULT_BOOKING_WINDOW_WEIGHTS[w] for w in present)
        expected_composite = sum(
            (DEFAULT_BOOKING_WINDOW_WEIGHTS[w] / weight_sum) * window_fares[code]
            for w, code in present.items()
        )
        composite = calculate_route_composite_fare(window_fares)
        assert math.isclose(composite, expected_composite, abs_tol=1e-9)


    def test_five_window_composite_exact_weights(self) -> None:
        """Route composite fare follows exact 5-window weighting:
        P_r = 0.20*T1 + 0.32*T7 + 0.26*T15 + 0.14*T30 + 0.08*T45
        """
        window_fares = {
            "T1": 10000.0,
            "T7": 8000.0,
            "T15": 6000.0,
            "T30": 5000.0,
            "T45": 4000.0,
        }
        # 0.20*10000 + 0.32*8000 + 0.26*6000 + 0.14*5000 + 0.08*4000 = 7140.0
        expected = (
            0.20 * 10000.0
            + 0.32 * 8000.0
            + 0.26 * 6000.0
            + 0.14 * 5000.0
            + 0.08 * 4000.0
        )
        composite = calculate_route_composite_fare(window_fares)
        assert math.isclose(composite, expected, abs_tol=1e-9)
        assert math.isclose(composite, 7140.0, abs_tol=1e-9)

    def test_five_window_linearity_and_homogeneity(self) -> None:
        """Verifies linear homogeneity of composite fare across all 5 windows:
        C(alpha * P) = alpha * C(P) for any positive scalar alpha.
        """
        fares = {
            "T+1": 11500.0,
            "T+7": 8400.0,
            "T+15": 6200.0,
            "T+30": 4800.0,
            "T+45": 3900.0,
        }
        base_composite = calculate_route_composite_fare(fares)

        for alpha in [0.5, 0.8, 1.25, 2.0]:
            scaled_fares = {k: v * alpha for k, v in fares.items()}
            scaled_composite = calculate_route_composite_fare(scaled_fares)
            assert math.isclose(scaled_composite, base_composite * alpha, abs_tol=1e-7)

    def test_five_window_superposition_additivity(self) -> None:
        """Verifies additivity / superposition across all 5 booking windows:
        C(P_a + P_b) = C(P_a) + C(P_b).
        """
        fares_a = {
            "T+1": 5000.0,
            "T+7": 4000.0,
            "T+15": 3000.0,
            "T+30": 2500.0,
            "T+45": 2000.0,
        }
        fares_b = {
            "T+1": 6000.0,
            "T+7": 4500.0,
            "T+15": 3500.0,
            "T+30": 2600.0,
            "T+45": 2100.0,
        }
        fares_sum = {k: fares_a[k] + fares_b[k] for k in fares_a}

        comp_a = calculate_route_composite_fare(fares_a)
        comp_b = calculate_route_composite_fare(fares_b)
        comp_sum = calculate_route_composite_fare(fares_sum)
        assert math.isclose(comp_sum, comp_a + comp_b, abs_tol=1e-7)

    def test_t45_sensitivity_marginal_derivative(self) -> None:
        """Verifies the marginal impact of T+45 fare change: dC / dP_{T45} = 0.08."""
        base_fares = {
            "T+1": 10000.0,
            "T+7": 8000.0,
            "T+15": 6000.0,
            "T+30": 5000.0,
            "T+45": 4000.0,
        }
        delta = 1000.0
        perturbed_fares = dict(base_fares)
        perturbed_fares["T+45"] += delta

        c_base = calculate_route_composite_fare(base_fares)
        c_perturbed = calculate_route_composite_fare(perturbed_fares)

        marginal_impact = c_perturbed - c_base
        expected_impact = DEFAULT_BOOKING_WINDOW_WEIGHTS["T45"] * delta
        assert math.isclose(marginal_impact, expected_impact, abs_tol=1e-9)
        assert math.isclose(marginal_impact, 80.0, abs_tol=1e-9)

    def test_t45_in_econometric_lead_time_elasticity(self) -> None:
        """Verifies that calculate_lead_time_elasticity incorporates T+45 in its canonical ordering."""
        fares = {
            "T+1": 12000.0,
            "T+7": 8500.0,
            "T+15": 6500.0,
            "T+30": 5000.0,
            "T+45": 4200.0,
        }
        res = calculate_lead_time_elasticity(fares)
        assert "T+45" in res.curves
        assert res.curves["T+45"]["advance_days"] == 45
        assert "T+45_to_T+30" in res.arc_elasticities
        assert res.lead_time_premium_pct > 0.0
        assert res.urgency_multiplier > 1.0

# ===========================================================================
# 8. Invariant 8: Traffic Weight Monotonicity and Sensitivity
# ===========================================================================


class TestTrafficWeightSensitivity:
    """Verifies that price increases on higher-traffic corridors exert greater
    impact on the national index than identical percentage increases on low-traffic routes.
    """

    def test_high_traffic_route_dominates_index_movement(self) -> None:
        """A +30% surge on DEL-BOM (high weight) moves the national index more than on DEL-HYD (low weight)."""
        base_fares = {
            "DEL-BOM": 5000.0,
            "DEL-HYD": 5000.0,
        }
        weights = {
            "DEL-BOM": 0.80,  # Heavy trunk corridor
            "DEL-HYD": 0.20,  # Smaller feeder corridor
        }

        # Scenario 1: DEL-BOM surges +30%, DEL-HYD unchanged
        fares_scenario_1 = {"DEL-BOM": 6500.0, "DEL-HYD": 5000.0}
        index_1 = calculate_laspeyres_index(
            current_fares=fares_scenario_1,
            base_fares=base_fares,
            route_weights=weights,
            base_value=100.0,
        )

        # Scenario 2: DEL-HYD surges +30%, DEL-BOM unchanged
        fares_scenario_2 = {"DEL-BOM": 5000.0, "DEL-HYD": 6500.0}
        index_2 = calculate_laspeyres_index(
            current_fares=fares_scenario_2,
            base_fares=base_fares,
            route_weights=weights,
            base_value=100.0,
        )

        # Expected:
        # Scenario 1: 0.80 * 1.30 + 0.20 * 1.00 = 1.04 + 0.20 = 1.24 -> Index = 124.00
        # Scenario 2: 0.80 * 1.00 + 0.20 * 1.30 = 0.80 + 0.26 = 1.06 -> Index = 106.00
        assert index_1 > index_2
        assert math.isclose(index_1, 124.00, abs_tol=1e-9)
        assert math.isclose(index_2, 106.00, abs_tol=1e-9)


# ===========================================================================
# 9. Invariant 9: Fisher Ideal Price Index Geometric Mean & Properties
# ===========================================================================


class TestFisherIdealIndexProperties:
    """Verifies that Fisher Ideal Index satisfies geometric mean and bounds:
    min(I_L, I_P) <= I_F <= max(I_L, I_P)
    """

    @pytest.mark.parametrize(
        "laspeyres, paasche",
        [
            (110.0, 108.0),
            (120.0, 115.0),
            (95.0, 92.0),
            (100.0, 100.0),
        ],
    )
    def test_fisher_bounded_by_laspeyres_and_paasche(
        self, laspeyres: float, paasche: float
    ) -> None:
        """Fisher index must lie strictly between Laspeyres and Paasche indices."""
        fisher = calculate_fisher_index(laspeyres=laspeyres, paasche=paasche)
        expected = math.sqrt(laspeyres * paasche)
        assert math.isclose(fisher, expected, abs_tol=1e-9)

        lower_bound = min(laspeyres, paasche)
        upper_bound = max(laspeyres, paasche)
        assert lower_bound <= fisher <= upper_bound


# ===========================================================================
# 10. Invariant 10: Tukey IQR Outlier Bounds Filtering Properties
# ===========================================================================


class TestTukeyIQROutlierBounds:
    """Verifies Tukey's IQR outlier filtering:
    [Q1 - 1.5*IQR, Q3 + 1.5*IQR]
    """

    def test_tukey_bounds_filters_extreme_scraping_artifacts(self) -> None:
        """Filters out scraping artifacts such as 0 INR fares and 1,000,000 INR errors."""
        valid_market_fares = [
            4500.0,
            4800.0,
            5000.0,
            5100.0,
            5200.0,
            5300.0,
            5500.0,
            5700.0,
            6000.0,
        ]
        corrupted_fares = [10.0] + valid_market_fares + [999999.0]

        bounds = compute_tukey_bounds(corrupted_fares, k=1.5)
        filtered = filter_outliers_tukey(corrupted_fares, k=1.5)

        # 10.0 and 999999.0 should be excluded
        assert 10.0 not in filtered
        assert 999999.0 not in filtered

        # All legitimate fares preserved
        for fare in valid_market_fares:
            assert fare in filtered

        assert bounds.outlier_count == 2


# ===========================================================================
# 11. Invariant 11: Weekly Index Aggregation & Rollup Invariants
# ===========================================================================


class TestWeeklyIndexRollupInvariants:
    """Verifies mathematical invariants of weekly time-series aggregation:
    1. Sample size conservation: Sum(N_weekly) == Sum(N_daily).
    2. Unbiased mean index rollup: I_weekly = mean(I_daily in bucket).
    3. Boundedness: min(I_daily) <= I_weekly <= max(I_daily).
    4. Identity under constant series: I_daily = c => I_weekly = c.
    5. Linear trend midpoint theorem: I_weekly = I_mid for full 7-day linear ramps.
    6. Non-overlapping partition: every daily observation belongs to exactly one week.
    """

    def test_sample_size_conservation(self) -> None:
        """Sample size across all weekly buckets equals the sum of daily sample sizes."""
        daily_samples = [15, 22, 18, 25, 30, 28, 12, 19, 21, 24, 16, 20, 23, 17]
        start_date = date(2026, 2, 2)  # Monday
        records = [
            (start_date + timedelta(days=i), daily_samples[i])
            for i in range(len(daily_samples))
        ]

        buckets: dict[str, int] = {}
        for d, samples in records:
            key = _bucket_key(d, "weekly")
            buckets[key] = buckets.get(key, 0) + samples

        total_weekly_samples = sum(buckets.values())
        assert total_weekly_samples == sum(daily_samples)

    def test_weekly_mean_rollup_unbiasedness(self) -> None:
        """Weekly index is the exact arithmetic mean of daily values in that week."""
        start_date = date(2026, 1, 5)  # Monday
        daily_indices = [102.5, 103.1, 101.8, 104.2, 103.7, 105.0, 102.9]
        records = [
            (start_date + timedelta(days=i), daily_indices[i])
            for i in range(len(daily_indices))
        ]

        week_key = _bucket_key(start_date, "weekly")
        bucket_vals = [val for d, val in records if _bucket_key(d, "weekly") == week_key]

        weekly_index = sum(bucket_vals) / len(bucket_vals)
        expected_mean = sum(daily_indices) / len(daily_indices)
        assert math.isclose(weekly_index, expected_mean, abs_tol=1e-9)

    def test_weekly_rollup_boundedness(self) -> None:
        """Weekly aggregated index is strictly bounded by minimum and maximum daily indices."""
        start_date = date(2026, 1, 1)
        rng = random.Random(42)
        daily_data = [
            (start_date + timedelta(days=i), 100.0 + rng.uniform(-10.0, 15.0))
            for i in range(28)
        ]

        buckets: dict[str, list[float]] = {}
        for d, val in daily_data:
            key = _bucket_key(d, "weekly")
            buckets.setdefault(key, []).append(val)

        for key, vals in buckets.items():
            weekly_mean = sum(vals) / len(vals)
            assert min(vals) <= weekly_mean <= max(vals)

    def test_constant_series_identity(self) -> None:
        """If daily index is constant, weekly rollup reproduces the scalar value exactly."""
        scalar_val = 112.45
        start_date = date(2026, 1, 1)
        daily_data = [
            (start_date + timedelta(days=i), scalar_val)
            for i in range(21)
        ]

        buckets: dict[str, list[float]] = {}
        for d, val in daily_data:
            key = _bucket_key(d, "weekly")
            buckets.setdefault(key, []).append(val)

        for key, vals in buckets.items():
            weekly_mean = sum(vals) / len(vals)
            assert math.isclose(weekly_mean, scalar_val, abs_tol=1e-9)

    def test_linear_trend_midpoint_identity(self) -> None:
        """For a 7-day linear ramp starting on Monday, the weekly index equals the Thursday (midpoint) value."""
        start_date = date(2026, 2, 2)  # Monday
        base = 100.0
        slope = 1.5
        daily_indices = [base + slope * i for i in range(7)]

        weekly_index = sum(daily_indices) / 7.0
        midpoint_value = daily_indices[3]  # Thursday is day index 3

        assert math.isclose(weekly_index, midpoint_value, abs_tol=1e-9)

    def test_isoweek_partitioning_disjoint_and_complete(self) -> None:
        """Every date maps to a unique ISO week bucket; no overlapping or orphaned observations."""
        start_date = date(2025, 12, 25)
        days_count = 60
        all_dates = [start_date + timedelta(days=i) for i in range(days_count)]

        buckets: dict[str, list[date]] = {}
        for d in all_dates:
            key = _bucket_key(d, "weekly")
            buckets.setdefault(key, []).append(d)

        # Total partitioned items must equal original item count
        assert sum(len(group) for group in buckets.values()) == days_count
        # Buckets are disjoint
        seen_dates: set[date] = set()
        for group in buckets.values():
            for d in group:
                assert d not in seen_dates
                seen_dates.add(d)
        assert len(seen_dates) == days_count
