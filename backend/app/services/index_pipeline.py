"""APIx Daily Index Pipeline Service.

End-to-end batch calculation service computing daily route-level and national
composite airfare price indices augmenting the Consumer Price Index (CPI).

Key Pipeline Steps:
1. Loads raw fares for calculation_date across all 10 monitored routes and 4 windows.
2. Runs cross-platform flight deduplication and Tukey IQR outlier trimming.
3. Calculates weighted median representative fare for each route and window.
4. Calculates composite route fare using booking window weights (0.20, 0.35, 0.30, 0.15).
5. Calculates Modified Laspeyres national price index (Base 100.0) using DGCA passenger traffic weights.
6. Evaluates rolling 30-day Z-scores and generates AnomalyAlert records when Z >= 2.0 or DoD surge >= 40%.
7. Persists RouteDailyIndex and NationalDailyIndex records to the database idempotently.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from backend.app.core.cleaning import is_index_eligible
from backend.app.db.seed import INITIAL_ROUTES
from backend.app.models.anomaly import AnomalyAlert
from backend.app.models.index import NationalDailyIndex, RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.route import Route
from backend.app.services.anomaly_detector import (
    calculate_dod_surge,
    calculate_z_score,
    compute_baseline_stats,
)
from backend.app.services.arbitrage_detector import (
    ArbitrageDetector,
    ArbitrageOpportunity,
)
from backend.app.services.econometric_engine import (
    calculate_fisher_index,
    calculate_lead_time_elasticity,
    calculate_mospi_cpi_divergence,
    calculate_paasche_index,
    calculate_substitution_bias,
)
from backend.app.services.index_engine import (
    DEFAULT_AIRLINE_MARKET_SHARES,
    _compute_percentile_linear,
    _extract_field,
    calculate_laspeyres_index,
    calculate_route_composite_fare,
    calculate_weighted_median,
    deduplicate_quotes,
    filter_quotes_tukey,
)
from backend.app.services.ml_anomaly_detector import (
    classify_surge_multifeature,
)
from backend.app.services.streaming_dedup import (
    StreamingDedupEngine,
)

logger = logging.getLogger("apix.services.index_pipeline")

# ---------------------------------------------------------------------------
# Default Constants and Benchmark Calibrations
# ---------------------------------------------------------------------------

# Advance booking purchase window weights (DGCA lead-time distribution)
# Formula: P_{r,t} = 0.20*T1 + 0.32*T7 + 0.26*T15 + 0.14*T30 + 0.08*T45
DEFAULT_WINDOW_WEIGHTS: dict[str, float] = {
    "T1": 0.20,
    "T+1": 0.20,
    "T7": 0.32,
    "T+7": 0.32,
    "T15": 0.26,
    "T+15": 0.26,
    "T30": 0.14,
    "T+30": 0.14,
    "T45": 0.08,
    "T+45": 0.08,
}

# Canonical 5 advance booking purchase windows
CANONICAL_WINDOWS: list[str] = ["T+1", "T+7", "T+15", "T+30", "T+45"]

# Mapping to canonical window tags
WINDOW_NORM_MAP: dict[str, str] = {
    "T1": "T+1",
    "T+1": "T+1",
    "1": "T+1",
    "T7": "T+7",
    "T+7": "T+7",
    "7": "T+7",
    "T15": "T+15",
    "T+15": "T+15",
    "15": "T+15",
    "T30": "T+30",
    "T+30": "T+30",
    "30": "T+30",
    "T45": "T+45",
    "T+45": "T+45",
    "45": "T+45",
}

# Top 10 Indian domestic directional flight corridors (DGCA traffic weights sum to 1.000)
DEFAULT_ROUTE_WEIGHTS: dict[str, float] = {
    "DEL-BOM": 0.175,
    "BOM-DEL": 0.175,
    "BLR-DEL": 0.125,
    "DEL-BLR": 0.125,
    "BOM-BLR": 0.090,
    "BLR-BOM": 0.090,
    "DEL-CCU": 0.065,
    "CCU-DEL": 0.065,
    "DEL-HYD": 0.045,
    "HYD-DEL": 0.045,
}

# Benchmark Base Period Fares (Base 100.0 Reference)
DEFAULT_BASE_FARES: dict[str, float] = {
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


def normalize_window_code(window_raw: Any) -> str:
    """Normalize booking window string to canonical format ('T+1', 'T+7', etc.)."""
    if not window_raw:
        return "T+7"
    w = str(window_raw).strip().upper()
    return WINDOW_NORM_MAP.get(w, w)


def run_streaming_dedup_and_arbitrage(
    quotes: Sequence[Any],
    window_seconds: float = 86400.0,
    min_spread_pct: float = 0.0,
) -> tuple[StreamingDedupEngine, list[ArbitrageOpportunity]]:
    """Runs quotes through StreamingDedupEngine and ArbitrageDetector.

    Args:
        quotes: Sequence of raw fare records, flight quotes, or mappings.
        window_seconds: Sliding window retention in seconds (default 24h).
        min_spread_pct: Minimum percentage threshold for actionable arbitrage.

    Returns:
        Tuple of (StreamingDedupEngine instance, List of ArbitrageOpportunity).
    """
    engine = StreamingDedupEngine(window_seconds=window_seconds)
    engine.ingest_batch(quotes)

    detector = ArbitrageDetector(min_spread_pct=min_spread_pct)
    opportunities = detector.detect_from_quotes(quotes, min_spread_pct=min_spread_pct)

    return engine, opportunities


def get_active_routes(db: Session) -> dict[str, Route]:
    """Load active domestic routes from DB, fallback to INITIAL_ROUTES mapping."""
    routes_by_code: dict[str, Route] = {}
    try:
        stmt = select(Route).where(Route.is_active == True)  # noqa: E712
        db_routes = db.execute(stmt).scalars().all()
        for r in db_routes:
            routes_by_code[r.route_code] = r
    except Exception as e:
        logger.warning("Could not query routes from database: %s", e)

    return routes_by_code


def get_route_weights(db: Session) -> dict[str, float]:
    """Retrieve normalized route weights from DB or fallback constants."""
    weights: dict[str, float] = {}
    routes = get_active_routes(db)
    if routes:
        for code, r in routes.items():
            weights[code] = float(r.weight)
    else:
        weights = dict(DEFAULT_ROUTE_WEIGHTS)

    # Normalize weights so they sum to 1.000
    total_w = sum(weights.values())
    if total_w > 0:
        return {code: w / total_w for code, w in weights.items()}
    return dict(DEFAULT_ROUTE_WEIGHTS)


def load_raw_fares_for_date(
    db: Session,
    calculation_date: date,
) -> list[RawFare]:
    """Loads all raw flight fares for a specific observation/calculation date.

    Matches either flight_date == calculation_date OR scraped_at on calculation_date.
    """
    start_of_day = datetime.combine(calculation_date, time.min).replace(tzinfo=UTC)
    end_of_day = datetime.combine(calculation_date, time.max).replace(tzinfo=UTC)

    stmt = select(RawFare).where(
        or_(
            RawFare.flight_date == calculation_date,
            and_(RawFare.scraped_at >= start_of_day, RawFare.scraped_at <= end_of_day),
            and_(
                RawFare.scraped_at >= start_of_day.replace(tzinfo=None),
                RawFare.scraped_at <= end_of_day.replace(tzinfo=None),
            ),
        )
    )
    results = db.execute(stmt).scalars().all()
    return list(results)


def get_rolling_30day_baseline(
    db: Session,
    origin: str,
    destination: str,
    booking_window: str,
    calculation_date: date,
    lookback_days: int = 30,
) -> tuple[float | None, float | None, float | None]:
    """Retrieves rolling 30-day baseline statistics from historical RouteDailyIndex records.

    Returns:
        (mean_30, std_30, previous_day_fare)
    """
    start_date = calculation_date - timedelta(days=lookback_days)
    stmt = (
        select(RouteDailyIndex)
        .where(
            RouteDailyIndex.origin == origin,
            RouteDailyIndex.destination == destination,
            RouteDailyIndex.booking_window == booking_window,
            RouteDailyIndex.index_date >= start_date,
            RouteDailyIndex.index_date < calculation_date,
        )
        .order_by(RouteDailyIndex.index_date.asc())
    )
    records = db.execute(stmt).scalars().all()

    if not records:
        return None, None, None

    historical_fares = [r.median_fare for r in records if r.median_fare > 0]
    if not historical_fares:
        return None, None, None

    mean_val, std_val = compute_baseline_stats(historical_fares)

    # Previous day's fare (latest available record before calculation_date)
    prev_fare = records[-1].median_fare

    return mean_val, std_val, prev_fare


def evaluate_anomaly_condition(
    origin: str,
    destination: str,
    booking_window: str,
    current_fare: float,
    baseline_mean: float | None,
    baseline_std: float | None,
    previous_fare: float | None,
    calculation_date: date,
    route_id: int | None = None,
) -> AnomalyAlert | None:
    """Evaluates rolling 30-day Z-scores and DoD surges for anomaly alerts.

    Thresholds:
    - CRITICAL: Z >= 3.0 OR DoD surge >= 40% (0.40)
    - HIGH/WARNING: 2.0 <= Z < 3.0 (and DoD surge < 40%)
    """
    if baseline_mean is None or baseline_mean <= 0:
        # Without historical baseline, check DoD surge if previous_fare exists
        if previous_fare is not None and previous_fare > 0:
            surge_pct: float = calculate_dod_surge(current_fare, previous_fare)
            if surge_pct >= 0.40:
                return AnomalyAlert(
                    route_id=route_id,
                    origin=origin,
                    destination=destination,
                    airline_code=None,
                    alert_type="SURGE_PRICING",
                    severity="CRITICAL",
                    flight_date=calculation_date,
                    booking_window=booking_window,
                    detected_fare=float(current_fare),
                    baseline_fare=float(previous_fare),
                    z_score=None,
                    pct_change=round(surge_pct * 100.0, 2),
                    description=(
                        f"Day-over-Day surge of {surge_pct * 100:.1f}% on {origin}-{destination} "
                        f"({booking_window}) exceeds 40.0% regulatory threshold."
                    ),
                    status="OPEN",
                    created_at=datetime.now(UTC),
                )
        return None

    # Calculate Z-score against 30-day baseline distribution
    std_to_use = baseline_std if baseline_std is not None else 0.0
    z_score = calculate_z_score(current_fare, baseline_mean, std_to_use)

    # Calculate DoD surge if previous day fare is available
    dod_surge: float | None = None
    if previous_fare is not None and previous_fare > 0:
        dod_surge = calculate_dod_surge(current_fare, previous_fare)

    # Map booking window to advance purchase lead days
    win_str = str(booking_window).upper()
    if "1" in win_str and "15" not in win_str:
        lead_days = 1
    elif "7" in win_str:
        lead_days = 7
    elif "15" in win_str:
        lead_days = 15
    elif "30" in win_str:
        lead_days = 30
    elif "45" in win_str:
        lead_days = 45
    else:
        lead_days = 7

    # Multi-feature ML anomaly evaluation
    ml_res = classify_surge_multifeature(
        fare=float(current_fare),
        baseline_mean=float(baseline_mean),
        baseline_std=float(std_to_use),
        lead_time_days=lead_days,
        previous_fare=previous_fare,
        route_median=float(baseline_mean),
        route_code=f"{origin}-{destination}",
        booking_window=booking_window,
    )

    is_z_anomaly = z_score >= 2.0
    is_dod_surge = dod_surge is not None and dod_surge >= 0.40

    if not is_z_anomaly and not is_dod_surge and not ml_res.is_anomaly:
        return None

    # Determine severity and alert type
    if ml_res.is_dgca_violation or z_score >= 3.0 or is_dod_surge:
        severity = "CRITICAL"
        alert_type = (
            "DGCA_STATUTORY_VIOLATION"
            if ml_res.is_dgca_violation
            else ("SURGE_PRICING" if is_dod_surge else "SPIKE")
        )
    else:
        severity = "HIGH"
        alert_type = "SPIKE"

    pct_change = (
        round(dod_surge * 100.0, 2)
        if dod_surge is not None
        else round(((current_fare - baseline_mean) / baseline_mean) * 100.0, 2)
    )

    description = ml_res.explanation
    return AnomalyAlert(
        route_id=route_id,
        origin=origin,
        destination=destination,
        airline_code=None,
        alert_type=alert_type,
        severity=severity,
        flight_date=calculation_date,
        booking_window=booking_window,
        detected_fare=float(current_fare),
        baseline_fare=float(baseline_mean),
        z_score=round(float(z_score), 4),
        pct_change=pct_change,
        description=description,
        status="OPEN",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Master Daily Batch Execution Function
# ---------------------------------------------------------------------------


def run_daily_index_pipeline(
    db: Session | None = None,
    calculation_date: date | str | None = None,
) -> dict[str, Any]:
    """Executes the daily airfare index calculation pipeline and DB persistence.

    Args:
        db: Optional active SQLAlchemy session. If None, opens and manages a new SessionLocal.
        calculation_date: Target calculation date (date object, 'YYYY-MM-DD' string, or None for today).

    Returns:
        Structured summary dictionary with execution metrics, record counts, and computed index values.
    """
    if db is None:
        from backend.app.db.session import SessionLocal

        with SessionLocal() as session:
            return _execute_daily_pipeline(session, calculation_date)
    else:
        return _execute_daily_pipeline(db, calculation_date)


def _execute_daily_pipeline(
    db: Session,
    calculation_date: date | str | None = None,
) -> dict[str, Any]:
    """Internal implementation of daily index pipeline with guaranteed session scope."""
    # 1. Resolve calculation_date
    if calculation_date is None:
        calc_date = datetime.now(UTC).date()
    elif isinstance(calculation_date, str):
        calc_date = date.fromisoformat(calculation_date.strip())
    elif isinstance(calculation_date, datetime):
        calc_date = calculation_date.date()
    else:
        calc_date = calculation_date

    logger.info(
        "Executing daily airfare index pipeline for calculation_date=%s", calc_date
    )

    # 2. Load routes and baseline configurations
    routes_map = get_active_routes(db)
    route_weights = get_route_weights(db)
    base_fares = dict(DEFAULT_BASE_FARES)

    # 3. Step 1: Load raw fares for calculation_date across all routes and windows
    raw_fares = load_raw_fares_for_date(db, calc_date)
    total_raw_fares = len(raw_fares)
    logger.info(
        "Loaded %d raw fares for calculation date %s", total_raw_fares, calc_date
    )
    # Step 1b: Run real-time streaming deduplication & cross-platform arbitrage detection
    streaming_engine, arbitrage_opportunities = run_streaming_dedup_and_arbitrage(
        raw_fares,
        window_seconds=86400.0,
        min_spread_pct=0.0,
    )
    streaming_stats = streaming_engine.stats()
    logger.info(
        "Streaming Dedup & Arbitrage: Processed %d quotes, Active flights=%d, "
        "Duplicates=%d, New minima=%d, Arbitrage opportunities=%d, Avg latency=%.2f us",
        streaming_stats["total_processed"],
        streaming_stats["active_buffer_size"],
        streaming_stats["duplicates_count"],
        streaming_stats["new_minima_count"],
        len(arbitrage_opportunities),
        streaming_stats["avg_latency_us"],
    )

    # Group raw fares by corridor (origin, destination) and canonical booking window
    # key: ((origin, destination), canonical_window) -> list of quotes
    grouped_fares: dict[tuple[tuple[str, str], str], list[RawFare]] = defaultdict(list)
    for rf in raw_fares:
        if not is_index_eligible(rf.flight_status, rf.index_exclusion_reason):
            continue
        orig = str(rf.origin).strip().upper()
        dest = str(rf.destination).strip().upper()
        win = normalize_window_code(rf.booking_window)
        grouped_fares[((orig, dest), win)].append(rf)

    # Track all distinct monitored corridors
    monitored_corridors: list[tuple[str, str]] = []
    if routes_map:
        for r in routes_map.values():
            corridor = (r.origin, r.destination)
            if corridor not in monitored_corridors:
                monitored_corridors.append(corridor)
    else:
        for r_item in INITIAL_ROUTES:
            corridor = (r_item["origin"], r_item["destination"])
            if corridor not in monitored_corridors:
                monitored_corridors.append(corridor)

    # Also include any corridors present in the raw data
    for (orig, dest), _win in grouped_fares:
        if (orig, dest) not in monitored_corridors:
            monitored_corridors.append((orig, dest))

    # Containers for generated domain entities
    route_indices_to_persist: list[RouteDailyIndex] = []
    anomalies_to_persist: list[AnomalyAlert] = []

    # Mapping of route_code -> composite fare for National Laspeyres calculation
    route_composite_fares: dict[str, float] = {}
    total_samples_all_routes = 0

    # 4. Steps 2, 3, 4: Deduplicate, Tukey trim, Weighted Median, Composite Fare
    for orig, dest in monitored_corridors:
        route_code = f"{orig}-{dest}"
        route_obj = routes_map.get(route_code)
        route_id = route_obj.id if route_obj else None
        base_fare = base_fares.get(route_code, 5000.0)

        # Store representative fares for all available booking windows on this route
        window_rep_fares: dict[str, float] = {}
        route_sample_size_total = 0

        for win in CANONICAL_WINDOWS:
            quotes = grouped_fares.get(((orig, dest), win), [])
            if not quotes:
                continue

            # Step 2: Cross-platform deduplication
            deduped_quotes = deduplicate_quotes(quotes)
            if not deduped_quotes:
                continue

            # Step 2: Tukey IQR Outlier Trimming
            trimmed_quotes: list[Any] = filter_quotes_tukey(deduped_quotes, k=1.5)
            if not trimmed_quotes:
                trimmed_quotes = deduped_quotes

            # Step 3: Weighted median representative fare using airline market shares
            rep_fare = calculate_weighted_median(
                trimmed_quotes, DEFAULT_AIRLINE_MARKET_SHARES
            )
            window_rep_fares[win] = rep_fare

            # Distribution statistics
            fare_values = [float(_extract_field(q, "fare")) for q in trimmed_quotes]
            fare_values.sort()
            sample_size = len(fare_values)
            route_sample_size_total += sample_size

            mean_fare = sum(fare_values) / sample_size
            min_fare = fare_values[0]
            max_fare = fare_values[-1]
            p25 = _compute_percentile_linear(fare_values, 0.25)
            p75 = _compute_percentile_linear(fare_values, 0.75)
            variance = (
                sum((x - mean_fare) ** 2 for x in fare_values) / (sample_size - 1)
                if sample_size > 1
                else 0.0
            )
            std_dev = math.sqrt(variance)

            # Window-specific index value relative to base fare (Base 100.0)
            window_index_value = round((rep_fare / base_fare) * 100.0, 2)

            # Step 6: Evaluate rolling 30-day Z-scores and DoD surge for window
            mu_win, sigma_win, prev_win = get_rolling_30day_baseline(
                db=db,
                origin=orig,
                destination=dest,
                booking_window=win,
                calculation_date=calc_date,
                lookback_days=30,
            )
            win_alert = evaluate_anomaly_condition(
                origin=orig,
                destination=dest,
                booking_window=win,
                current_fare=rep_fare,
                baseline_mean=mu_win,
                baseline_std=sigma_win,
                previous_fare=prev_win,
                calculation_date=calc_date,
                route_id=route_id,
            )
            if win_alert is not None:
                anomalies_to_persist.append(win_alert)

            # Create RouteDailyIndex for this window
            r_window_index = RouteDailyIndex(
                route_id=route_id,
                origin=orig,
                destination=dest,
                index_date=calc_date,
                booking_window=win,
                index_type="weighted_median",
                sample_size=sample_size,
                median_fare=round(rep_fare, 2),
                mean_fare=round(mean_fare, 2),
                min_fare=round(min_fare, 2),
                max_fare=round(max_fare, 2),
                percentile_25=round(p25, 2),
                percentile_75=round(p75, 2),
                std_dev=round(std_dev, 2),
                index_value=window_index_value,
                base_period="2026-01-01",
                calculation_timestamp=datetime.now(UTC),
            )
            route_indices_to_persist.append(r_window_index)

        # Step 4: Calculate composite route fare using booking window weights (0.20, 0.35, 0.30, 0.15)
        if window_rep_fares:
            composite_fare = calculate_route_composite_fare(
                window_fares=window_rep_fares,
                weights=DEFAULT_WINDOW_WEIGHTS,
            )
            route_composite_fares[route_code] = composite_fare
            total_samples_all_routes += route_sample_size_total

            route_index_value = round((composite_fare / base_fare) * 100.0, 2)

            # Step 6: Evaluate composite-level rolling 30-day Z-scores and DoD surges
            mu_comp, sigma_comp, prev_comp = get_rolling_30day_baseline(
                db=db,
                origin=orig,
                destination=dest,
                booking_window="COMPOSITE",
                calculation_date=calc_date,
                lookback_days=30,
            )
            comp_alert = evaluate_anomaly_condition(
                origin=orig,
                destination=dest,
                booking_window="COMPOSITE",
                current_fare=composite_fare,
                baseline_mean=mu_comp,
                baseline_std=sigma_comp,
                previous_fare=prev_comp,
                calculation_date=calc_date,
                route_id=route_id,
            )
            if comp_alert is not None:
                anomalies_to_persist.append(comp_alert)

            # Persist composite record in RouteDailyIndex
            r_composite_index = RouteDailyIndex(
                route_id=route_id,
                origin=orig,
                destination=dest,
                index_date=calc_date,
                booking_window="COMPOSITE",
                index_type="weighted_median",
                sample_size=route_sample_size_total,
                median_fare=round(composite_fare, 2),
                mean_fare=round(composite_fare, 2),
                min_fare=min(window_rep_fares.values()),
                max_fare=max(window_rep_fares.values()),
                percentile_25=min(window_rep_fares.values()),
                percentile_75=max(window_rep_fares.values()),
                std_dev=0.0,
                index_value=route_index_value,
                base_period="2026-01-01",
                calculation_timestamp=datetime.now(UTC),
            )
            route_indices_to_persist.append(r_composite_index)

    # 5. Step 5: Calculate Modified Laspeyres National Price Index (Base 100.0)
    # Using DGCA passenger traffic weights
    if route_composite_fares:
        national_index_val = calculate_laspeyres_index(
            current_fares=route_composite_fares,
            base_fares=base_fares,
            route_weights=route_weights,
            base_value=100.0,
        )

        # DGCA passenger-weighted mean fare across routes
        total_pax_weight = sum(route_weights.get(r, 0.1) for r in route_composite_fares)
        weighted_national_mean = sum(
            route_composite_fares[r] * route_weights.get(r, 0.1)
            for r in route_composite_fares
        ) / (total_pax_weight if total_pax_weight > 0 else 1.0)
    else:
        # Fallback if no valid quotes on this date
        national_index_val = 100.0
        weighted_national_mean = 5000.0

    # Calculate Inflation DoD and MoM rates
    prev_nat_stmt = select(NationalDailyIndex).where(
        NationalDailyIndex.index_date == calc_date - timedelta(days=1),
        NationalDailyIndex.booking_window == "COMPOSITE",
        NationalDailyIndex.index_type == "laspeyres",
    )
    prev_nat = db.execute(prev_nat_stmt).scalars().first()
    inflation_dod_pct = 0.0
    if prev_nat and prev_nat.index_value > 0:
        inflation_dod_pct = round(
            ((national_index_val - prev_nat.index_value) / prev_nat.index_value)
            * 100.0,
            4,
        )

    mom_nat_stmt = select(NationalDailyIndex).where(
        NationalDailyIndex.index_date == calc_date - timedelta(days=30),
        NationalDailyIndex.booking_window == "COMPOSITE",
        NationalDailyIndex.index_type == "laspeyres",
    )
    mom_nat = db.execute(mom_nat_stmt).scalars().first()
    inflation_mom_pct = 0.0
    if mom_nat and mom_nat.index_value > 0:
        inflation_mom_pct = round(
            ((national_index_val - mom_nat.index_value) / mom_nat.index_value) * 100.0,
            4,
        )

    # 5b. Econometric Price Indices: Paasche, Fisher Ideal Index, Substitution Bias
    if route_composite_fares:
        paasche_index_val = calculate_paasche_index(
            current_fares=route_composite_fares,
            base_fares=base_fares,
            current_weights=route_weights,
            base_value=100.0,
        )
        fisher_index_val = calculate_fisher_index(
            laspeyres_index=national_index_val,
            paasche_index=paasche_index_val,
        )
        substitution_bias = calculate_substitution_bias(
            laspeyres_index=national_index_val,
            fisher_index=fisher_index_val,
            paasche_index=paasche_index_val,
        )
    else:
        paasche_index_val = 100.0
        fisher_index_val = 100.0
        substitution_bias = calculate_substitution_bias(100.0, 100.0, 100.0)

    # 5c. Lead-Time Price Elasticity Curve
    window_avg_fares: dict[str, float] = {}
    for win in CANONICAL_WINDOWS:
        fares_for_win = [
            ri.median_fare
            for ri in route_indices_to_persist
            if ri.booking_window == win and ri.median_fare > 0
        ]
        if fares_for_win:
            window_avg_fares[win] = sum(fares_for_win) / len(fares_for_win)

    if len(window_avg_fares) >= 2:
        lead_time_elasticity = calculate_lead_time_elasticity(
            window_fares=window_avg_fares,
            window_pax_shares=DEFAULT_WINDOW_WEIGHTS,
        )
    else:
        lead_time_elasticity = calculate_lead_time_elasticity(
            window_fares={
                "T+1": 6500.0,
                "T+7": 5200.0,
                "T+15": 4500.0,
                "T+30": 3800.0,
                "T+45": 3500.0,
            },
        )

    # 5d. MoSPI CPI Transport Sub-Index Divergence Analytics
    cpi_divergence = calculate_mospi_cpi_divergence(
        apix_index_series=[
            {"date": calc_date.isoformat(), "index_value": national_index_val}
        ],
    )

    # Construct NationalDailyIndex records for all 3 superlative index formulations
    national_records_to_persist = [
        NationalDailyIndex(
            index_date=calc_date,
            booking_window="COMPOSITE",
            index_type="laspeyres",
            index_value=round(national_index_val, 4),
            weighted_median_fare=round(weighted_national_mean, 2),
            weighted_mean_fare=round(weighted_national_mean, 2),
            total_samples=total_samples_all_routes,
            routes_covered=len(route_composite_fares),
            inflation_dod_pct=inflation_dod_pct,
            inflation_mom_pct=inflation_mom_pct,
            base_period="2026-01-01",
            calculation_timestamp=datetime.now(UTC),
        ),
        NationalDailyIndex(
            index_date=calc_date,
            booking_window="COMPOSITE",
            index_type="paasche",
            index_value=round(paasche_index_val, 4),
            weighted_median_fare=round(weighted_national_mean, 2),
            weighted_mean_fare=round(weighted_national_mean, 2),
            total_samples=total_samples_all_routes,
            routes_covered=len(route_composite_fares),
            inflation_dod_pct=inflation_dod_pct,
            inflation_mom_pct=inflation_mom_pct,
            base_period="2026-01-01",
            calculation_timestamp=datetime.now(UTC),
        ),
        NationalDailyIndex(
            index_date=calc_date,
            booking_window="COMPOSITE",
            index_type="fisher",
            index_value=round(fisher_index_val, 4),
            weighted_median_fare=round(weighted_national_mean, 2),
            weighted_mean_fare=round(weighted_national_mean, 2),
            total_samples=total_samples_all_routes,
            routes_covered=len(route_composite_fares),
            inflation_dod_pct=inflation_dod_pct,
            inflation_mom_pct=inflation_mom_pct,
            base_period="2026-01-01",
            calculation_timestamp=datetime.now(UTC),
        ),
    ]

    # 6. Step 7: Persist RouteDailyIndex, NationalDailyIndex (all types), and AnomalyAlerts idempotently
    _persist_route_indices(db, route_indices_to_persist)
    for n_rec in national_records_to_persist:
        _persist_national_index(db, n_rec)
    _persist_anomaly_alerts(db, anomalies_to_persist)

    # Forward-compatible persistence into EconometricIndex if model is present (idempotent upsert)
    try:
        from backend.app.models.econometrics import EconometricIndex

        existing_econ = (
            db.query(EconometricIndex)
            .filter(
                EconometricIndex.date == calc_date,
                EconometricIndex.route_code == "NATIONAL",
                EconometricIndex.calculation_method == "dgca_traffic_weighted",
            )
            .first()
        )
        if existing_econ:
            existing_econ.laspeyres_index = round(national_index_val, 4)
            existing_econ.paasche_index = round(paasche_index_val, 4)
            existing_econ.fisher_ideal_index = round(fisher_index_val, 4)
            existing_econ.substitution_bias = round(substitution_bias.bias_points, 4)
        else:
            econ_rec = EconometricIndex(
                date=calc_date,
                route_code="NATIONAL",
                laspeyres_index=round(national_index_val, 4),
                paasche_index=round(paasche_index_val, 4),
                fisher_ideal_index=round(fisher_index_val, 4),
                substitution_bias=round(substitution_bias.bias_points, 4),
                calculation_method="dgca_traffic_weighted",
                created_at=datetime.now(UTC),
            )
            db.add(econ_rec)
    except Exception as e:
        logger.warning("Could not persist EconometricIndex: %s", e)

    # Forward-compatible persistence into RouteElasticity (fixes Issue #1 empty elasticity chart)
    try:
        from backend.app.db.econometrics_repo import upsert_route_elasticity

        t1_t7 = abs(
            lead_time_elasticity.arc_elasticities.get(
                "T+7_to_T+1",
                lead_time_elasticity.arc_elasticities.get("T+1_to_T+7", 1.25),
            )
        )
        t7_t15 = abs(
            lead_time_elasticity.arc_elasticities.get(
                "T+15_to_T+7",
                lead_time_elasticity.arc_elasticities.get("T+7_to_T+15", 1.10),
            )
        )
        t15_t30 = abs(
            lead_time_elasticity.arc_elasticities.get(
                "T+30_to_T+15",
                lead_time_elasticity.arc_elasticities.get("T+15_to_T+30", 0.95),
            )
        )
        avg_decay = (
            abs(lead_time_elasticity.lead_time_premium_pct) / 100.0 / 30.0
            if lead_time_elasticity.lead_time_premium_pct
            else 0.035
        )

        upsert_route_elasticity(
            db=db,
            route_code="NATIONAL",
            calculation_date=calc_date,
            t1_t7_elasticity=round(t1_t7, 4),
            t7_t15_elasticity=round(t7_t15, 4),
            t15_t30_elasticity=round(t15_t30, 4),
            avg_lead_time_decay=round(avg_decay, 4),
            confidence_score=1.0,
            commit=False,
        )
    except Exception as e:
        logger.warning("Could not persist RouteElasticity for NATIONAL: %s", e)

    db.commit()

    logger.info(
        "Successfully completed daily index pipeline for %s: "
        "Laspeyres=%.2f, Paasche=%.2f, Fisher=%.2f, SubBias=%.2f pts, Routes=%d, Route Indices Saved=%d, Anomalies=%d",
        calc_date,
        national_index_val,
        paasche_index_val,
        fisher_index_val,
        substitution_bias.bias_points,
        len(route_composite_fares),
        len(route_indices_to_persist),
        len(anomalies_to_persist),
    )

    return {
        "status": "success",
        "calculation_date": calc_date.isoformat(),
        "total_raw_fares": total_raw_fares,
        "routes_covered": len(route_composite_fares),
        "national_index_value": round(national_index_val, 4),
        "laspeyres_index_value": round(national_index_val, 4),
        "paasche_index_value": round(paasche_index_val, 4),
        "fisher_index_value": round(fisher_index_val, 4),
        "substitution_bias": substitution_bias,
        "substitution_bias_points": substitution_bias.bias_points,
        "substitution_bias_pct": substitution_bias.bias_pct,
        "lead_time_elasticity": lead_time_elasticity.to_dict(),
        "cpi_divergence": cpi_divergence.to_dict(),
        "weighted_national_mean_fare": round(weighted_national_mean, 2),
        "inflation_dod_pct": inflation_dod_pct,
        "inflation_mom_pct": inflation_mom_pct,
        "route_indices_count": len(route_indices_to_persist),
        "anomalies_count": len(anomalies_to_persist),
        "national_index": national_records_to_persist[0],
        "laspeyres_index": national_records_to_persist[0],
        "paasche_index": national_records_to_persist[1],
        "fisher_index": national_records_to_persist[2],
        "national_records": national_records_to_persist,
        "route_indices": route_indices_to_persist,
        "anomalies": anomalies_to_persist,
        "streaming_dedup_stats": streaming_stats,
        "arbitrage_count": len(arbitrage_opportunities),
        "arbitrage_opportunities": [
            opp.to_dict() for opp in arbitrage_opportunities[:50]
        ],
    }


def _persist_route_indices(db: Session, records: list[RouteDailyIndex]) -> None:
    """Idempotently upserts RouteDailyIndex records."""
    for rec in records:
        stmt = select(RouteDailyIndex).where(
            RouteDailyIndex.origin == rec.origin,
            RouteDailyIndex.destination == rec.destination,
            RouteDailyIndex.index_date == rec.index_date,
            RouteDailyIndex.booking_window == rec.booking_window,
            RouteDailyIndex.index_type == rec.index_type,
        )
        existing = db.execute(stmt).scalars().first()
        if existing:
            existing.sample_size = rec.sample_size
            existing.median_fare = rec.median_fare
            existing.mean_fare = rec.mean_fare
            existing.min_fare = rec.min_fare
            existing.max_fare = rec.max_fare
            existing.percentile_25 = rec.percentile_25
            existing.percentile_75 = rec.percentile_75
            existing.std_dev = rec.std_dev
            existing.index_value = rec.index_value
            existing.calculation_timestamp = rec.calculation_timestamp
            existing.route_id = rec.route_id
        else:
            db.add(rec)


def _persist_national_index(db: Session, record: NationalDailyIndex) -> None:
    """Idempotently upserts NationalDailyIndex record."""
    stmt = select(NationalDailyIndex).where(
        NationalDailyIndex.index_date == record.index_date,
        NationalDailyIndex.booking_window == record.booking_window,
        NationalDailyIndex.index_type == record.index_type,
    )
    existing = db.execute(stmt).scalars().first()
    if existing:
        existing.index_value = record.index_value
        existing.weighted_median_fare = record.weighted_median_fare
        existing.weighted_mean_fare = record.weighted_mean_fare
        existing.total_samples = record.total_samples
        existing.routes_covered = record.routes_covered
        existing.inflation_dod_pct = record.inflation_dod_pct
        existing.inflation_mom_pct = record.inflation_mom_pct
        existing.calculation_timestamp = record.calculation_timestamp
    else:
        db.add(record)


def _persist_anomaly_alerts(db: Session, alerts: list[AnomalyAlert]) -> None:
    """Persists newly identified AnomalyAlert records avoiding duplicate open alerts."""
    for alert in alerts:
        stmt = select(AnomalyAlert).where(
            AnomalyAlert.origin == alert.origin,
            AnomalyAlert.destination == alert.destination,
            AnomalyAlert.flight_date == alert.flight_date,
            AnomalyAlert.booking_window == alert.booking_window,
            AnomalyAlert.alert_type == alert.alert_type,
            AnomalyAlert.status == "OPEN",
        )
        existing = db.execute(stmt).scalars().first()
        if existing:
            existing.detected_fare = alert.detected_fare
            existing.baseline_fare = alert.baseline_fare
            existing.z_score = alert.z_score
            existing.pct_change = alert.pct_change
            existing.severity = alert.severity
            existing.description = alert.description
        else:
            db.add(alert)
