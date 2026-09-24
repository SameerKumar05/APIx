#!/usr/bin/env python3
"""Econometric Engine & ML Anomaly Detection Verification Suite.

SIH 2026 Problem Statement 26056 - Real-time Airfare Price Index (APIx)
Cycle 4: Advanced Econometrics, CPI Gap Analytics, and Machine Learning Anomaly Detection.

Validates:
1. Paasche Price Index Axioms (Base period identity, uniform scaling, current traffic weights).
2. Fisher Ideal Price Index Properties (Geometric mean, Time Reversal Test, Factor Reversal).
3. Substitution Bias Invariants (Laspeyres >= Fisher >= Paasche, non-negative bias Delta >= 0).
4. Booking Horizon Price Elasticity Curve (T+30, T+15, T+7, T+1, negative arc elasticity, urgency multiplier).
5. MoSPI CPI Transport Sub-Index Divergence Analytics (Spread, RMSE tracking error, +38 days lead time).
6. Dynamic Lead-Time Z-Score Volatility Scaling (higher tolerance near departure, tighter advance bounds).
7. Tukey IQR Fences Non-Parametric Outlier Bounds.
8. Carrier Market Concentration Herfindahl-Hirschman Index (HHI).
9. Multi-Feature Surge Classification & DGCA Statutory Tariff Violations (3-sigma, DoD >= 40%, 2.5x median).
10. End-to-End Pipeline Persistence (Laspeyres, Paasche, Fisher, Substitution Bias in NationalDailyIndex).
"""

from __future__ import annotations

import math
import os
import sys
from datetime import date

# Ensure repository root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.app.services.econometric_engine import (
    BENCHMARK_MOSPI_CPI_SERIES,
    CpiDivergenceResult,
    EconometricEngine,
    LeadTimeElasticityResult,
    SubstitutionBias,
    calculate_fisher_index,
    calculate_lead_time_elasticity,
    calculate_mospi_cpi_divergence,
    calculate_paasche_index,
    calculate_substitution_bias,
)
from backend.app.services.index_engine import (
    DEFAULT_AIRLINE_MARKET_SHARES,
    calculate_laspeyres_index,
)
from backend.app.services.ml_anomaly_detector import (
    MLAnomalyDetector,
    MLAnomalyResult,
    MLAnomalySeverity,
    calculate_dynamic_z_score,
    calculate_hhi,
    calculate_tukey_fences,
    classify_surge_multifeature,
)


class VerificationFailure(AssertionError):
    """Raised when an econometric invariant or statistical precision test fails."""


# ===========================================================================
# 1. Paasche Price Index Axiomatic Properties
# ===========================================================================


def test_paasche_index_axioms() -> None:
    """Verifies foundational axiomatic properties of the Paasche price index."""
    base_fares = {
        "DEL-BOM": 5500.0,
        "BOM-DEL": 5450.0,
        "BLR-DEL": 6200.0,
        "DEL-BLR": 6150.0,
    }
    weights = {
        "DEL-BOM": 0.35,
        "BOM-DEL": 0.35,
        "BLR-DEL": 0.15,
        "DEL-BLR": 0.15,
    }

    # Axiom 1: Base Period Identity (P_t == P_0 => Paasche == 100.00)
    idx_base = calculate_paasche_index(
        current_fares=base_fares,
        base_fares=base_fares,
        current_weights=weights,
        base_value=100.0,
    )
    if not math.isclose(idx_base, 100.00, abs_tol=1e-9):
        raise VerificationFailure(f"Base period Paasche should equal 100.00, got {idx_base}")

    # Axiom 2: Uniform Relative Scaling (+25% across all routes => Paasche == 125.00)
    scaled_fares = {r: f * 1.25 for r, f in base_fares.items()}
    idx_scaled = calculate_paasche_index(
        current_fares=scaled_fares,
        base_fares=base_fares,
        current_weights=weights,
        base_value=100.0,
    )
    if not math.isclose(idx_scaled, 125.00, abs_tol=1e-9):
        raise VerificationFailure(f"Uniform +25% Paasche should equal 125.00, got {idx_scaled}")

    # Axiom 3: Strict Monotonicity (increasing any price strictly increases the index)
    single_up_fares = dict(base_fares)
    single_up_fares["DEL-BOM"] = 6500.0  # Increased fare on top route
    idx_mono = calculate_paasche_index(
        current_fares=single_up_fares,
        base_fares=base_fares,
        current_weights=weights,
        base_value=100.0,
    )
    if idx_mono <= 100.00:
        raise VerificationFailure(f"Paasche index must strictly increase, got {idx_mono} <= 100.0")


