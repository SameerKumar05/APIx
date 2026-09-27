"""Shared browser scrape for a PS-named airline or OTA portal.

Consults robots_gate before any request. A denial, HTTP 403, or captcha is the
outcome: zero live records and an explicit reason. A page with no readable fare
is the same shape of outcome. Synthetic fallback, when used, stays labelled.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ingestion.base import BaseScraper, RawFareRecord, ScrapeResult
from ingestion.config import (
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    BookingWindow,
    IngestionConfig,
    Route,
)
from ingestion.crawlers.amadeus import AmadeusFlightClient
from ingestion.crawlers.portal_browser import read_search_payloads
from ingestion.crawlers.portal_parse import parse_portal_flights
from ingestion.crawlers.synthetic import SyntheticFlightGenerator

logger = logging.getLogger("ingestion.crawlers.portal")

PAGE_YIELDED_NO_FARE = "page yielded no fare"


class PortalScraper(BaseScraper):
    """One PS portal. Subclasses supply the search URL and API path patterns."""

    BASE_URL = ""
    SOURCE_NAME = ""
    SOURCE_TYPE = ""
    AIRLINE_CODE: str | None = None
    API_URL_PATTERNS: tuple[str, ...] = ()
    API_REJECT_PATTERNS: tuple[str, ...] = (
        r"getStationDetails",
        r"getAllCities",
        r"stationsFullName",
        r"metaInfo",
        r"featureconfig",
    )

    def __init__(
        self,
        config: IngestionConfig | None = None,
        amadeus_client: AmadeusFlightClient | None = None,
        synthetic_generator: SyntheticFlightGenerator | None = None,
        proxy: str | dict[str, str] | None = None,
    ) -> None:
        super().__init__(config)
        self.proxy = proxy or getattr(self.config, "proxy_url", None)
        self.amadeus_client = amadeus_client or AmadeusFlightClient(config=self.config)
        self.synthetic_generator = synthetic_generator or SyntheticFlightGenerator(
            config=self.config
        )
        self.live_block_reason: str | None = None

    def build_search_url(
        self,
        origin: str,
        destination: str,
        flight_date: date,
        adults: int = 1,
    ) -> str:
        """Subclasses build the public search URL for this portal."""
        raise NotImplementedError

    def is_flight_api_url(self, url: str) -> bool:
        """True when an intercepted response is a flight-availability body."""
        if any(re.search(pat, url, re.IGNORECASE) for pat in self.API_REJECT_PATTERNS):
            return False
        return any(re.search(pat, url, re.IGNORECASE) for pat in self.API_URL_PATTERNS)

    def parse_flight_json(
        self,
        payload: dict[str, Any],
        origin: str,
        destination: str,
        window_code: str,
        capture_dt: datetime | None = None,
    ) -> list[RawFareRecord]:
        """Parse a response. is_synthetic stays False only when a fare was read."""
        return parse_portal_flights(
            self,
            payload,
            origin,
            destination,
            window_code,
            self.SOURCE_NAME,
            self.AIRLINE_CODE,
            capture_dt,
        )

    def _read_search_payloads(
        self, search_url: str
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Open the search URL. A 403 or captcha comes back as a reason, not a fare."""
        return read_search_payloads(self, search_url)

    def _scrape_with_playwright(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
    ) -> list[RawFareRecord]:
        """Fetch one route. robots_gate runs before the browser is launched."""
        self.live_block_reason = None
        search_url = self.build_search_url(origin, destination, target_date)
        denial = self.robots_gate(search_url)
        if denial is not None:
            self.live_block_reason = denial
            logger.warning("robots.txt blocked %s scrape: %s", self.BASE_URL, denial)
            return []
        try:
            payloads, fetch_reason = self._read_search_payloads(search_url)
        except OSError as exc:
            self.live_block_reason = f"browser error for {search_url}: {exc}"
            return []
        if fetch_reason:
            self.live_block_reason = fetch_reason
            return []
        capture_time = datetime.now(UTC)
        records: list[RawFareRecord] = []
        for payload in payloads:
            records.extend(
                self.parse_flight_json(
                    payload, origin, destination, window_code, capture_time
                )
            )
        if not records:
            self.live_block_reason = PAGE_YIELDED_NO_FARE
        return records

    def collect_live(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
    ) -> ScrapeResult:
        """Live tier only. Zero records carry the reason. No synthetic fill-in."""
        started = time.time()
        records = self._scrape_with_playwright(
            origin, destination, target_date, window_code
        )
        reason = self.live_block_reason
        errors = [reason] if reason and not records else []
        return ScrapeResult(
            source=self.SOURCE_NAME,
            success=bool(records),
            records=records,
            errors=errors,
            duration_ms=round((time.time() - started) * 1000, 2),
            metadata={
                "tier": 1,
                "live": True,
                "reason": reason,
                "source": self.SOURCE_NAME,
            },
        )

    def _label_synthetic(self, record: RawFareRecord) -> RawFareRecord:
        airline = record.airline_code
        flight_number = record.flight_number
        if self.AIRLINE_CODE and airline != self.AIRLINE_CODE:
            airline = self.AIRLINE_CODE
            suffix = flight_number.split("-")[-1]
            digits = "".join(ch for ch in suffix if ch.isdigit())
            if digits:
                flight_number = f"{airline}-{digits}"
        return RawFareRecord(
            airline_code=airline,
            flight_number=flight_number,
            origin=record.origin,
            destination=record.destination,
            departure_datetime=record.departure_datetime,
            arrival_datetime=record.arrival_datetime,
            booking_datetime=record.booking_datetime,
            fare_inr=record.fare_inr,
            cabin_class=record.cabin_class,
            stops=record.stops,
            source=self.SOURCE_NAME,
            booking_window=record.booking_window,
            flight_date=record.flight_date,
            duration_minutes=record.duration_minutes,
            base_fare=record.base_fare,
            taxes_and_fees=record.taxes_and_fees,
            flight_status=record.flight_status,
            is_synthetic=True,
            source_platform=self.SOURCE_NAME,
        )

    def _synthetic_fallback(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
    ) -> ScrapeResult:
        generated = self.synthetic_generator.scrape_route(
            origin, destination, target_date, window_code
        )
        labelled = [self._label_synthetic(record) for record in generated.records]
        return ScrapeResult(
            source=self.SOURCE_NAME,
            success=bool(labelled),
            records=labelled,
            errors=list(generated.errors),
            duration_ms=generated.duration_ms,
            metadata={
                "tier": 3,
                "source": f"{self.SOURCE_NAME}_tier3_synthetic",
                "records_count": len(labelled),
            },
        )

    def scrape_route(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
    ) -> ScrapeResult:
        """Live search, then labelled Amadeus, then labelled synthetic."""
        started = time.time()
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        mode = self.config.ingestion_mode.lower()
        if mode == "synthetic":
            result = self._synthetic_fallback(
                norm_orig, norm_dest, target_date, window_code
            )
            result.metadata["tier"] = 3
            return result
        if mode == "mock":
            amadeus = self.amadeus_client.scrape_route(
                norm_orig, norm_dest, target_date, window_code
            )
            if amadeus.success and amadeus.records:
                amadeus.metadata["tier"] = 2
                amadeus.metadata["source"] = f"{self.SOURCE_NAME}_tier2_amadeus_mock"
                return amadeus
            result = self._synthetic_fallback(
                norm_orig, norm_dest, target_date, window_code
            )
            result.metadata["tier"] = 3
            return result

        live = self.collect_live(norm_orig, norm_dest, target_date, window_code)
        if live.records:
            live.duration_ms = round((time.time() - started) * 1000, 2)
            return live
        tier1_errors = list(live.errors)
        try:
            amadeus = self.amadeus_client.scrape_route(
                norm_orig, norm_dest, target_date, window_code
            )
        except (OSError, ValueError, RuntimeError) as exc:
            amadeus = ScrapeResult(
                source="amadeus", success=False, records=[], errors=[str(exc)]
            )
        if amadeus.success and amadeus.records:
            amadeus.metadata["tier"] = 2
            amadeus.metadata["tier1_errors"] = tier1_errors
            amadeus.errors = tier1_errors + list(amadeus.errors)
            amadeus.duration_ms = round((time.time() - started) * 1000, 2)
            return amadeus
        fallback = self._synthetic_fallback(
            norm_orig, norm_dest, target_date, window_code
        )
        fallback.errors = tier1_errors + list(fallback.errors)
        fallback.metadata["tier1_errors"] = tier1_errors
        fallback.duration_ms = round((time.time() - started) * 1000, 2)
        return fallback

    def scrape_all(
        self,
        routes: list[Route] | None = None,
        windows: list[BookingWindow] | None = None,
    ) -> list[ScrapeResult]:
        """Scrape every configured route and booking window."""
        target_routes = routes or DEFAULT_ROUTES
        target_windows = windows or BOOKING_WINDOWS
        today = date.today()
        results: list[ScrapeResult] = []
        for route in target_routes:
            for window in target_windows:
                target_date = today + timedelta(days=window.days_advance)
                results.append(
                    self.scrape_route(
                        route.origin, route.destination, target_date, window.code
                    )
                )
        return results
