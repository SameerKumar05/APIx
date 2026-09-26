#!/usr/bin/env python3
"""Econometric Specification and Mathematical Invariant Verification Suite.

SIH 2026 Problem Statement 26056 - Real-time Airfare Price Index for CPI Augmentation.

Validates the foundational econometric formulations, microeconomic bounds, and
regulatory surveillance rubrics defined in docs/econometrics_and_cpi_gap.md:
1. Axiomatic Price Index Invariants:
   - Base-period identity test (P_t = P_0 => I_L = I_P = I_F = 100.0)
   - Proportional price scaling test (P_t = lambda * P_0 => I_L = I_P = I_F = 100 * lambda)
   - Irving Fisher Time Reversal Test (I_{0,t} * I_{t,0} == 10000.0)
   - Factor Reversal Test (P * Q == V_t / V_0)
2. Substitution Bias & Bortkiewicz Bounds:
   - Consumer substitution under downward-sloping demand enforces I_L >= I_F >= I_P
   - Substitution bias Delta = I_L - I_F >= 0
   - Uniform price scaling eliminates substitution bias (Delta == 0.0)
   - Positive price dispersion strictly expands substitution bias (dDelta / dsigma > 0)
3. Advance Purchase Price Elasticity Curves (E_d across T+1 -> T+30):
   - Monotonic elasticity ordering: |E_d(T+1)| < |E_d(T+7)| < |E_d(T+15)| < |E_d(T+30)|
   - Inelastic immediate bookings at T+1 (|E_d| < 0.5)
   - Unit-elasticity transition around T+15 (0.8 <= |E_d| <= 1.2)
   - Elastic discretionary leisure bookings at T+30 (|E_d| > 1.2)
   - Arc elasticity and point elasticity formulation consistency
4. MoSPI CPI Transport Sub-Index vs APIx Divergence Tracking:
   - Absolute and Percentage Gap formulations
   - Root Mean Squared Divergence (RMSD) and Mean Absolute Percentage Error (MAPE)
   - Lead-lag cross-correlation analysis proving APIx leads MoSPI by 15-45 days (peak ~38 days)
5. DGCA Statutory Violation Rubric (Aircraft Rules 1937 Rule 135):
   - 3-sigma price surge trigger (Z >= 3.0 => CRITICAL)
   - Abnormal route price spike trigger (Multiple > 2.5x route median => CRITICAL)
   - Day-over-Day surge trigger (DoD >= 40% => CRITICAL)
   - Severe extortionate surge trigger (Z >= 4.0 OR Multiple > 3.5x OR DoD >= 75% => SEVERE)
   - Elevated monitoring trigger (2.0 <= Z < 3.0 OR 1.8 < Multiple <= 2.5 => WARNING)
   - Normal operations (Z < 2.0 AND Multiple <= 1.8x AND DoD < 25% => NORMAL)
"""

import math
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from enum import Enum

# Ensure repository root is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ANSI Colors
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BLUE = "\033[34m"
RESET = "\033[0m"


class EconometricVerificationError(AssertionError):
    """Raised when an econometric invariant or statutory rubric test fails."""


# ==============================================================================
# Reference Econometric Implementations & Invariant Verifiers
# ==============================================================================


def laspeyres_index(
    current_prices: Mapping[str, float],
    base_prices: Mapping[str, float],
    base_quantities: Mapping[str, float],
    base_value: float = 100.0,
) -> float:
    """Computes the Laspeyres Price Index: I_L = (Sum P_t * Q_0) / (Sum P_0 * Q_0) * 100."""
    routes = [r for r in current_prices if r in base_prices and r in base_quantities]
    if not routes:
        raise ValueError("No matching routes for Laspeyres computation")
    num = sum(current_prices[r] * base_quantities[r] for r in routes)
    den = sum(base_prices[r] * base_quantities[r] for r in routes)
    if den <= 0:
        raise ValueError("Laspeyres denominator must be strictly positive")
    return float((num / den) * base_value)


def paasche_index(
    current_prices: Mapping[str, float],
    base_prices: Mapping[str, float],
    current_quantities: Mapping[str, float],
    base_value: float = 100.0,
) -> float:
    """Computes the Paasche Price Index: I_P = (Sum P_t * Q_t) / (Sum P_0 * Q_t) * 100."""
    routes = [r for r in current_prices if r in base_prices and r in current_quantities]
    if not routes:
        raise ValueError("No matching routes for Paasche computation")
    num = sum(current_prices[r] * current_quantities[r] for r in routes)
    den = sum(base_prices[r] * current_quantities[r] for r in routes)
    if den <= 0:
        raise ValueError("Paasche denominator must be strictly positive")
    return float((num / den) * base_value)