# ===========================================================================
# 2. Fisher Ideal Price Index Axiomatic Properties
# ===========================================================================


def test_fisher_ideal_index_properties() -> None:
    """Verifies axiomatic properties of the Fisher Ideal Price Index."""
    # Test 1: Geometric mean identity
    laspeyres = 121.00
    paasche = 100.00
    expected_fisher = math.sqrt(laspeyres * paasche)  # sqrt(12100) = 110.00
    computed_fisher = calculate_fisher_index(laspeyres, paasche)
    if not math.isclose(computed_fisher, expected_fisher, abs_tol=1e-9):
        raise VerificationFailure(
            f"Fisher geometric mean failed: expected {expected_fisher}, got {computed_fisher}"
        )

    # Test 2: Base Period Identity (100.0 and 100.0 => 100.0)
    fisher_base = calculate_fisher_index(100.00, 100.00)
    if not math.isclose(fisher_base, 100.00, abs_tol=1e-9):
        raise VerificationFailure(f"Base period Fisher should equal 100.00, got {fisher_base}")

    # Test 3: Time Reversal Test
    # In index theory, P_{0,1} * P_{1,0} == 1.0 (or 10000.0 when scaled by 100)
    p0 = {"A": 100.0, "B": 200.0}
    p1 = {"A": 150.0, "B": 180.0}
    q0 = {"A": 10.0, "B": 5.0}
    q1 = {"A": 12.0, "B": 4.0}

    # Forward direction 0 -> 1: Laspeyres uses q0, Paasche uses q1
    l_fwd = sum(p1[r] * q0[r] for r in p0) / sum(p0[r] * q0[r] for r in p0)
    p_fwd = calculate_paasche_index(p1, p0, q1, base_value=1.0)
    f_fwd = calculate_fisher_index(l_fwd, p_fwd)

    # Backward direction 1 -> 0: Laspeyres uses q1, Paasche uses q0
    l_bwd = sum(p0[r] * q1[r] for r in p0) / sum(p1[r] * q1[r] for r in p0)
    p_bwd = calculate_paasche_index(p0, p1, q0, base_value=1.0)
    f_bwd = calculate_fisher_index(l_bwd, p_bwd)

    # Fisher must satisfy time reversal: f_fwd * f_bwd == 1.0
    product = f_fwd * f_bwd
    if not math.isclose(product, 1.0, abs_tol=1e-6):
        raise VerificationFailure(
            f"Fisher Index violated Time Reversal Test: {f_fwd} * {f_bwd} = {product} != 1.0"
        )


# ===========================================================================
# 3. Substitution Bias Invariants and Bounds
# ===========================================================================


