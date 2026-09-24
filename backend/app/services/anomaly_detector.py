"""APIx Anomaly Detector - Dynamic Airfare Spike & Regulatory Surveillance.

Implements:
1. 30-day rolling baseline statistics (mean mu_30, standard deviation sigma_30).
2. Rolling Z-score calculation: Z = (P - mu_30) / sigma_30.
3. Day-over-Day (DoD) surge calculation: DoD = (P_t - P_{t-1}) / P_{t-1}.
4. Severity classification:
   - NORMAL: Z < 2.0 (and DoD surge < 40%)
   - WARNING: 2.0 <= Z < 3.0 (and DoD surge < 40%)
   - CRITICAL: Z >= 3.0 OR DoD surge >= 40% (0.40)
5. Regulatory notification dispatch formatting for DGCA oversight.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union


class AnomalySeverity(str, Enum):
    """Classification of airfare pricing anomalies."""

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class AnomalyResult:
    """Detailed result of an anomaly evaluation."""

    observed_fare: float
    baseline_mean: float
    baseline_std: float
    z_score: float
    dod_surge: Optional[float]
    severity: AnomalySeverity
    is_anomaly: bool
    reason: str
    route_id: Optional[str] = None
    booking_window: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert anomaly result to dictionary."""
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


def calculate_z_score(
    observed_fare: float,
    baseline_mean: float,
    baseline_std: float,
) -> float:
    """Calculates the standard Z-score against a baseline distribution.

    Formula:
        Z = (P - mu) / sigma

    Edge Cases:
        - If sigma is 0 and observed == mean: returns 0.0.
        - If sigma is 0 and observed > mean: returns 999.0 (infinite spike).
        - If sigma is 0 and observed < mean: returns -999.0 (infinite drop).

    Args:
        observed_fare: The observed price P.
        baseline_mean: Rolling mean mu.
        baseline_std: Rolling standard deviation sigma.

    Returns:
        Z-score as float.
    """
    diff = float(observed_fare - baseline_mean)
    std = float(baseline_std)

    if std <= 1e-9:
        if math.isclose(diff, 0.0, abs_tol=1e-9):
            return 0.0
        return 999.0 if diff > 0 else -999.0

    return float(diff / std)


def calculate_dod_surge(
    current_fare: float,
    previous_fare: float,
) -> float:
    """Calculates the Day-over-Day (DoD) relative price surge.

    Formula:
        DoD = (P_t - P_{t-1}) / P_{t-1}

    Args:
        current_fare: Current period price P_t.
        previous_fare: Previous period price P_{t-1}.

    Returns:
        Relative surge (e.g. 0.40 for a 40% price surge).
    """
    if previous_fare <= 0.0:
        if current_fare > 0.0:
            return 1.0  # From zero to positive is considered a major spike
        return 0.0

    return float((current_fare - previous_fare) / previous_fare)


def classify_anomaly(
    z_score: float,
    dod_surge: Optional[float] = None,
) -> AnomalySeverity:
    """Classifies anomaly severity based on Z-score and DoD surge thresholds.

    Rules:
    - CRITICAL: Z >= 3.0 OR DoD surge >= 40% (0.40)
    - WARNING: 2.0 <= Z < 3.0 (and DoD surge < 40%)
    - NORMAL: Z < 2.0 (and DoD surge < 40%)

    Invariant:
        A 3-sigma surge (Z >= 3.0) ALWAYS triggers CRITICAL anomaly alert.

    Args:
        z_score: Calculated Z-score.
        dod_surge: Optional Day-over-Day price surge ratio (e.g. 0.45 for 45%).

    Returns:
        AnomalySeverity enum value.
    """
    is_dod_critical = dod_surge is not None and dod_surge >= 0.40

    if z_score >= 3.0 or is_dod_critical:
        return AnomalySeverity.CRITICAL

    if 2.0 <= z_score < 3.0:
        return AnomalySeverity.WARNING

    return AnomalySeverity.NORMAL


