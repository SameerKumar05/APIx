"""MakeMyTrip Scraper Module with Playwright Stealth, XHR Interception, and 3-Tier Fallback.

Provides production-grade scraping for MakeMyTrip domestic flight queries:
- Anti-bot stealth evasion (randomized viewports, canvas/webgl emulation, navigator overrides)
- Dynamic route query generation for Indian trunk routes and booking windows
- Playwright XHR network response interception for real-time fare JSON
- 3-tier resilient fallback: Tier 1 (MMT Live/XHR) -> Tier 2 (Amadeus GDS) -> Tier 3 (DGCA Synthetic)
- Schema normalization into canonical RawFareRecord dataclasses
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

try:
    from playwright.sync_api import (
        BrowserContext,
        Page,
        Playwright,
        Request as PlaywrightRequest,
        Response as PlaywrightResponse,
        Route as PlaywrightRoute,
        sync_playwright,
    )
    HAS_PLAYWRIGHT_SYNC = True
except ImportError:
    HAS_PLAYWRIGHT_SYNC = False

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from ingestion.base import BaseScraper, RawFareRecord, ScrapeResult
from ingestion.config import (
    BOOKING_WINDOW_MAP,
    DEFAULT_ROUTES,
    IngestionConfig,
    Route,
    VALID_AIRLINE_CODES,
    VALID_IATA_CODES,
)
from ingestion.crawlers.amadeus import AmadeusFlightClient
from ingestion.crawlers.synthetic import SyntheticFlightGenerator

logger = logging.getLogger("ingestion.crawlers.makemytrip")

# Standard desktop viewports for randomized fingerprinting
STEALTH_VIEWPORTS: List[Dict[str, int]] = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
    {"width": 1680, "height": 1050},
    {"width": 2560, "height": 1440},
]

# Playwright browser stealth launch arguments
PLAYWRIGHT_STEALTH_ARGS: List[str] = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-infobars",
    "--window-position=0,0",
    "--ignore-certificate-errors",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-extensions",
    "--disable-sync",
    "--disable-translate",
    "--metrics-recording-only",
    "--mute-audio",
    "--no-first-run",
    "--safebrowsing-disable-auto-update",
]

# Known telemetry, ad, tracker, and metric domains to abort during scraping
TRACKER_DOMAINS: List[str] = [
    r"google-analytics\.com",
    r"googletagmanager\.com",
    r"doubleclick\.net",
    r"facebook\.net",
    r"hotjar\.com",
    r"clarity\.ms",
    r"clevertap\.com",
    r"branch\.io",
    r"appsflyer\.com",
    r"vizury\.com",
    r"criteo\.com",
    r"optimizely\.com",
    r"newrelic\.com",
    r"segment\.io",
    r"moatads\.com",
    r"scorecardresearch\.com",
    r"adservice\.google",
    r"adroll\.com",
]

# Resource types to abort for speed and bandwidth optimization
BLOCKED_RESOURCE_TYPES: frozenset[str] = frozenset(
    {"image", "imageset", "media", "font", "stylesheet"}
)

# Client-side JavaScript injected into every new page context before scripts execute
STEALTH_INIT_SCRIPT = """
(() => {
    // 1. Hide webdriver flag
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true
    });

    // 2. Mock chrome runtime and app objects
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
        },
        loadTimes: function() {},
        csi: function() {}
    };

    // 3. Mock languages (Indian primary)
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-IN', 'en-GB', 'en-US', 'en'],
        configurable: true
    });

    // 4. Mock plugins length
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
        configurable: true
    });

    // 5. Mock WebGL vendor / renderer to avoid SwiftShader headless tell
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) { // UNMASKED_VENDOR_WEBGL
            return 'Intel Inc.';
        }
        if (parameter === 37446) { // UNMASKED_RENDERER_WEBGL
            return 'Intel Iris OpenGL Engine';
        }
        return getParameter.apply(this, arguments);
    };

    // 6. Mock notification permissions query
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
})();
"""


SYSTEM_CHROMIUM_CANDIDATES: List[str] = [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
]


def resolve_launch_kwargs(config: Any) -> Dict[str, Any]:
    """Pick the Chromium build to drive.

    Akamai fingerprints the HTTP/2 frame and rejects Playwright's bundled Chromium
    with ERR_HTTP2_PROTOCOL_ERROR, while accepting the distro build of the same
    browser. Measured on this host: bundled build fails, /usr/bin/chromium serves
    the page. So prefer a system Chromium and fall back to the bundled build.
    """
    kwargs: Dict[str, Any] = {
        "headless": config.playwright_headless,
        "args": PLAYWRIGHT_STEALTH_ARGS,
    }
    explicit = getattr(config, "playwright_browser_executable", None)
    candidates = [explicit] if explicit else list(SYSTEM_CHROMIUM_CANDIDATES)
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            kwargs["executable_path"] = path
            return kwargs
    return kwargs


def should_abort_resource(url: str, resource_type: str) -> bool:
    """Checks whether a network request should be aborted to optimize scraping performance."""
    if resource_type in BLOCKED_RESOURCE_TYPES:
        return True
    return any(re.search(pat, url, re.IGNORECASE) for pat in TRACKER_DOMAINS)


class MakeMyTripScraper(BaseScraper):
    """Production MakeMyTrip Scraper with Playwright stealth, XHR interception, and 3-tier fallback."""

    BASE_URL = "https://www.makemytrip.com"

    def __init__(
        self,
        config: Optional[IngestionConfig] = None,
        amadeus_client: Optional[AmadeusFlightClient] = None,
        synthetic_generator: Optional[SyntheticFlightGenerator] = None,
        proxy: Optional[Union[str, Dict[str, str]]] = None,
    ) -> None:
        super().__init__(config)
        self.amadeus_client = amadeus_client or AmadeusFlightClient(config=self.config)
        self.synthetic_generator = synthetic_generator or SyntheticFlightGenerator(config=self.config)
        self.proxy = proxy or getattr(self.config, "proxy_url", None)

    def get_playwright_context_options(self, proxy_override: Optional[Union[str, Dict[str, str]]] = None) -> Dict[str, Any]:
        """Generates randomized stealth browser context options with Indian locale and timezone."""
        viewport = random.choice(STEALTH_VIEWPORTS)
        user_agent = random.choice(self.config.user_agents)
        proxy_config = proxy_override or self.proxy

        options: Dict[str, Any] = {
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

        if proxy_config:
            if isinstance(proxy_config, str):
                options["proxy"] = {"server": proxy_config}
            elif isinstance(proxy_config, dict):
                options["proxy"] = proxy_config

        return options

    def build_search_url(
        self,
        origin: str,
        destination: str,
        flight_date: date,
        cabin_class: str = "E",
        adults: int = 1,
    ) -> str:
        """Constructs MakeMyTrip domestic search query URL with dynamic route parameters.

        Format: https://www.makemytrip.com/flight/search?itinerary=DEL-BOM-25/09/2026&tripType=O&paxType=A-1_C-0_I-0&intl=false&cabinClass=E
        """
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        date_str = flight_date.strftime("%d/%m/%Y")
        itinerary = f"{norm_orig}-{norm_dest}-{date_str}"
        pax = f"A-{adults}_C-0_I-0"
        return f"{self.BASE_URL}/flight/search?itinerary={itinerary}&tripType=O&paxType={pax}&intl=false&cabinClass={cabin_class}"

    def is_flight_api_url(self, url: str) -> bool:
        """Determines if an intercepted network request is a MakeMyTrip flight pricing endpoint."""
        target_patterns = [
            r"/flight/search",
            r"/air-search-service/",
            r"/search-summary",
            r"/v2/search",
            r"/api/flight/search",
            r"/flightList",
            r"/get-flight-details",
            r"/airSearch",
            r"/flights/v1/search",
            r"/flight-search-pwa",
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
        """Parses intercepted XHR JSON response from MakeMyTrip search API into RawFareRecords."""
        records: List[RawFareRecord] = []
        capture_time = capture_dt or datetime.now(timezone.utc)
        booking_dt_str = capture_time.strftime("%Y-%m-%dT%H:%M:%S")

        norm_origin = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)

        # Handle diverse MakeMyTrip JSON response variations
        flight_items: List[Dict[str, Any]] = []

        if isinstance(payload, dict):
            # Check multiple common payload shapes
            if "flights" in payload and isinstance(payload["flights"], list):
                flight_items = payload["flights"]
            elif "data" in payload and isinstance(payload["data"], dict):
                data = payload["data"]
                flight_items = (
                    data.get("flights")
                    or data.get("itineraries")
                    or data.get("flightDetails")
                    or []
                )
            elif "searchResult" in payload and isinstance(payload["searchResult"], dict):
                sr = payload["searchResult"]
                flight_items = sr.get("flightDetails") or sr.get("flights") or []
            elif "itineraries" in payload and isinstance(payload["itineraries"], list):
                flight_items = payload["itineraries"]
            elif "flightDetails" in payload and isinstance(payload["flightDetails"], list):
                flight_items = payload["flightDetails"]
            elif "legs" in payload and isinstance(payload["legs"], list):
                flight_items = payload["legs"]
            elif "searchData" in payload and isinstance(payload["searchData"], dict):
                flight_items = payload["searchData"].get("flights") or []

        if not isinstance(flight_items, list):
            logger.debug("MakeMyTrip: unexpected flight items structure: %s", type(flight_items))
            return records

        for item in flight_items:
            try:
                # 1. Airline code and flight number
                airline_code_raw = (
                    item.get("airlineCode")
                    or item.get("carrierCode")
                    or item.get("airline", {}).get("code")
                    or item.get("al")
                    or ""
                )

                flight_no_raw = str(
                    item.get("flightNumber")
                    or item.get("flightNo")
                    or item.get("fn")
                    or item.get("flight_number")
                    or ""
                )

                # Segment-based extraction if item has segments/legs
                segments = item.get("segments") or item.get("legs") or []
                if not airline_code_raw and segments and isinstance(segments, list) and segments[0]:
                    first_seg = segments[0]
                    airline_code_raw = first_seg.get("airlineCode") or first_seg.get("carrierCode") or ""
                    if not flight_no_raw:
                        flight_no_raw = str(first_seg.get("flightNumber") or first_seg.get("flightNo") or "")

                if not airline_code_raw and "-" in flight_no_raw:
                    airline_code_raw = flight_no_raw.split("-")[0]
                elif not airline_code_raw and len(flight_no_raw) >= 2 and flight_no_raw[:2].isalpha():
                    airline_code_raw = flight_no_raw[:2]

                airline_code = self.normalize_airline_code(airline_code_raw or "6E")

                # Flight designator formatting
                clean_num = flight_no_raw.strip()
                if clean_num.upper().startswith(airline_code):
                    clean_num = clean_num[len(airline_code):].lstrip("- ")
                else:
                    clean_num = re.sub(r"^[A-Za-z]{2}[-\s]?", "", clean_num)
                clean_num = clean_num.strip() or "101"
                full_flight_no = f"{airline_code}-{clean_num}"
                # 2. Departure and arrival datetimes
                dep_raw = (
                    item.get("departureTime")
                    or item.get("depTime")
                    or item.get("departureDateTime")
                    or item.get("dt")
                )
                arr_raw = (
                    item.get("arrivalTime")
                    or item.get("arrTime")
                    or item.get("arrivalDateTime")
                    or item.get("at")
                )

                if (not dep_raw or not arr_raw) and segments and isinstance(segments, list):
                    first_seg = segments[0]
                    last_seg = segments[-1]
                    dep_raw = dep_raw or first_seg.get("departureTime") or first_seg.get("depTime")
                    arr_raw = arr_raw or last_seg.get("arrivalTime") or last_seg.get("arrTime")

                dep_dt_str = self.normalize_datetime(dep_raw) if dep_raw else None
                arr_dt_str = self.normalize_datetime(arr_raw) if arr_raw else None

                if not dep_dt_str or not arr_dt_str:
                    continue

                # 3. Fare extraction
                fare_raw = (
                    item.get("totalFare")
                    or item.get("fare")
                    or item.get("price")
                    or item.get("totalPrice")
                    or item.get("grossFare")
                    or item.get("tf")
                )

                if fare_raw is None:
                    fare_details = item.get("fareDetails") or item.get("priceBreakup") or {}
                    fare_raw = (
                        fare_details.get("totalFare")
                        or fare_details.get("total")
                        or fare_details.get("grossFare")
                    )

                fare_inr = self.normalize_fare(fare_raw)

                # Base fare and taxes if provided
                base_fare_val = None
                taxes_val = None
                if isinstance(item.get("fareDetails"), dict):
                    fd = item["fareDetails"]
                    if "baseFare" in fd:
                        base_fare_val = float(fd["baseFare"])
                    if "tax" in fd or "taxes" in fd:
                        taxes_val = float(fd.get("tax") or fd.get("taxes") or 0.0)

                # Duration and stops
                duration = int(item.get("duration") or item.get("durationMinutes") or item.get("dur", 120))
                stops = int(item.get("stops", len(segments) - 1 if segments else 0))
                if stops < 0:
                    stops = 0

                cabin_class = str(item.get("cabinClass") or item.get("cabin") or "economy").lower()
                if "econ" in cabin_class:
                    cabin_class = "economy"
                elif "bus" in cabin_class:
                    cabin_class = "business"

                record = RawFareRecord(
                    airline_code=airline_code,
                    flight_number=full_flight_no,
                    origin=norm_origin,
                    destination=norm_dest,
                    departure_datetime=dep_dt_str,
                    arrival_datetime=arr_dt_str,
                    booking_datetime=booking_dt_str,
                    fare_inr=fare_inr,
                    cabin_class=cabin_class,
                    stops=stops,
                    source="makemytrip",
                    booking_window=window_code,
                    flight_date=dep_dt_str.split("T")[0],
                    duration_minutes=duration,
                    base_fare=base_fare_val,
                    taxes_and_fees=taxes_val,
                    is_synthetic=False,
                    source_platform="makemytrip",
                )

                is_valid, validation_errors = self.validate_record(record)
                if is_valid:
                    records.append(record)
                else:
                    logger.debug("Skipping invalid MMT record: %s", validation_errors)

            except Exception as exc:
                logger.debug("Skipping unparseable MMT flight item: %s", exc)
                continue

        return records

    def _scrape_with_playwright(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
    ) -> List[RawFareRecord]:
        """Launches Playwright with MakeMyTrip stealth configuration and captures flight search XHR JSON."""
        if not HAS_PLAYWRIGHT_SYNC:
            raise RuntimeError("playwright.sync_api is not installed")

        search_url = self.build_search_url(origin, destination, target_date)
        collected_records: List[RawFareRecord] = []
        capture_time = datetime.now(timezone.utc)

        with sync_playwright() as p:
            browser = p.chromium.launch(**resolve_launch_kwargs(self.config))
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
                            if "application/json" in content_type or "text/plain" in content_type:
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
                                        "Intercepted %d records from MakeMyTrip (%s)",
                                        len(parsed),
                                        url,
                                    )
                    except Exception as resp_err:
                        logger.debug("Error in MMT response interception handler: %s", resp_err)

                page.on("response", handle_response)

                page.goto(search_url, wait_until="domcontentloaded", timeout=20000)

                # Wait briefly for XHR flight pricing responses
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass

                if not collected_records:
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

        Tier 1: MakeMyTrip Playwright stealth crawler / live XHR
        Tier 2: Amadeus Flight Offers Search API (Fallback)
        Tier 3: Synthetic DGCA Flight Generator (Ultimate Fallback)
        """
        start_time = time.time()
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        mode = self.config.ingestion_mode.lower()

        # Direct synthetic / mock mode bypass
        if mode == "synthetic":
            res = self.synthetic_generator.scrape_route(norm_orig, norm_dest, target_date, window_code)
            for r in res.records:
                r.source = "makemytrip"
                r.source_platform = "makemytrip"
            res.source = "makemytrip"
            res.metadata["tier"] = 3
            res.metadata["source"] = "makemytrip_tier3_synthetic"
            return res
        if mode == "mock":
            res = self.amadeus_client.scrape_route(norm_orig, norm_dest, target_date, window_code)
            if res.success and res.records:
                res.metadata["tier"] = 2
                res.metadata["source"] = "makemytrip_tier2_amadeus_mock"
                return res
            res = self.synthetic_generator.scrape_route(norm_orig, norm_dest, target_date, window_code)
            res.metadata["tier"] = 3
            res.metadata["source"] = "makemytrip_tier3_synthetic"
            return res

        # Tier 1: Live Playwright MakeMyTrip Scraper
        tier1_errors: List[str] = []
        try:
            logger.info("Tier 1: Scraping MakeMyTrip for %s-%s on %s", norm_orig, norm_dest, target_date)
            records = self._scrape_with_playwright(norm_orig, norm_dest, target_date, window_code)
            if records:
                elapsed_ms = round((time.time() - start_time) * 1000, 2)
                logger.info("Tier 1 Success: %d records from MakeMyTrip in %.2fms", len(records), elapsed_ms)
                return ScrapeResult(
                    source="makemytrip",
                    success=True,
                    records=records,
                    errors=[],
                    duration_ms=elapsed_ms,
                    metadata={
                        "tier": 1,
                        "source": "makemytrip_playwright",
                        "records_count": len(records),
                        "origin": norm_orig,
                        "destination": norm_dest,
                        "date": target_date.isoformat(),
                        "window": window_code,
                    },
                )
            tier1_errors.append("Playwright navigation succeeded but no flight records intercepted")
        except Exception as t1_exc:
            err_msg = f"Tier 1 MakeMyTrip Playwright failure: {t1_exc}"
            logger.warning(err_msg)
            tier1_errors.append(err_msg)

        # Tier 2: Amadeus GDS Fallback
        tier2_errors: List[str] = []
        try:
            logger.info("Tier 2 Fallback: Querying Amadeus GDS for %s-%s on %s", norm_orig, norm_dest, target_date)
            t2_res = self.amadeus_client.scrape_route(norm_orig, norm_dest, target_date, window_code)
            if t2_res.success and t2_res.records:
                elapsed_ms = round((time.time() - start_time) * 1000, 2)
                t2_res.duration_ms = elapsed_ms
                t2_res.metadata["tier"] = 2
                t2_res.metadata["source"] = "makemytrip_tier2_amadeus"
                t2_res.metadata["tier1_errors"] = tier1_errors
                return t2_res
            tier2_errors.extend(t2_res.errors)
        except Exception as t2_exc:
            err_msg = f"Tier 2 Amadeus failure: {t2_exc}"
            logger.warning(err_msg)
            tier2_errors.append(err_msg)

        # Tier 3: Deterministic DGCA Synthetic Generator
        logger.info("Tier 3 Fallback: Generating DGCA-calibrated synthetic flights for %s-%s on %s", norm_orig, norm_dest, target_date)
        t3_res = self.synthetic_generator.scrape_route(norm_orig, norm_dest, target_date, window_code)
        for r in t3_res.records:
            r.source = "makemytrip"
            r.source_platform = "makemytrip"
        t3_res.source = "makemytrip"
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        t3_res.duration_ms = elapsed_ms
        t3_res.metadata["tier"] = 3
        t3_res.metadata["source"] = "makemytrip_tier3_synthetic"
        t3_res.metadata["tier1_errors"] = tier1_errors
        t3_res.metadata["tier2_errors"] = tier2_errors
        return t3_res

    def scrape_all(
        self,
        routes: Optional[List[Route]] = None,
        windows: Optional[List[BookingWindow]] = None,
    ) -> List[ScrapeResult]:
        """Scrapes all routes and windows using MakeMyTrip 3-tier fallback pipeline."""
        target_routes = routes or DEFAULT_ROUTES
        target_windows = windows or BOOKING_WINDOWS
        today = date.today()

        results: List[ScrapeResult] = []
        for route in target_routes:
            for window in target_windows:
                target_date = today + timedelta(days=window.days_advance)
                res = self.scrape_route(route.origin, route.destination, target_date, window.code)
                results.append(res)
        return results

    def scrape_all_routes(
        self,
        routes: Optional[List[Route]] = None,
        target_date: Optional[date] = None,
        window_code: str = "T+7",
    ) -> List[ScrapeResult]:
        """Scrapes all standard routes for a single booking window with fallback."""
        target_routes = routes or DEFAULT_ROUTES
        flight_date = target_date or (date.today() + timedelta(days=7))
        results: List[ScrapeResult] = []

        for r in target_routes:
            res = self.scrape_route(
                origin=r.origin,
                destination=r.destination,
                target_date=flight_date,
                window_code=window_code,
            )
            results.append(res)
            time.sleep(random.uniform(0.5, 1.5))

        return results