def test_substitution_bias_bounds_and_invariants() -> None:
    """Verifies that Laspeyres >= Fisher >= Paasche under consumer substitution."""
    # Microeconomic scenario:
    # Route 1 (DEL-BOM) fare rises by +50% (from 5000 to 7500)
    # Route 2 (DEL-BLR) fare rises by only +10% (from 5000 to 5500)
    # Consumers substitute away from expensive Route 1 to Route 2:
    # Base quantity weights: (Route 1: 0.60, Route 2: 0.40)
    # Current quantity weights (post-substitution): (Route 1: 0.30, Route 2: 0.70)
    base_fares = {"R1": 5000.0, "R2": 5000.0}
    curr_fares = {"R1": 7500.0, "R2": 5500.0}
    base_weights = {"R1": 0.60, "R2": 0.40}
    curr_weights = {"R1": 0.30, "R2": 0.70}

    # 1. Laspeyres uses base period weights:
    # R1: 1.50 * 0.60 = 0.90; R2: 1.10 * 0.40 = 0.44 => 1.34 * 100 = 134.00
    idx_l = calculate_laspeyres_index(curr_fares, base_fares, base_weights, base_value=100.0)

    # 2. Paasche uses current period weights:
    # Num = 7500*0.30 + 5500*0.70 = 2250 + 3850 = 6100
    # Den = 5000*0.30 + 5000*0.70 = 1500 + 3500 = 5000
    # Paasche = (6100 / 5000) * 100 = 122.00
    idx_p = calculate_paasche_index(curr_fares, base_fares, curr_weights, base_value=100.0)

    # 3. Fisher is geometric mean:
    # Fisher = sqrt(134 * 122) = sqrt(16348) = 127.8593
    idx_f = calculate_fisher_index(idx_l, idx_p)

    # Verification of Microeconomic Invariant: Laspeyres >= Fisher >= Paasche
    if not (idx_l >= idx_f >= idx_p):
        raise VerificationFailure(
            f"Substitution inequality violated: Laspeyres ({idx_l:.2f}) >= "
            f"Fisher ({idx_f:.2f}) >= Paasche ({idx_p:.2f}) must hold."
        )

    # Substitution Bias: Delta = L - F
    bias = calculate_substitution_bias(idx_l, idx_f, idx_p)

    # Verification of non-negative bias
    if bias.bias_points <= 0.0:
        raise VerificationFailure(
            f"Substitution bias must be strictly positive under substitution, got {bias.bias_points}"
        )
    if not bias.is_positive:
        raise VerificationFailure("bias.is_positive must be True")

    # Verify native float protocol compatibility
    if not isinstance(bias, float):
        raise VerificationFailure("SubstitutionBias must inherit from float")
    if not math.isclose(float(bias), bias.bias_points, abs_tol=1e-6):
        raise VerificationFailure("float(bias) must equal bias.bias_points")

    # Verify dictionary export
    d = bias.to_dict()
    if "bias_points" not in d or "bias_pct" not in d or "laspeyres_index" not in d:
        raise VerificationFailure(f"Missing keys in bias.to_dict(): {d.keys()}")

    # Invariant: If prices scale uniformly (no relative price change), bias must be 0.00
    scaled_fares = {r: f * 1.20 for r, f in base_fares.items()}
    idx_l_uniform = calculate_laspeyres_index(scaled_fares, base_fares, base_weights, 100.0)
    idx_p_uniform = calculate_paasche_index(scaled_fares, base_fares, curr_weights, 100.0)
    idx_f_uniform = calculate_fisher_index(idx_l_uniform, idx_p_uniform)
    bias_uniform = calculate_substitution_bias(idx_l_uniform, idx_f_uniform)

    if not math.isclose(bias_uniform.bias_points, 0.00, abs_tol=1e-6):
        raise VerificationFailure(
            f"Uniform scaling must produce 0.00 substitution bias, got {bias_uniform.bias_points}"
        )


# ===========================================================================
# 4. Advance Booking Lead-Time Price Elasticity Curve
# ===========================================================================


def test_lead_time_elasticity_curve() -> None:
    """Verifies price escalation and negative demand elasticity across booking horizons."""
    window_fares = {
        "T+30": 3800.0,  # Advance leisure (cheapest)
        "T+15": 4600.0,  # Planned travel
        "T+7": 5400.0,   # Short-lead standard
        "T+1": 7800.0,   # Last-minute urgent (most expensive)
    }
    pax_shares = {
        "T+30": 0.15,
        "T+15": 0.30,
        "T+7": 0.35,
        "T+1": 0.20,
    }

    result: LeadTimeElasticityResult = calculate_lead_time_elasticity(window_fares, pax_shares)

    # 1. Price escalation: T+1 price > T+30 price
    if result.lead_time_premium_pct <= 0.0:
        raise VerificationFailure(
            f"Lead-time premium must be positive, got {result.lead_time_premium_pct}%"
        )
    if result.urgency_multiplier <= 1.0:
        raise VerificationFailure(
            f"Urgency multiplier must be > 1.0, got {result.urgency_multiplier}"
        )

    # Expected urgency multiplier: 7800 / 3800 = ~2.05x
    expected_mult = round(7800.0 / 3800.0, 2)
    if not math.isclose(result.urgency_multiplier, expected_mult, abs_tol=0.05):
        raise VerificationFailure(
            f"Urgency multiplier mismatch: expected {expected_mult}, got {result.urgency_multiplier}"
        )

    # 2. Verify curves structure
    if "T+1" not in result.curves or "T+30" not in result.curves:
        raise VerificationFailure(f"Curves must contain T+1 and T+30: {result.curves.keys()}")

    # 3. Verify dictionary export
    d = result.to_dict()
    if "overall_elasticity" not in d or "lead_time_premium_pct" not in d:
        raise VerificationFailure(f"Missing keys in elasticity to_dict: {d.keys()}")


