"""Deterministic DGCA-calibrated synthetic flight fare generator.

Generates realistic flight schedules, airline allocations according to DGCA domestic
market share, and dynamic pricing curves across all 40 route-window combinations
(10 top routes x 4 booking windows: T+1, T+7, T+15, T+30).
"""

from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ingestion.base import BaseScraper, RawFareRecord, ScrapeResult
from ingestion.config import (
    AIRLINE_MAP,
    AIRLINES,
    BOOKING_WINDOW_MAP,
    BOOKING_WINDOWS,
    BookingWindow,
    DEFAULT_ROUTES,
    IngestionConfig,
    Route,
    VALID_AIRLINE_CODES,
    VALID_IATA_CODES,
)

logger = logging.getLogger("ingestion.crawlers.synthetic")

# Typical daily flight departures for domestic trunk routes (hour, minute, is_peak)
SCHEDULE_SLOTS = [
    (6, 0, True),    # Early morning business departure (Peak)
    (7, 15, True),   # Morning rush (Peak)
    (8, 45, True),   # Morning business (Peak)
    (11, 20, False), # Mid-day off-peak
    (14, 10, False), # Afternoon off-peak
    (17, 30, True),  # Evening rush (Peak)
    (19, 15, True),  # Evening rush (Peak)
    (21, 40, False), # Late evening off-peak
]

# Flight number prefixes and ranges by airline
AIRLINE_FLIGHT_PREFIXES: Dict[str, Tuple[int, int]] = {
    "6E": (100, 999),    # e.g. 6E-205, 6E-532
    "AI": (101, 899),    # e.g. AI-804, AI-665
    "IX": (1100, 2900),  # e.g. IX-1132
    "QP": (1301, 1999),  # e.g. QP-1304
    "SG": (8100, 8900),  # e.g. SG-8114
}


