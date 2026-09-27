"""Shared fare-component rules for ingestion and persistence.

Base versus tax is estimated only when a source omits both parts. User
development fee and convenience charge are never estimated.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

# Calibration baseline used when no carrier or route is provided.
# Replaced the single fixed 0.78 constant with carrier- and route-aware
# calibrated ratios while retaining DEFAULT_BASE_FARE_RATIO for backward compatibility.
DEFAULT_BASE_FARE_RATIO: Final[float] = 0.78
ESTIMATED_BASE_FARE_RATIO: Final[float] = DEFAULT_BASE_FARE_RATIO

# Carrier-aware calibrated base fare ratios based on Indian domestic airline economics.
# FSCs (e.g. Air India) bundle baggage (25kg), meals, and seat selection into the base fare,
# yielding a higher base proportion (~0.81). LCCs (IndiGo, Akasa, SpiceJet) unbundle ancillaries
# and levy higher relative fuel/convenience charges (~0.74 - 0.78).
CARRIER_BASE_FARE_RATIOS: Final[dict[str, float]] = {
    "6E": 0.78,  # IndiGo (LCC reference trunk share)
    "AI": 0.81,  # Air India (Full-service carrier with bundled services)
    "IX": 0.76,  # Air India Express (LCC subsidiary)
    "QP": 0.76,  # Akasa Air (LCC)
    "SG": 0.74,  # SpiceJet (LCC unbundled ancillaries)
}

CARRIER_BASE_FARE_OFFSETS: Final[dict[str, float]] = {
    "6E": 0.00,
    "AI": 0.03,
    "IX": -0.02,
    "QP": -0.02,
    "SG": -0.04,
}

# Route-aware calibrated base fare ratios. Fixed passenger airport charges (UDF, PSF/ASF)
# form a larger proportion of short-haul low-fare routes (lower base ratio), and a smaller
# proportion of long-haul high-fare routes (higher base ratio).
ROUTE_BASE_FARE_RATIOS: Final[dict[tuple[str, str], float]] = {
    ("DEL", "BOM"): 0.78,
    ("BOM", "DEL"): 0.78,
    ("DEL", "BLR"): 0.81,
    ("BLR", "DEL"): 0.81,
    ("BOM", "BLR"): 0.74,
    ("BLR", "BOM"): 0.74,
    ("DEL", "HYD"): 0.77,
    ("HYD", "DEL"): 0.77,
    ("DEL", "CCU"): 0.78,
    ("CCU", "DEL"): 0.78,
    ("DEL", "MAA"): 0.81,
    ("MAA", "DEL"): 0.81,
    ("BLR", "HYD"): 0.72,
    ("HYD", "BLR"): 0.72,
}

# Configurable recomposition integrity check tolerance: ±1 INR absolute or ±0.5% relative
RECOMPOSITION_TOLERANCE_ABSOLUTE_INR: Final[float] = 1.0
RECOMPOSITION_TOLERANCE_RELATIVE: Final[float] = 0.005  # 0.5%

FLIGHT_STATUS_SCHEDULED: Final[str] = "scheduled"
FLIGHT_STATUS_CANCELLED: Final[str] = "cancelled"
FLIGHT_STATUS_SOLD_OUT: Final[str] = "sold_out"

# Canonical flight_status tokens. NULL means the source did not report one.
# British spelling "cancelled" is the stored form; "canceled" is accepted.
FLIGHT_STATUS_VALUES: Final[tuple[str, ...]] = (
    FLIGHT_STATUS_SCHEDULED,
    FLIGHT_STATUS_CANCELLED,
    FLIGHT_STATUS_SOLD_OUT,
)

_FLIGHT_STATUS_ALIASES: Final[dict[str, str]] = {
    "scheduled": FLIGHT_STATUS_SCHEDULED,
    "schedule": FLIGHT_STATUS_SCHEDULED,
    "cancelled": FLIGHT_STATUS_CANCELLED,
    "canceled": FLIGHT_STATUS_CANCELLED,
    "sold_out": FLIGHT_STATUS_SOLD_OUT,
    "soldout": FLIGHT_STATUS_SOLD_OUT,
}


def canonical_booking_class(value: str | None) -> str | None:
    """Return an uppercase booking/fare-basis code, or None if absent.

    This is the RBD or fare-basis token (Y, B, M, X), not cabin class.
    """
    if value is None:
        return None
    token = value.strip().upper()
    if token == "":
        return None
    return token


def canonical_flight_status(value: str | None) -> str | None:
    """Normalise a reported flight status. Never invents one.

    Known aliases collapse to scheduled, cancelled, or sold_out. Any other
    non-empty token is stored lowercased so an unrecognised report is kept
    rather than rewritten as scheduled or dropped.
    """
    if value is None:
        return None
    token = value.strip().lower().replace("-", "_").replace(" ", "_")
    if token == "":
        return None
    return _FLIGHT_STATUS_ALIASES.get(token, token)


def optional_amount(value: float | int | str | None) -> float | None:
    """Parse a supplied fee. Blank and missing stay None; zero is kept."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        token = value.strip()
        if token == "":
            return None
        return float(token)
    return float(value)