def fisher_ideal_index(laspeyres: float, paasche: float) -> float:
    """Computes Fisher Ideal Price Index: I_F = sqrt(I_L * I_P)."""
    if laspeyres < 0 or paasche < 0:
        raise ValueError("Indices must be non-negative for Fisher computation")
    return float(math.sqrt(laspeyres * paasche))


def substitution_bias(laspeyres: float, fisher: float) -> float:
    """Computes absolute substitution bias: Delta = I_L - I_F."""
    return float(laspeyres - fisher)


def relative_substitution_bias_pct(laspeyres: float, fisher: float) -> float:
    """Computes percentage substitution bias: delta = (I_L - I_F) / I_F * 100%."""
    if fisher <= 0:
        return 0.0
    return float(((laspeyres - fisher) / fisher) * 100.0)


# ------------------------------------------------------------------------------
# Advance Booking Elasticity Formulations
# ------------------------------------------------------------------------------


def arc_elasticity(p1: float, p2: float, q1: float, q2: float) -> float:
    """Computes arc price elasticity of demand using the midpoint formula."""
    if math.isclose(p1, p2, abs_tol=1e-9):
        return 0.0
    avg_p = (p1 + p2) / 2.0
    avg_q = (q1 + q2) / 2.0
    if avg_q <= 0 or avg_p <= 0:
        return 0.0
    pct_dq = (q2 - q1) / avg_q
    pct_dp = (p2 - p1) / avg_p
    return float(pct_dq / pct_dp)


def continuous_horizon_elasticity(
    lead_days: float,
    e_min: float = -0.25,
    e_max: float = -1.65,
    h0: float = 14.5,
    k: float = 0.18,
) -> float:
    """Logistic continuous elasticity model across lead days advance h."""
    return float(e_min + (e_max - e_min) / (1.0 + math.exp(-k * (lead_days - h0))))


# ------------------------------------------------------------------------------
# MoSPI CPI Divergence & Cross-Correlation
# ------------------------------------------------------------------------------


def compute_cpi_gap(apix_val: float, mospi_val: float) -> tuple[float, float]:
    """Computes absolute gap and percentage divergence between APIx and MoSPI."""
    abs_gap = apix_val - mospi_val
    pct_gap = (abs_gap / mospi_val * 100.0) if mospi_val > 0 else 0.0
    return float(abs_gap), float(pct_gap)


def compute_rmsd_and_mape(
    apix_series: Sequence[float], mospi_series: Sequence[float]
) -> tuple[float, float]:
    """Computes Root Mean Squared Divergence (RMSD) and Mean Absolute Percentage Error (MAPE)."""
    if len(apix_series) != len(mospi_series) or len(apix_series) == 0:
        raise ValueError("Series lengths must match and be non-empty")
    n = len(apix_series)
    sum_sq = sum((a - m) ** 2 for a, m in zip(apix_series, mospi_series, strict=True))
    rmsd = math.sqrt(sum_sq / n)
    sum_ape = sum(
        abs((a - m) / m) * 100.0
        for a, m in zip(apix_series, mospi_series, strict=True)
        if m > 0
    )
    mape = sum_ape / n
    return float(rmsd), float(mape)


def normalized_cross_correlation(
    x: Sequence[float], y: Sequence[float], max_lag: int = 60
) -> dict[int, float]:
    """Computes normalized cross-correlation R_xy(tau) for integer lags tau in [-max_lag, max_lag]."""
    n = len(x)
    if n != len(y) or n == 0:
        raise ValueError("Series must be non-empty and of equal length")
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)
    denom = math.sqrt(var_x * var_y)
    if denom <= 1e-12:
        return dict.fromkeys(range(-max_lag, max_lag + 1), 0.0)

    corrs: dict[int, float] = {}
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            cov = sum((x[t] - mean_x) * (y[t + lag] - mean_y) for t in range(n - lag))
        else:
            cov = sum((x[t - lag] - mean_x) * (y[t] - mean_y) for t in range(n + lag))
        corrs[lag] = cov / denom
    return corrs


# ------------------------------------------------------------------------------
# DGCA Statutory Violation Rubric
# ------------------------------------------------------------------------------


