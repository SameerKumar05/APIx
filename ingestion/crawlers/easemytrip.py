"""EaseMyTrip scraper module with Playwright stealth options and XHR response interception.

Implements browser evasion strategies (navigator.webdriver cloaking, randomized viewports,
header rotation) and network-level XHR response interception to capture structured JSON
flight pricing payloads directly from backend APIs.
"""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from ingestion.base import BaseScraper, RawFareRecord, ScrapeResult
from ingestion.config import (
    BOOKING_WINDOW_MAP,
    BookingWindow,
    DEFAULT_ROUTES,
    IngestionConfig,
    Route,
    VALID_AIRLINE_CODES,
    VALID_IATA_CODES,
)

logger = logging.getLogger("ingestion.crawlers.easemytrip")

# Standard desktop viewports for randomized fingerprinting
STEALTH_VIEWPORTS: List[Dict[str, int]] = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
]

# Playwright browser stealth launch arguments
PLAYWRIGHT_STEALTH_ARGS: List[str] = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-infobars",
    "--window-position=0,0",
    "--ignore-certifcate-errors",
    "--ignore-certifcate-errors-spki-list",
    "--disable-dev-shm-usage",
    "--disable-accelerated-2d-canvas",
    "--disable-gpu",
    "--lang=en-US,en;q=0.9",
]

# Client-side JavaScript injected into every new page context before scripts execute
STEALTH_INIT_SCRIPT = """
// 1. Evade navigator.webdriver detection
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
});

// 2. Mock Chrome runtime
window.chrome = {
    app: {
        isInstalled: false,
        InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
        RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
    },
    runtime: {
        OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
        OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
        PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
        PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
        RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }
    }
};

// 3. Spoof plugins and languages
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

// 4. Permissions spoofing
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
"""