class FareSplitBasis(StrEnum):
    """How a stored base/tax pair was obtained. Downstream must not treat them alike."""

    MEASURED = "measured"
    RESIDUAL = "residual"
    CALIBRATED = "calibrated"
    ESTIMATED = "estimated"


def get_calibrated_base_fare_ratio_and_basis(
    airline_code: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
) -> tuple[float, FareSplitBasis]:
    """Derive calibrated base fare ratio and basis label from route and carrier."""
    code = (airline_code or "").strip().upper()
    orig = (origin or "").strip().upper()
    dest = (destination or "").strip().upper()

    has_carrier = code in CARRIER_BASE_FARE_RATIOS
    route_key = (orig, dest)
    has_route = route_key in ROUTE_BASE_FARE_RATIOS

    if not has_carrier and not has_route:
        return DEFAULT_BASE_FARE_RATIO, FareSplitBasis.ESTIMATED

    if has_route:
        base_ratio = ROUTE_BASE_FARE_RATIOS[route_key]
        carrier_offset = CARRIER_BASE_FARE_OFFSETS.get(code, 0.0)
        calibrated_ratio = round(base_ratio + carrier_offset, 4)
    else:
        calibrated_ratio = CARRIER_BASE_FARE_RATIOS[code]

    clamped_ratio = max(0.60, min(0.90, calibrated_ratio))
    return clamped_ratio, FareSplitBasis.CALIBRATED


def get_calibrated_base_fare_ratio(
    airline_code: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
) -> float:
    """Derive calibrated base fare ratio without basis label."""
    ratio, _ = get_calibrated_base_fare_ratio_and_basis(
        airline_code=airline_code,
        origin=origin,
        destination=destination,
    )
    return ratio


def check_fare_recomposition(
    total_fare: float,
    base_fare: float | None,
    taxes_and_fees: float | None,
    udf_fee: float | None = None,
    convenience_fee: float | None = None,
    *,
    abs_tolerance: float = RECOMPOSITION_TOLERANCE_ABSOLUTE_INR,
    rel_tolerance: float = RECOMPOSITION_TOLERANCE_RELATIVE,
) -> bool:
    """Assert total ≈ base + taxes + UDF + convenience within configurable tolerance.

    Returns True if recomposition holds within max(abs_tolerance, rel_tolerance * total_fare).
    Returns False if components exist and their sum violates total recomposition.
    """
    if base_fare is None and taxes_and_fees is None:
        return True

    base = float(base_fare) if base_fare is not None else 0.0
    taxes = float(taxes_and_fees) if taxes_and_fees is not None else 0.0
    udf = float(udf_fee) if udf_fee is not None else 0.0
    conv = float(convenience_fee) if convenience_fee is not None else 0.0

    component_sum = base + taxes + udf + conv
    delta = abs(float(total_fare) - component_sum)
    allowed = max(abs_tolerance, rel_tolerance * abs(float(total_fare)))

    return delta <= allowed

@dataclass(frozen=True, slots=True)
class FareSplit:
    """Base and tax amounts plus the basis that produced them."""

    base_fare: float
    taxes_and_fees: float
    basis: FareSplitBasis


def classify_fare_split(
    total_fare: float,
    base_fare: float | None = None,
    taxes_and_fees: float | None = None,
    airline_code: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
) -> FareSplit:
    """Split a total without inventing a ratio the source already made unnecessary.

    Both sides supplied: measured. One side supplied: the other is the residual
    of the total, not the ratio. Neither supplied: route- and carrier-aware calibrated
    ratio or documented fallback estimate.
    """
    if base_fare is not None and taxes_and_fees is not None:
        return FareSplit(
            float(base_fare), float(taxes_and_fees), FareSplitBasis.MEASURED
        )
    if base_fare is not None:
        return FareSplit(
            float(base_fare),
            round(total_fare - base_fare, 2),
            FareSplitBasis.RESIDUAL,
        )
    if taxes_and_fees is not None:
        return FareSplit(
            round(total_fare - taxes_and_fees, 2),
            float(taxes_and_fees),
            FareSplitBasis.RESIDUAL,
        )
    ratio, basis = get_calibrated_base_fare_ratio_and_basis(
        airline_code=airline_code,
        origin=origin,
        destination=destination,
    )
    estimated_base = round(total_fare * ratio, 2)
    return FareSplit(
        estimated_base,
        round(total_fare - estimated_base, 2),
        basis,
    )


def split_base_and_taxes(
    total_fare: float,
    base_fare: float | None = None,
    taxes_and_fees: float | None = None,
    airline_code: str | None = None,
    origin: str | None = None,
    destination: str | None = None,
) -> tuple[float, float]:
    """Return (base, taxes). Prefer classify_fare_split when the basis must travel."""
    split = classify_fare_split(
        total_fare,
        base_fare,
        taxes_and_fees,
        airline_code=airline_code,
        origin=origin,
        destination=destination,
    )
    return split.base_fare, split.taxes_and_fees


