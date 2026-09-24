"""APIx ML-Augmented Anomaly Detector - Dynamic Airfare Spike & Regulatory Surveillance.

Implements SIH 2026 Problem Statement 26056 advanced surveillance specifications:
1. Rolling Dynamic Z-scores with lead-time volatility scaling:
   Adjusts dispersion expectations based on booking horizon urgency (T+1 vs T+30).
2. Tukey IQR Fences:
   Non-parametric outlier boundaries [Q1 - k*IQR, Q3 + k*IQR] robust to skewed fare distributions.
3. Multi-Feature Surge Classification:
   Ensemble feature vector combining fare level ratio, booking lead time, historical route
   volatility (CV), Day-over-Day surge, and carrier market concentration (HHI).
4. DGCA Statutory Violation Triggers:
   - 3-sigma statistical price shock (Z >= 3.0)
   - Day-over-Day surge >= 40% (DoD >= 0.40)
   - Excessive route surge multiple: fare > 2.5x route baseline median
   - Market dominance exploitation: HHI >= 0.40 with Z >= 2.5
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from backend.app.services.index_engine import DEFAULT_AIRLINE_MARKET_SHARES


class MLAnomalySeverity(StrEnum):
    """Classification of airfare pricing anomalies and regulatory alerts."""

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class MLAnomalyResult:
    """Detailed result of multi-feature machine learning anomaly classification."""

    observed_fare: float
    baseline_mean: float
    baseline_std: float
    dynamic_z_score: float
    standard_z_score: float
    tukey_lower: float
    tukey_upper: float
    is_tukey_outlier: bool
    dod_surge: float | None
    lead_time_days: int
    lead_time_urgency_factor: float
    route_volatility: float
    carrier_hhi: float
    fare_to_median_ratio: float
    anomaly_score: float
    severity: MLAnomalySeverity
    is_anomaly: bool
    is_dgca_violation: bool
    violation_code: str | None
    feature_contributions: dict[str, float]
    explanation: str
    route_code: str | None = None
    airline_code: str | None = None
    flight_number: str | None = None
    booking_window: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


# ---------------------------------------------------------------------------
# 1. Rolling Dynamic Z-Score Calculation
# ---------------------------------------------------------------------------


def calculate_dynamic_z_score(
    observed_fare: float,
    baseline_mean: float,
    baseline_std: float,
    lead_time_days: int = 7,
) -> tuple[float, float, float]:
    """Calculates lead-time adjusted dynamic Z-score.

    In airline pricing, fares closer to departure (e.g. 1 day out) naturally
    exhibit higher standard deviation than advance fares (e.g. 30 days out).
    A static Z-score produces excessive false positives on T+1 and false negatives
    on T+30. The dynamic Z-score scales expected volatility phi(h):
        sigma_dyn = sigma * (1.0 + 0.35 * exp(-lead_time / 10.0))

    Args:
        observed_fare: Observed fare price P.
        baseline_mean: Rolling historical baseline mean mu.
        baseline_std: Rolling historical baseline standard deviation sigma.
        lead_time_days: Booking horizon lead time in days (e.g. 1, 7, 15, 30).

    Returns:
        Tuple of (dynamic_z_score, standard_z_score, urgency_factor).
    """
    p = float(observed_fare)
    mu = float(baseline_mean)
    sigma = float(baseline_std)
    h = max(1, int(lead_time_days))

    # Standard Z-score
    diff = p - mu
    if sigma <= 1e-9:
        if math.isclose(diff, 0.0, abs_tol=1e-9):
            return 0.0, 0.0, 1.0
        standard_z = 999.0 if diff > 0 else -999.0
        return standard_z, standard_z, 1.0

    standard_z = diff / sigma

    # Dynamic scaling: higher tolerance near departure, tighter tolerance far out
    urgency_factor = 1.0 + 0.35 * math.exp(-float(h) / 10.0)
    sigma_dyn = sigma * urgency_factor

    dynamic_z = diff / sigma_dyn
    return round(float(dynamic_z), 4), round(float(standard_z), 4), round(float(urgency_factor), 4)


# ---------------------------------------------------------------------------
# 2. Tukey IQR Fences
# ---------------------------------------------------------------------------


def calculate_tukey_fences(
    fares: Sequence[float],
    k: float = 1.5,
) -> dict[str, float]:
    """Computes Tukey Interquartile Range (IQR) fences for non-parametric outlier bounds.

    Formula:
        IQR = Q3 - Q1
        Lower Fence = Q1 - k * IQR
        Upper Fence = Q3 + k * IQR

    Args:
        fares: Collection of fare values.
        k: IQR multiplier (default 1.5 for outliers, 3.0 for extreme outliers).

    Returns:
        Dictionary with q1, q3, iqr, lower_fence, upper_fence.
    """
    valid = [float(f) for f in fares if f is not None and f > 0]
    if not valid:
        return {
            "q1": 0.0,
            "q3": 0.0,
            "iqr": 0.0,
            "lower_fence": 0.0,
            "upper_fence": 0.0,
        }

    valid.sort()
    n = len(valid)

    def _get_pct(p: float) -> float:
        idx = p * (n - 1)
        low = int(math.floor(idx))
        high = int(math.ceil(idx))
        if low == high:
            return valid[low]
        weight = idx - low
        return valid[low] * (1.0 - weight) + valid[high] * weight

    q1 = _get_pct(0.25)
    q3 = _get_pct(0.75)
    iqr = max(0.0, q3 - q1)

    lower = max(0.0, q1 - k * iqr)
    upper = q3 + k * iqr

    return {
        "q1": round(q1, 2),
        "q3": round(q3, 2),
        "iqr": round(iqr, 2),
        "lower_fence": round(lower, 2),
        "upper_fence": round(upper, 2),
    }


# ---------------------------------------------------------------------------
# 3. Carrier Concentration (Herfindahl-Hirschman Index)
# ---------------------------------------------------------------------------


def calculate_hhi(carrier_shares: Mapping[str, float]) -> float:
    """Computes the Herfindahl-Hirschman Index (HHI) for carrier market concentration.

    Formula:
        HHI = Sum(s_i^2) where s_i is carrier market share normalized to 1.0.
        Value ranges from (1/N) (perfect competition) to 1.0 (monopoly).

    Args:
        carrier_shares: Mapping of carrier codes to market share or seat capacity.

    Returns:
        Normalized HHI index between 0.0 and 1.0.
    """
    if not carrier_shares:
        return 0.25

    total = sum(v for v in carrier_shares.values() if v > 0)
    if total <= 0:
        return 0.25

    normalized = [v / total for v in carrier_shares.values() if v > 0]
    hhi = sum(s ** 2 for s in normalized)
    return round(float(hhi), 4)


# ---------------------------------------------------------------------------
# 4. Multi-Feature Surge Classification
# ---------------------------------------------------------------------------


def classify_surge_multifeature(
    fare: float,
    baseline_mean: float,
    baseline_std: float,
    lead_time_days: int = 7,
    route_volatility: float = 0.15,
    carrier_hhi: float = 0.42,
    previous_fare: float | None = None,
    route_median: float | None = None,
    fares_sample: Sequence[float] | None = None,
    route_code: str | None = None,
    airline_code: str | None = None,
    flight_number: str | None = None,
    booking_window: str | None = None,
) -> MLAnomalyResult:
    """Classifies airfare anomalies using multi-feature statistical and regulatory rules.

    Features:
    1. Dynamic Z-score: Lead-time adjusted deviation from historical mean.
    2. Tukey IQR Fence breach: Non-parametric upper bound violation.
    3. Day-over-Day (DoD) surge: Relative 24-hour rate of change.
    4. Route Volatility: Baseline coefficient of variation (sigma / mu).
    5. Carrier Concentration (HHI): Market power measure.
    6. Surge Multiple: Observed fare / route median fare.

    Regulatory Violation Rules (DGCA Civil Aviation Requirements):
    - Rule 1: Dynamic Z-score >= 3.0 (3-sigma statistical price spike).
    - Rule 2: Day-over-Day surge >= 40% (DoD >= 0.40).
    - Rule 3: Surge multiple > 2.5x route baseline median (predatory tariff).
    - Rule 4: High concentration market dominance spike (HHI >= 0.40 and Z >= 2.5).

    Args:
        fare: Observed flight quote fare in INR.
        baseline_mean: Rolling historical baseline mean.
        baseline_std: Rolling historical baseline standard deviation.
        lead_time_days: Advance purchase days.
        route_volatility: Historical route coefficient of variation (sigma / mu).
        carrier_hhi: Carrier market concentration HHI.
        previous_fare: Previous observation fare for DoD rate calculation.
        route_median: Baseline route median fare.
        fares_sample: Sample of peer fares on same route for Tukey fences.
        route_code: Optional route identifier (e.g. 'DEL-BOM').
        airline_code: Optional airline IATA code.
        flight_number: Optional flight identifier.
        booking_window: Canonical window (e.g. 'T+1', 'T+7').

    Returns:
        MLAnomalyResult with continuous score, severity classification, and DGCA status.
    """
    p = float(fare)
    mu = float(baseline_mean)
    sigma = float(baseline_std)

    # 1. Dynamic Z-score
    dyn_z, std_z, urgency_fac = calculate_dynamic_z_score(p, mu, sigma, lead_time_days)

    # 2. Tukey Fences
    if fares_sample and len(fares_sample) >= 4:
        fences = calculate_tukey_fences(fares_sample, k=1.5)
        tukey_lower = fences["lower_fence"]
        tukey_upper = fences["upper_fence"]
        is_tukey = p > tukey_upper or (tukey_lower > 0 and p < tukey_lower)
    else:
        # Calibrated default fences based on mean and std
        tukey_lower = max(0.0, round(mu - 2.5 * sigma, 2))
        tukey_upper = round(mu + 2.5 * sigma, 2)
        is_tukey = p > tukey_upper or (tukey_lower > 0 and p < tukey_lower)

    # 3. Day-over-Day Surge
    dod_surge = None
    if previous_fare is not None and previous_fare > 0:
        dod_surge = round(float((p - previous_fare) / previous_fare), 4)

    # 4. Surge Multiple relative to median
    eff_median = float(route_median) if route_median is not None and route_median > 0 else (mu if mu > 0 else 5000.0)
    fare_ratio = round(p / eff_median, 3)

    # 5. Composite Anomaly Score (0.0 to 1.0)
    # Feature 1: Z-score contribution (normalized via sigmoid/clamp)
    score_z = min(1.0, max(0.0, dyn_z / 3.5)) if dyn_z > 0 else 0.0

    # Feature 2: Surge multiple contribution
    score_ratio = min(1.0, max(0.0, (fare_ratio - 1.0) / 1.5)) if fare_ratio > 1.0 else 0.0

    # Feature 3: DoD surge contribution
    score_dod = min(1.0, max(0.0, dod_surge / 0.50)) if dod_surge is not None and dod_surge > 0 else 0.0

    # Feature 4: Market power multiplier (HHI penalty on concentrated routes)
    score_hhi = min(1.0, max(0.0, (carrier_hhi - 0.25) / 0.50)) if carrier_hhi > 0.25 else 0.0

    # Feature 5: Tukey outlier contribution
    score_tukey = 1.0 if is_tukey else 0.0

    # Weighted ensemble score
    anomaly_score = (
        0.35 * score_z
        + 0.25 * score_ratio
        + 0.20 * score_dod
        + 0.10 * score_tukey
        + 0.10 * score_hhi
    )
    anomaly_score = round(min(1.0, max(0.0, anomaly_score)), 4)

    feature_contributions = {
        "dynamic_z": round(0.35 * score_z, 4),
        "surge_multiple": round(0.25 * score_ratio, 4),
        "dod_surge": round(0.20 * score_dod, 4),
        "tukey_outlier": round(0.10 * score_tukey, 4),
        "market_concentration_hhi": round(0.10 * score_hhi, 4),
    }

    # Regulatory and Statutory Violation Checks
    is_dgca_violation = False
    violation_code = None
    violations_found: list[str] = []

    # Check 1: 3-sigma statistical surge
    if dyn_z >= 3.0:
        is_dgca_violation = True
        violations_found.append(f"3-Sigma Surge (Z={dyn_z:.2f} >= 3.0)")
        violation_code = "DGCA_CAR_SECTION_3_SERIES_M_3SIGMA"

    # Check 2: Day-over-Day surge >= 40%
    if dod_surge is not None and dod_surge >= 0.40:
        is_dgca_violation = True
        violations_found.append(f"DoD Surge ({dod_surge * 100:.1f}% >= 40%)")
        violation_code = violation_code or "DGCA_CAR_SERIES_M_EXCESSIVE_DOD"

    # Check 3: Route price > 2.5x route baseline median
    if fare_ratio >= 2.50:
        is_dgca_violation = True
        violations_found.append(f"Surge Multiple ({fare_ratio:.2f}x >= 2.50x Route Median)")
        violation_code = "DGCA_CAR_TARIFF_CEILING_BREACH"

    # Check 4: Anti-competitive predatory spike in concentrated market
    if carrier_hhi >= 0.40 and dyn_z >= 2.5:
        is_dgca_violation = True
        violations_found.append(f"Concentrated Market Price Shock (HHI={carrier_hhi:.2f}, Z={dyn_z:.2f})")
        violation_code = violation_code or "DGCA_ANTI_COMPETITIVE_SURGE"

    # Severity classification
    if is_dgca_violation or anomaly_score >= 0.65:
        severity = MLAnomalySeverity.CRITICAL
        is_anomaly = True
    elif dyn_z >= 2.0 or (dod_surge is not None and dod_surge >= 0.25) or anomaly_score >= 0.35:
        severity = MLAnomalySeverity.WARNING
        is_anomaly = True
    else:
        severity = MLAnomalySeverity.NORMAL
        is_anomaly = False

    # Build human-readable explanation
    if violations_found:
        explanation = (
            f"DGCA STATUTORY TARIFF VIOLATION: {', '.join(violations_found)}. "
            f"Observed fare INR {p:.2f} vs baseline INR {mu:.2f} (Z={dyn_z:.2f}, Score={anomaly_score:.2f})."
        )
    elif is_anomaly:
        reasons: list[str] = []
        if dyn_z >= 2.0:
            reasons.append(f"Z={dyn_z:.2f} >= 2.0")
        if dod_surge is not None and dod_surge >= 0.25:
            reasons.append(f"DoD surge {dod_surge * 100:.1f}%")
        if is_tukey:
            reasons.append(f"exceeds Tukey fence INR {tukey_upper:.2f}")
        explanation = (
            f"Pricing anomaly detected: {', '.join(reasons)}. "
            f"Fare INR {p:.2f} vs baseline INR {mu:.2f} (Score={anomaly_score:.2f})."
        )
    else:
        explanation = (
            f"Normal pricing within statistical bounds (Z={dyn_z:.2f}, Score={anomaly_score:.2f})."
        )

    return MLAnomalyResult(
        observed_fare=round(p, 2),
        baseline_mean=round(mu, 2),
        baseline_std=round(sigma, 2),
        dynamic_z_score=dyn_z,
        standard_z_score=std_z,
        tukey_lower=tukey_lower,
        tukey_upper=tukey_upper,
        is_tukey_outlier=is_tukey,
        dod_surge=dod_surge,
        lead_time_days=int(lead_time_days),
        lead_time_urgency_factor=urgency_fac,
        route_volatility=round(float(route_volatility), 4),
        carrier_hhi=round(float(carrier_hhi), 4),
        fare_to_median_ratio=fare_ratio,
        anomaly_score=anomaly_score,
        severity=severity,
        is_anomaly=is_anomaly,
        is_dgca_violation=is_dgca_violation,
        violation_code=violation_code,
        feature_contributions=feature_contributions,
        explanation=explanation,
        route_code=route_code,
        airline_code=airline_code,
        flight_number=flight_number,
        booking_window=booking_window,
        metadata={
            "score_z": score_z,
            "score_ratio": score_ratio,
            "score_dod": score_dod,
            "score_tukey": score_tukey,
            "score_hhi": score_hhi,
        },
    )


# ---------------------------------------------------------------------------
# ML Anomaly Detector Class
# ---------------------------------------------------------------------------


class MLAnomalyDetector:
    """Stateful ML-augmented anomaly detection engine for airline pricing surveillance."""

    def __init__(
        self,
        airline_market_shares: Mapping[str, float] | None = None,
        default_lead_time_days: int = 7,
    ) -> None:
        self.airline_shares = dict(
            airline_market_shares if airline_market_shares is not None else DEFAULT_AIRLINE_MARKET_SHARES
        )
        self.default_lead_time = default_lead_time_days
        self.cached_hhi = calculate_hhi(self.airline_shares)

    def evaluate_quote(
        self,
        fare: float,
        baseline_mean: float,
        baseline_std: float,
        lead_time_days: int | None = None,
        previous_fare: float | None = None,
        route_median: float | None = None,
        route_code: str | None = None,
        airline_code: str | None = None,
        flight_number: str | None = None,
        booking_window: str | None = None,
        route_shares: Mapping[str, float] | None = None,
    ) -> MLAnomalyResult:
        """Evaluates a single flight quote against dynamic ML anomaly criteria."""
        h = lead_time_days if lead_time_days is not None else self.default_lead_time
        hhi = calculate_hhi(route_shares) if route_shares else self.cached_hhi

        # Route volatility approximation: sigma / mu
        volatility = (baseline_std / baseline_mean) if baseline_mean > 0 else 0.15

        return classify_surge_multifeature(
            fare=fare,
            baseline_mean=baseline_mean,
            baseline_std=baseline_std,
            lead_time_days=h,
            route_volatility=volatility,
            carrier_hhi=hhi,
            previous_fare=previous_fare,
            route_median=route_median,
            route_code=route_code,
            airline_code=airline_code,
            flight_number=flight_number,
            booking_window=booking_window,
        )

    def batch_evaluate(
        self,
        quotes: Sequence[Mapping[str, Any]],
        baselines: Mapping[str, tuple[float, float, float]],
    ) -> list[MLAnomalyResult]:
        """Evaluates a collection of quotes against route baselines.

        Args:
            quotes: List of flight quotes with 'fare', 'route_code' or 'origin'/'destination',
                    'booking_window', etc.
            baselines: Mapping of route/window key to (mean, std, previous_fare).

        Returns:
            List of MLAnomalyResult instances.
        """
        results: list[MLAnomalyResult] = []
        for q in quotes:
            fare = float(q.get("fare", q.get("total_fare", 0.0)))
            orig = q.get("origin", "")
            dest = q.get("destination", "")
            route_code = q.get("route_code", f"{orig}-{dest}" if orig and dest else "UNKNOWN")
            win = q.get("booking_window", "T+7")

            key = f"{route_code}:{win}"
            base_mean, base_std, prev_fare = baselines.get(key, (5000.0, 500.0, 5000.0))

            lead_days = 7
            if "1" in str(win):
                lead_days = 1
            elif "7" in str(win):
                lead_days = 7
            elif "15" in str(win):
                lead_days = 15
            elif "30" in str(win):
                lead_days = 30

            res = self.evaluate_quote(
                fare=fare,
                baseline_mean=base_mean,
                baseline_std=base_std,
                lead_time_days=lead_days,
                previous_fare=prev_fare,
                route_median=base_mean,
                route_code=route_code,
                airline_code=q.get("airline_code"),
                flight_number=q.get("flight_number"),
                booking_window=win,
            )
            results.append(res)

        return results
