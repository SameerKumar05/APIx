"""PS portal scrapers: search URL, robots decline, and no invented fare."""

from __future__ import annotations

from datetime import date

import pytest

from ingestion.base import BaseScraper
from ingestion.config import IngestionConfig
from ingestion.crawlers.airindia import AirIndiaScraper
from ingestion.crawlers.airindia_express import AirIndiaExpressScraper
from ingestion.crawlers.akasa import AkasaScraper
from ingestion.crawlers.cleartrip import CleartripScraper
from ingestion.crawlers.goibibo import GoibiboScraper
from ingestion.crawlers.indigo import IndiGoScraper
from ingestion.crawlers.ixigo import IxigoScraper
from ingestion.crawlers.portal import PAGE_YIELDED_NO_FARE, PortalScraper
from ingestion.crawlers.yatra import YatraScraper
from ingestion.robots import RobotsPolicy, clear_policy_cache, parse_robots_txt

TARGET = date(2026, 9, 25)

SCRAPERS: list[type[PortalScraper]] = [
    IndiGoScraper,
    AirIndiaScraper,
    AirIndiaExpressScraper,
    AkasaScraper,
    YatraScraper,
    CleartripScraper,
    IxigoScraper,
    GoibiboScraper,
]

URL_FRAGMENTS: dict[str, str] = {
    "indigo": "https://www.goindigo.in/booking/flight-select.html?origin=DEL&destination=BOM&departureDate=2026-09-25&adults=1&tripType=oneWay",
    "airindia": "https://www.airindia.com/in/en/book-flights?origin=DEL&destination=BOM&departureDate=2026-09-25&adults=1&cabin=ECONOMY&tripType=O",
    "airindiaexpress": "https://www.airindiaexpress.com/flight-availability?origin=DEL&destination=BOM&departureDate=2026-09-25&adult=1&child=0&infant=0&tripType=oneWay",
    "akasa": "https://www.akasaair.com/fly/flight-search?from=DEL&to=BOM&departDate=2026-09-25&adults=1&tripType=one-way",
    "yatra": "https://flight.yatra.com/air-search-ui/dom2/trigger?type=O&viewName=normal&flexi=0&noOfSegments=1&origin=DEL&originCountry=IN&destination=BOM&destinationCountry=IN&flight_depart_date=25/09/2026&ADT=1&CHD=0&INF=0&class=Economy&hb=0",
    "cleartrip": "https://www.cleartrip.com/flights/search?from=DEL&to=BOM&depart_date=25/09/2026&adults=1&childs=0&infants=0&class=Economy&intl=n",
    "ixigo": "https://www.ixigo.com/search/result/flight?from=DEL&to=BOM&date=25092026&adults=1&children=0&infants=0&class=e",
    "goibibo": "https://www.goibibo.com/flight/search?itinerary=DEL-BOM-25/09/2026&tripType=O&paxType=A-1_C-0_I-0&cabinClass=E&intl=false",
}

AIX_ROBOTS = "User-agent: *\nDisallow: /flight-availability\n"
CLEARTRIP_ROBOTS = "User-agent: *\nDisallow: /flights/search*\nDisallow: /api/\n"
IXIGO_ROBOTS = "User-agent: *\nDisallow: /search/result/\nDisallow: /flights/search\nDisallow: /api/\n"
AKASA_ROBOTS = "User-Agent: *\nSitemap: https://www.akasaair.com/sitemap.xml\n"


def _scraper(cls: type[PortalScraper]) -> PortalScraper:
    config = IngestionConfig(
        ingestion_mode="live",
        rate_limit_delay_seconds=0,
        rate_limit_jitter_seconds=0,
    )
    return cls(config=config, proxy="http://127.0.0.1:9")


@pytest.fixture(autouse=True)
def _clear_robots_cache() -> None:
    clear_policy_cache()
    yield
    clear_policy_cache()


@pytest.mark.parametrize("cls", SCRAPERS, ids=lambda cls: cls.SOURCE_NAME)
def test_build_search_url(cls: type[PortalScraper]) -> None:
    scraper = _scraper(cls)
    url = scraper.build_search_url("del", "bom", TARGET, adults=1)
    assert url == URL_FRAGMENTS[cls.SOURCE_NAME]


