"""Shared fare JSON parsing for PS portal scrapers.

A record is emitted only when a fare, a flight number, and both timestamps
were read from the payload. A missing fare is skipped. Nothing here substitutes
a number.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from backend.app.core.cleaning import reported_flight_status, sourced_duration_minutes
from ingestion.base import BaseScraper, RawFareRecord

logger = logging.getLogger("ingestion.crawlers.portal_parse")

FARE_KEYS: tuple[str, ...] = (
    "totalFare",
    "TotalFare",
    "fare",
    "Fare",
    "price",
    "grossFare",
    "GrossFare",
    "totalAmount",
    "fare_inr",
    "totalPrice",
    "amount",
    "tf",
)
FLIGHT_NUMBER_KEYS: tuple[str, ...] = (
    "flightNumber",
    "flightNo",
    "FlightNo",
    "fn",
)
AIRLINE_KEYS: tuple[str, ...] = (
    "airlineCode",
    "carrierCode",
    "carrier",
    "AirlineCode",
    "ac",
)
DEPARTURE_KEYS: tuple[str, ...] = (
    "departureTime",
    "depTime",
    "departureDateTime",
    "DepTime",
    "dt",
)
ARRIVAL_KEYS: tuple[str, ...] = (
    "arrivalTime",
    "arrTime",
    "arrivalDateTime",
    "ArrTime",
    "at",
)


def _first_present(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _read_fare(item: dict[str, Any]) -> float | None:
    """Return a fare read from this object, or None. Never invents one."""
    for key in FARE_KEYS:
        if key not in item or item[key] in (None, ""):
            continue
        try:
            return BaseScraper.normalize_fare(item[key])
        except ValueError:
            continue
    nested = item.get("fares")
    if isinstance(nested, list) and nested and isinstance(nested[0], dict):
        found = _read_fare(nested[0])
        if found is not None:
            return found
    details = item.get("fareDetails")
    if isinstance(details, dict):
        return _read_fare(details)
    return None


def flight_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull flight dicts out of the shapes Indian portal APIs actually return."""
    if not isinstance(payload, dict):
        return []
    direct_keys = ("flights", "journeys", "FlightDetails", "availability", "results")
    for key in direct_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("flights", "journeys", "availability"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    trips = payload.get("trips")
    if isinstance(trips, list):
        found: list[dict[str, Any]] = []
        for trip in trips:
            if not isinstance(trip, dict):
                continue
            journeys = trip.get("journeys") or trip.get("journeyList") or []
            if isinstance(journeys, list):
                found.extend(item for item in journeys if isinstance(item, dict))
        return found
    air = payload.get("AirSearchResult")
    if isinstance(air, dict):
        details = air.get("FlightDetails")
        if isinstance(details, list):
            return [item for item in details if isinstance(item, dict)]
    return []


def _flight_number(item: dict[str, Any], segments: list[Any]) -> str | None:
    first = segments[0] if segments and isinstance(segments[0], dict) else item
    raw = _first_present(first, FLIGHT_NUMBER_KEYS)
    if raw is None:
        raw = _first_present(item, FLIGHT_NUMBER_KEYS)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _airline_code(
    item: dict[str, Any], segments: list[Any], fallback: str | None
) -> str | None:
    first = segments[0] if segments and isinstance(segments[0], dict) else item
    raw = (
        _first_present(first, AIRLINE_KEYS)
        or _first_present(item, AIRLINE_KEYS)
        or fallback
    )
    if raw is None:
        return None
    try:
        return BaseScraper.normalize_airline_code(str(raw))
    except ValueError:
        return None


def parse_portal_flights(
    scraper: BaseScraper,
    payload: dict[str, Any],
    origin: str,
    destination: str,
    window_code: str,
    source_name: str,
    airline_fallback: str | None,
    capture_dt: datetime | None = None,
) -> list[RawFareRecord]:
    """Parse one JSON body. is_synthetic is False only because a fare was read."""
    records: list[RawFareRecord] = []
    capture_time = capture_dt or datetime.now(UTC)
    booking_dt_str = capture_time.strftime("%Y-%m-%dT%H:%M:%S")
    norm_origin = scraper.normalize_iata(origin)
    norm_dest = scraper.normalize_iata(destination)

    for item in flight_items(payload):
        segments = (
            item.get("segments") if isinstance(item.get("segments"), list) else []
        )
        first = segments[0] if segments and isinstance(segments[0], dict) else item
        fare_inr = _read_fare(item)
        if fare_inr is None and isinstance(first, dict):
            fare_inr = _read_fare(first)
        if fare_inr is None:
            continue
        seg_list: list[Any] = list(segments) if isinstance(segments, list) else []
        flight_no_raw = _flight_number(item, seg_list)
        airline_code = _airline_code(item, seg_list, airline_fallback)
        if flight_no_raw is None or airline_code is None:
            continue
        clean_num = flight_no_raw
        if clean_num.upper().startswith(airline_code):
            clean_num = clean_num[len(airline_code) :].lstrip("- ")
        else:
            clean_num = re.sub(r"^[A-Za-z]{2}[-\s]?", "", clean_num)
        clean_num = clean_num.strip()
        if not clean_num:
            continue
        full_flight_no = (
            clean_num
            if clean_num.upper().startswith(f"{airline_code}-")
            else f"{airline_code}-{clean_num}"
        )
        dep_raw = (
            _first_present(first, DEPARTURE_KEYS) if isinstance(first, dict) else None
        )
        if dep_raw is None:
            dep_raw = _first_present(item, DEPARTURE_KEYS)
        last = segments[-1] if segments and isinstance(segments[-1], dict) else first
        arr_raw = _first_present(last, ARRIVAL_KEYS) if isinstance(last, dict) else None
        if arr_raw is None:
            arr_raw = _first_present(item, ARRIVAL_KEYS)
        if not dep_raw or not arr_raw:
            continue
        dep_dt_str = scraper.normalize_datetime(dep_raw)
        arr_dt_str = scraper.normalize_datetime(arr_raw)
        duration = sourced_duration_minutes(
            item.get("duration") or item.get("durationMinutes") or item.get("Duration"),
            dep_dt_str,
            arr_dt_str,
        )
        stops_raw = item.get(
            "stops", item.get("Stops", len(segments) - 1 if segments else 0)
        )
        try:
            stops = int(stops_raw)
        except (TypeError, ValueError):
            stops = 0
        if stops < 0:
            stops = 0
        record = RawFareRecord(
            airline_code=airline_code,
            flight_number=full_flight_no,
            origin=norm_origin,
            destination=norm_dest,
            departure_datetime=dep_dt_str,
            arrival_datetime=arr_dt_str,
            booking_datetime=booking_dt_str,
            fare_inr=fare_inr,
            cabin_class="economy",
            stops=stops,
            source=source_name,
            booking_window=window_code,
            flight_date=dep_dt_str.split("T")[0],
            duration_minutes=duration,
            flight_status=reported_flight_status(item),
            is_synthetic=False,
            source_platform=source_name,
        )
        is_valid, validation_errors = scraper.validate_record(record)
        if is_valid:
            records.append(record)
        else:
            logger.debug(
                "Skipping invalid %s record: %s", source_name, validation_errors
            )
    return records
