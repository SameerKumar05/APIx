"""EaseMyTrip Scraper Module with Playwright Stealth, XHR Interception, and 3-Tier Fallback.

Implements browser evasion strategies (navigator.webdriver cloaking, randomized viewports,
Indian locale/timezone emulation, WebGL vendor masking) and network-level XHR response
interception to capture structured JSON flight pricing payloads directly from backend APIs.

Resource routing automatically aborts images, fonts, styles, and third-party trackers
to achieve high throughput.

Resilience architecture implements a 3-tier fallback chain:
  - Tier 1: Live Playwright EaseMyTrip Scraper
  - Tier 2: Amadeus Flight Offers Search API Client
  - Tier 3: Deterministic DGCA-Calibrated Synthetic Generator
"""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import UTC, date, datetime, timedelta
from importlib.util import find_spec
from typing import Any

# Optional Playwright import for headless browser automation
from backend.app.core.cleaning import reported_flight_status, sourced_duration_minutes
from ingestion.base import BaseScraper, RawFareRecord, ScrapeResult
from ingestion.config import (
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    BookingWindow,
    IngestionConfig,
    Route,
)
from ingestion.crawlers.amadeus import AmadeusFlightClient
from ingestion.crawlers.synthetic import SyntheticFlightGenerator

try:
    from playwright.sync_api import Response as PlaywrightResponse
    from playwright.sync_api import Route as PlaywrightRoute
    from playwright.sync_api import sync_playwright

    HAS_PLAYWRIGHT_SYNC = True
except ImportError:
    HAS_PLAYWRIGHT_SYNC = False

HAS_PLAYWRIGHT_ASYNC = find_spec("playwright.async_api") is not None

logger = logging.getLogger("ingestion.crawlers.easemytrip")

# Standard desktop viewports for randomized fingerprinting
STEALTH_VIEWPORTS: list[dict[str, int]] = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
]

# Playwright browser stealth launch arguments
PLAYWRIGHT_STEALTH_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-infobars",
    "--window-position=0,0",
    "--ignore-certificate-errors",
    "--ignore-certificate-errors-spki-list",
    "--disable-dev-shm-usage",
    "--disable-accelerated-2d-canvas",
    "--disable-gpu",
    "--lang=en-IN,en-US,en;q=0.9",
]

# Known telemetry, ad, and tracker domains to abort during scraping
TRACKER_DOMAINS: list[str] = [
    r"google-analytics\.com",
    r"googletagmanager\.com",
    r"doubleclick\.net",
    r"facebook\.net",
    r"facebook\.com",
    r"clevertap\.com",
    r"hotjar\.com",
    r"mixpanel\.com",
    r"clarity\.ms",
    r"newrelic\.com",
    r"appsflyer\.com",
    r"branch\.io",
    r"vizury\.com",
    r"criteo\.com",
    r"adroll\.com",
    r"segment\.io",
    r"sentry\.io",
]

# Resource types to abort for speed and bandwidth optimization
BLOCKED_RESOURCE_TYPES: frozenset[str] = frozenset(
    {"image", "imageset", "media", "font", "stylesheet"}
)

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

// 3. Spoof plugins and Indian English languages
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-IN', 'en-US', 'en'],
});

