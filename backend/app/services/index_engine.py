"""APIx Index Engine - Statistical and Quantitative Pricing Service.

Implements:
1. Cross-platform flight deduplication (group by origin, dest, date, airline,
   flight number, departure time; select minimum consumer total fare).
2. Outlier filtering using Tukey's IQR bounds [Q1 - 1.5*IQR, Q3 + 1.5*IQR].
3. Exact weighted median using airline domestic market share weights:
   IndiGo (6E): 0.62, Air India (AI): 0.20, Air India Express (IX): 0.08,
   Akasa Air (QP): 0.05, SpiceJet (SG): 0.04.
4. Route composite fare: P_r,t = 0.20*T1 + 0.32*T7 + 0.26*T15 + 0.14*T30 + 0.08*T45.
5. National Modified Laspeyres Index:
   APIx_t = Sum(w_r * (P_r,t / P_r,0)) * 100, Base t_0 = 100.0.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

# MODELLED domestic airline market shares, not a DGCA release. These mirror
# AIRLINES in ingestion/config.py so the index and the seed data cannot disagree.
# They sum to exactly 1.0; the previous values summed to 0.99, which quietly
# under-weighted every carrier in the composite.
DEFAULT_AIRLINE_MARKET_SHARES: dict[str, float] = {
    "6E": 0.60,  # IndiGo
    "AI": 0.15,  # Air India
    "IX": 0.10,  # Air India Express
    "QP": 0.10,  # Akasa Air
    "SG": 0.05,  # SpiceJet
}

# MODELLED advance-purchase weights, not a measured DGCA lead-time distribution.
# These mirror DEFAULT_LEAD_TIME_PAX_SHARES in econometric_engine.py so the two
# weight tables cannot drift. T+45 was absent here, which left the fifth booking
# window contributing nothing to the composite fare.
DEFAULT_BOOKING_WINDOW_WEIGHTS: dict[str, float] = {
    "T1": 0.20,  # 1-day advance (urgent / business / emergency)
    "T7": 0.32,  # 7-day advance (short-lead standard)
    "T15": 0.26,  # 15-day advance (planned leisure)
    "T30": 0.14,  # 30-day advance (early bird / holiday)
    "T45": 0.08,  # 45-day advance (far-planned / corporate travel policy)
}

# DGCA Form A domestic scheduled passenger traffic shares (Directorate of Air Transport).
# Calibrated from DGCA monthly city-pair passenger traffic reports.
# Basket weights sum to exactly 1.000000 across monitored trunk corridors.
DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES: dict[str, float] = {
    "DEL-BOM": 0.150,
    "BOM-DEL": 0.150,
    "BLR-DEL": 0.110,
    "DEL-BLR": 0.110,
    "BOM-BLR": 0.080,
    "BLR-BOM": 0.080,
    "DEL-CCU": 0.055,
    "CCU-DEL": 0.055,
    "DEL-HYD": 0.040,
    "HYD-DEL": 0.040,
    "DEL-MAA": 0.040,
    "MAA-DEL": 0.040,
    "BLR-HYD": 0.025,
    "HYD-BLR": 0.025,
}


@dataclass(frozen=True)
class FlightQuote:
    """Canonical representation of a single flight quote from an OTA or airline portal."""

    origin: str
    destination: str
    flight_date: str
    airline_code: str
    flight_number: str
    departure_time: str
    fare: float
    source_portal: str | None = "unknown"
    booking_window: str | None = None
    currency: str = "INR"
    is_nonstop: bool = True
    base_fare: float | None = None
    taxes_and_fees: float | None = None
    udf_fee: float | None = None
    convenience_fee: float | None = None
    flight_status: str | None = None
    fare_split_basis: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert quote to dictionary representation."""
        return asdict(self)


@dataclass(frozen=True)
class TukeyBounds:
    """Statistical summary of Tukey IQR outlier detection."""

    q1: float
    q3: float
    iqr: float
    lower_bound: float
    upper_bound: float
    total_count: int
    retained_count: int
    outlier_count: int