class EaseMyTripScraper(BaseScraper):
    """Production scraper skeleton for EaseMyTrip domestic flight search."""

    BASE_URL = "https://flight.easemytrip.com"

    def __init__(self, config: Optional[IngestionConfig] = None) -> None:
        super().__init__(config)

    def get_playwright_context_options(self) -> Dict[str, Any]:
        """Generates randomized stealth browser context options."""
        viewport = random.choice(STEALTH_VIEWPORTS)
        user_agent = random.choice(self.config.user_agents)
        return {
            "viewport": viewport,
            "user_agent": user_agent,
            "locale": "en-US",
            "timezone_id": "Asia/Kolkata",
            "geolocation": {"latitude": 28.6139, "longitude": 77.2090},  # New Delhi
            "permissions": ["geolocation"],
            "ignore_https_errors": True,
            "java_script_enabled": True,
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        }

    def build_search_url(self, origin: str, destination: str, flight_date: date) -> str:
        """Constructs EaseMyTrip domestic search query URL.

        Format: /FlightList/Index?srch=DEL-BOM-24/09/2026&px=1-0-0&cbn=0&ar=e&isSplitItinerary=false
        """
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        date_str = flight_date.strftime("%d/%m/%Y")
        srch_param = f"{norm_orig}-{norm_dest}-{date_str}"
        return f"{self.BASE_URL}/FlightList/Index?srch={srch_param}&px=1-0-0&cbn=0&ar=e&isSplitItinerary=false"

    def is_flight_api_url(self, url: str) -> bool:
        """Determines if an intercepted network request is a flight pricing endpoint."""
        target_patterns = [
            r"/Flight/GetFlightList",
            r"/FlightList/GetFlightList",
            r"/api/flight/search",
            r"/Flight/Search",
            r"/AirSearch/",
        ]
        return any(re.search(pat, url, re.IGNORECASE) for pat in target_patterns)

    def parse_flight_json(
        self,
        payload: Dict[str, Any],
        origin: str,
        destination: str,
        window_code: str,
        capture_dt: Optional[datetime] = None,
    ) -> List[RawFareRecord]:
        """Parses intercepted XHR JSON response from EaseMyTrip search API into RawFareRecords."""
        records: List[RawFareRecord] = []
        capture_time = capture_dt or datetime.now()

        # EaseMyTrip typical JSON response wraps flight sectors in 'AirSearchResult' or 'FlightDetails' or 'Flights'
        flight_items = (
            payload.get("FlightDetails")
            or payload.get("AirSearchResult", {}).get("FlightDetails")
            or payload.get("Flights")
            or payload.get("data", {}).get("flights")
            or []
        )

        if not isinstance(flight_items, list):
            logger.warning("Unexpected flight_items payload structure: %s", type(flight_items))
            return records

        for item in flight_items:
            try:
                # Extract airline code and flight number
                airline_code = self.normalize_airline_code(
                    item.get("AirlineCode") or item.get("airline_code") or item.get("ac", "6E")
                )
                flight_no = str(item.get("FlightNo") or item.get("flight_number") or item.get("fn", "101"))
                if not flight_no.startswith(airline_code):
                    full_flight_no = f"{airline_code}-{flight_no}"
                else:
                    full_flight_no = flight_no

                # Extract departure and arrival timestamps
                dep_raw = item.get("DepTime") or item.get("departure_time") or item.get("dt")
                arr_raw = item.get("ArrTime") or item.get("arrival_time") or item.get("at")
                dep_dt_str = self.normalize_datetime(dep_raw) if dep_raw else None
                arr_dt_str = self.normalize_datetime(arr_raw) if arr_raw else None

                if not dep_dt_str or not arr_dt_str:
                    continue

                # Extract fare
                fare_raw = (
                    item.get("TotalFare")
                    or item.get("Fare")
                    or item.get("GrossFare")
                    or item.get("fare_inr")
                    or item.get("tf")
                )
                fare_inr = self.normalize_fare(fare_raw)

                # Duration and stops
                duration = int(item.get("Duration") or item.get("duration_minutes") or item.get("dur", 120))
                stops = int(item.get("Stops") or item.get("stops") or 0)

                record = RawFareRecord(
                    airline_code=airline_code,
                    flight_number=full_flight_no,
                    origin=self.normalize_iata(origin),
                    destination=self.normalize_iata(destination),
                    departure_datetime=dep_dt_str,
                    arrival_datetime=arr_dt_str,
                    booking_datetime=capture_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    fare_inr=fare_inr,
                    cabin_class="economy",
                    stops=stops,
                    source="easemytrip",
                    booking_window=window_code,
                    duration_minutes=duration,
                    is_synthetic=False,
                    source_platform="easemytrip",
                )

                is_valid, _ = self.validate_record(record)
                if is_valid:
                    records.append(record)

            except Exception as exc:
                logger.debug("Skipping unparseable flight item: %s", exc)
                continue

        return records

    async def intercept_response(self, response: Any, collected_records: List[RawFareRecord], context_meta: Dict[str, Any]) -> None:
        """Playwright response event listener to intercept and parse XHR flight search JSON."""
        try:
            url = response.url
            if self.is_flight_api_url(url) and response.status == 200:
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type or "text/plain" in content_type:
                    body = await response.text()
                    data = json.loads(body)
                    parsed = self.parse_flight_json(
                        payload=data,
                        origin=context_meta.get("origin", "DEL"),
                        destination=context_meta.get("destination", "BOM"),
                        window_code=context_meta.get("window_code", "T+1"),
                    )
                    collected_records.extend(parsed)
                    logger.info("Intercepted %d flight records from %s", len(parsed), url)
        except Exception as exc:
            logger.warning("Error intercepting network response: %s", exc)

    def scrape_route(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
    ) -> ScrapeResult:
        """Executes Playwright browser scrape session for EaseMyTrip (synchronous wrapper/skeleton)."""
        search_url = self.build_search_url(origin, destination, target_date)
        logger.info("EaseMyTrip scraping target URL: %s (window %s)", search_url, window_code)

        # In Cycle 1 scaffold, if Playwright is not running, return structured skeleton result
        return ScrapeResult(
            source="easemytrip",
            success=True,
            records=[],
            errors=[],
            duration_ms=0.0,
            metadata={
                "target_url": search_url,
                "origin": origin,
                "destination": destination,
                "window": window_code,
                "status": "scaffold_initialized",
            },
        )

    def scrape_all(
        self,
        routes: Optional[List[Route]] = None,
        windows: Optional[List[BookingWindow]] = None,
    ) -> List[ScrapeResult]:
        """Scrapes all routes and windows using EaseMyTrip."""
        target_routes = routes or DEFAULT_ROUTES
        target_windows = windows or []
        today = date.today()

        results: List[ScrapeResult] = []
        for route in target_routes:
            for window in target_windows:
                target_date = today + timedelta(days=window.days_advance)
                res = self.scrape_route(route.origin, route.destination, target_date, window.code)
                results.append(res)
        return results
