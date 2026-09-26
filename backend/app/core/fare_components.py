"""Shared fare-component rules for ingestion and persistence.

Base versus tax is estimated only when a source omits both parts. User
development fee and convenience charge are never estimated.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

# ESTIMATE used only when the source does not supply a base/tax split.
# Never a measurement. Rows already stored under the old 0.85 repository
# fallback are left as they are; this constant is not a backfill.
ESTIMATED_BASE_FARE_RATIO: Final[float] = 0.78

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
    ESTIMATED = "estimated"


@dataclass(frozen=True, slots=True)
class FareSplit:
    """Base and tax amounts plus the basis that produced them."""

    base_fare: float
    taxes_and_fees: float
    basis: FareSplitBasis


def classify_fare_split(
    total_fare: float,
    base_fare: float | None,
    taxes_and_fees: float | None,
) -> FareSplit:
    """Split a total without inventing a ratio the source already made unnecessary.

    Both sides supplied: measured. One side supplied: the other is the residual
    of the total, not the ratio. Neither supplied: the single documented estimate.
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
    estimated_base = round(total_fare * ESTIMATED_BASE_FARE_RATIO, 2)
    return FareSplit(
        estimated_base,
        round(total_fare - estimated_base, 2),
        FareSplitBasis.ESTIMATED,
    )


def split_base_and_taxes(
    total_fare: float,
    base_fare: float | None,
    taxes_and_fees: float | None,
) -> tuple[float, float]:
    """Return (base, taxes). Prefer classify_fare_split when the basis must travel."""
    split = classify_fare_split(total_fare, base_fare, taxes_and_fees)
    return split.base_fare, split.taxes_and_fees