class SyntheticFlightGenerator(BaseScraper):
    """Deterministic DGCA-calibrated synthetic flight fare generator.

    Produces realistic schedules, market share distribution, and dynamic
    pricing curves for airfare price index benchmarking.
    """

    def __init__(
        self,
        config: Optional[IngestionConfig] = None,
        seed: int = 42,
    ) -> None:
        super().__init__(config)
        self.seed = seed
        self._rng = random.Random(seed)

    def set_seed(self, seed: int) -> None:
        """Reset the deterministic RNG seed."""
        self.seed = seed
        self._rng = random.Random(seed)

    def _pick_airline(self, rng: random.Random) -> str:
        """Select an airline weighted by calibrated DGCA domestic market share."""
        # IndiGo: 60%, Air India: 15%, Akasa: 10%, AI Express: 10%, SpiceJet: 5%
        r = rng.random()
        cumulative = 0.0
        for airline in AIRLINES:
            cumulative += airline.market_share
            if r <= cumulative:
                return airline.code
        return "6E"

    def _generate_flight_number(self, airline_code: str, rng: random.Random) -> str:
        """Generate a realistic flight designator (e.g. 6E-204, AI-805)."""
        min_num, max_num = AIRLINE_FLIGHT_PREFIXES.get(airline_code, (100, 999))
        num = rng.randint(min_num, max_num)
        return f"{airline_code}-{num}"

    def calculate_calibrated_fare(
        self,
        distance_km: int,
        window: BookingWindow,
        airline_code: str,
        is_peak: bool,
        rng: random.Random,
    ) -> float:
        """Calculates DGCA-calibrated domestic airfare based on economic models.

        Base Fare Formula:
          base_fare = (distance_km * rate_per_km + airport_charges)
                      * window_multiplier
                      * peak_multiplier
                      * airline_factor
                      * random_noise (±3%)
        """
        airline = AIRLINE_MAP.get(airline_code)
        airline_factor = airline.base_price_factor if airline else 1.0

        # DGCA baseline economy rate per km in India: ~Rs. 3.20 - 3.80 / km
        rate_per_km = 3.50 + rng.uniform(-0.15, 0.15)

        # Fixed airport development fees (UDF/PSF) and security: ~Rs. 950
        fixed_airport_fee = 950.0 + rng.uniform(-50.0, 50.0)

        # Baseline distance fare
        baseline = (distance_km * rate_per_km) + fixed_airport_fee

        # Advance booking window multiplier (T+1 highest, T+30 baseline)
        window_mult = window.price_multiplier * rng.uniform(0.97, 1.03)

        # Time of day peak vs off-peak
        peak_mult = 1.15 if is_peak else 0.92

        # Combine multipliers
        total = baseline * window_mult * peak_mult * airline_factor

        # Round to nearest Rs. 10
        fare = round(total / 10.0) * 10.0

        # Ensure reasonable domestic fare bounds (Rs. 2,000 to Rs. 28,000)
        fare = max(2100.0, min(fare, 28000.0))
        return float(fare)

    def generate_slot(
        self,
        route: Route,
        window: BookingWindow,
        capture_time: Optional[datetime] = None,
    ) -> ScrapeResult:
        """Generates flight fare records for a single (Route, BookingWindow) slot.

        Deterministic given the generator seed, route, and window code.
        """
        capture_dt = capture_time or datetime(2026, 9, 24, 6, 0, 0)
        # Booking date is advance days from capture date
        flight_dt_date = (capture_dt + timedelta(days=window.days_advance)).date()

        # Slot-specific deterministic RNG derived from master seed + slot identifiers
        slot_seed = hash((self.seed, route.pair_key, window.code)) & 0xFFFFFFFF
        slot_rng = random.Random(slot_seed)

        # 4 to 7 flights per slot to represent high-frequency trunk route schedule
        flight_count = slot_rng.randint(4, 7)
        sampled_slots = slot_rng.sample(SCHEDULE_SLOTS, flight_count)
        sampled_slots.sort(key=lambda s: (s[0], s[1]))

        records: List[RawFareRecord] = []
        errors: List[str] = []

        for hour, minute, is_peak in sampled_slots:
            airline_code = self._pick_airline(slot_rng)
            flight_number = self._generate_flight_number(airline_code, slot_rng)

            # Departure datetime on flight_dt_date
            dep_dt = datetime(flight_dt_date.year, flight_dt_date.month, flight_dt_date.day, hour, minute, 0)

            # Duration: typical route duration ± up to 10 minutes jitter
            duration_minutes = route.typical_duration_min + slot_rng.randint(-5, 10)
            arr_dt = dep_dt + timedelta(minutes=duration_minutes)

            # Calculate fare
            fare_inr = self.calculate_calibrated_fare(
                distance_km=route.distance_km,
                window=window,
                airline_code=airline_code,
                is_peak=is_peak,
                rng=slot_rng,
            )

            record = RawFareRecord(
                airline_code=airline_code,
                flight_number=flight_number,
                origin=route.origin,
                destination=route.destination,
                departure_datetime=dep_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                arrival_datetime=arr_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                booking_datetime=capture_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                fare_inr=fare_inr,
                cabin_class="economy",
                stops=0,  # All selected trunk routes are non-stop direct flights
                source="synthetic",
                booking_window=window.code,
                flight_date=flight_dt_date.isoformat(),
                duration_minutes=duration_minutes,
                is_synthetic=True,
                source_platform="synthetic_dgca",
            )

            # Validate against strict schema
            is_valid, validation_errors = self.validate_record(
                record,
                allowed_origins=VALID_IATA_CODES,
                allowed_destinations=VALID_IATA_CODES,
                allowed_airlines=VALID_AIRLINE_CODES,
            )
            if not is_valid:
                errors.extend(validation_errors)

            records.append(record)

        return ScrapeResult(
            source="synthetic",
            success=len(errors) == 0,
            records=records,
            errors=errors,
            duration_ms=1.5,
            metadata={
                "route": route.pair_key,
                "window": window.code,
                "advance_days": window.days_advance,
                "flight_count": len(records),
            },
        )

    def generate_all_slots(
        self,
        routes: Optional[List[Route]] = None,
        windows: Optional[List[BookingWindow]] = None,
        capture_time: Optional[datetime] = None,
    ) -> List[ScrapeResult]:
        """Generates all 40 route-window slots (10 routes x 4 booking windows).

        Returns exactly 40 ScrapeResult objects.
        """
        target_routes = routes or DEFAULT_ROUTES
        target_windows = windows or BOOKING_WINDOWS

        slots: List[ScrapeResult] = []
        for route in target_routes:
            for window in target_windows:
                slot_result = self.generate_slot(route, window, capture_time=capture_time)
                slots.append(slot_result)

        logger.info(
            "Generated %d synthetic slots (%d routes x %d windows)",
            len(slots),
            len(target_routes),
            len(target_windows),
        )
        return slots

    def generate_all_records(
        self,
        routes: Optional[List[Route]] = None,
        windows: Optional[List[BookingWindow]] = None,
        capture_time: Optional[datetime] = None,
    ) -> List[RawFareRecord]:
        """Generates and flattens all records across the 40 slots."""
        slots = self.generate_all_slots(routes, windows, capture_time=capture_time)
        all_records: List[RawFareRecord] = []
        for slot in slots:
            all_records.extend(slot.records)
        return all_records

    def scrape_route(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
    ) -> ScrapeResult:
        """Implements BaseScraper.scrape_route for synthetic crawler."""
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)

        # Locate route definition
        matched_route = next(
            (r for r in DEFAULT_ROUTES if r.origin == norm_orig and r.destination == norm_dest),
            None,
        )
        if not matched_route:
            matched_route = Route(
                origin=norm_orig,
                destination=norm_dest,
                distance_km=1200,
                typical_duration_min=130,
                dgca_weight=0.10,
            )

        matched_window = BOOKING_WINDOW_MAP.get(window_code, BOOKING_WINDOWS[0])
        capture_dt = datetime.combine(target_date - timedelta(days=matched_window.days_advance), datetime.min.time())
        return self.generate_slot(matched_route, matched_window, capture_time=capture_dt)

    def scrape_all(
        self,
        routes: Optional[List[Route]] = None,
        windows: Optional[List[BookingWindow]] = None,
    ) -> List[ScrapeResult]:
        """Implements BaseScraper.scrape_all for synthetic crawler."""
        return self.generate_all_slots(routes=routes, windows=windows)

    def generate_40_route_window_records(
        self,
        routes: Optional[List[Route]] = None,
        windows: Optional[List[BookingWindow]] = None,
        capture_time: Optional[datetime] = None,
    ) -> List[RawFareRecord]:
        """Generates exactly 40 synthetic route-window fare records (1 per route-window slot)."""
        target_routes = routes or DEFAULT_ROUTES
        target_windows = windows or BOOKING_WINDOWS
        records: List[RawFareRecord] = []
        for route in target_routes:
            for window in target_windows:
                slot_result = self.generate_slot(route, window, capture_time=capture_time)
                if slot_result.records:
                    records.append(slot_result.records[0])
        return records


# Canonical alias for crawler nomenclature
SyntheticCrawler = SyntheticFlightGenerator
