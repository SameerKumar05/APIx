"""Pytest suite for APIx Statistical Engine mathematical verification.

Mirrors and exposes verification tests from scripts/test_math_engine.py:
- Invariant 1: Equal price distribution weighted median equals scalar price.
- Invariant 2: Base period prices yield national index = 100.00.
- Invariant 3: +20% uniform price increase yields national index = 120.00.
- Invariant 4: 3-sigma surge triggers CRITICAL anomaly alert.
- Cross-platform flight deduplication (minimum consumer fare selection).
- Outlier filtering using Tukey's IQR rule [Q1 - 1.5*IQR, Q3 + 1.5*IQR].
- Booking window route composite fare weighting.
- Asymmetric airline market share weighted median.
- Non-uniform route price Laspeyres calculations.
- Stateful rolling 30-day anomaly detector.
"""

from scripts.test_math_engine import (
    test_asymmetric_weighted_median,
    test_cross_platform_flight_deduplication,
    test_invariant_1_equal_price_distribution_weighted_median,
    test_invariant_2_base_period_prices_yield_national_index_100,
    test_invariant_3_uniform_20_percent_price_increase_yields_120,
    test_invariant_4_three_sigma_surge_triggers_critical_alert,
    test_non_uniform_laspeyres_index,
    test_route_composite_fare_formula,
    test_stateful_anomaly_detector_simulation,
    test_tukey_iqr_outlier_filtering,
)

__all__ = [
    "test_asymmetric_weighted_median",
    "test_cross_platform_flight_deduplication",
    "test_invariant_1_equal_price_distribution_weighted_median",
    "test_invariant_2_base_period_prices_yield_national_index_100",
    "test_invariant_3_uniform_20_percent_price_increase_yields_120",
    "test_invariant_4_three_sigma_surge_triggers_critical_alert",
    "test_non_uniform_laspeyres_index",
    "test_route_composite_fare_formula",
    "test_stateful_anomaly_detector_simulation",
    "test_tukey_iqr_outlier_filtering",
]