def _extract_field(
    item: FlightQuote | Mapping[str, Any] | Any, field_name: str, default: Any = None
) -> Any:
    """Extract field from FlightQuote, dictionary, or generic object with alias resolution."""
    fare_aliases = ("fare", "total_fare", "fare_inr", "price")
    alias_map: dict[str, tuple[str, ...]] = {
        "fare": fare_aliases,
        "total_fare": fare_aliases,
        "fare_inr": fare_aliases,
        "price": fare_aliases,
        "source_portal": ("source_portal", "source_platform", "source", "portal"),
        "origin": ("origin", "origin_iata"),
        "destination": ("destination", "destination_iata"),
        "flight_date": ("flight_date", "departure_date"),
        "is_nonstop": ("is_nonstop", "nonstop", "direct"),
    }

    candidates = alias_map.get(field_name, (field_name,))

    if isinstance(item, FlightQuote):
        for attr in candidates:
            if hasattr(item, attr):
                val = getattr(item, attr)
                if val is not None:
                    return val
        if field_name in ("is_nonstop", "nonstop", "direct"):
            return item.is_nonstop
        return default

    if isinstance(item, Mapping):
        for key in candidates:
            if key in item and item[key] is not None:
                return item[key]
        if field_name in ("is_nonstop", "nonstop", "direct") and "stops" in item:
            stops_val = item["stops"]
            if stops_val is not None:
                try:
                    return int(stops_val) == 0
                except (ValueError, TypeError):
                    return stops_val == 0
        return default

    for attr in candidates:
        val = getattr(item, attr, None)
        if val is not None:
            return val
    if field_name in ("is_nonstop", "nonstop", "direct") and hasattr(item, "stops"):
        stops_val = item.stops
        if stops_val is not None:
            try:
                return int(stops_val) == 0
            except (ValueError, TypeError):
                return stops_val == 0
    return default


def _normalize_code(code: Any) -> str:
    """Normalize airport or airline code to uppercase stripped string."""
    return str(code).strip().upper() if code is not None else ""


def _normalize_flight_number(raw_num: Any, airline_code: str = "") -> str:
    """Normalize flight number (e.g. '6E 204', '6E-204', '204' -> '6E204')."""
    if raw_num is None:
        return ""
    s = str(raw_num).strip().upper()
    s = s.replace(" ", "").replace("-", "")
    ac = airline_code.strip().upper()
    if ac and s.startswith(ac):
        return s
    if ac and s.isdigit():
        return f"{ac}{s}"
    return s


def _normalize_departure_time(raw_time: Any) -> str:
    """Normalize departure time to HH:MM string or ISO date string."""
    if raw_time is None:
        return ""
    if isinstance(raw_time, datetime):
        return raw_time.strftime("%H:%M")
    if isinstance(raw_time, str):
        # Handle ISO strings or HH:MM:SS
        parts = raw_time.strip().split("T")
        time_part = parts[-1]
        time_subparts = time_part.split(":")
        if len(time_subparts) >= 2:
            return f"{time_subparts[0].zfill(2)}:{time_subparts[1].zfill(2)}"
        return raw_time.strip()
    return str(raw_time).strip()


def _normalize_date(raw_date: Any) -> str:
    """Normalize date to YYYY-MM-DD string."""
    if raw_date is None:
        return ""
    if isinstance(raw_date, (date, datetime)):
        return raw_date.strftime("%Y-%m-%d")
    s = str(raw_date).strip()
    # If ISO timestamp containing T, take date part
    if "T" in s:
        s = s.split("T")[0]
    return s


# ---------------------------------------------------------------------------
# 1. Cross-Platform Flight Deduplication
# ---------------------------------------------------------------------------


