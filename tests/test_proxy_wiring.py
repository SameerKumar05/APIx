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


@pytest.mark.parametrize("name,factory", [("makemytrip", MakeMyTripScraper), ("easemytrip", EaseMyTripScraper)])
def test_proxy_override_reaches_the_browser_context(name, factory) -> None:
    scraper = factory(config=IngestionConfig(ingestion_mode="live", proxy_url=None))
    options = scraper.get_playwright_context_options(proxy_override=PROXY)
    assert options.get("proxy") == {"server": PROXY}, f"{name} dropped the override"


@pytest.mark.parametrize("name,factory", [("makemytrip", MakeMyTripScraper), ("easemytrip", EaseMyTripScraper)])
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
        code="T+1", days_advance=1, description="d", price_multiplier=1.0,
        multiplier_range=(1.0, 1.0),
    )
    orch.scrape_slot("DEL", "BOM", window, date.today(), proxy=PROXY)
    assert orch.scraper.proxy == PROXY