@pytest.mark.parametrize("cls", SCRAPERS, ids=lambda cls: cls.SOURCE_NAME)
def test_declines_robots_denied_path_without_launching_browser(
    cls: type[PortalScraper],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = _scraper(cls)
    search_url = scraper.build_search_url("DEL", "BOM", TARGET)
    denial = f"robots.txt disallows {search_url}"

    def deny(url: str) -> str:
        assert url == search_url
        return denial

    def must_not_launch(url: str) -> tuple[list[dict[str, str]], None]:
        raise AssertionError(f"browser launched for denied url {url}")

    monkeypatch.setattr(scraper, "robots_gate", deny)
    monkeypatch.setattr(scraper, "_read_search_payloads", must_not_launch)
    result = scraper.collect_live("DEL", "BOM", TARGET, "T+7")
    assert result.records == []
    assert result.errors == [denial]
    assert result.metadata["reason"] == denial


@pytest.mark.parametrize("cls", SCRAPERS, ids=lambda cls: cls.SOURCE_NAME)
def test_page_with_no_fare_returns_zero_records_and_reason(
    cls: type[PortalScraper],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = _scraper(cls)
    payload = {
        "flights": [
            {
                "airlineCode": "6E",
                "flightNumber": "6E-532",
                "departureTime": "2026-09-25T06:00:00",
                "arrivalTime": "2026-09-25T08:15:00",
            }
        ]
    }

    def allow(url: str) -> None:
        return None

    def empty_fare(url: str) -> tuple[list[dict[str, object]], None]:
        return [payload], None

    monkeypatch.setattr(scraper, "robots_gate", allow)
    monkeypatch.setattr(scraper, "_read_search_payloads", empty_fare)
    result = scraper.collect_live("DEL", "BOM", TARGET, "T+7")
    assert result.records == []
    assert result.errors == [PAGE_YIELDED_NO_FARE]


@pytest.mark.parametrize("cls", SCRAPERS, ids=lambda cls: cls.SOURCE_NAME)
def test_parse_sets_live_only_when_fare_is_read(cls: type[PortalScraper]) -> None:
    scraper = _scraper(cls)
    missing = scraper.parse_flight_json(
        {
            "flights": [
                {
                    "flightNumber": "6E-1",
                    "departureTime": "2026-09-25T06:00:00",
                    "arrivalTime": "2026-09-25T08:00:00",
                }
            ]
        },
        "DEL",
        "BOM",
        "T+7",
    )
    assert missing == []
    priced = scraper.parse_flight_json(
        {
            "flights": [
                {
                    "airlineCode": scraper.AIRLINE_CODE or "6E",
                    "flightNumber": "532",
                    "departureTime": "2026-09-25T06:00:00",
                    "arrivalTime": "2026-09-25T08:15:00",
                    "totalFare": 4510.5,
                }
            ]
        },
        "DEL",
        "BOM",
        "T+7",
    )
    assert len(priced) == 1
    assert priced[0].fare_inr == 4510.5
    assert priced[0].is_synthetic is False
    assert priced[0].source == cls.SOURCE_NAME


def test_published_search_paths_are_denied_by_robots() -> None:
    cases: list[tuple[PortalScraper, str, str]] = [
        (
            _scraper(AirIndiaExpressScraper),
            AIX_ROBOTS,
            "https://www.airindiaexpress.com/robots.txt",
        ),
        (
            _scraper(CleartripScraper),
            CLEARTRIP_ROBOTS,
            "https://www.cleartrip.com/robots.txt",
        ),
        (_scraper(IxigoScraper), IXIGO_ROBOTS, "https://www.ixigo.com/robots.txt"),
    ]
    for scraper, body, robots_url in cases:
        policy = parse_robots_txt(robots_url, body, user_agent="APIxBot")
        url = scraper.build_search_url("DEL", "BOM", TARGET)
        assert policy.can_fetch(url) is False


def test_akasa_published_robots_allows_search_url() -> None:
    scraper = _scraper(AkasaScraper)
    policy = parse_robots_txt(
        "https://www.akasaair.com/robots.txt", AKASA_ROBOTS, user_agent="APIxBot"
    )
    assert policy.can_fetch(scraper.build_search_url("DEL", "BOM", TARGET)) is True


def test_unreachable_robots_fails_closed_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = _scraper(IndiGoScraper)
    policy = RobotsPolicy.deny_all(
        "https://www.goindigo.in/robots.txt",
        "ReadTimeout: The read operation timed out",
    )
    monkeypatch.setattr(scraper, "robots_policy", lambda: policy)
    reason = scraper.robots_gate(scraper.build_search_url("DEL", "BOM", TARGET))
    assert reason is not None
    assert reason.startswith("robots.txt unavailable")
    assert "ReadTimeout" in reason


def test_launch_kwargs_come_from_base_class() -> None:
    scraper = _scraper(IndiGoScraper)
    assert IndiGoScraper.resolve_launch_kwargs is BaseScraper.resolve_launch_kwargs
    assert scraper.proxy == "http://127.0.0.1:9"


def test_synthetic_fallback_keeps_label_and_generator_fare() -> None:
    scraper = _scraper(IndiGoScraper)
    scraper.config.ingestion_mode = "synthetic"
    generated = scraper.synthetic_generator.scrape_route("DEL", "BOM", TARGET, "T+7")
    result = scraper.scrape_route("DEL", "BOM", TARGET, "T+7")
    assert result.records
    assert result.metadata["tier"] == 3
    assert [record.fare_inr for record in result.records] == [
        record.fare_inr for record in generated.records
    ]
    for record in result.records:
        assert record.is_synthetic is True
        assert record.source == "indigo"
        assert record.airline_code == "6E"
        assert record.base_fare is not None
        assert record.taxes_and_fees is not None
        assert record.fare_split_basis in (
            "measured",
            "residual",
            "estimated",
            "calibrated",
        )


def test_valid_iata_codes_includes_maa() -> None:
    from ingestion.config import VALID_IATA_CODES

    assert "MAA" in VALID_IATA_CODES


@pytest.mark.parametrize("cls", SCRAPERS, ids=lambda cls: cls.SOURCE_NAME)
def test_parse_preserves_base_fare_and_taxes_when_supplied(
    cls: type[PortalScraper],
) -> None:
    scraper = _scraper(cls)
    priced = scraper.parse_flight_json(
        {
            "flights": [
                {
                    "airlineCode": scraper.AIRLINE_CODE or "6E",
                    "flightNumber": "532",
                    "departureTime": "2026-09-25T06:00:00",
                    "arrivalTime": "2026-09-25T08:15:00",
                    "totalFare": 4510.5,
                    "baseFare": 3500.0,
                    "tax": 1010.5,
                }
            ]
        },
        "DEL",
        "BOM",
        "T+7",
    )
    assert len(priced) == 1
    assert priced[0].fare_inr == 4510.5
    assert priced[0].base_fare == 3500.0
    assert priced[0].taxes_and_fees == 1010.5
    assert priced[0].fare_split_basis == "measured"