def deduplicate_quotes(
    quotes: Iterable[FlightQuote | Mapping[str, Any] | Any],
) -> list[FlightQuote]:
    """Deduplicates cross-platform flight quotes.

    Groups quotes by (origin, destination, flight_date, airline_code,
    flight_number, departure_time) and takes the minimum consumer total fare.

    Args:
        quotes: Iterable of FlightQuote instances, mappings, or objects.

    Returns:
        List of canonical deduplicated FlightQuote objects, each having the
        lowest consumer fare across reporting platforms.
    """
    grouped: dict[tuple[str, str, str, str, str, str], list[FlightQuote]] = defaultdict(
        list
    )

    for item in quotes:
        origin = _normalize_code(_extract_field(item, "origin"))
        destination = _normalize_code(_extract_field(item, "destination"))
        flight_date = _normalize_date(_extract_field(item, "flight_date"))
        airline_code = _normalize_code(_extract_field(item, "airline_code"))
        flight_number = _normalize_flight_number(
            _extract_field(item, "flight_number"), airline_code
        )
        departure_time = _normalize_departure_time(
            _extract_field(item, "departure_time")
        )
        fare = float(_extract_field(item, "fare", 0.0))
        source_portal = str(_extract_field(item, "source_portal", "unknown"))
        booking_window = _extract_field(item, "booking_window", None)
        currency = str(_extract_field(item, "currency", "INR"))
        is_nonstop = bool(_extract_field(item, "is_nonstop", True))
        metadata = _extract_field(item, "metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        quote_obj = FlightQuote(
            origin=origin,
            destination=destination,
            flight_date=flight_date,
            airline_code=airline_code,
            flight_number=flight_number,
            departure_time=departure_time,
            fare=fare,
            source_portal=source_portal,
            booking_window=booking_window,
            currency=currency,
            is_nonstop=is_nonstop,
            metadata=metadata,
        )

        dedup_key = (
            origin,
            destination,
            flight_date,
            airline_code,
            flight_number,
            departure_time,
        )
        grouped[dedup_key].append(quote_obj)

    deduplicated: list[FlightQuote] = []
    for _key, quote_group in grouped.items():
        # Select quote with the minimum consumer fare
        best_quote = min(quote_group, key=lambda q: q.fare)
        deduplicated.append(best_quote)

    return deduplicated


# ---------------------------------------------------------------------------
# 2. Outlier Filtering: Tukey IQR Bounds
# ---------------------------------------------------------------------------


def _compute_percentile_linear(
    sorted_values: Sequence[float], percentile: float
) -> float:
    """Compute percentile using linear interpolation (standard numpy/R type 7).

    Args:
        sorted_values: Ascending sorted sequence of numbers.
        percentile: Float between 0.0 and 1.0 (e.g. 0.25 for Q1).

    Returns:
        Interpolated percentile value.
    """
    n = len(sorted_values)
    if n == 0:
        raise ValueError("Cannot compute percentile of empty sequence")
    if n == 1:
        return sorted_values[0]

    index = percentile * (n - 1)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    weight = index - lower

    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def compute_tukey_bounds(fares: Sequence[float], k: float = 1.5) -> TukeyBounds:
    """Computes Tukey's IQR lower and upper bounds for outlier detection.

    Bounds: [Q1 - k*IQR, Q3 + k*IQR]

    Args:
        fares: Sequence of numeric fare prices.
        k: IQR multiplier, default 1.5 (Tukey's standard rule).

    Returns:
        TukeyBounds object containing Q1, Q3, IQR, bounds, and counts.
    """
    if not fares:
        return TukeyBounds(
            q1=0.0,
            q3=0.0,
            iqr=0.0,
            lower_bound=0.0,
            upper_bound=0.0,
            total_count=0,
            retained_count=0,
            outlier_count=0,
        )

    clean_fares = sorted(
        [float(x) for x in fares if not math.isnan(x) and not math.isinf(x)]
    )
    total_count = len(clean_fares)

    if total_count < 4:
        # Insufficient data points for meaningful quartiles; retain all
        min_f = clean_fares[0]
        max_f = clean_fares[-1]
        return TukeyBounds(
            q1=min_f,
            q3=max_f,
            iqr=max_f - min_f,
            lower_bound=min_f,
            upper_bound=max_f,
            total_count=total_count,
            retained_count=total_count,
            outlier_count=0,
        )

    q1 = _compute_percentile_linear(clean_fares, 0.25)
    q3 = _compute_percentile_linear(clean_fares, 0.75)
    iqr = q3 - q1

    lower_bound = q1 - k * iqr
    upper_bound = q3 + k * iqr

    retained = [x for x in clean_fares if lower_bound <= x <= upper_bound]
    outliers_count = total_count - len(retained)

    return TukeyBounds(
        q1=q1,
        q3=q3,
        iqr=iqr,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        total_count=total_count,
        retained_count=len(retained),
        outlier_count=outliers_count,
    )