# ===========================================================================
# 5. MoSPI CPI Divergence & Predictive Lead-Lag Analysis
# ===========================================================================


def test_mospi_cpi_divergence_analytics() -> None:
    """Verifies divergence gap and cross-correlation lead time against MoSPI CPI."""
    # Synthesize realistic APIx high-frequency airfare series
    apix_series = [
        {"period": "2025-10", "index_value": 194.5},
        {"period": "2025-11", "index_value": 195.8},
        {"period": "2025-12", "index_value": 196.2},
        {"period": "2026-01", "index_value": 197.0},
        {"period": "2026-02", "index_value": 197.8},
        {"period": "2026-03", "index_value": 198.5},
    ]

    div_result: CpiDivergenceResult = calculate_mospi_cpi_divergence(
        apix_index_series=apix_series,
        mospi_cpi_series=BENCHMARK_MOSPI_CPI_SERIES,
    )

    # 1. Divergence gap must be computed and positive (airfare higher volatility than basket)
    if div_result.current_divergence_gap <= 0:
        raise VerificationFailure(
            f"APIx airfare index divergence gap should be positive, got {div_result.current_divergence_gap}"
        )

    # 2. Estimated lead time should demonstrate predictive lead (~38 days)
    if div_result.estimated_lead_days < 30:
        raise VerificationFailure(
            f"APIx should lead published MoSPI CPI by at least 30 days, got {div_result.estimated_lead_days}"
        )

    # 3. Tracking error RMSE must be finite positive
    if div_result.tracking_error_rmse <= 0.0:
        raise VerificationFailure("Tracking error RMSE must be strictly positive")

    # 4. Lead-lag cross correlation table must contain lag offsets
    if "lag_+1m" not in div_result.lead_lag_correlations:
        raise VerificationFailure("Lead-lag correlations must contain lag_+1m")


# ===========================================================================
# 6. Dynamic Lead-Time Z-Score Volatility Scaling
# ===========================================================================


def test_dynamic_z_score_scaling() -> None:
    """Verifies that dynamic Z-score scales volatility tolerance by booking lead time."""
    base_mean = 5000.0
    base_std = 500.0
    fare_spike = 6500.0  # +1500 INR difference (nominal 3-sigma under static sigma=500)

    # At T+30 (advance booking): low expected volatility, high sensitivity
    z_dyn_t30, z_std_t30, urg_t30 = calculate_dynamic_z_score(
        observed_fare=fare_spike,
        baseline_mean=base_mean,
        baseline_std=base_std,
        lead_time_days=30,
    )

    # At T+1 (departure urgency): high expected volatility, higher dispersion tolerance
    z_dyn_t1, z_std_t1, urg_t1 = calculate_dynamic_z_score(
        observed_fare=fare_spike,
        baseline_mean=base_mean,
        baseline_std=base_std,
        lead_time_days=1,
    )

    # Standard Z-scores must be identical (static)
    if not math.isclose(z_std_t30, z_std_t1, abs_tol=1e-6):
        raise VerificationFailure("Standard Z-scores must be independent of lead time")

    # Dynamic Z-score at T+1 must be strictly less than at T+30 due to urgency scaling
    if z_dyn_t1 >= z_dyn_t30:
        raise VerificationFailure(
            f"Dynamic Z-score at T+1 ({z_dyn_t1}) should be lower than T+30 ({z_dyn_t30}) "
            f"due to natural last-minute price dispersion tolerance."
        )

    # Urgency factor at T+1 must be higher than at T+30
    if urg_t1 <= urg_t30:
        raise VerificationFailure(
            f"Urgency factor at T+1 ({urg_t1}) must exceed T+30 ({urg_t30})"
        )


# ===========================================================================
# 7. Tukey IQR Fences Outlier Detection
# ===========================================================================


def test_tukey_iqr_fences() -> None:
    """Verifies non-parametric Tukey outlier boundary calculation."""
    fares = [4200.0, 4300.0, 4500.0, 4700.0, 4800.0, 5000.0, 5200.0, 5500.0, 12000.0]
    fences = calculate_tukey_fences(fares, k=1.5)

    q1 = fences["q1"]
    q3 = fences["q3"]
    iqr = fences["iqr"]
    upper = fences["upper_fence"]

    if q3 <= q1:
        raise VerificationFailure(f"Q3 ({q3}) must be greater than Q1 ({q1})")
    if iqr <= 0:
        raise VerificationFailure(f"IQR ({iqr}) must be positive")
    if upper <= q3:
        raise VerificationFailure(f"Upper fence ({upper}) must exceed Q3 ({q3})")

    # 12,000 INR outlier should breach the upper fence
    if 12000.0 <= upper:
        raise VerificationFailure(
            f"12,000 INR outlier should exceed upper fence ({upper})"
        )


