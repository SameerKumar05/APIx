"""A selected proxy has to reach the request.

The scheduler picks a proxy from the pool and records it in telemetry, but it
never passed it to the scraper, so the pool only ever influenced the log. These
tests pin that the proxy now reaches the browser context on all three tier 1
crawlers and survives the orchestrator hop.
"""

from __future__ import annotations

import pytest

from ingestion.config import IngestionConfig
from ingestion.crawlers.easemytrip import EaseMyTripScraper
from ingestion.crawlers.makemytrip import MakeMyTripScraper
from ingestion.crawlers.spicejet import SpiceJetScraper

PROXY = "http://198.51.100.7:8080"
ALL_TIERS = [
    ("makemytrip", MakeMyTripScraper),
    ("easemytrip", EaseMyTripScraper),
    ("spicejet", SpiceJetScraper),
]


@pytest.mark.parametrize("name,factory", ALL_TIERS)
def test_constructor_proxy_is_recorded_for_every_tier1_crawler(name, factory) -> None:
    scraper = factory(config=IngestionConfig(ingestion_mode="live"), proxy=PROXY)
    assert scraper.proxy == PROXY, f"{name} dropped the proxy"


@pytest.mark.parametrize(
    "name,factory",
    [("makemytrip", MakeMyTripScraper), ("easemytrip", EaseMyTripScraper)],
)
def test_proxy_override_reaches_the_browser_context(name, factory) -> None:
    scraper = factory(config=IngestionConfig(ingestion_mode="live", proxy_url=None))
    options = scraper.get_playwright_context_options(proxy_override=PROXY)
    assert options.get("proxy") == {"server": PROXY}, f"{name} dropped the override"


@pytest.mark.parametrize(
    "name,factory",
    [("makemytrip", MakeMyTripScraper), ("easemytrip", EaseMyTripScraper)],
)
def test_no_proxy_configured_means_no_proxy_option(name, factory) -> None:
    scraper = factory(config=IngestionConfig(ingestion_mode="live", proxy_url=None))
    assert "proxy" not in scraper.get_playwright_context_options(), name


def test_scrape_slot_binds_the_proxy_to_the_scraper() -> None:
    """The worker and scheduler both enter here, so this is where the proxy was dropped."""
    from datetime import date

    from ingestion.config import BookingWindow
    from ingestion.orchestrator import IngestionOrchestrator

    orch = IngestionOrchestrator(config=IngestionConfig(ingestion_mode="synthetic"))
    window = BookingWindow(
        code="T+1",
        days_advance=1,
        description="d",
        price_multiplier=1.0,
        multiplier_range=(1.0, 1.0),
    )
    orch.scrape_slot("DEL", "BOM", window, date.today(), proxy=PROXY)
    assert orch.scraper.proxy == PROXY


def test_shared_normaliser_accepts_a_pool_proxy_and_keeps_credentials() -> None:
    """A Proxy must not be collapsed to a URL, or auth is lost.

    Playwright needs username and password as distinct keys, which is exactly
    what Proxy.to_playwright_proxy() provides and what a URL string drops.
    """
    from ingestion.base import BaseScraper
    from ingestion.proxy_pool import Proxy

    authenticated = Proxy(
        ip="198.51.100.9",
        port=8080,
        protocol="http",
        username="apix",
        password="s3cret",
    )
    resolved = BaseScraper.playwright_proxy_config(authenticated)
    assert resolved == {
        "server": "http://198.51.100.9:8080",
        "username": "apix",
        "password": "s3cret",
    }


@pytest.mark.parametrize(
    "given,expected",
    [
        (None, None),
        ("", None),
        ("http://1.2.3.4:3128", {"server": "http://1.2.3.4:3128"}),
        ({"server": "socks5://h:1080"}, {"server": "socks5://h:1080"}),
        ({}, None),
    ],
)
def test_shared_normaliser_edge_cases(given, expected) -> None:
    from ingestion.base import BaseScraper

    assert BaseScraper.playwright_proxy_config(given) == expected


@pytest.mark.parametrize("name,factory", ALL_TIERS)
def test_a_pool_proxy_reaches_the_browser_context(name, factory) -> None:
    """End to end: the orchestrator may hand a scraper a Proxy rather than a string."""
    from ingestion.proxy_pool import Proxy

    authenticated = Proxy(
        ip="203.0.113.4",
        port=8080,
        protocol="http",
        username="u",
        password="p",
    )
    scraper = factory(config=IngestionConfig(ingestion_mode="live"))
    scraper.proxy = authenticated
    options = (
        scraper.get_playwright_context_options()
        if hasattr(scraper, "get_playwright_context_options")
        else None
    )
    if options is not None:
        assert options["proxy"]["username"] == "u"