def compute_baseline_stats(
    fares: Sequence[float],
) -> Tuple[float, float]:
    """Computes sample mean and sample standard deviation over a sequence of fares.

    Args:
        fares: Sequence of numeric prices.

    Returns:
        Tuple of (mean, sample_std).
    """
    clean_fares = [float(x) for x in fares if not math.isnan(x) and not math.isinf(x)]
    n = len(clean_fares)

    if n == 0:
        return 0.0, 0.0
    if n == 1:
        return clean_fares[0], 0.0

    mean_val = sum(clean_fares) / n

    # Sample variance (ddof=1)
    variance = sum((x - mean_val) ** 2 for x in clean_fares) / (n - 1)
    std_val = math.sqrt(variance)

    return mean_val, std_val


def detect_anomaly(
    observed_fare: float,
    baseline_mean: float,
    baseline_std: float,
    previous_fare: Optional[float] = None,
    route_id: Optional[str] = None,
    booking_window: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> AnomalyResult:
    """Evaluates an observed fare against rolling baseline statistics.

    Args:
        observed_fare: Current observed price.
        baseline_mean: Rolling 30-day mean mu_30.
        baseline_std: Rolling 30-day standard deviation sigma_30.
        previous_fare: Optional previous period fare for DoD surge calculation.
        route_id: Optional route identifier.
        booking_window: Optional booking window (T1, T7, T15, T30).
        timestamp: Optional timestamp string.

    Returns:
        AnomalyResult containing detailed evaluation and severity.
    """
    z_score = calculate_z_score(observed_fare, baseline_mean, baseline_std)

    dod_surge: Optional[float] = None
    if previous_fare is not None:
        dod_surge = calculate_dod_surge(observed_fare, previous_fare)

    severity = classify_anomaly(z_score, dod_surge)
    is_anomaly = severity != AnomalySeverity.NORMAL

    reasons: List[str] = []
    if z_score >= 3.0:
        reasons.append(f"Z-score {z_score:.2f} >= 3.0 (3-sigma surge)")
    elif z_score >= 2.0:
        reasons.append(f"Z-score {z_score:.2f} >= 2.0 (elevated price)")

    if dod_surge is not None and dod_surge >= 0.40:
        reasons.append(f"DoD surge {dod_surge * 100:.1f}% >= 40.0%")

    if not reasons:
        reasons.append("Price within normal historical baseline")

    reason_str = "; ".join(reasons)

    return AnomalyResult(
        observed_fare=float(observed_fare),
        baseline_mean=float(baseline_mean),
        baseline_std=float(baseline_std),
        z_score=float(z_score),
        dod_surge=float(dod_surge) if dod_surge is not None else None,
        severity=severity,
        is_anomaly=is_anomaly,
        reason=reason_str,
        route_id=route_id,
        booking_window=booking_window,
        timestamp=timestamp,
    )


class AnomalyDetector:
    """Stateful anomaly detection engine with rolling 30-day baseline management."""

    def __init__(self, window_size: int = 30):
        self.window_size = window_size
        # key: (route_id, booking_window) -> list of historical fares
        self.history: Dict[Tuple[str, str], List[float]] = {}
        # key: (route_id, booking_window) -> last observed fare
        self.last_fares: Dict[Tuple[str, str], float] = {}

    def record_fare(
        self,
        route_id: str,
        booking_window: str,
        fare: float,
    ) -> None:
        """Appends a fare observation to the rolling history."""
        key = (route_id.strip().upper(), booking_window.strip().upper())
        if key not in self.history:
            self.history[key] = []
        self.history[key].append(float(fare))
        if len(self.history[key]) > self.window_size:
            self.history[key].pop(0)
        self.last_fares[key] = float(fare)

    def evaluate(
        self,
        route_id: str,
        booking_window: str,
        current_fare: float,
        timestamp: Optional[str] = None,
    ) -> AnomalyResult:
        """Evaluates current fare against stored rolling baseline for route/window."""
        key = (route_id.strip().upper(), booking_window.strip().upper())
        hist = self.history.get(key, [])
        prev_fare = self.last_fares.get(key)

        if len(hist) >= 2:
            mu, sigma = compute_baseline_stats(hist)
        elif len(hist) == 1:
            mu, sigma = hist[0], 0.0
        else:
            mu, sigma = current_fare, 0.0

        result = detect_anomaly(
            observed_fare=current_fare,
            baseline_mean=mu,
            baseline_std=sigma,
            previous_fare=prev_fare,
            route_id=route_id,
            booking_window=booking_window,
            timestamp=timestamp,
        )

        # Update history with this new observation
        self.record_fare(route_id, booking_window, current_fare)
        return result