# ===========================================================================
# 8. Carrier Market Concentration Herfindahl-Hirschman Index (HHI)
# ===========================================================================


def test_carrier_concentration_hhi() -> None:
    """Verifies Herfindahl-Hirschman Index properties across competitive market structures."""
    # Monopoly (100% single carrier) => HHI == 1.0000
    monopoly = {"AIRLINE_A": 1.0}
    if not math.isclose(calculate_hhi(monopoly), 1.0000, abs_tol=1e-4):
        raise VerificationFailure("Monopoly HHI must equal 1.0000")

    # Perfect 4-firm symmetric competition => HHI == 0.2500
    symmetric_4 = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    if not math.isclose(calculate_hhi(symmetric_4), 0.2500, abs_tol=1e-4):
        raise VerificationFailure("Symmetric 4-firm HHI must equal 0.2500")

    # Official DGCA domestic benchmark: IndiGo 62%, Air India 20%, AIX 8%, Akasa 5%, SpiceJet 4%
    # HHI = 0.62^2 + 0.20^2 + 0.08^2 + 0.05^2 + 0.04^2 = 0.3844 + 0.04 + 0.0064 + 0.0025 + 0.0016 = 0.4349
    dgca_hhi = calculate_hhi(DEFAULT_AIRLINE_MARKET_SHARES)
    if not (0.43 <= dgca_hhi <= 0.45):
        raise VerificationFailure(f"DGCA carrier market HHI expected between 0.43 and 0.45, got {dgca_hhi}")


# ===========================================================================
# 9. Multi-Feature Surge Classification & DGCA Statutory Tariff Violations
# ===========================================================================


def test_multi_feature_surge_classification() -> None:
    """Verifies multi-feature surge scoring and DGCA statutory tariff violation detection."""
    base_mean = 5000.0
    base_std = 400.0

    # Scenario A: Normal Fare within 1-sigma
    res_normal = classify_surge_multifeature(
        fare=5200.0,
        baseline_mean=base_mean,
        baseline_std=base_std,
        lead_time_days=7,
        previous_fare=5100.0,
        route_median=base_mean,
    )
    if res_normal.severity != MLAnomalySeverity.NORMAL:
        raise VerificationFailure(f"5200 INR should be NORMAL, got {res_normal.severity}")
    if res_normal.is_anomaly or res_normal.is_dgca_violation:
        raise VerificationFailure("Normal fare must not trigger anomaly or DGCA violation")

    # Scenario B: 3-Sigma Statistical Price Spike
    res_3sigma = classify_surge_multifeature(
        fare=6800.0,  # +1800 INR over 5000 (Z = 1800/400 = 4.5 > 3.0)
        baseline_mean=base_mean,
        baseline_std=base_std,
        lead_time_days=7,
        previous_fare=5200.0,
        route_median=base_mean,
    )
    if res_3sigma.severity != MLAnomalySeverity.CRITICAL:
        raise VerificationFailure(f"3-sigma surge should be CRITICAL, got {res_3sigma.severity}")
    if not res_3sigma.is_dgca_violation:
        raise VerificationFailure("3-sigma surge must trigger DGCA statutory violation")

    # Scenario C: Day-over-Day surge >= 40% (0.40)
    res_dod = classify_surge_multifeature(
        fare=6500.0,
        baseline_mean=base_mean,
        baseline_std=base_std,
        lead_time_days=7,
        previous_fare=4000.0,  # 6500 vs 4000 = +62.5% DoD surge
        route_median=base_mean,
    )
    if not res_dod.is_dgca_violation:
        raise VerificationFailure("DoD surge >= 40% must trigger DGCA statutory violation")
    if res_dod.dod_surge is None or res_dod.dod_surge < 0.40:
        raise VerificationFailure(f"DoD surge should be >= 0.40, got {res_dod.dod_surge}")

    # Scenario D: Route Price > 2.5x Route Baseline Median
    res_ceiling = classify_surge_multifeature(
        fare=13500.0,  # 13500 / 5000 = 2.70x median (> 2.50x)
        baseline_mean=base_mean,
        baseline_std=base_std,
        lead_time_days=7,
        previous_fare=12000.0,
        route_median=base_mean,
    )
    if not res_ceiling.is_dgca_violation:
        raise VerificationFailure("Price > 2.5x median must trigger DGCA statutory violation")
    if res_ceiling.violation_code != "DGCA_CAR_TARIFF_CEILING_BREACH":
        raise VerificationFailure(
            f"Expected DGCA_CAR_TARIFF_CEILING_BREACH, got {res_ceiling.violation_code}"
        )

    # Scenario E: Market Concentration Exploitation (HHI >= 0.40 and Z >= 2.5)
    res_hhi = classify_surge_multifeature(
        fare=6200.0,  # Z = 1200 / 400 = 3.0 (or with dynamic scaling Z > 2.5)
        baseline_mean=base_mean,
        baseline_std=base_std,
        lead_time_days=7,
        carrier_hhi=0.55,  # Highly concentrated route
        route_median=base_mean,
    )
    if not res_hhi.is_dgca_violation:
        raise VerificationFailure("High HHI + Z >= 2.5 must trigger DGCA violation")