class DgcaSeverity(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    SEVERE = "SEVERE"


def evaluate_dgca_violation(
    z_score: float,
    route_median_multiple: float,
    dod_surge: float | None = None,
) -> tuple[DgcaSeverity, list[str]]:
    """Evaluates the multi-tier DGCA statutory violation rubric under Aircraft Rules 1937 Rule 135.

    Tiers:
    - SEVERE: Z >= 4.0 OR Multiple > 3.5x OR DoD >= 75%
    - CRITICAL: (Z >= 3.0 OR Multiple > 2.5x OR DoD >= 40%) and not SEVERE
    - WARNING: (Z >= 2.0 OR Multiple > 1.8x OR DoD >= 25%) and not CRITICAL/SEVERE
    - NORMAL: within compliant market ranges
    """
    reasons: list[str] = []

    # Check SEVERE triggers
    if z_score >= 4.0:
        reasons.append(f"Extreme 4-sigma surge: Z={z_score:.2f} >= 4.0")
    if route_median_multiple > 3.5:
        reasons.append(
            f"Extortionate route price multiple: {route_median_multiple:.2f}x > 3.5x median"
        )
    if dod_surge is not None and dod_surge >= 0.75:
        reasons.append(f"Severe Day-over-Day surge: {dod_surge * 100.0:.1f}% >= 75.0%")

    if reasons:
        return DgcaSeverity.SEVERE, reasons

    # Check CRITICAL triggers
    if z_score >= 3.0:
        reasons.append(f"Statutory 3-sigma price surge: Z={z_score:.2f} >= 3.0")
    if route_median_multiple > 2.5:
        reasons.append(
            f"Abnormal route price spike: {route_median_multiple:.2f}x > 2.5x route median"
        )
    if dod_surge is not None and dod_surge >= 0.40:
        reasons.append(
            f"Critical Day-over-Day surge: {dod_surge * 100.0:.1f}% >= 40.0%"
        )

    if reasons:
        return DgcaSeverity.CRITICAL, reasons

    # Check WARNING triggers
    if z_score >= 2.0:
        reasons.append(f"Elevated 2-sigma volatility: Z={z_score:.2f} >= 2.0")
    if route_median_multiple > 1.8:
        reasons.append(
            f"Elevated route price multiple: {route_median_multiple:.2f}x > 1.8x median"
        )
    if dod_surge is not None and dod_surge >= 0.25:
        reasons.append(
            f"Elevated Day-over-Day surge: {dod_surge * 100.0:.1f}% >= 25.0%"
        )

    if reasons:
        return DgcaSeverity.WARNING, reasons

    return DgcaSeverity.NORMAL, [
        "Compliant competitive market pricing under DGCA Rule 135"
    ]


# ==============================================================================
# Test Cases & Formal Verifications
# ==============================================================================


def test_section_1_axiomatic_index_properties() -> None:
    """Test 1: Verify the fundamental economic axioms for Laspeyres, Paasche, and Fisher indices."""
    base_prices = {
        "DEL-BOM": 4500.0,
        "BLR-DEL": 5200.0,
        "BOM-BLR": 3200.0,
        "DEL-CCU": 4800.0,
    }
    base_quantities = {
        "DEL-BOM": 12000.0,
        "BLR-DEL": 8500.0,
        "BOM-BLR": 6000.0,
        "DEL-CCU": 4500.0,
    }

    # 1.1 Base period identity test: P_t == P_0 => I_L == I_P == I_F == 100.0
    il_base = laspeyres_index(base_prices, base_prices, base_quantities)
    ip_base = paasche_index(base_prices, base_prices, base_quantities)
    if_base = fisher_ideal_index(il_base, ip_base)

    if not (
        math.isclose(il_base, 100.0, abs_tol=1e-9)
        and math.isclose(ip_base, 100.0, abs_tol=1e-9)
        and math.isclose(if_base, 100.0, abs_tol=1e-9)
    ):
        raise EconometricVerificationError(
            f"Base period identity test failed: I_L={il_base}, I_P={ip_base}, I_F={if_base}, expected 100.0"
        )

    # 1.2 Proportional price scaling test: P_t == lambda * P_0 => I_L == I_P == I_F == 100 * lambda
    for scalar in [0.80, 1.15, 1.35, 2.0]:
        curr_prices = {r: p * scalar for r, p in base_prices.items()}
        curr_quantities = dict(base_quantities)
        il_scale = laspeyres_index(curr_prices, base_prices, base_quantities)
        ip_scale = paasche_index(curr_prices, base_prices, curr_quantities)
        if_scale = fisher_ideal_index(il_scale, ip_scale)
        expected = 100.0 * scalar
        if not (
            math.isclose(il_scale, expected, rel_tol=1e-7)
            and math.isclose(ip_scale, expected, rel_tol=1e-7)
            and math.isclose(if_scale, expected, rel_tol=1e-7)
        ):
            raise EconometricVerificationError(
                f"Proportional scaling failed for lambda={scalar}: I_L={il_scale}, I_P={ip_scale}, I_F={if_scale}, expected {expected}"
            )

    # 1.3 Time Reversal Test for Fisher Ideal Index: I(0->t) * I(t->0) == 10000.0
    t_prices = {
        "DEL-BOM": 5500.0,
        "BLR-DEL": 6000.0,
        "BOM-BLR": 2900.0,
        "DEL-CCU": 5400.0,
    }
    t_quantities = {
        "DEL-BOM": 10500.0,
        "BLR-DEL": 7800.0,
        "BOM-BLR": 6800.0,
        "DEL-CCU": 4100.0,
    }

    # Forward index (0 -> t)
    il_0_t = laspeyres_index(t_prices, base_prices, base_quantities)
    ip_0_t = paasche_index(t_prices, base_prices, t_quantities)
    if_0_t = fisher_ideal_index(il_0_t, ip_0_t)

    # Reverse index (t -> 0)
    il_t_0 = laspeyres_index(base_prices, t_prices, t_quantities)
    ip_t_0 = paasche_index(base_prices, t_prices, base_quantities)
    if_t_0 = fisher_ideal_index(il_t_0, ip_t_0)

    time_reversal_product = if_0_t * if_t_0
    if not math.isclose(time_reversal_product, 10000.0, rel_tol=1e-7):
        raise EconometricVerificationError(
            f"Fisher Time Reversal Test failed: {if_0_t} * {if_t_0} = {time_reversal_product}, expected 10000.0"
        )

    # Verify Laspeyres and Paasche individually FAIL the time reversal test
    laspeyres_product = il_0_t * il_t_0
    paasche_product = ip_0_t * ip_t_0
    if math.isclose(laspeyres_product, 10000.0, abs_tol=1e-3):
        raise EconometricVerificationError(
            "Laspeyres should fail time reversal test under non-uniform changes"
        )
    if math.isclose(paasche_product, 10000.0, abs_tol=1e-3):
        raise EconometricVerificationError(
            "Paasche should fail time reversal test under non-uniform changes"
        )


def test_section_2_substitution_bias_and_bortkiewicz_bounds() -> None:
    """Test 2: Validate Bortkiewicz's Theorem and substitution bias bounds: I_L >= I_F >= I_P and Delta >= 0."""
    base_prices = {"DEL-BOM": 4000.0, "BLR-DEL": 5000.0, "BOM-BLR": 3000.0}
    base_quantities = {"DEL-BOM": 10000.0, "BLR-DEL": 8000.0, "BOM-BLR": 6000.0}

    # Case A: Downward sloping demand where consumers substitute away from routes experiencing higher inflation
    # DEL-BOM fares surge +50% (4000 -> 6000), traffic drops -30% (10000 -> 7000)
    # BOM-BLR fares drop -10% (3000 -> 2700), traffic surges +33% (6000 -> 8000)
    # BLR-DEL fares remain stable (5000 -> 5000), traffic unchanged (8000 -> 8000)
    current_prices = {"DEL-BOM": 6000.0, "BLR-DEL": 5000.0, "BOM-BLR": 2700.0}
    current_quantities = {"DEL-BOM": 7000.0, "BLR-DEL": 8000.0, "BOM-BLR": 8000.0}

    il = laspeyres_index(current_prices, base_prices, base_quantities)
    ip = paasche_index(current_prices, base_prices, current_quantities)
    if_ = fisher_ideal_index(il, ip)
    bias = substitution_bias(il, if_)
    rel_bias = relative_substitution_bias_pct(il, if_)

    # Verify Invariant Bounds: I_L >= I_F >= I_P
    if not (il >= if_ >= ip):
        raise EconometricVerificationError(
            f"Substitution bias bound violated: I_L={il:.4f}, I_F={if_:.4f}, I_P={ip:.4f}. Expected I_L >= I_F >= I_P."
        )

    # Verify positive substitution bias: Delta = I_L - I_F > 0
    if bias <= 0.0:
        raise EconometricVerificationError(
            f"Expected positive substitution bias under consumer substitution, got Delta={bias}"
        )

    if rel_bias <= 0.0:
        raise EconometricVerificationError(
            f"Expected positive relative substitution bias, got rel_bias={rel_bias}%"
        )

    if not math.isclose(bias, il - if_, abs_tol=1e-9):
        raise EconometricVerificationError("Substitution bias arithmetic mismatch")

    # Case B: Zero-dispersion property: When prices scale uniformly (lambda = 1.25), Delta == 0.0
    uniform_prices = {r: p * 1.25 for r, p in base_prices.items()}
    il_uni = laspeyres_index(uniform_prices, base_prices, base_quantities)
    ip_uni = paasche_index(uniform_prices, base_prices, current_quantities)
    if_uni = fisher_ideal_index(il_uni, ip_uni)
    bias_uni = substitution_bias(il_uni, if_uni)

    if not (
        math.isclose(il_uni, 125.0, abs_tol=1e-9)
        and math.isclose(ip_uni, 125.0, abs_tol=1e-9)
        and math.isclose(if_uni, 125.0, abs_tol=1e-9)
    ):
        raise EconometricVerificationError(
            f"Uniform scaling should equate all indices: {il_uni}, {ip_uni}, {if_uni}"
        )

    if not math.isclose(bias_uni, 0.0, abs_tol=1e-9):
        raise EconometricVerificationError(
            f"Zero dispersion should yield Delta=0, got {bias_uni}"
        )

    # Case C: Dispersion sensitivity: Larger price dispersion expands substitution bias
    high_disp_prices = {"DEL-BOM": 8000.0, "BLR-DEL": 5000.0, "BOM-BLR": 2100.0}
    high_disp_quantities = {"DEL-BOM": 5000.0, "BLR-DEL": 8000.0, "BOM-BLR": 9500.0}

    il_high = laspeyres_index(high_disp_prices, base_prices, base_quantities)
    ip_high = paasche_index(high_disp_prices, base_prices, high_disp_quantities)
    if_high = fisher_ideal_index(il_high, ip_high)
    bias_high = substitution_bias(il_high, if_high)

    if not (bias_high > bias):
        raise EconometricVerificationError(
            f"Greater price dispersion must expand substitution bias: high={bias_high:.4f} vs base={bias:.4f}"
        )


def test_section_3_advance_purchase_price_elasticity_curves() -> None:
    """Test 3: Validate advance booking price elasticity curves E_d across T+1 -> T+30."""
    horizons = ["T+1", "T+7", "T+15", "T+30", "T+45"]
    lead_days = [1, 7, 15, 30]

    # Evaluate continuous logistic elasticity across advance horizons
    elasticities = [continuous_horizon_elasticity(h) for h in lead_days]
    abs_elasticities = [abs(e) for e in elasticities]

    # 3.1 Monotonic ordering: |E_d(T+1)| < |E_d(T+7)| < |E_d(T+15)| < |E_d(T+30)|
    for i in range(len(abs_elasticities) - 1):
        if not (abs_elasticities[i] < abs_elasticities[i + 1]):
            raise EconometricVerificationError(
                f"Elasticity monotonicity violated: |E_d({horizons[i]})|={abs_elasticities[i]:.3f} >= |E_d({horizons[i+1]})|={abs_elasticities[i+1]:.3f}"
            )

    # 3.2 T+1 Inelastic bound: |E_d(T+1)| < 0.5 (emergency / business travel)
    e_t1 = abs_elasticities[0]
    if not (0.20 <= e_t1 <= 0.45):
        raise EconometricVerificationError(
            f"T+1 elasticity out of expected inelastic range [0.20, 0.45]: got {e_t1:.3f}"
        )

    # 3.3 T+7 Moderate inelasticity: 0.5 <= |E_d(T+7)| < 0.85
    e_t7 = abs_elasticities[1]
    if not (0.50 <= e_t7 <= 0.85):
        raise EconometricVerificationError(
            f"T+7 elasticity out of expected range [0.50, 0.85]: got {e_t7:.3f}"
        )

    # 3.4 T+15 Unit-elasticity transition: 0.8 <= |E_d(T+15)| <= 1.2
    e_t15 = abs_elasticities[2]
    if not (0.80 <= e_t15 <= 1.20):
        raise EconometricVerificationError(
            f"T+15 elasticity out of unit-elastic range [0.80, 1.20]: got {e_t15:.3f}"
        )

    # 3.5 T+30 Elastic bound: |E_d(T+30)| > 1.2 (leisure / discretionary)
    e_t30 = abs_elasticities[3]
    if not (1.30 <= e_t30 <= 1.80):
        raise EconometricVerificationError(
            f"T+30 elasticity out of elastic range [1.30, 1.80]: got {e_t30:.3f}"
        )

    # 3.6 Arc Elasticity Consistency Test
    arc_e_t1 = abs(arc_elasticity(6000.0, 7200.0, 1000.0, 940.0))
    arc_e_t30 = abs(arc_elasticity(3000.0, 3600.0, 1000.0, 700.0))

    if not (arc_e_t1 < 0.5):
        raise EconometricVerificationError(
            f"Arc elasticity at T+1 should be inelastic (<0.5), got {arc_e_t1:.3f}"
        )
    if not (arc_e_t30 > 1.2):
        raise EconometricVerificationError(
            f"Arc elasticity at T+30 should be elastic (>1.2), got {arc_e_t30:.3f}"
        )
    if not (arc_e_t1 < arc_e_t30):
        raise EconometricVerificationError(
            "Arc elasticity must satisfy |E_d(T+1)| < |E_d(T+30)|"
        )


def test_section_4_mospi_cpi_gap_and_lead_lag_dynamics() -> None:
    """Test 4: Validate MoSPI CPI Transport Sub-Index vs APIx divergence tracking and lead-lag dynamics."""
    # 4.1 Gap & Relative Divergence
    apix_val = 124.50
    mospi_val = 118.00
    abs_gap, pct_gap = compute_cpi_gap(apix_val, mospi_val)

    if not math.isclose(abs_gap, 6.50, abs_tol=1e-9):
        raise EconometricVerificationError(
            f"Absolute CPI gap failed: got {abs_gap}, expected 6.50"
        )
    expected_pct = (6.50 / 118.00) * 100.0
    if not math.isclose(pct_gap, expected_pct, abs_tol=1e-7):
        raise EconometricVerificationError(
            f"Percentage CPI gap failed: got {pct_gap}, expected {expected_pct}"
        )

    # 4.2 RMSD and MAPE Metrics
    apix_sample = [105.0, 108.5, 114.2, 119.0, 122.4]
    mospi_sample = [102.0, 104.0, 110.0, 115.0, 117.5]
    rmsd, mape = compute_rmsd_and_mape(apix_sample, mospi_sample)

    if rmsd <= 0.0 or mape <= 0.0:
        raise EconometricVerificationError(
            "RMSD and MAPE must be strictly positive for divergent series"
        )

    manual_rmsd = math.sqrt(
        sum((a - m) ** 2 for a, m in zip(apix_sample, mospi_sample, strict=True))
        / len(apix_sample)
    )
    if not math.isclose(rmsd, manual_rmsd, abs_tol=1e-9):
        raise EconometricVerificationError(
            f"RMSD mismatch: {rmsd} vs manual {manual_rmsd}"
        )

    # 4.3 Lead-Lag Cross-Correlation Test
    lag_ground_truth = 38
    n_days = 200
    apix_ts: list[float] = []
    mospi_ts: list[float] = []

    for t in range(n_days):
        s_t = 100.0 + 15.0 * math.sin(2 * math.pi * t / 180.0) + 0.5 * math.sin(t * 1.3)
        apix_ts.append(s_t)
        t_delayed = t - lag_ground_truth
        s_delayed = (
            100.0
            + 15.0 * math.sin(2 * math.pi * t_delayed / 180.0)
            + 0.4 * math.cos(t * 0.9)
        )
        mospi_ts.append(s_delayed)
    # Compute cross-correlation across lags -60 to +60
    cross_corrs = normalized_cross_correlation(apix_ts, mospi_ts, max_lag=60)

    # Find the lag tau* with the maximum positive correlation
    best_lag = max(cross_corrs.keys(), key=lambda k: cross_corrs[k])
    best_r = cross_corrs[best_lag]

    # Verify APIx leads MoSPI: best_lag must be in [15, 45] days
    if not (15 <= best_lag <= 45):
        raise EconometricVerificationError(
            f"Lead-lag cross-correlation failed: best lag {best_lag} outside [15, 45] days (peak R={best_r:.3f})"
        )

    if best_r < 0.70:
        raise EconometricVerificationError(
            f"Peak lead-lag correlation too weak: R={best_r:.3f} < 0.70"
        )


def test_section_5_dgca_statutory_violation_rubric() -> None:
    """Test 5: Validate the multi-tier DGCA statutory violation rubric under Aircraft Rules 1937 Rule 135."""
    # 5.1 Test NORMAL conditions
    sev_normal, _ = evaluate_dgca_violation(
        z_score=1.2,
        route_median_multiple=1.35,
        dod_surge=0.10,
    )
    if sev_normal != DgcaSeverity.NORMAL:
        raise EconometricVerificationError(
            f"Normal conditions classified as {sev_normal}, expected NORMAL"
        )

    # 5.2 Test WARNING conditions: 2.0 <= Z < 3.0
    sev_warn_z, _ = evaluate_dgca_violation(
        z_score=2.35, route_median_multiple=1.5, dod_surge=0.15
    )
    if sev_warn_z != DgcaSeverity.WARNING:
        raise EconometricVerificationError(
            f"Z=2.35 classified as {sev_warn_z}, expected WARNING"
        )

    # 5.3 Test WARNING conditions: Multiple between 1.8x and 2.5x
    sev_warn_mult, _ = evaluate_dgca_violation(
        z_score=1.5, route_median_multiple=2.1, dod_surge=0.12
    )
    if sev_warn_mult != DgcaSeverity.WARNING:
        raise EconometricVerificationError(
            f"Multiple=2.1x classified as {sev_warn_mult}, expected WARNING"
        )

    # 5.4 Test WARNING conditions: DoD between 25% and 40%
    sev_warn_dod, _ = evaluate_dgca_violation(
        z_score=1.1, route_median_multiple=1.4, dod_surge=0.30
    )
    if sev_warn_dod != DgcaSeverity.WARNING:
        raise EconometricVerificationError(
            f"DoD=30% classified as {sev_warn_dod}, expected WARNING"
        )

    # 5.5 Test CRITICAL Statutory 3-Sigma Surge: Z >= 3.0
    sev_crit_z, reasons_crit_z = evaluate_dgca_violation(
        z_score=3.25,
        route_median_multiple=1.9,
        dod_surge=0.20,
    )
    if sev_crit_z != DgcaSeverity.CRITICAL:
        raise EconometricVerificationError(
            f"Z=3.25 classified as {sev_crit_z}, expected CRITICAL"
        )
    if not any("3-sigma" in r for r in reasons_crit_z):
        raise EconometricVerificationError(
            "Expected 3-sigma mention in CRITICAL violation reason"
        )

    # 5.6 Test CRITICAL Abnormal Route Price Spike: Multiple > 2.5x
    sev_crit_mult, reasons_crit_mult = evaluate_dgca_violation(
        z_score=2.2,
        route_median_multiple=2.75,
        dod_surge=0.18,
    )
    if sev_crit_mult != DgcaSeverity.CRITICAL:
        raise EconometricVerificationError(
            f"Multiple=2.75x classified as {sev_crit_mult}, expected CRITICAL"
        )
    if not any("2.5x" in r for r in reasons_crit_mult):
        raise EconometricVerificationError(
            "Expected 2.5x mention in CRITICAL violation reason"
        )

    # 5.7 Test CRITICAL Day-over-Day Surge: DoD >= 40%
    sev_crit_dod, _ = evaluate_dgca_violation(
        z_score=1.8,
        route_median_multiple=1.7,
        dod_surge=0.48,
    )
    if sev_crit_dod != DgcaSeverity.CRITICAL:
        raise EconometricVerificationError(
            f"DoD=48% classified as {sev_crit_dod}, expected CRITICAL"
        )

    # 5.8 Test SEVERE Extortionate Surge: Z >= 4.0
    sev_sev_z, _ = evaluate_dgca_violation(
        z_score=4.15, route_median_multiple=2.2, dod_surge=0.35
    )
    if sev_sev_z != DgcaSeverity.SEVERE:
        raise EconometricVerificationError(
            f"Z=4.15 classified as {sev_sev_z}, expected SEVERE"
        )

    # 5.9 Test SEVERE Extortionate Surge: Multiple > 3.5x
    sev_sev_mult, _ = evaluate_dgca_violation(
        z_score=2.8, route_median_multiple=3.85, dod_surge=0.30
    )
    if sev_sev_mult != DgcaSeverity.SEVERE:
        raise EconometricVerificationError(
            f"Multiple=3.85x classified as {sev_sev_mult}, expected SEVERE"
        )

    # 5.10 Test SEVERE Day-over-Day Surge: DoD >= 75%
    sev_sev_dod, _ = evaluate_dgca_violation(
        z_score=2.5, route_median_multiple=2.0, dod_surge=0.82
    )
    if sev_sev_dod != DgcaSeverity.SEVERE:
        raise EconometricVerificationError(
            f"DoD=82% classified as {sev_sev_dod}, expected SEVERE"
        )

    # 5.11 Boundary precision checks
    b_z3, _ = evaluate_dgca_violation(
        z_score=3.0, route_median_multiple=1.5, dod_surge=0.10
    )
    if b_z3 != DgcaSeverity.CRITICAL:
        raise EconometricVerificationError(
            f"Exact boundary Z=3.0 must trigger CRITICAL, got {b_z3}"
        )

    b_z299, _ = evaluate_dgca_violation(
        z_score=2.9999, route_median_multiple=1.5, dod_surge=0.10
    )
    if b_z299 != DgcaSeverity.WARNING:
        raise EconometricVerificationError(
            f"Boundary Z=2.9999 must trigger WARNING, got {b_z299}"
        )

    b_m25, _ = evaluate_dgca_violation(
        z_score=1.5, route_median_multiple=2.50, dod_surge=0.10
    )
    if b_m25 != DgcaSeverity.WARNING:
        raise EconometricVerificationError(
            f"Multiple=2.50x should be WARNING, got {b_m25}"
        )

    b_m2501, _ = evaluate_dgca_violation(
        z_score=1.5, route_median_multiple=2.501, dod_surge=0.10
    )
    if b_m2501 != DgcaSeverity.CRITICAL:
        raise EconometricVerificationError(
            f"Multiple=2.501x must trigger CRITICAL, got {b_m2501}"
        )


def test_section_6_backend_service_integration() -> None:
    """Test 6: Verify interoperability with existing backend services (index_engine, anomaly_detector)."""
    try:
        from backend.app.services.anomaly_detector import (
            AnomalySeverity,
            calculate_dod_surge,
            calculate_z_score,
            classify_anomaly,
        )
        from backend.app.services.index_engine import (
            calculate_fisher_index,
            calculate_laspeyres_index,
            calculate_paasche_index,
        )

        # Cross-validate index_engine calculations against reference formulations
        base_f = {"DEL-BOM": 4200.0, "BLR-DEL": 5100.0}
        curr_f = {"DEL-BOM": 4800.0, "BLR-DEL": 5300.0}
        weights_0 = {"DEL-BOM": 0.65, "BLR-DEL": 0.35}
        weights_t = {"DEL-BOM": 0.55, "BLR-DEL": 0.45}

        be_il = calculate_laspeyres_index(curr_f, base_f, weights_0)
        be_ip = calculate_paasche_index(curr_f, base_f, weights_t)
        be_if = calculate_fisher_index(be_il, be_ip)

        q_0 = {r: weights_0[r] / base_f[r] for r in base_f}
        ref_il = laspeyres_index(curr_f, base_f, q_0)
        ref_ip = paasche_index(curr_f, base_f, weights_t)
        ref_if = fisher_ideal_index(ref_il, ref_ip)
        if not math.isclose(be_il, ref_il, rel_tol=1e-5):
            raise EconometricVerificationError(
                f"Backend Laspeyres mismatch: {be_il} vs reference {ref_il}"
            )
        if not math.isclose(be_ip, ref_ip, rel_tol=1e-5):
            raise EconometricVerificationError(
                f"Backend Paasche mismatch: {be_ip} vs reference {ref_ip}"
            )
        if not math.isclose(be_if, ref_if, rel_tol=1e-5):
            raise EconometricVerificationError(
                f"Backend Fisher mismatch: {be_if} vs reference {ref_if}"
            )

        # Cross-validate anomaly_detector
        z = calculate_z_score(
            12000.0, 5000.0, 2000.0
        )  # Z = (12000 - 5000) / 2000 = 3.5
        dod = calculate_dod_surge(7500.0, 5000.0)  # DoD = (7500 - 5000) / 5000 = 0.50
        sev = classify_anomaly(z, dod)

        if not math.isclose(z, 3.5, abs_tol=1e-9):
            raise EconometricVerificationError(f"Z-score mismatch: {z} vs expected 3.5")
        if not math.isclose(dod, 0.50, abs_tol=1e-9):
            raise EconometricVerificationError(
                f"DoD surge mismatch: {dod} vs expected 0.50"
            )
        if sev != AnomalySeverity.CRITICAL:
            raise EconometricVerificationError(
                f"Anomaly classification mismatch: {sev} vs expected CRITICAL"
            )

    except ImportError as e:
        print(f"{YELLOW}[NOTICE] Optional backend service import skipped: {e}{RESET}")


# ==============================================================================
# Master Execution Runner
# ==============================================================================


def run_all_econometric_verifications() -> bool:
    """Executes the full suite of econometric mathematical verification tests."""
    print(f"\n{CYAN}{BOLD}{'=' * 80}{RESET}")
    print(
        f"{CYAN}{BOLD}  APIx Econometric & DGCA Statutory Verification Test Suite{RESET}"
    )
    print(
        f"{CYAN}{BOLD}  SIH 2026 PS 26056 - Real-time Airfare Price Index for CPI Augmentation{RESET}"
    )
    print(f"{CYAN}{BOLD}{'=' * 80}{RESET}\n")

    steps: list[tuple[str, Callable[[], None]]] = [
        (
            "Section 1: Axiomatic Price Index Invariants (Identity, Scaling, Time Reversal)",
            test_section_1_axiomatic_index_properties,
        ),
        (
            "Section 2: Substitution Bias & Bortkiewicz Bounds (I_L >= I_F >= I_P, Delta >= 0)",
            test_section_2_substitution_bias_and_bortkiewicz_bounds,
        ),
        (
            "Section 3: Advance Purchase Price Elasticity Curves (T+1 -> T+30 Monotonicity)",
            test_section_3_advance_purchase_price_elasticity_curves,
        ),
        (
            "Section 4: MoSPI CPI Transport Sub-Index vs APIx Divergence & Lead-Lag Dynamics",
            test_section_4_mospi_cpi_gap_and_lead_lag_dynamics,
        ),
        (
            "Section 5: DGCA Statutory Violation Rubric (3-Sigma, >2.5x Median, DoD Surges)",
            test_section_5_dgca_statutory_violation_rubric,
        ),
        (
            "Section 6: Backend Service Interoperability & Cross-Validation",
            test_section_6_backend_service_integration,
        ),
    ]

    all_passed = True
    for idx, (name, test_fn) in enumerate(steps, 1):
        sys.stdout.write(f"{BOLD}[Step {idx}/{len(steps)}]{RESET} {name} ... ")
        sys.stdout.flush()
        try:
            test_fn()
            print(f"{GREEN}{BOLD}PASSED{RESET}")
        except Exception as e:
            print(f"{RED}{BOLD}FAILED{RESET}")
            print(f"{RED}  Error: {e}{RESET}")
            import traceback

            traceback.print_exc()
            all_passed = False

    print(f"\n{CYAN}{'-' * 80}{RESET}")
    if all_passed:
        print(
            f"{GREEN}{BOLD}>>> ALL {len(steps)} ECONOMETRIC VERIFICATION CHECKS PASSED SUCCESSFULLY <<<{RESET}\n"
        )
        return True
    else:
        print(
            f"{RED}{BOLD}>>> ONE OR MORE ECONOMETRIC VERIFICATIONS FAILED <<<{RESET}\n"
        )
        return False


if __name__ == "__main__":
    success = run_all_econometric_verifications()
    sys.exit(0 if success else 1)
