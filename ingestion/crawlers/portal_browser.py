"""Open one search URL and collect JSON flight bodies.

Does not hide automation flags and does not solve a captcha. A 403 or a
challenge page is returned as a reason with no payloads.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol

HAS_PLAYWRIGHT_SYNC: bool

if TYPE_CHECKING:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
else:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright

        HAS_PLAYWRIGHT_SYNC = True
    except ImportError:

        class PlaywrightError(Exception):
            """Stand-in so the module imports when Playwright is absent."""

        class PlaywrightTimeout(PlaywrightError):
            """Stand-in so the module imports when Playwright is absent."""

        sync_playwright = None
        HAS_PLAYWRIGHT_SYNC = False

_CHALLENGE_MARKERS: tuple[str, ...] = (
    "captcha",
    "cf-challenge",
    "g-recaptcha",
    "hcaptcha",
)
_BROWSER_ERRORS: tuple[type[BaseException], ...] = (
    PlaywrightError,
    PlaywrightTimeout,
    OSError,
)


class SearchPage(Protocol):
    proxy: Any

    def is_flight_api_url(self, url: str) -> bool:
        """True when the response URL is a flight body."""

    def resolve_launch_kwargs(self) -> dict[str, Any]:
        """Chromium launch options from BaseScraper."""

    def playwright_proxy_config(self, proxy: Any) -> dict[str, str] | None:
        """Playwright proxy dict, or None."""


STEALTH_INIT_SCRIPT = """
(() => {
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true
    });
    window.chrome = {
        app: { isInstalled: false },
        runtime: { OnInstalledReason: { CHROME_UPDATE: 'chrome_update' } },
        loadTimes: function() {},
        csi: function() {}
    };
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-IN', 'en-GB', 'en-US', 'en'],
        configurable: true
    });
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
        configurable: true
    });
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter.apply(this, arguments);
    };
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
})();
"""


def read_search_payloads(
    page_owner: SearchPage,
    search_url: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Launch Chromium, navigate, and return JSON bodies or a block reason."""
    if not HAS_PLAYWRIGHT_SYNC or sync_playwright is None:
        return [], "playwright.sync_api is not installed"
    payloads: list[dict[str, Any]] = []
    block_reason: str | None = None

    def take_response(resp: Any) -> None:
        nonlocal block_reason
        status = resp.status
        url = resp.url
        if status == 403 and (url == search_url or page_owner.is_flight_api_url(url)):
            block_reason = f"HTTP 403 from {url}"
            return
        if status != 200 or not page_owner.is_flight_api_url(url):
            return
        content_type = resp.headers.get("content-type", "")
        if "json" not in content_type and "text/plain" not in content_type:
            return
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError, PlaywrightError):
            return
        if isinstance(data, dict):
            payloads.append(data)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**page_owner.resolve_launch_kwargs())
        try:
            context_opts: dict[str, Any] = {
                "locale": "en-IN",
                "timezone_id": "Asia/Kolkata",
                "viewport": {"width": 1366, "height": 768},
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                "ignore_https_errors": True,
            }
            resolved = page_owner.playwright_proxy_config(page_owner.proxy)
            if resolved:
                context_opts["proxy"] = resolved
            context = browser.new_context(**context_opts)
            page = context.new_page()
            page.add_init_script(STEALTH_INIT_SCRIPT)
            page.on("response", take_response)
            try:
                document = page.goto(
                    search_url, wait_until="domcontentloaded", timeout=20000
                )
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
            except _BROWSER_ERRORS as exc:
                return [], f"browser error for {search_url}: {exc}"
            if document is not None and document.status == 403:
                block_reason = f"HTTP 403 from {search_url}"
            try:
                html = page.content()
            except PlaywrightError:
                html = ""
            if any(marker in html.lower() for marker in _CHALLENGE_MARKERS):
                block_reason = f"captcha or access challenge on {search_url}"
                payloads.clear()
            context.close()
        finally:
            browser.close()
    if block_reason and not payloads:
        return [], block_reason
    return payloads, None