// 4. Permissions spoofing
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// 5. Spoof WebGL Vendor and Renderer
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) { // UNMASKED_VENDOR_WEBGL
        return 'Intel Inc.';
    }
    if (parameter === 37446) { // UNMASKED_RENDERER_WEBGL
        return 'Intel Iris OpenGL Engine';
    }
    return getParameter.apply(this, [parameter]);
};
"""


def should_abort_resource(url: str, resource_type: str) -> bool:
    """Checks whether a network request should be aborted to optimize scraping performance."""
    if resource_type.lower() in BLOCKED_RESOURCE_TYPES:
        return True
    return any(re.search(pat, url, re.IGNORECASE) for pat in TRACKER_DOMAINS)


class EaseMyTripScraper(BaseScraper):
    """Production EaseMyTrip Scraper with Playwright stealth, XHR interception, and 3-tier fallback."""

    BASE_URL = "https://flight.easemytrip.com"

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

    def get_playwright_context_options(
        self, proxy_override: str | dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Generates randomized stealth browser context options with Indian locale and timezone."""
        viewport = random.choice(STEALTH_VIEWPORTS)
        user_agent = random.choice(self.config.user_agents)
        options: dict[str, Any] = {
            "viewport": viewport,
            "user_agent": user_agent,
            "locale": "en-IN",
            "timezone_id": "Asia/Kolkata",
            "geolocation": {"latitude": 28.6139, "longitude": 77.2090},  # New Delhi
            "permissions": ["geolocation"],
            "ignore_https_errors": True,
            "java_script_enabled": True,
            "extra_http_headers": {
                "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
                "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Linux"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        }
        proxy_config = proxy_override or self.proxy
        if proxy_config:
            resolved = self.playwright_proxy_config(proxy_config)
            if resolved:
                options["proxy"] = resolved
        return options

    def build_search_url(self, origin: str, destination: str, flight_date: date) -> str:
        """Constructs EaseMyTrip domestic search query URL.

        Format: /FlightList/Index?srch=DEL-BOM-25/09/2026&px=1-0-0&cbn=0&ar=e&isSplitItinerary=false
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
            r"/SearchFlight",
        ]
        return any(re.search(pat, url, re.IGNORECASE) for pat in target_patterns)

    def parse_flight_json(
        self,
        payload: dict[str, Any],
        origin: str,
        destination: str,
        window_code: str,
        capture_dt: datetime | None = None,
    ) -> list[RawFareRecord]:
        """Parses intercepted XHR JSON response from EaseMyTrip search API into RawFareRecords."""
        records: list[RawFareRecord] = []
        capture_time = capture_dt or datetime.now(UTC)
        booking_dt_str = capture_time.strftime("%Y-%m-%dT%H:%M:%S")

        # EaseMyTrip typical JSON response wraps flight sectors in 'AirSearchResult' or 'FlightDetails' or 'Flights'
        flight_items = (
            payload.get("FlightDetails")
            or payload.get("AirSearchResult", {}).get("FlightDetails")
            or payload.get("Flights")
            or payload.get("data", {}).get("flights")
            or []
        )

        if not isinstance(flight_items, list):
            logger.debug(
                "Unexpected flight_items payload structure: %s", type(flight_items)
            )
            return records

        norm_origin = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)

        for item in flight_items:
            try:
                # Extract airline code and flight number
                airline_code = self.normalize_airline_code(
                    item.get("AirlineCode")
                    or item.get("airline_code")
                    or item.get("ac", "6E")
                )
                flight_no = str(
                    item.get("FlightNo")
                    or item.get("flight_number")
                    or item.get("fn", "101")
                )
                if not flight_no.startswith(airline_code):
                    full_flight_no = f"{airline_code}-{flight_no}"
                else:
                    full_flight_no = flight_no

                # Extract departure and arrival timestamps
                dep_raw = (
                    item.get("DepTime") or item.get("departure_time") or item.get("dt")
                )
                arr_raw = (
                    item.get("ArrTime") or item.get("arrival_time") or item.get("at")
                )
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
                duration = sourced_duration_minutes(
                    item.get("Duration")
                    or item.get("duration_minutes")
                    or item.get("dur"),
                    dep_dt_str,
                    arr_dt_str,
                )
                flight_status = reported_flight_status(item)
                stops = int(item.get("Stops") or item.get("stops") or 0)

                base_fare_val = None
                taxes_val = None
                if item.get("BaseFare") is not None:
                    try:
                        base_fare_val = self.normalize_fare(item["BaseFare"])
                    except ValueError:
                        pass
                if item.get("Tax") is not None or item.get("Taxes") is not None:
                    try:
                        taxes_val = self.normalize_fare(item.get("Tax") or item.get("Taxes"))
                    except ValueError:
                        pass

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
                    source="easemytrip",
                    booking_window=window_code,
                    flight_date=dep_dt_str.split("T")[0],
                    duration_minutes=duration,
                    base_fare=base_fare_val,
                    taxes_and_fees=taxes_val,
                    flight_status=flight_status,
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

    def _scrape_with_playwright(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
    ) -> list[RawFareRecord]:
        """Launches Playwright with stealth configurations and captures flight search XHR JSON."""
        if not HAS_PLAYWRIGHT_SYNC:
            raise RuntimeError("playwright.sync_api is not installed")

        search_url = self.build_search_url(origin, destination, target_date)

        denial = self.robots_gate(search_url)
        if denial is not None:
            logger.warning("robots.txt blocked %s scrape: %s", self.BASE_URL, denial)
            return []
        collected_records: list[RawFareRecord] = []
        capture_time = datetime.now(UTC)

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.config.playwright_headless,
                args=PLAYWRIGHT_STEALTH_ARGS,
            )
            try:
                context_options = self.get_playwright_context_options()
                context = browser.new_context(**context_options)
                context.add_init_script(STEALTH_INIT_SCRIPT)

                # Resource routing to abort images, fonts, styles, and trackers
                def handle_route(route: PlaywrightRoute) -> None:
                    req = route.request
                    if should_abort_resource(req.url, req.resource_type):
                        route.abort()
                    else:
                        route.continue_()

                context.route("**/*", handle_route)

                page = context.new_page()

                # Response interception handler
                def handle_response(resp: PlaywrightResponse) -> None:
                    try:
                        url = resp.url
                        if self.is_flight_api_url(url) and resp.status == 200:
                            content_type = resp.headers.get("content-type", "")
                            if (
                                "application/json" in content_type
                                or "text/plain" in content_type
                            ):
                                data = resp.json()
                                parsed = self.parse_flight_json(
                                    payload=data,
                                    origin=origin,
                                    destination=destination,
                                    window_code=window_code,
                                    capture_dt=capture_time,
                                )
                                if parsed:
                                    collected_records.extend(parsed)
                                    logger.info(
                                        "Intercepted %d records from EaseMyTrip (%s)",
                                        len(parsed),
                                        url,
                                    )
                    except Exception as resp_err:
                        logger.debug(
                            "Error in response interception handler: %s", resp_err
                        )

                page.on("response", handle_response)

                # Navigate with domcontentloaded for high-speed scraping
                page.goto(search_url, wait_until="domcontentloaded", timeout=20000)

                # Allow brief settling time for XHR search endpoints
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass

                if not collected_records:
                    # Give asynchronous requests a moment to complete
                    try:
                        page.wait_for_timeout(2500)
                    except Exception:
                        pass

                context.close()
            finally:
                browser.close()

        return collected_records

    def scrape_route(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
    ) -> ScrapeResult:
        """Executes scrape for a single route-window slot with automatic 3-tier fallback.

        Tier 1: EaseMyTrip Playwright crawler
        Tier 2: Amadeus Flight Offers Search API (Fallback)
        Tier 3: Synthetic DGCA Flight Generator (Ultimate Fallback)
        """
        start_time = time.time()
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        mode = self.config.ingestion_mode.lower()

        # Direct synthetic / mock mode bypass
        if mode == "synthetic":
            res = self.synthetic_generator.scrape_route(
                norm_orig, norm_dest, target_date, window_code
            )
            res.metadata["tier"] = 3
            res.metadata["source"] = "easemytrip_tier3_synthetic"
            return res

        if mode == "mock":
            # Test Tier 2 Amadeus mock first
            res = self.amadeus_client.scrape_route(
                norm_orig, norm_dest, target_date, window_code
            )
            if res.success and res.records:
                res.metadata["tier"] = 2
                res.metadata["source"] = "easemytrip_tier2_amadeus_mock"
                return res
            # Otherwise synthetic
            res = self.synthetic_generator.scrape_route(
                norm_orig, norm_dest, target_date, window_code
            )
            res.metadata["tier"] = 3
            res.metadata["source"] = "easemytrip_tier3_synthetic"
            return res

        # Tier 1: Live Playwright EaseMyTrip Scraper
        tier1_errors: list[str] = []
        try:
            logger.info(
                "Tier 1: Initiating EaseMyTrip Playwright scrape for %s-%s (%s)",
                norm_orig,
                norm_dest,
                window_code,
            )
            records = self._scrape_with_playwright(
                norm_orig, norm_dest, target_date, window_code
            )
            if records:
                elapsed_ms = (time.time() - start_time) * 1000.0
                return ScrapeResult(
                    source="easemytrip",
                    success=True,
                    records=records,
                    errors=[],
                    duration_ms=round(elapsed_ms, 2),
                    metadata={
                        "tier": 1,
                        "origin": norm_orig,
                        "destination": norm_dest,
                        "window": window_code,
                        "date": target_date.isoformat(),
                    },
                )
            tier1_errors.append(
                "EaseMyTrip Tier 1 returned 0 records (anti-bot or no flights)"
            )
        except Exception as t1_exc:
            err_msg = f"EaseMyTrip Tier 1 exception: {t1_exc}"
            logger.warning(err_msg)
            tier1_errors.append(err_msg)

        # Tier 2: Amadeus Flight Offers Search Fallback
        logger.info(
            "Tier 2 Fallback: Invoking Amadeus Flight Offers Search for %s-%s (%s)",
            norm_orig,
            norm_dest,
            window_code,
        )
        try:
            t2_res = self.amadeus_client.scrape_route(
                norm_orig, norm_dest, target_date, window_code
            )
            if t2_res.success and t2_res.records:
                elapsed_ms = (time.time() - start_time) * 1000.0
                t2_res.metadata["tier"] = 2
                t2_res.metadata["fallback"] = "amadeus"
                t2_res.metadata["tier1_errors"] = tier1_errors
                t2_res.duration_ms = round(elapsed_ms, 2)
                return t2_res
        except Exception as t2_exc:
            logger.warning("Amadeus Tier 2 fallback failed: %s", t2_exc)

        # Tier 3: Synthetic DGCA Flight Generator Fallback
        logger.info(
            "Tier 3 Fallback: Invoking Synthetic DGCA Generator for %s-%s (%s)",
            norm_orig,
            norm_dest,
            window_code,
        )
        t3_res = self.synthetic_generator.scrape_route(
            norm_orig, norm_dest, target_date, window_code
        )
        elapsed_ms = (time.time() - start_time) * 1000.0
        t3_res.metadata["tier"] = 3
        t3_res.metadata["fallback"] = "synthetic"
        t3_res.metadata["tier1_errors"] = tier1_errors
        t3_res.duration_ms = round(elapsed_ms, 2)
        return t3_res

    def scrape_all(
        self,
        routes: list[Route] | None = None,
        windows: list[BookingWindow] | None = None,
    ) -> list[ScrapeResult]:
        """Scrapes all routes and windows using EaseMyTrip 3-tier fallback pipeline."""
        target_routes = routes or DEFAULT_ROUTES
        target_windows = windows or BOOKING_WINDOWS
        today = date.today()

        results: list[ScrapeResult] = []
        for route in target_routes:
            for window in target_windows:
                target_date = today + timedelta(days=window.days_advance)
                res = self.scrape_route(
                    route.origin, route.destination, target_date, window.code
                )
                results.append(res)
        return results