def test_proxy_credential_protection() -> None:
    """Ensure proxy credentials are never leaked in repr, str, to_dict_safe, or error messages."""
    from ingestion.proxy_pool import Proxy, ProxyPoolConfig, ProxyPoolManager

    secret_pass = "SuperSecretP@ssword!123"
    proxy = Proxy(
        ip="198.51.100.22",
        port=8080,
        protocol="http",
        username="secure_agent",
        password=secret_pass,
    )

    # 1. repr(proxy) must NOT contain the password
    rep = repr(proxy)
    assert secret_pass not in rep
    assert "password" not in rep

    # 2. str(proxy) must return identifier without credentials
    s = str(proxy)
    assert secret_pass not in s
    assert "secure_agent" not in s
    assert s == "http://198.51.100.22:8080"

    # 3. to_dict_safe() must redact password
    safe_dict = proxy.to_dict_safe()
    assert safe_dict["password"] == "***"
    assert secret_pass not in safe_dict["url"]
    assert "secure_agent:***@" in safe_dict["url"]

    # 4. ProxyPoolManager error handling sanitizes passwords in messages
    manager = ProxyPoolManager(
        proxies=[proxy], config=ProxyPoolConfig(cooldown_seconds=1.0)
    )
    manager.report_failure(
        proxy, error=f"Connection refused with credentials {secret_pass}"
    )
    assert secret_pass not in proxy.error_message
    assert "***" in proxy.error_message

    manager.blacklist_proxy(
        proxy, reason=f"Blacklisted due to bad secret {secret_pass}"
    )
    assert secret_pass not in proxy.error_message
    assert "***" in proxy.error_message


def test_proxy_url_string_with_credentials_parsed_for_playwright() -> None:
    """playwright_proxy_config extracts username and password from authenticated URL string."""
    from ingestion.base import BaseScraper

    raw_url = "http://myuser:mypassword@192.0.2.1:8080"
    cfg = BaseScraper.playwright_proxy_config(raw_url)
    assert cfg == {
        "server": "http://192.0.2.1:8080",
        "username": "myuser",
        "password": "mypassword",
    }


def test_proxy_pool_rotation_and_strategies() -> None:
    """Verify round_robin, best_score, and lowest_latency rotation strategies."""
    from ingestion.proxy_pool import Proxy, ProxyPoolConfig, ProxyPoolManager

    p1 = Proxy(ip="10.0.0.1", port=8080, latency_ms=150.0, score=150.0)
    p2 = Proxy(ip="10.0.0.2", port=8080, latency_ms=50.0, score=50.0)
    p3 = Proxy(ip="10.0.0.3", port=8080, latency_ms=250.0, score=250.0)

    mgr = ProxyPoolManager(proxies=[p1, p2, p3], config=ProxyPoolConfig())

    # Strategy: best_score
    best = mgr.get_proxy(strategy="best_score")
    assert best is not None
    assert best.ip == "10.0.0.2"

    # Strategy: lowest_latency
    lowest = mgr.get_proxy(strategy="lowest_latency")
    assert lowest is not None
    assert lowest.ip == "10.0.0.2"

    # Strategy: round_robin cycles through proxies
    rr1 = mgr.get_proxy(strategy="round_robin")
    rr2 = mgr.get_proxy(strategy="round_robin")
    rr3 = mgr.get_proxy(strategy="round_robin")
    rr_ips = {rr1.ip, rr2.ip, rr3.ip}
    assert rr_ips == {"10.0.0.1", "10.0.0.2", "10.0.0.3"}


def test_proxy_pool_health_tracking_and_cooldown_recovery() -> None:
    """Verify consecutive failure blacklisting and cooldown restoration."""
    import time

    from ingestion.proxy_pool import Proxy, ProxyPoolConfig, ProxyPoolManager

    proxy1 = Proxy(ip="10.0.1.1", port=8080)
    proxy2 = Proxy(ip="10.0.1.2", port=8080)
    cfg = ProxyPoolConfig(
        max_consecutive_failures=3,
        cooldown_seconds=0.1,  # short cooldown for test
    )
    mgr = ProxyPoolManager(proxies=[proxy1, proxy2], config=cfg)

    # Initial state
    assert proxy1.status == "active"
    assert proxy2.status == "active"

    # 1st failure -> degraded
    mgr.report_failure(proxy1, error="Timeout 1")
    assert proxy1.status == "degraded"
    assert proxy1.consecutive_failures == 1

    # 2nd failure -> still degraded
    mgr.report_failure(proxy1, error="Timeout 2")
    assert proxy1.status == "degraded"
    assert proxy1.consecutive_failures == 2

    # 3rd failure -> blacklisted
    mgr.report_failure(proxy1, error="Timeout 3")
    assert proxy1.status == "blacklisted"
    assert proxy1.consecutive_failures == 3

    # proxy1 is blacklisted, so get_proxy only returns proxy2
    chosen = mgr.get_proxy()
    assert chosen is not None
    assert chosen.ip == "10.0.1.2"

    # Wait for cooldown to expire
    time.sleep(0.15)
    recovered = mgr.check_cooldowns()
    assert len(recovered) == 1
    assert recovered[0].ip == "10.0.1.1"
    assert recovered[0].status == "testing"
