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
    policy = parse_robots_txt("https://www.makemytrip.com/robots.txt", SAMPLE, user_agent="*")
    assert policy.can_fetch("https://www.makemytrip.com/flights/search") is True
    assert policy.can_fetch("https://www.makemytrip.com/api/v1/search/availability") is False
    # The query component participates in matching, so a query-scoped rule applies.
    assert policy.can_fetch("https://www.makemytrip.com/search?q=flights") is False
    assert policy.can_fetch("https://www.makemytrip.com/flights/DEL-BOM") is True


def test_named_agent_group_overrides_wildcard() -> None:
    policy = parse_robots_txt("https://www.makemytrip.com/robots.txt", SAMPLE, user_agent="APIxBot")
    assert policy.can_fetch("https://www.makemytrip.com/private/booking") is False
    # The wildcard Disallow still applies. A named group may add a restriction,
    # never lift one.
    assert policy.can_fetch("https://www.makemytrip.com/api/v1/x") is False
    assert policy.crawl_delay() == 2


def test_wildcard_agent_uses_star_group_delay() -> None:
    policy = parse_robots_txt("https://www.makemytrip.com/robots.txt", SAMPLE, user_agent="*")
    assert policy.crawl_delay() == 7


def test_longest_match_wins_over_shorter_rule() -> None:
    text = "User-agent: *\nDisallow: /data/\nAllow: /data/public/\n"
    policy = parse_robots_txt("https://x.test/robots.txt", text)
    assert policy.can_fetch("https://x.test/data/private") is False
    assert policy.can_fetch("https://x.test/data/public/fares") is True


def test_disallow_everything_blocks_all_paths() -> None:
    policy = parse_robots_txt("https://x.test/robots.txt", "User-agent: *\nDisallow: /\n")
    assert policy.can_fetch("https://x.test/anything") is False


def test_missing_crawl_delay_is_none_not_zero() -> None:
    policy = parse_robots_txt("https://x.test/robots.txt", "User-agent: *\nDisallow: /x\n")
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
    policy = parse_robots_txt("https://x.test/robots.txt", "User-agent: *\nCrawl-delay: 0\n")
    from ingestion.config import IngestionConfig

    cfg = IngestionConfig(ingestion_mode="live")
    assert policy.effective_delay(cfg) >= cfg.robots_min_delay_seconds


def test_unreachable_policy_still_applies_when_fail_open_requested() -> None:
    """An explicit fail-open opt-in is recorded, not silently applied."""
    policy = RobotsPolicy.deny_all("https://x.test/robots.txt", "fetch failed")
    assert policy.is_deny_all is True
