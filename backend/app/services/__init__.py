"""APIx Services Package for Quant Engine, Ingestion, and Anomaly Detection."""

from backend.app.services.anomaly_detector import (
    AnomalyDetector,
    AnomalyResult,
    AnomalySeverity,
    calculate_dod_surge,
    calculate_z_score,
    classify_anomaly,
    detect_anomaly,
)
from backend.app.services.index_engine import (
    DEFAULT_AIRLINE_MARKET_SHARES,
    DEFAULT_BOOKING_WINDOW_WEIGHTS,
    FlightQuote,
    TukeyBounds,
    calculate_fisher_index,
    calculate_laspeyres_index,
    calculate_paasche_index,
    calculate_route_composite_fare,
    calculate_weighted_median,
    deduplicate_quotes,
    filter_outliers_tukey,
    filter_quotes_tukey,
    weighted_median_values,
)
from backend.app.services.index_pipeline import (
    DEFAULT_BASE_FARES,
    DEFAULT_ROUTE_WEIGHTS,
    DEFAULT_WINDOW_WEIGHTS,
    run_daily_index_pipeline,
)

__all__ = [
    "DEFAULT_AIRLINE_MARKET_SHARES",
    "DEFAULT_BOOKING_WINDOW_WEIGHTS",
    "FlightQuote",
    "TukeyBounds",
    "calculate_fisher_index",
    "calculate_laspeyres_index",
    "calculate_paasche_index",
    "calculate_route_composite_fare",
    "calculate_weighted_median",
    "deduplicate_quotes",
    "filter_outliers_tukey",
    "filter_quotes_tukey",
    "weighted_median_values",
    "AnomalyDetector",
    "AnomalyResult",
    "AnomalySeverity",
    "calculate_dod_surge",
    "calculate_z_score",
    "classify_anomaly",
    "detect_anomaly",
    "run_daily_index_pipeline",
    "DEFAULT_BASE_FARES",
    "DEFAULT_ROUTE_WEIGHTS",
]