def filter_outliers_tukey(fares: Sequence[float], k: float = 1.5) -> list[float]:
    """Filters fares using Tukey IQR bounds [Q1 - k*IQR, Q3 + k*IQR].

    Args:
        fares: Sequence of numeric prices.
        k: Outlier multiplier (default 1.5).

    Returns:
        List of fares falling within the Tukey acceptance interval.
    """
    if not fares:
        return []
    bounds = compute_tukey_bounds(fares, k=k)
    return [x for x in fares if bounds.lower_bound <= x <= bounds.upper_bound]


def filter_quotes_tukey(
    quotes: Sequence[FlightQuote | Mapping[str, Any] | Any],
    k: float = 1.5,
) -> list[FlightQuote | Mapping[str, Any] | Any]:
    """Filters flight quote items using Tukey IQR bounds on fare amount.

    Args:
        quotes: Sequence of FlightQuote objects or mappings.
        k: Outlier multiplier (default 1.5).

    Returns:
        Filtered list of quote objects within Tukey bounds.
    """
    if not quotes:
        return []
    fares = [_extract_field(q, "fare") for q in quotes]
    bounds = compute_tukey_bounds(fares, k=k)
    return [
        q
        for q in quotes
        if bounds.lower_bound <= float(_extract_field(q, "fare")) <= bounds.upper_bound
    ]


# ---------------------------------------------------------------------------
# 3. Weighted Median Calculation
# ---------------------------------------------------------------------------


