"""Install session reuse and challenge detection on Playwright contexts.

Crawlers open ``browser.new_context`` themselves. This hook runs after
``robots_gate`` — the crawler calls that before launch — and does not skip it.
A cooldown skips navigation. It does not grant a fetch the gate denied.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from ingestion.base import ScrapeResult
from ingestion.captcha import (
    DEFAULT_BACKOFF_SECONDS,
    CaptchaBackoff,
    consume_challenge,
    detect_challenge,
    note_challenge,
    take_challenge,
)
from ingestion.session_store import (
    InvalidStorageState,
    SessionStore,
    cookies_for_host,
    origin_host,
    parse_storage_state,
    session_settings_from_env,
)

logger = logging.getLogger("ingestion.scrape_hooks")

_INSTALLED = "_apix_hooked"


class BackoffLedger:
    """In-process cooldown after a challenge. Mutable: it records deadlines."""

    def __init__(self, backoff_seconds: int = DEFAULT_BACKOFF_SECONDS) -> None:
        self._until: dict[str, float] = {}
        self._backoff = backoff_seconds

    def record(self, origin: str, now: float) -> None:
        self._until[origin] = now + self._backoff

    def in_backoff(self, origin: str, now: float) -> bool:
        until = self._until.get(origin)
        if until is None:
            return False
        if now >= until:
            del self._until[origin]
            return False
        return True


def install_scrape_hooks(store: SessionStore, ledger: BackoffLedger) -> bool:
    """Wrap ``Browser.new_context`` once. No-op when Playwright is absent."""
    try:
        from playwright.sync_api import Browser
        from playwright.sync_api import Error as PlaywrightError
    except ImportError:
        return False
    if getattr(Browser.new_context, _INSTALLED, False):
        return True
    original = Browser.new_context

    def hooked(self, *args, **kwargs):  # noqa: ANN001
        context = original(self, *args, **kwargs)
        _watch(context, store, ledger, PlaywrightError)
        return context

    setattr(hooked, _INSTALLED, True)
    setattr(Browser, "new_context", hooked)
    return True


def _host_of(url: str) -> str:
    if "://" in url:
        return origin_host(url)
    return origin_host(f"https://{url}")


def _watch(context, store: SessionStore, ledger: BackoffLedger, playwright_error: type[Exception]) -> None:
    new_page = context.new_page
    close = context.close
    seen: list[str] = []

    def guarded_new_page(*args, **kwargs):  # noqa: ANN001
        page = new_page(*args, **kwargs)
        goto = page.goto

        def guarded_goto(url: str, *goto_args, **goto_kwargs):  # noqa: ANN001
            host = _host_of(url)
            seen.append(host)
            now = time.monotonic()
            if ledger.in_backoff(host, now):
                note_challenge(host, "backoff")
                raise CaptchaBackoff(origin=host, marker="backoff")
            _restore_cookies(context, store, host)
            response = goto(url, *goto_args, **goto_kwargs)
            _note_if_challenge(page, host, ledger, playwright_error, time.monotonic())
            return response

        page.goto = guarded_goto
        return page

    def guarded_close(*args, **kwargs):  # noqa: ANN001
        host = seen[-1] if seen else ""
        if host and store.enabled:
            noted = take_challenge()
            if noted is not None:
                note_challenge(noted.origin, noted.marker)
                store.discard(host)
            else:
                _save_context(context, store, host, playwright_error)
        return close(*args, **kwargs)

    context.new_page = guarded_new_page
    context.close = guarded_close


def _restore_cookies(context, store: SessionStore, host: str) -> None:
    if not store.enabled:
        return
    state = store.load(host)
    if state is None:
        return
    cookies = cookies_for_host(state, host)
    if cookies:
        context.add_cookies(cookies)


def _note_if_challenge(page, host: str, ledger: BackoffLedger, playwright_error: type[Exception], now: float) -> None:
    try:
        html = page.content()
        title = page.title()
    except playwright_error:
        return
    marker = detect_challenge(html, title)
    if marker is None:
        return
    note_challenge(host, marker)
    ledger.record(host, now)
    logger.warning("challenge page on %s marker=%s", host, marker)


def _save_context(context, store: SessionStore, host: str, playwright_error: type[Exception]) -> None:
    try:
        raw = context.storage_state()
    except playwright_error:
        return
    if not isinstance(raw, dict):
        return
    try:
        store.save(host, parse_storage_state(raw))
    except (InvalidStorageState, KeyError):
        return


def arm_orchestrator(orchestrator) -> None:  # noqa: ANN001
    """Install hooks and wrap every scraper the orchestrator currently holds.

    ``_recycle_session`` replaces those instances. The wrapper is reapplied so a
    recycled scraper cannot skip challenge classification.
    """
    if not getattr(install_scrape_hooks, _INSTALLED, False):
        install_scrape_hooks(SessionStore(session_settings_from_env()), BackoffLedger())
        setattr(install_scrape_hooks, _INSTALLED, True)
    _wrap_scrapers(orchestrator)
    if getattr(orchestrator, _INSTALLED, False):
        return
    recycle = orchestrator._recycle_session

    def recycle_and_wrap(current_slot: int) -> None:
        recycle(current_slot)
        _wrap_scrapers(orchestrator)

    orchestrator._recycle_session = recycle_and_wrap
    setattr(orchestrator, _INSTALLED, True)


def _wrap_scrapers(orchestrator) -> None:  # noqa: ANN001
    for scraper in orchestrator.scrapers.values():
        scraper.scrape_route = guard_scrape(scraper.scrape_route)


def guard_scrape(scrape: Callable[..., ScrapeResult]) -> Callable[..., ScrapeResult]:
    """Wrap ``scrape_route`` so a challenge cannot return synthetic records."""
    if getattr(scrape, "_apix_guarded", False):
        return scrape

    def wrapped(*args, **kwargs) -> ScrapeResult:  # noqa: ANN001
        return consume_challenge(scrape(*args, **kwargs))

    setattr(wrapped, "_apix_guarded", True)
    return wrapped
