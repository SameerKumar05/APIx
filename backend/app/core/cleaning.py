"""Data-cleaning policy for raw quotes. This is the one place those rules live.

1. Null or non-positive total fare is rejected at the scraper boundary
   (BaseScraper.normalize_fare). It is never stored and never estimated.
2. A missing base/tax split uses ESTIMATED_BASE_FARE_RATIO and is stored with
   fare_split_basis "estimated". A supplied side is kept and the other side is
   the residual ("residual"). Both supplied is "measured". udf_fee and
   convenience_fee stay NULL unless the source supplied them. They are never
   derived from the ratio.
3. A missing departure time does not become a duration. duration_minutes stays
   NULL. A supplied 0 without a departure clock is the same absence, not a
   zero-length flight.
4. cancelled and sold_out are persisted and excluded from the index and from
   the representative fare. A cancelled flight has no payable fare. NULL status
   is not rewritten to scheduled.
5. An outlier is persisted with index_exclusion_reason "outlier" and excluded
   from the index. It is not deleted: an auditor can still see the quote and
   the reason it did not enter the index. Deleting it would hide a scraper
   fault and make the exclusion unauditable.

A fare is an outlier when it falls outside Tukey fences (k=1.5) computed from
payable peers on the same corridor and booking window whose scrape time is
inside OUTLIER_LOOKBACK_DAYS. Fewer than MIN_TUKEY_PEERS peers is not an
outlier: the fence is not identified, so the fare is kept. The lookback matches
the 30-day route baseline already used by the index.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final

from backend.app.core.fare_components import (
    FLIGHT_STATUS_CANCELLED,
    FLIGHT_STATUS_SOLD_OUT,
    FLIGHT_STATUS_VALUES,
    canonical_flight_status,
)
from backend.app.services.index_engine import compute_tukey_bounds

OUTLIER_LOOKBACK_DAYS: Final[int] = 30
MIN_TUKEY_PEERS: Final[int] = 4
TUKEY_K: Final[float] = 1.5

EXCLUSION_OUTLIER: Final[str] = "outlier"
EXCLUSION_CANCELLED: Final[str] = "cancelled"
EXCLUSION_SOLD_OUT: Final[str] = "sold_out"

_STATUS_TEXT_KEYS: Final[tuple[str, ...]] = (
    "flight_status",
    "flightStatus",
    "FlightStatus",
)
_SOLD_OUT_KEYS: Final[tuple[str, ...]] = (
    "soldOut",
    "sold_out",
    "isSoldOut",
    "SoldOut",
    "is_sold_out",
)
_CANCELLED_KEYS: Final[tuple[str, ...]] = (
    "cancelled",
    "canceled",
    "isCancelled",
    "isCanceled",
    "IsCancelled",
)
_StatusValue = str | bool | int | float | None


def outlier_against_peers(fare: float, peer_fares: Sequence[float]) -> bool:
    """True when fare is outside Tukey fences of a large enough payable peer set.

    The candidate is not part of peer_fares. A short peer list returns False:
    compute_tukey_bounds itself refuses to call that sample an outlier.
    """
    if len(peer_fares) < MIN_TUKEY_PEERS:
        return False
    bounds = compute_tukey_bounds(peer_fares, k=TUKEY_K)
    return fare < bounds.lower_bound or fare > bounds.upper_bound


def is_payable_status(flight_status: str | None) -> bool:
    """True unless the source reported cancelled or sold_out."""
    status = canonical_flight_status(flight_status)
    return status not in (FLIGHT_STATUS_CANCELLED, FLIGHT_STATUS_SOLD_OUT)


def is_index_eligible(flight_status: str | None, exclusion_reason: str | None) -> bool:
    """Payable, unflagged quotes are the only ones that may enter an index."""
    if exclusion_reason:
        return False
    return is_payable_status(flight_status)


def exclusion_for_fare(
    total_fare: float,
    flight_status: str | None,
    peer_fares: Sequence[float],
) -> str | None:
    """Reason the quote must stay out of the index, or None if it may enter.

    Non-payable status wins over the outlier test: a cancelled fare is not a
    price observation, so it is not used to decide whether another fare is extreme.
    """
    status = canonical_flight_status(flight_status)
    if status == FLIGHT_STATUS_CANCELLED:
        return EXCLUSION_CANCELLED
    if status == FLIGHT_STATUS_SOLD_OUT:
        return EXCLUSION_SOLD_OUT
    if outlier_against_peers(total_fare, peer_fares):
        return EXCLUSION_OUTLIER
    return None


def resolve_duration_minutes(
    supplied: int | None,
    departure: datetime | None,
    arrival: datetime | None,
) -> int | None:
    """Duration in minutes, or None when the departure clock is missing.

    A missing departure is not stored as 0 and is not filled with a default.
    A positive supplied duration is kept. Otherwise the span of the two clocks
    is used, and only when arrival is strictly later.
    """
    if departure is None:
        return None
    if supplied is not None and supplied > 0:
        return supplied
    if arrival is None or arrival <= departure:
        return None
    minutes = int((arrival - departure).total_seconds() // 60)
    if minutes <= 0:
        return None
    return minutes


def reported_flight_status(item: Mapping[str, _StatusValue]) -> str | None:
    """Status the source actually showed. Never invents scheduled.

    Only known tokens and explicit sold-out / cancelled booleans are accepted.
    An unrelated status string such as "available" stays None.
    """
    for key in _STATUS_TEXT_KEYS:
        raw = item.get(key)
        if isinstance(raw, str):
            canonical = canonical_flight_status(raw)
            if canonical in FLIGHT_STATUS_VALUES:
                return canonical
    for key in _SOLD_OUT_KEYS:
        if item.get(key) is True:
            return FLIGHT_STATUS_SOLD_OUT
    for key in _CANCELLED_KEYS:
        if item.get(key) is True:
            return FLIGHT_STATUS_CANCELLED
    raw_status = item.get("status")
    if not isinstance(raw_status, str):
        raw_status = item.get("Status")
    if isinstance(raw_status, str):
        canonical = canonical_flight_status(raw_status)
        if canonical in FLIGHT_STATUS_VALUES:
            return canonical
    return None


def sourced_duration_minutes(
    supplied: int | float | str | None,
    departure: str | None,
    arrival: str | None,
) -> int | None:
    """Duration from a source field, else from the two clocks. Never a default."""
    return resolve_duration_minutes(
        _positive_minutes(supplied),
        _parse_clock(departure),
        _parse_clock(arrival),
    )


def _positive_minutes(supplied: int | float | str | None) -> int | None:
    if supplied is None or isinstance(supplied, bool):
        return None
    if isinstance(supplied, str):
        token = supplied.strip()
        if token == "":
            return None
        try:
            parsed = float(token)
        except ValueError:
            return None
        if parsed <= 0:
            return None
        return int(parsed)
    if not isinstance(supplied, (int, float)) or supplied <= 0:
        return None
    return int(supplied)


def _parse_clock(value: str | None) -> datetime | None:
    if value is None or value.strip() == "":
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
