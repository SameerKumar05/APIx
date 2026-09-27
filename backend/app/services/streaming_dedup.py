"""APIx Real-Time Streaming Flight Deduplication Engine.

Provides high-throughput, sub-millisecond latency deduplication across multiple
OTA and airline direct booking portals. Implements sliding window buffering,
out-of-order arrival tolerance, LRU memory bounding, and deterministic hash fingerprinting
to resolve minimum consumer price across platforms in real time.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from backend.app.services.index_engine import (
    FlightQuote,
    _extract_field,
    _normalize_code,
    _normalize_date,
    _normalize_departure_time,
    _normalize_flight_number,
)

logger = logging.getLogger("apix.services.streaming_dedup")


def _parse_timestamp(raw_ts: Any) -> datetime | None:
    """Parse various timestamp representations into timezone-aware UTC datetime."""
    if raw_ts is None:
        return None
    if isinstance(raw_ts, datetime):
        if raw_ts.tzinfo is None:
            return raw_ts.replace(tzinfo=UTC)
        return raw_ts.astimezone(UTC)
    if isinstance(raw_ts, date):
        return datetime(raw_ts.year, raw_ts.month, raw_ts.day, tzinfo=UTC)
    if isinstance(raw_ts, (int, float)):
        # Epoch timestamp in seconds or milliseconds
        val = float(raw_ts)
        if val > 1e11:  # Milliseconds
            val /= 1000.0
        return datetime.fromtimestamp(val, tz=UTC)
    if isinstance(raw_ts, str):
        s = raw_ts.strip()
        if not s:
            return None
        # Handle trailing Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            pass
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC)
            except ValueError:
                continue
    return None


@dataclass
class FlightBufferState:
    """In-memory state of an active flight in the streaming deduplication buffer."""

    flight_key: str
    hash_id: str
    airline_code: str
    flight_number: str
    origin: str
    destination: str
    flight_date: str
    departure_time: str
    cabin_class: str
    quotes_by_portal: dict[str, FlightQuote] = field(default_factory=dict)
    min_fare: float = float("inf")
    best_quote: FlightQuote | None = None
    best_source_portal: str = "unknown"
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    latest_event_time: datetime | None = None
    total_quotes_received: int = 0

    def update_quote(
        self, quote: FlightQuote, arrival_dt: datetime
    ) -> tuple[bool, bool, float | None]:
        """Updates buffer with quote.

        Returns:
            (is_new_minimum, is_duplicate_price, previous_min_fare)
        """
        portal = quote.source_portal or "unknown"
        prev_min = self.min_fare if self.min_fare != float("inf") else None
        prev_quote_for_portal = self.quotes_by_portal.get(portal)

        is_duplicate = False
        if (
            prev_quote_for_portal is not None
            and abs(prev_quote_for_portal.fare - quote.fare) < 1e-6
        ):
            is_duplicate = True

        self.quotes_by_portal[portal] = quote
        self.last_updated_at = arrival_dt
        self.total_quotes_received += 1

        # Check latest event time
        event_dt = _parse_timestamp(
            quote.metadata.get("departure_datetime")
            or quote.metadata.get("booking_datetime")
        )
        if event_dt:
            if self.latest_event_time is None or event_dt > self.latest_event_time:
                self.latest_event_time = event_dt

        # Re-resolve minimum consumer price across platforms
        best_q: FlightQuote | None = None
        min_p = float("inf")

        for _p_name, q in self.quotes_by_portal.items():
            status = getattr(q, "flight_status", None)
            if status in ("cancelled", "sold_out"):
                continue
            if q.fare < min_p:
                min_p = q.fare
                best_q = q

        self.min_fare = min_p
        self.best_quote = best_q
        self.best_source_portal = (
            best_q.source_portal if best_q and best_q.source_portal else "unknown"
        )

        is_new_min = False
        if prev_min is None or (self.min_fare < prev_min - 1e-6):
            is_new_min = True

        return is_new_min, is_duplicate, prev_min

    def get_fare_spread(self) -> tuple[float | None, float | None]:
        """Calculates current fare spread (max - min) in INR and percentage across portals."""
        if (
            len(self.quotes_by_portal) <= 1
            or self.min_fare <= 0
            or self.min_fare == float("inf")
        ):
            return None, None
        max_fare = max(q.fare for q in self.quotes_by_portal.values())
        spread_inr = round(max_fare - self.min_fare, 2)
        spread_pct = round((spread_inr / self.min_fare) * 100.0, 4)
        return spread_inr, spread_pct

    def to_dict(self) -> dict[str, Any]:
        spread_inr, spread_pct = self.get_fare_spread()
        return {
            "flight_key": self.flight_key,
            "hash_id": self.hash_id,
            "airline_code": self.airline_code,
            "flight_number": self.flight_number,
            "origin": self.origin,
            "destination": self.destination,
            "flight_date": self.flight_date,
            "departure_time": self.departure_time,
            "cabin_class": self.cabin_class,
            "min_fare": self.min_fare if self.min_fare != float("inf") else 0.0,
            "best_source_portal": self.best_source_portal,
            "best_quote": self.best_quote.to_dict() if self.best_quote else None,
            "portal_count": len(self.quotes_by_portal),
            "portal_fares": {p: q.fare for p, q in self.quotes_by_portal.items()},
            "spread_inr": spread_inr,
            "spread_pct": spread_pct,
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_updated_at": self.last_updated_at.isoformat(),
            "total_quotes_received": self.total_quotes_received,
        }


@dataclass
class DedupResult:
    """Result emitted after processing an individual flight quote in real time."""

    flight_key: str
    hash_id: str
    is_new_flight: bool
    is_new_minimum: bool
    is_duplicate_price: bool
    min_fare: float
    best_quote: FlightQuote
    previous_min_fare: float | None
    portal_count: int
    current_portal: str
    current_fare: float
    latency_us: float
    spread_inr: float | None = None
    spread_pct: float | None = None
    portal_fares: dict[str, float] = field(default_factory=dict)
    out_of_order: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "flight_key": self.flight_key,
            "hash_id": self.hash_id,
            "is_new_flight": self.is_new_flight,
            "is_new_minimum": self.is_new_minimum,
            "is_duplicate_price": self.is_duplicate_price,
            "min_fare": self.min_fare,
            "best_quote": self.best_quote.to_dict() if self.best_quote else None,
            "previous_min_fare": self.previous_min_fare,
            "portal_count": self.portal_count,
            "current_portal": self.current_portal,
            "current_fare": self.current_fare,
            "latency_us": self.latency_us,
            "spread_inr": self.spread_inr,
            "spread_pct": self.spread_pct,
            "portal_fares": self.portal_fares,
            "out_of_order": self.out_of_order,
        }


class StreamingDedupEngine:
    """Real-time streaming flight deduplication engine.

    Buffers cross-portal fare quotes and resolves minimum consumer price across platforms
    in sub-millisecond latency. Supports sliding window retention, out-of-order timestamp
    tolerance, and strict LRU memory bounding.
    """

    def __init__(
        self,
        window_seconds: float = 300.0,
        max_buffer_size: int = 100_000,
        drop_stale_quotes: bool = False,
        auto_prune_interval: int = 500,
    ) -> None:
        """Initialize streaming deduplication engine.

        Args:
            window_seconds: Sliding window duration in seconds (default 300s = 5 min).
            max_buffer_size: Maximum active flights stored in buffer (LRU eviction).
            drop_stale_quotes: Whether to discard quotes older than window watermark.
            auto_prune_interval: Ingestion count interval between background window prunes.
        """
        self.window_seconds = float(window_seconds)
        self.max_buffer_size = int(max_buffer_size)
        self.drop_stale_quotes = bool(drop_stale_quotes)
        self.auto_prune_interval = int(auto_prune_interval)

        # In-memory buffer: OrderedDict for O(1) key lookup and LRU eviction
        # Mapping: flight_key -> FlightBufferState
        self._buffer: OrderedDict[str, FlightBufferState] = OrderedDict()
        # Mapping: hash_id -> flight_key
        self._hash_to_key: dict[str, str] = {}

        # Streaming metrics & statistics
        self._total_processed: int = 0
        self._duplicates_count: int = 0
        self._new_minima_count: int = 0
        self._lru_evictions_count: int = 0
        self._window_evictions_count: int = 0
        self._out_of_order_count: int = 0
        self._total_latency_ns: int = 0
        self._max_latency_ns: int = 0
        self._watermark_ts: datetime | None = None

    @staticmethod
    def generate_flight_key(
        item: FlightQuote | Mapping[str, Any] | Any,
    ) -> tuple[str, str]:
        """Generates deterministic canonical flight key and SHA-256 hash fingerprint.

        Canonical components:
            (airline_code, flight_number, origin, destination, flight_date, departure_time, cabin_class)

        Returns:
            Tuple of (canonical_flight_key, sha256_hash_id)
        """
        airline_code = _normalize_code(_extract_field(item, "airline_code"))
        raw_flight_num = _extract_field(item, "flight_number")
        flight_number = _normalize_flight_number(raw_flight_num, airline_code)
        origin = _normalize_code(_extract_field(item, "origin"))
        destination = _normalize_code(_extract_field(item, "destination"))
        flight_date = _normalize_date(_extract_field(item, "flight_date"))
        departure_time = _normalize_departure_time(
            _extract_field(item, "departure_time")
        )

        cabin_class = (
            str(_extract_field(item, "cabin_class", "economy")).strip().lower()
        )
        if not cabin_class:
            cabin_class = "economy"

        # If flight_date or departure_time missing, check departure_datetime
        dep_dt_raw = _extract_field(item, "departure_datetime")
        if dep_dt_raw:
            if not flight_date:
                flight_date = _normalize_date(dep_dt_raw)
            if not departure_time:
                departure_time = _normalize_departure_time(dep_dt_raw)

        canonical_key = f"{airline_code}:{flight_number}:{origin}:{destination}:{flight_date}:{departure_time}:{cabin_class}"
        hash_id = hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()
        return canonical_key, hash_id

    def _normalize_to_quote(
        self,
        item: FlightQuote | Mapping[str, Any] | Any,
    ) -> tuple[FlightQuote, str, str, str]:
        """Convert input item into normalized FlightQuote and extracted key components."""
        origin = _normalize_code(_extract_field(item, "origin"))
        destination = _normalize_code(_extract_field(item, "destination"))
        flight_date = _normalize_date(_extract_field(item, "flight_date"))
        airline_code = _normalize_code(_extract_field(item, "airline_code"))
        raw_flight_num = _extract_field(item, "flight_number")
        flight_number = _normalize_flight_number(raw_flight_num, airline_code)
        departure_time = _normalize_departure_time(
            _extract_field(item, "departure_time")
        )

        dep_dt_raw = _extract_field(item, "departure_datetime")
        if dep_dt_raw:
            if not flight_date:
                flight_date = _normalize_date(dep_dt_raw)
            if not departure_time:
                departure_time = _normalize_departure_time(dep_dt_raw)

        fare = float(_extract_field(item, "fare", 0.0))
        source_portal = str(_extract_field(item, "source_portal", "unknown"))
        booking_window = _extract_field(item, "booking_window", None)
        currency = str(_extract_field(item, "currency", "INR"))
        is_nonstop = bool(_extract_field(item, "is_nonstop", True))
        cabin_class = (
            str(_extract_field(item, "cabin_class", "economy")).strip().lower()
            or "economy"
        )

        metadata = _extract_field(item, "metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        if dep_dt_raw and "departure_datetime" not in metadata:
            metadata["departure_datetime"] = str(dep_dt_raw)
        b_dt_raw = _extract_field(item, "booking_datetime")
        if b_dt_raw and "booking_datetime" not in metadata:
            metadata["booking_datetime"] = str(b_dt_raw)

        canonical_key, hash_id = self.generate_flight_key(item)

        base_fare_val = _extract_field(item, "base_fare")
        base_fare = float(base_fare_val) if base_fare_val is not None else None
        taxes_and_fees_val = _extract_field(item, "taxes_and_fees")
        taxes_and_fees = (
            float(taxes_and_fees_val) if taxes_and_fees_val is not None else None
        )
        udf_fee_val = _extract_field(item, "udf_fee")
        udf_fee = float(udf_fee_val) if udf_fee_val is not None else None
        conv_fee_val = _extract_field(item, "convenience_fee")
        convenience_fee = float(conv_fee_val) if conv_fee_val is not None else None
        flight_status = _extract_field(item, "flight_status")
        fare_split_basis = _extract_field(item, "fare_split_basis")

        quote = FlightQuote(
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
            base_fare=base_fare,
            taxes_and_fees=taxes_and_fees,
            udf_fee=udf_fee,
            convenience_fee=convenience_fee,
            flight_status=flight_status,
            fare_split_basis=fare_split_basis,
            metadata=metadata,
        )
        return quote, canonical_key, hash_id, cabin_class

    def ingest(
        self,
        quote_input: FlightQuote | Mapping[str, Any] | Any,
        arrival_time: datetime | None = None,
    ) -> DedupResult:
        """Ingests a streaming flight fare quote and resolves minimum consumer price in sub-millisecond latency.

        Args:
            quote_input: Incoming raw flight quote (RawFareRecord, FlightQuote, dict, etc.).
            arrival_time: Optional timestamp when quote arrived at engine (defaults to now UTC).

        Returns:
            DedupResult containing deduplicated flight state, minimum consumer price, and latency.
        """
        start_ns = time.perf_counter_ns()
        now_utc = arrival_time or datetime.now(UTC)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=UTC)

        quote, flight_key, hash_id, cabin_class = self._normalize_to_quote(quote_input)

        # Check timestamp watermark and out-of-order arrival
        quote_ts = (
            _parse_timestamp(quote.metadata.get("booking_datetime"))
            or _parse_timestamp(quote.metadata.get("departure_datetime"))
            or now_utc
        )

        out_of_order = False
        if self._watermark_ts is not None:
            if quote_ts < self._watermark_ts:
                out_of_order = True
                self._out_of_order_count += 1
                # If configured to drop stale quotes older than the window
                if self.drop_stale_quotes:
                    age_seconds = (self._watermark_ts - quote_ts).total_seconds()
                    if age_seconds > self.window_seconds:
                        # Stale quote outside sliding window
                        elapsed_ns = time.perf_counter_ns() - start_ns
                        return DedupResult(
                            flight_key=flight_key,
                            hash_id=hash_id,
                            is_new_flight=False,
                            is_new_minimum=False,
                            is_duplicate_price=False,
                            min_fare=0.0,
                            best_quote=quote,
                            previous_min_fare=None,
                            portal_count=0,
                            current_portal=quote.source_portal or "unknown",
                            current_fare=quote.fare,
                            latency_us=round(elapsed_ns / 1000.0, 3),
                            out_of_order=True,
                        )
            elif quote_ts > self._watermark_ts:
                self._watermark_ts = quote_ts
        else:
            self._watermark_ts = quote_ts

        # Retrieve or initialize flight buffer state
        is_new_flight = False
        state = self._buffer.get(flight_key)

        if state is None:
            is_new_flight = True
            state = FlightBufferState(
                flight_key=flight_key,
                hash_id=hash_id,
                airline_code=quote.airline_code,
                flight_number=quote.flight_number,
                origin=quote.origin,
                destination=quote.destination,
                flight_date=quote.flight_date,
                departure_time=quote.departure_time,
                cabin_class=cabin_class,
                first_seen_at=now_utc,
                last_updated_at=now_utc,
            )
            self._buffer[flight_key] = state
            self._hash_to_key[hash_id] = flight_key
        else:
            # Move to end of OrderedDict for LRU tracking
            self._buffer.move_to_end(flight_key)

        # Update flight state with new portal quote
        is_new_min, is_duplicate, prev_min = state.update_quote(quote, now_utc)

        if is_duplicate:
            self._duplicates_count += 1
        if is_new_min:
            self._new_minima_count += 1

        self._total_processed += 1

        # Periodic sliding window pruning
        if self._total_processed % self.auto_prune_interval == 0:
            self.prune_expired(now_utc)

        # Memory bounding: Evict LRU items if capacity exceeded
        if len(self._buffer) > self.max_buffer_size:
            self._evict_lru(len(self._buffer) - self.max_buffer_size)

        spread_inr, spread_pct = state.get_fare_spread()
        elapsed_ns = time.perf_counter_ns() - start_ns
        self._total_latency_ns += elapsed_ns
        if elapsed_ns > self._max_latency_ns:
            self._max_latency_ns = elapsed_ns

        latency_us = round(elapsed_ns / 1000.0, 3)

        return DedupResult(
            flight_key=flight_key,
            hash_id=hash_id,
            is_new_flight=is_new_flight,
            is_new_minimum=is_new_min,
            is_duplicate_price=is_duplicate,
            min_fare=state.min_fare,
            best_quote=state.best_quote or quote,
            previous_min_fare=prev_min,
            portal_count=len(state.quotes_by_portal),
            current_portal=quote.source_portal or "unknown",
            current_fare=quote.fare,
            latency_us=latency_us,
            spread_inr=spread_inr,
            spread_pct=spread_pct,
            portal_fares={p: q.fare for p, q in state.quotes_by_portal.items()},
            out_of_order=out_of_order,
        )

    def ingest_batch(
        self,
        quotes: Iterable[FlightQuote | Mapping[str, Any] | Any],
    ) -> list[DedupResult]:
        """Ingests a sequence/batch of streaming flight quotes in sequence.

        Returns:
            List of DedupResult objects corresponding to each quote.
        """
        results: list[DedupResult] = []
        for q in quotes:
            results.append(self.ingest(q))
        return results

    def get_best_quote(self, flight_key: str) -> FlightQuote | None:
        """Returns the current best (minimum consumer price) FlightQuote for a flight key."""
        state = self._buffer.get(flight_key)
        return state.best_quote if state else None

    def get_best_quote_by_hash(self, hash_id: str) -> FlightQuote | None:
        """Returns the current best FlightQuote for a given SHA-256 hash fingerprint."""
        flight_key = self._hash_to_key.get(hash_id)
        if not flight_key:
            return None
        return self.get_best_quote(flight_key)

    def get_flight_state(self, flight_key: str) -> FlightBufferState | None:
        """Returns the internal FlightBufferState for a flight key."""
        return self._buffer.get(flight_key)

    def get_all_resolved_quotes(self) -> list[FlightQuote]:
        """Returns a snapshot of all canonical deduplicated quotes currently in buffer."""
        resolved: list[FlightQuote] = []
        for state in self._buffer.values():
            if state.best_quote is not None:
                resolved.append(state.best_quote)
        return resolved

    def prune_expired(self, current_time: datetime | None = None) -> int:
        """Evicts expired records whose last update age exceeds window_seconds.

        Args:
            current_time: Reference timestamp (default now UTC).

        Returns:
            Number of flight records evicted from buffer.
        """
        now_utc = current_time or datetime.now(UTC)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=UTC)

        cutoff_seconds = self.window_seconds
        keys_to_remove: list[str] = []

        for key, state in self._buffer.items():
            age = (now_utc - state.last_updated_at).total_seconds()
            if age > cutoff_seconds:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            if key not in self._buffer:
                continue
            state = self._buffer.pop(key)
            if state:
                self._hash_to_key.pop(state.hash_id, None)
                self._window_evictions_count += 1

        return len(keys_to_remove)

    def _evict_lru(self, count: int) -> int:
        """Evicts oldest accessed/updated flight records to enforce max_buffer_size limit."""
        evicted = 0
        while (
            self._buffer
            and len(self._buffer) > self.max_buffer_size
            and evicted < count
        ):
            # popitem(last=False) pops the oldest (least recently used) item
            _key, state = self._buffer.popitem(last=False)
            self._hash_to_key.pop(state.hash_id, None)
            self._lru_evictions_count += 1
            evicted += 1
        return evicted

    def clear(self) -> None:
        """Clears all buffered flight state and resets statistics."""
        self._buffer.clear()
        self._hash_to_key.clear()
        self._total_processed = 0
        self._duplicates_count = 0
        self._new_minima_count = 0
        self._lru_evictions_count = 0
        self._window_evictions_count = 0
        self._out_of_order_count = 0
        self._total_latency_ns = 0
        self._max_latency_ns = 0
        self._watermark_ts = None

    def stats(self) -> dict[str, Any]:
        """Returns operational metrics and latency statistics of the deduplication engine."""
        avg_latency_us = 0.0
        if self._total_processed > 0:
            avg_latency_us = round(
                (self._total_latency_ns / self._total_processed) / 1000.0, 3
            )

        return {
            "total_processed": self._total_processed,
            "active_buffer_size": len(self._buffer),
            "duplicates_count": self._duplicates_count,
            "new_minima_count": self._new_minima_count,
            "lru_evictions_count": self._lru_evictions_count,
            "window_evictions_count": self._window_evictions_count,
            "out_of_order_count": self._out_of_order_count,
            "avg_latency_us": avg_latency_us,
            "max_latency_us": round(self._max_latency_ns / 1000.0, 3),
            "sub_millisecond_compliant": avg_latency_us < 1000.0,
            "window_seconds": self.window_seconds,
            "max_buffer_size": self.max_buffer_size,
        }