def weighted_median_values(
    values: Sequence[float],
    weights: Sequence[float],
) -> float:
    """Calculates exact weighted median of numeric values given their weights.

    Algorithm:
    1. Sort values x_1 <= x_2 <= ... <= x_n along with corresponding weights w_i.
    2. Normalize weights such that Sum(w_i) = 1.0.
    3. Compute cumulative weights C_k = Sum_{i=1}^k w_i.
    4. The weighted median is the value where cumulative weight reaches 0.5:
       - If C_k > 0.5 and C_{k-1} < 0.5, median is x_k.
       - If C_k == 0.5 exactly, median is (x_k + x_{k+1}) / 2.0.

    Invariant:
        If all values are identical (equal price distribution), weighted median
        equals the scalar price regardless of weight distribution.

    Args:
        values: Sequence of numeric prices.
        weights: Sequence of positive weights corresponding to each value.

    Returns:
        Exact weighted median as a float.
    """
    if not values or not weights:
        raise ValueError("Cannot calculate weighted median of empty sequences")
    if len(values) != len(weights):
        raise ValueError(
            f"Length mismatch: {len(values)} values vs {len(weights)} weights"
        )

    # Invariant 1 fast path: if all values are identical, return the scalar value immediately
    first_val = values[0]
    if all(math.isclose(v, first_val, abs_tol=1e-12) for v in values):
        return float(first_val)

    # Pair and sort by value
    pairs = sorted(zip(values, weights, strict=True), key=lambda p: p[0])
    sorted_vals = [p[0] for p in pairs]
    sorted_weights = [max(0.0, float(p[1])) for p in pairs]

    total_weight = sum(sorted_weights)
    if total_weight <= 0.0:
        # Fall back to unweighted median
        mid = len(sorted_vals) // 2
        if len(sorted_vals) % 2 == 1:
            return float(sorted_vals[mid])
        return float((sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0)

    # Normalize weights so they sum to 1.0
    norm_weights = [w / total_weight for w in sorted_weights]

    cum_weight = 0.0
    n = len(sorted_vals)

    for i in range(n):
        cum_weight += norm_weights[i]

        # Check if cumulative weight crosses 0.5
        if math.isclose(cum_weight, 0.5, abs_tol=1e-9):
            if i + 1 < n:
                return float((sorted_vals[i] + sorted_vals[i + 1]) / 2.0)
            return float(sorted_vals[i])

        if cum_weight > 0.5:
            # We crossed 0.5 at this element
            return float(sorted_vals[i])

    return float(sorted_vals[-1])


def calculate_weighted_median(
    quotes: Sequence[FlightQuote | Mapping[str, Any] | Any],
    market_shares: Mapping[str, float] | None = None,
) -> float:
    """Computes exact weighted median of flight quotes using airline market shares.

    Market Share Weights (DGCA Domestic):
    - 6E (IndiGo): 0.62
    - AI (Air India): 0.20
    - IX (Air India Express): 0.08
    - QP (Akasa Air): 0.05
    - SG (SpiceJet): 0.04

    The market share weight of each airline is normalized among present airlines
    and distributed equally across all quotes belonging to that carrier.

    Args:
        quotes: Sequence of FlightQuote items or mappings.
        market_shares: Optional custom market share mapping. Defaults to
                       DEFAULT_AIRLINE_MARKET_SHARES.

    Returns:
        Weighted median fare as a float.
    """
    if not quotes:
        raise ValueError("Cannot calculate weighted median on empty quote collection")

    shares = dict(
        market_shares if market_shares is not None else DEFAULT_AIRLINE_MARKET_SHARES
    )

    # Invariant 1 fast path check: if all quotes have the exact same fare
    fares = [float(_extract_field(q, "fare")) for q in quotes]
    first_fare = fares[0]
    if all(math.isclose(f, first_fare, abs_tol=1e-12) for f in fares):
        return float(first_fare)

    # Count quotes per airline
    airline_counts: dict[str, int] = defaultdict(int)
    for q in quotes:
        ac = _normalize_code(_extract_field(q, "airline_code"))
        airline_counts[ac] += 1

    # Determine market share for each present airline
    present_shares: dict[str, float] = {}
    for ac in airline_counts:
        # If airline not in default dictionary, assign a minimal positive share (e.g. 0.01)
        present_shares[ac] = shares.get(ac, 0.01)

    sum_present = sum(present_shares.values())
    if sum_present > 0:
        normalized_carrier_shares = {
            ac: share / sum_present for ac, share in present_shares.items()
        }
    else:
        normalized_carrier_shares = {
            ac: 1.0 / len(airline_counts) for ac in airline_counts
        }

    # Assign weight to each quote: carrier_weight / count_quotes_for_carrier
    weights: list[float] = []
    for q in quotes:
        ac = _normalize_code(_extract_field(q, "airline_code"))
        carrier_weight = normalized_carrier_shares[ac]
        quote_weight = carrier_weight / airline_counts[ac]
        weights.append(quote_weight)

    return weighted_median_values(fares, weights)


# Alias for compute_weighted_median
compute_weighted_median = calculate_weighted_median


# ---------------------------------------------------------------------------
# 4. Route Composite Fare
# ---------------------------------------------------------------------------


def calculate_route_composite_fare(
    window_fares: Mapping[str, float],
    weights: Mapping[str, float] | None = None,
) -> float:
    """Computes the route composite fare across booking horizon windows.

    Formula:
        P_r,t = 0.20*T1 + 0.32*T7 + 0.26*T15 + 0.14*T30 + 0.08*T45
    Args:
        window_fares: Mapping of booking window names to fares (e.g. {"T1": 6000,
                      "T7": 5200, "T15": 4800, "T30": 4200}).
        weights: Optional custom window weights. Defaults to
                 DEFAULT_BOOKING_WINDOW_WEIGHTS.

    Returns:
        Composite route fare as a float.
    """
    if not window_fares:
        raise ValueError("Cannot calculate composite fare from empty window fares")

    raw_weights = weights if weights is not None else DEFAULT_BOOKING_WINDOW_WEIGHTS
    target_weights: dict[str, float] = {}
    for k, v in raw_weights.items():
        sk = str(k).strip().upper().replace("+", "")
        if not sk.startswith("T") and sk.isdigit():
            sk = f"T{sk}"
        target_weights[sk] = float(v)
    # Standardize window keys (e.g. 'T+1' -> 'T1', '1' -> 'T1')
    normalized_fares: dict[str, float] = {}
    for k, v in window_fares.items():
        sk = str(k).strip().upper().replace("+", "")
        if not sk.startswith("T") and sk.isdigit():
            sk = f"T{sk}"
        normalized_fares[sk] = float(v)

    # Weight by the windows we actually hold a fare for, renormalised to 1.0.
    #
    # A previous version fast-pathed the four original windows and returned their
    # weighted sum unnormalised. Once T+45 took 0.08 of the weight those four
    # totalled 0.92, so identical fares produced a composite 8% low and T+45 was
    # never consulted at all. One intersection-and-renormalise path is correct for
    # every subset of windows, so there is no longer a case to keep in sync.
    present_weights: dict[str, float] = {
        window: target_weights.get(window, 0.0) for window in normalized_fares
    }
    weight_sum = sum(present_weights.values())
    if weight_sum <= 0:
        # None of the supplied windows are weighted, so fall back to an even mix
        # rather than returning an unweighted number.
        weight_sum = float(len(normalized_fares))
        present_weights = dict.fromkeys(normalized_fares, 1.0)

    composite = sum(
        (present_weights[window] / weight_sum) * normalized_fares[window]
        for window in normalized_fares
    )
    return float(composite)


# ---------------------------------------------------------------------------
# 5. National Modified Laspeyres Index
# ---------------------------------------------------------------------------


def calculate_true_laspeyres_index(
    current_fares: Mapping[str, float],
    base_fares: Mapping[str, float],
    base_quantities: Mapping[str, float],
    base_value: float = 100.0,
) -> float:
    """Computes the True Laspeyres Price Index using base-period physical quantities Q_{r,0}.

    Formula:
        I_L = Sum(P_{r,t} * Q_{r,0}) / Sum(P_{r,0} * Q_{r,0}) * Base_0

    When paired with Paasche using current quantities Q_{r,t}, the Fisher Ideal
    Price Index sqrt(I_L * I_P) satisfies Irving Fisher's Factor Reversal Test identically:
        P_F * Q_F = (Sum P_{r,t} * Q_{r,t}) / (Sum P_{r,0} * Q_{r,0}) = V_t / V_0.
    """
    if not current_fares or not base_fares or not base_quantities:
        raise ValueError(
            "Current fares, base fares, and base quantities cannot be empty"
        )

    common_routes = [
        r for r in current_fares if r in base_fares and r in base_quantities
    ]
    if not common_routes:
        raise ValueError("No matching common routes between fares and base quantities")

    numerator = sum(
        float(current_fares[r]) * float(base_quantities[r]) for r in common_routes
    )
    denominator = sum(
        float(base_fares[r]) * float(base_quantities[r]) for r in common_routes
    )

    if denominator <= 0:
        raise ValueError("True Laspeyres denominator must be strictly positive")

    return float((numerator / denominator) * base_value)


def calculate_laspeyres_index(
    current_fares: Mapping[str, float],
    base_fares: Mapping[str, float],
    route_weights: Mapping[str, float] | None = None,
    base_value: float = 100.0,
    base_quantities: Mapping[str, float] | None = None,
) -> float:
    """Computes the National Modified Laspeyres Airfare Price Index or True Laspeyres.

    Formula:
        Modified Laspeyres (statutory MoSPI CPI fixed-weight relative mean):
            APIx_t = Sum_{r} (w_r * (P_{r,t} / P_{r,0})) * Base_0
            where Base_0 = 100.0, and Sum(w_r) = 1.0.

        True Laspeyres (when base_quantities Q_{r,0} is supplied):
            APIx_t = Sum_{r} (P_{r,t} * Q_{r,0}) / Sum_{r} (P_{r,0} * Q_{r,0}) * Base_0

    Invariants:
    1. Base period prices (P_{r,t} == P_{r,0}) yield national index = 100.00.
    2. Uniform +20% price increase (P_{r,t} == 1.20 * P_{r,0}) yields 120.00.

    Args:
        current_fares: Mapping of route identifiers to current composite fares P_{r,t}.
        base_fares: Mapping of route identifiers to base composite fares P_{r,0}.
        route_weights: Mapping of route identifiers to traffic weights w_r.
                       If None, equal weighting (1/N) is applied.
        base_value: Base period index value (default 100.0).
        base_quantities: Optional base-period physical traffic quantities Q_{r,0}.
                         If provided, computes True Laspeyres index satisfying factor reversal.

    Returns:
        Computed National Laspeyres Index value.
    """
    if not current_fares or not base_fares:
        raise ValueError("Current fares and base fares cannot be empty")

    if base_quantities is not None:
        return calculate_true_laspeyres_index(
            current_fares=current_fares,
            base_fares=base_fares,
            base_quantities=base_quantities,
            base_value=base_value,
        )

    common_routes = [r for r in current_fares if r in base_fares]
    if not common_routes:
        raise ValueError("No matching routes between current fares and base fares")

    # Invariant 2 fast path check: if all current fares equal base fares
    all_equal = True
    for r in common_routes:
        if not math.isclose(
            current_fares[r], base_fares[r], rel_tol=1e-12, abs_tol=1e-12
        ):
            all_equal = False
            break
    if all_equal:
        return float(base_value)

    # Invariant 3 fast path check: if all current fares are exactly ratio * base
    first_r = common_routes[0]
    base_f0 = base_fares[first_r]
    if base_f0 <= 0:
        raise ValueError(f"Base fare for route {first_r} must be strictly positive")
    ratio_0 = current_fares[first_r] / base_f0
    uniform_ratio = True
    for r in common_routes:
        b = base_fares[r]
        if b <= 0:
            raise ValueError(f"Base fare for route {r} must be strictly positive")
        if not math.isclose(
            current_fares[r] / b, ratio_0, rel_tol=1e-12, abs_tol=1e-12
        ):
            uniform_ratio = False
            break
    if uniform_ratio:
        return float(ratio_0 * base_value)

    # Route weights
    raw_weights: dict[str, float] = {}
    if route_weights is not None:
        for r in common_routes:
            raw_weights[r] = float(route_weights.get(r, 0.0))
    else:
        for r in common_routes:
            raw_weights[r] = 1.0 / len(common_routes)

    total_w = sum(raw_weights.values())
    if total_w <= 0.0:
        total_w = len(common_routes)
        raw_weights = dict.fromkeys(common_routes, 1.0)

    normalized_weights = {r: raw_weights[r] / total_w for r in common_routes}

    index_sum = 0.0
    for r in common_routes:
        p_t = float(current_fares[r])
        p_0 = float(base_fares[r])
        if p_0 <= 0:
            raise ValueError(f"Base fare for route '{r}' must be positive, got {p_0}")
        price_relative = p_t / p_0
        index_sum += normalized_weights[r] * price_relative

    return float(index_sum * base_value)


def calculate_paasche_index(
    current_fares: Mapping[str, float],
    base_fares: Mapping[str, float],
    current_traffic_weights: Mapping[str, float],
    base_value: float = 100.0,
) -> float:
    """Computes the Paasche Price Index using current-period traffic weights.

    Formula:
        I_P = Sum(P_{r,t} * Q_{r,t}) / Sum(P_{r,0} * Q_{r,t}) * 100
    """
    common_routes = [
        r for r in current_fares if r in base_fares and r in current_traffic_weights
    ]
    if not common_routes:
        raise ValueError("No common routes available for Paasche calculation")

    numerator = sum(
        current_fares[r] * current_traffic_weights[r] for r in common_routes
    )
    denominator = sum(base_fares[r] * current_traffic_weights[r] for r in common_routes)

    if denominator <= 0:
        raise ValueError("Paasche denominator must be positive")

    return float((numerator / denominator) * base_value)


def calculate_fisher_index(
    laspeyres: float,
    paasche: float,
) -> float:
    """Computes the Fisher Ideal Price Index (geometric mean of Laspeyres and Paasche).

    Formula:
        I_F = sqrt(I_L * I_P)
    """
    if laspeyres < 0 or paasche < 0:
        raise ValueError("Index values must be non-negative for Fisher calculation")
    return float(math.sqrt(laspeyres * paasche))


# ---------------------------------------------------------------------------
# High-level Pipeline Class
# ---------------------------------------------------------------------------


class IndexEngine:
    """Orchestrates end-to-end airfare data processing and index calculation."""

    def __init__(
        self,
        airline_weights: Mapping[str, float] | None = None,
        booking_window_weights: Mapping[str, float] | None = None,
        route_traffic_shares: Mapping[str, float] | None = None,
    ):
        self.airline_weights = dict(
            airline_weights
            if airline_weights is not None
            else DEFAULT_AIRLINE_MARKET_SHARES
        )
        self.booking_window_weights = dict(
            booking_window_weights
            if booking_window_weights is not None
            else DEFAULT_BOOKING_WINDOW_WEIGHTS
        )
        self.route_traffic_shares = dict(
            route_traffic_shares
            if route_traffic_shares is not None
            else DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES
        )

    def process_raw_quotes(
        self,
        raw_quotes: Iterable[FlightQuote | Mapping[str, Any] | Any],
        iqr_multiplier: float = 1.5,
    ) -> list[FlightQuote]:
        """Runs deduplication and Tukey outlier filtering on raw quotes."""
        deduped = deduplicate_quotes(raw_quotes)
        filtered = filter_quotes_tukey(deduped, k=iqr_multiplier)
        return [q if isinstance(q, FlightQuote) else FlightQuote(**q) for q in filtered]

    def compute_window_representative_fare(
        self,
        quotes: Sequence[FlightQuote | Mapping[str, Any] | Any],
    ) -> float:
        """Computes weighted median representative fare for a specific route window."""
        return calculate_weighted_median(quotes, market_shares=self.airline_weights)

    def compute_route_composite(
        self,
        window_fares: Mapping[str, float],
    ) -> float:
        """Computes composite fare for a route across T1, T7, T15, T30, T45."""
        return calculate_route_composite_fare(
            window_fares, weights=self.booking_window_weights
        )

    def compute_national_index(
        self,
        current_composite_fares: Mapping[str, float],
        base_composite_fares: Mapping[str, float],
        custom_route_weights: Mapping[str, float] | None = None,
    ) -> float:
        """Computes National Modified Laspeyres Index."""
        weights = (
            custom_route_weights
            if custom_route_weights is not None
            else self.route_traffic_shares
        )
        return calculate_laspeyres_index(
            current_fares=current_composite_fares,
            base_fares=base_composite_fares,
            route_weights=weights,
            base_value=100.0,
        )
