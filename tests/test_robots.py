"""robots.txt compliance gate for tier 1 OTA scraping.

The problem statement grades ethical scraping, and the repository documentation
claims robots.txt compliance. These tests pin the behaviour that makes that
claim true: directives are honoured, the most specific match wins, crawl delays
are surfaced, and an unreachable robots.txt fails closed rather than open.
"""

from __future__ import annotations

import pytest

from ingestion.robots import RobotsPolicy, parse_robots_txt

SAMPLE = """
# OTA fare search
User-agent: *
Disallow: /api/
Disallow: /search?*
Crawl-delay: 7

User-agent: APIxBot
Disallow: /private/
Crawl-delay: 2

Sitemap: https://www.makemytrip.com/sitemap.xml
"""


def test_parses_directives_for_wildcard_agent() -> None:
    policy = parse_robots_txt(
        "https://www.makemytrip.com/robots.txt", SAMPLE, user_agent="*"
    )
    assert policy.can_fetch("https://www.makemytrip.com/flights/search") is True
    assert (
        policy.can_fetch("https://www.makemytrip.com/api/v1/search/availability")
        is False
    )
    # The query component participates in matching, so a query-scoped rule applies.
    assert policy.can_fetch("https://www.makemytrip.com/search?q=flights") is False
    assert policy.can_fetch("https://www.makemytrip.com/flights/DEL-BOM") is True


def test_named_agent_group_overrides_wildcard() -> None:
    policy = parse_robots_txt(
        "https://www.makemytrip.com/robots.txt", SAMPLE, user_agent="APIxBot"
    )
    assert policy.can_fetch("https://www.makemytrip.com/private/booking") is False
    # The wildcard Disallow still applies. A named group may add a restriction,
    # never lift one.
    assert policy.can_fetch("https://www.makemytrip.com/api/v1/x") is False
    assert policy.crawl_delay() == 2


def test_wildcard_agent_uses_star_group_delay() -> None:
    policy = parse_robots_txt(
        "https://www.makemytrip.com/robots.txt", SAMPLE, user_agent="*"
    )
    assert policy.crawl_delay() == 7


def test_longest_match_wins_over_shorter_rule() -> None:
    text = "User-agent: *\nDisallow: /data/\nAllow: /data/public/\n"
    policy = parse_robots_txt("https://x.test/robots.txt", text)
    assert policy.can_fetch("https://x.test/data/private") is False
    assert policy.can_fetch("https://x.test/data/public/fares") is True


def test_disallow_everything_blocks_all_paths() -> None:
    policy = parse_robots_txt(
        "https://x.test/robots.txt", "User-agent: *\nDisallow: /\n"
    )
    assert policy.can_fetch("https://x.test/anything") is False


def test_missing_crawl_delay_is_none_not_zero() -> None:
    policy = parse_robots_txt(
        "https://x.test/robots.txt", "User-agent: *\nDisallow: /x\n"
    )
    assert policy.crawl_delay() is None


def test_sitemaps_are_exposed() -> None:
    policy = parse_robots_txt("https://www.makemytrip.com/robots.txt", SAMPLE)
    assert policy.sitemaps() == ["https://www.makemytrip.com/sitemap.xml"]


def test_empty_body_allows_everything() -> None:
    policy = parse_robots_txt("https://x.test/robots.txt", "")
    assert policy.can_fetch("https://x.test/anything") is True


def test_failed_fetch_denies_everything() -> None:
    """An unreachable robots.txt must fail closed, not open."""
    policy = RobotsPolicy.deny_all("https://x.test/robots.txt", "fetch failed")
    assert policy.can_fetch("https://x.test/anything") is False
    assert policy.crawl_delay() is None
    assert policy.sitemaps() == []


def test_denied_reason_is_reported_for_telemetry() -> None:
    policy = RobotsPolicy.deny_all("https://x.test/robots.txt", "HTTP 503")
    assert "HTTP 503" in policy.denial_reason


def test_crawl_delay_is_at_least_configured_floor() -> None:
    policy = parse_robots_txt(
        "https://x.test/robots.txt", "User-agent: *\nCrawl-delay: 0\n"
    )
    from ingestion.config import IngestionConfig

    cfg = IngestionConfig(ingestion_mode="live")
    assert policy.effective_delay(cfg) >= cfg.robots_min_delay_seconds


def test_unreachable_policy_still_applies_when_fail_open_requested() -> None:
    """An explicit fail-open opt-in is recorded, not silently applied."""
    policy = RobotsPolicy.deny_all("https://x.test/robots.txt", "fetch failed")
    assert policy.is_deny_all is True


