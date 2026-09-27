"""APIx Services Package for Quant Engine, Econometrics, Ingestion, and Anomaly Detection."""

from backend.app.services.anomaly_detector import (
    AnomalyDetector,
    AnomalyResult,
    AnomalySeverity,
    calculate_dod_surge,
    calculate_z_score,
    classify_anomaly,
    detect_anomaly,
)
from backend.app.services.arbitrage_detector import (
    ArbitrageDetector,
    ArbitrageOpportunity,
    calculate_spread,
    get_current_arbitrage_opportunities,
)
from backend.app.services.econometric_engine import (
    BENCHMARK_MOSPI_CPI_SERIES,
    DEFAULT_LEAD_TIME_PAX_SHARES,
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
    DEFAULT_BOOKING_WINDOW_WEIGHTS,
    DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
    FlightQuote,
    IndexEngine,
    TukeyBounds,
    calculate_laspeyres_index,
    calculate_route_composite_fare,
    calculate_weighted_median,
    compute_tukey_bounds,
    compute_weighted_median,
    deduplicate_quotes,
    filter_outliers_tukey,
    filter_quotes_tukey,
    weighted_median_values,
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
from backend.app.services.streaming_dedup import (
    DedupResult,
    FlightBufferState,
    StreamingDedupEngine,
)

try:
    from backend.app.services.index_pipeline import (
        DEFAULT_BASE_FARES,
        DEFAULT_ROUTE_WEIGHTS,
        DEFAULT_WINDOW_WEIGHTS,
        run_daily_index_pipeline,
        run_streaming_dedup_and_arbitrage,
    )
except ImportError:
    pass

__all__ = [
    # Index Engine
    "DEFAULT_AIRLINE_MARKET_SHARES",
    "DEFAULT_BOOKING_WINDOW_WEIGHTS",
    "DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES",
    "FlightQuote",
    "IndexEngine",
    "TukeyBounds",
    "calculate_laspeyres_index",
    "calculate_route_composite_fare",
    "calculate_weighted_median",
    "compute_tukey_bounds",
    "compute_weighted_median",
    "deduplicate_quotes",
    "filter_outliers_tukey",
    "filter_quotes_tukey",
    "weighted_median_values",
    # Econometric Engine
    "calculate_paasche_index",
    "calculate_fisher_index",
    "calculate_substitution_bias",
    "calculate_lead_time_elasticity",
    "calculate_mospi_cpi_divergence",
    "EconometricEngine",
    "SubstitutionBias",
    "LeadTimeElasticityResult",
    "CpiDivergenceResult",
    "BENCHMARK_MOSPI_CPI_SERIES",
    "DEFAULT_LEAD_TIME_PAX_SHARES",
    # ML Anomaly Detector
    "MLAnomalyDetector",
    "MLAnomalyResult",
    "MLAnomalySeverity",
    "calculate_dynamic_z_score",
    "calculate_tukey_fences",
    "calculate_hhi",
    "classify_surge_multifeature",
    # Legacy Anomaly Detector
    "AnomalyDetector",
    "AnomalyResult",
    "AnomalySeverity",
    "calculate_dod_surge",
    "calculate_z_score",
    "classify_anomaly",
    "detect_anomaly",
    # Pipeline
    "run_daily_index_pipeline",
    "DEFAULT_BASE_FARES",
    "DEFAULT_ROUTE_WEIGHTS",
    "DEFAULT_WINDOW_WEIGHTS",
    # Streaming & Arbitrage
    "StreamingDedupEngine",
    "DedupResult",
    "FlightBufferState",
    "ArbitrageDetector",
    "ArbitrageOpportunity",
    "calculate_spread",
    "get_current_arbitrage_opportunities",
    "run_streaming_dedup_and_arbitrage",
]