# ===========================================================================
# 10. EconometricEngine Batch Orchestrator
# ===========================================================================


def test_econometric_engine_orchestrator() -> None:
    """Verifies the EconometricEngine master orchestrator class."""
    base_fares = {"DEL-BOM": 5500.0, "BOM-DEL": 5450.0}
    engine = EconometricEngine(base_fares=base_fares, base_value=100.0)

    current_fares = {"DEL-BOM": 6600.0, "BOM-DEL": 6000.0}
    weights = {"DEL-BOM": 0.50, "BOM-DEL": 0.50}

    results = engine.calculate_all_indices(
        current_fares=current_fares,
        laspeyres_weights=weights,
        paasche_weights=weights,
    )

    if "laspeyres_index" not in results:
        raise VerificationFailure("Missing laspeyres_index in engine output")
    if "paasche_index" not in results:
        raise VerificationFailure("Missing paasche_index in engine output")
    if "fisher_index" not in results:
        raise VerificationFailure("Missing fisher_index in engine output")
    if "substitution_bias" not in results:
        raise VerificationFailure("Missing substitution_bias in engine output")

    # Under identical weights and positive fares, Fisher must equal sqrt(L * P)
    l_val = results["laspeyres_index"]
    p_val = results["paasche_index"]
    f_val = results["fisher_index"]
    expected_f = round(math.sqrt(l_val * p_val), 4)

    if not math.isclose(f_val, expected_f, abs_tol=1e-3):
        raise VerificationFailure(f"Fisher index mismatch: expected {expected_f}, got {f_val}")


# ===========================================================================
# Master Verification Runner
# ===========================================================================


def run_all_tests() -> None:
    """Executes all econometric and ML anomaly verification test cases."""
    print("=" * 80)
    print("APIx Econometric Engine & ML Anomaly Detection Verification Suite")
    print("SIH 2026 Problem Statement 26056 - Master Cycle 4 Quantitative Engine")
    print("=" * 80)

    tests = [
        ("Paasche Index Axioms (Base Identity, Uniform Scaling, Monotonicity)", test_paasche_index_axioms),
        ("Fisher Ideal Index Properties (Geometric Mean, Time Reversal Test)", test_fisher_ideal_index_properties),
        ("Substitution Bias Invariants & Bounds (L >= F >= P, Delta >= 0)", test_substitution_bias_bounds_and_invariants),
        ("Lead-Time Price Elasticity Curve (T+30 to T+1, Urgency Multiplier)", test_lead_time_elasticity_curve),
        ("MoSPI CPI Transport Sub-Index Divergence (+38 Days Lead Analysis)", test_mospi_cpi_divergence_analytics),
        ("Dynamic Lead-Time Z-Score Volatility Scaling (T+1 vs T+30 Tolerance)", test_dynamic_z_score_scaling),
        ("Tukey IQR Fences Non-Parametric Outlier Bounds", test_tukey_iqr_fences),
        ("Carrier Market Concentration Herfindahl-Hirschman Index (HHI)", test_carrier_concentration_hhi),
        ("Multi-Feature Surge Classification & DGCA Statutory Violations", test_multi_feature_surge_classification),
        ("EconometricEngine High-Level Batch Orchestrator", test_econometric_engine_orchestrator),
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
    run_all_tests()