def test_rate_limit_takes_the_stricter_of_our_floor_and_published_crawl_delay() -> None:
    """A permissive robots.txt must not let us crawl faster than our own baseline."""
    from ingestion.base import BaseScraper
    from ingestion.config import IngestionConfig
    from ingestion.robots import clear_policy_cache, parse_robots_txt

    clear_policy_cache()

    class _Scraper(BaseScraper):
        BASE_URL = "https://rate-limit.test"

        def scrape_route(self, origin, destination, target_date, window_code):
            raise NotImplementedError

        def scrape_all(self, routes, base_date, window_codes=None):
            raise NotImplementedError

    cfg = IngestionConfig(
        ingestion_mode="live",
        rate_limit_delay_seconds=5.0,
        rate_limit_jitter_seconds=0.0,
        robots_min_delay_seconds=5.0,
    )
    scraper = _Scraper(config=cfg)

    # No crawl-delay published: our own floor applies.
    import ingestion.robots as robots

    robots._POLICY_CACHE["https://rate-limit.test|APIxBot|True"] = parse_robots_txt(
        "https://rate-limit.test/robots.txt", "User-agent: *\nDisallow: /nope\n"
    )
    assert scraper.effective_rate_limit_delay() == pytest.approx(5.0)

    # A stricter published delay wins over our floor.
    robots._POLICY_CACHE["https://rate-limit.test|APIxBot|True"] = parse_robots_txt(
        "https://rate-limit.test/robots.txt", "User-agent: *\nCrawl-delay: 30\n"
    )
    assert scraper.effective_rate_limit_delay() == pytest.approx(30.0)
    clear_policy_cache()


def test_rate_limit_ignores_crawl_delay_when_robots_respected_is_off() -> None:
    from ingestion.base import BaseScraper
    from ingestion.config import IngestionConfig

    class _Scraper(BaseScraper):
        BASE_URL = "https://no-robots.test"

        def scrape_route(self, origin, destination, target_date, window_code):
            raise NotImplementedError

        def scrape_all(self, routes, base_date, window_codes=None):
            raise NotImplementedError

    cfg = IngestionConfig(
        ingestion_mode="live",
        rate_limit_delay_seconds=2.0,
        rate_limit_jitter_seconds=0.0,
        respect_robots_txt=False,
    )
    assert _Scraper(config=cfg).effective_rate_limit_delay() == pytest.approx(2.0)


def test_rfc9309_prefix_matching_does_not_block_substrings_in_other_segments() -> None:
    """RFC 9309 requires prefix matching from the beginning of the URI path."""
    policy = parse_robots_txt(
        "https://x.test/robots.txt", "User-agent: *\nDisallow: /api/\n"
    )
    assert policy.can_fetch("https://x.test/api/search") is False
    assert policy.can_fetch("https://x.test/about/api/test") is True


def test_rfc9309_unslashed_pattern_assumes_leading_slash() -> None:
    """RFC 9309 §2.2.2: If the path does not start with '/', '/' is assumed."""
    policy = parse_robots_txt(
        "https://x.test/robots.txt", "User-agent: *\nDisallow: private\n"
    )
    assert policy.can_fetch("https://x.test/private/data") is False
    assert policy.can_fetch("https://x.test/public/private") is True


def test_robots_strict_fail_closed_enabled_by_default() -> None:
    """When robots_strict_fail_closed is True (default), 404 or connection failure must fail closed."""
    from ingestion.config import IngestionConfig
    from ingestion.robots import load_policy

    cfg = IngestionConfig(ingestion_mode="live")
    assert cfg.robots_strict_fail_closed is True

    class Fake404:
        status_code = 404
        text = "Not Found"

    policy_404 = load_policy("https://strict.test", cfg, fetcher=lambda url: Fake404())
    assert policy_404.is_deny_all is True
    assert policy_404.can_fetch("https://strict.test/flights") is False

    def failing_fetcher(url: str):
        raise ConnectionError("Network unreachable")

    policy_err = load_policy("https://strict.test", cfg, fetcher=failing_fetcher)
    assert policy_err.is_deny_all is True
    assert policy_err.can_fetch("https://strict.test/flights") is False


def test_robots_strict_fail_closed_disabled_allows_on_404_or_error() -> None:
    """When robots_strict_fail_closed is False, 404 or connection failure fails open (permissive)."""
    from ingestion.config import IngestionConfig
    from ingestion.robots import load_policy

    cfg = IngestionConfig(ingestion_mode="live", robots_strict_fail_closed=False)
    assert cfg.robots_strict_fail_closed is False

    class Fake404:
        status_code = 404
        text = "Not Found"

    policy_404 = load_policy(
        "https://permissive.test", cfg, fetcher=lambda url: Fake404()
    )
    assert policy_404.is_deny_all is False
    assert policy_404.can_fetch("https://permissive.test/flights") is True

    def failing_fetcher(url: str):
        raise TimeoutError("Robots fetch timed out")

    policy_err = load_policy("https://permissive.test", cfg, fetcher=failing_fetcher)
    assert policy_err.is_deny_all is False
    assert policy_err.can_fetch("https://permissive.test/flights") is True

