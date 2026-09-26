"""Challenge-page detection for tier-1 scrapes.

Detect and report. This module never solves, clicks through, or retries a
challenge. A classified page is a failed scrape: no records, not live data.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Final

from ingestion.base import ScrapeResult

BLOCKED_BY_CAPTCHA: Final = "blocked_by_captcha"
TELEMETRY_STATUS: Final = "CAPTCHA"
DEFAULT_BACKOFF_SECONDS: Final = 900

_TITLE = re.compile(
    r"just a moment|attention required|verify you are human|are you a robot|"
    r"security check|please verify you are",
    re.IGNORECASE,
)
_INTERSTITIAL = re.compile(
    r"cf-turnstile|cf-challenge|cf-browser-verification|challenges\.cloudflare\.com|"
    r"g-recaptcha|google\.com/recaptcha|h-captcha|js\.hcaptcha\.com|"
    r"id=[\"']captcha|class=[\"'][^\"']*captcha|"
    r"px-captcha|geo\.captcha-delivery|"
    r"verify you are human|are you a robot|please complete the security check",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CaptchaVerdict:
    """A page that is a challenge, not a fare result."""

    outcome: str
    marker: str
    origin: str


@dataclass(frozen=True, slots=True)
class CaptchaBackoff(Exception):
    """Raised before navigation when this origin is still in cooldown.

    The crawler treats this as a tier-1 failure and may fall through to
    synthetic data. ``consume_challenge`` strips that fallback. The exception
    text carries the outcome token so the strip still works if the note is lost.
    """

    origin: str
    marker: str

    def __str__(self) -> str:
        return f"{BLOCKED_BY_CAPTCHA}:{self.origin}"


@dataclass(frozen=True, slots=True)
class _Noted:
    origin: str
    marker: str


_local = threading.local()


def detect_challenge(html: str, title: str) -> str | None:
    """Return the matched marker, or None when the page is not a challenge.

    A long page that merely ships a captcha script is not classified. Challenge
    titles match at any length. Widget markup matches only on a short page, which
    is what an interstitial actually is.
    """
    title_match = _TITLE.search(title)
    if title_match is not None:
        return title_match.group(0).lower()
    if len(html) >= 80_000:
        return None
    body_match = _INTERSTITIAL.search(html)
    if body_match is None:
        return None
    return body_match.group(0).lower()


def note_challenge(origin: str, marker: str) -> None:
    """Remember a challenge on this thread until ``consume_challenge`` reads it."""
    _local.verdict = _Noted(origin=origin, marker=marker)


def take_challenge() -> CaptchaVerdict | None:
    """Pop the thread-local note, if the scrape that just returned hit one."""
    noted: _Noted | None = getattr(_local, "verdict", None)
    _local.verdict = None
    if noted is None:
        return None
    return CaptchaVerdict(outcome=BLOCKED_BY_CAPTCHA, marker=noted.marker, origin=noted.origin)


def block_result(result: ScrapeResult, marker: str) -> ScrapeResult:
    """Replace any records, including synthetic fallback, with a captcha failure."""
    metadata = dict(result.metadata)
    metadata["outcome"] = BLOCKED_BY_CAPTCHA
    metadata["captcha_marker"] = marker
    metadata["records_count"] = 0
    metadata["is_live"] = False
    metadata["backoff_seconds"] = DEFAULT_BACKOFF_SECONDS
    return ScrapeResult(
        source=result.source,
        success=False,
        records=[],
        errors=[BLOCKED_BY_CAPTCHA],
        duration_ms=result.duration_ms,
        metadata=metadata,
    )


def _list_mentions_block(values: list[str]) -> bool:
    return any(BLOCKED_BY_CAPTCHA in item for item in values)


def consume_challenge(result: ScrapeResult) -> ScrapeResult:
    """Drop records when this scrape hit a challenge or inherited that failure.

    Synthetic fallback after a challenge still carries the token in
    ``tier1_errors``. Those records must not be ingested as live or as a
    successful empty scrape.
    """
    verdict = take_challenge()
    if verdict is not None:
        return block_result(result, verdict.marker)
    if _list_mentions_block(result.errors):
        return block_result(result, "error")
    tier1 = result.metadata.get("tier1_errors")
    if isinstance(tier1, list) and _list_mentions_block([str(item) for item in tier1]):
        return block_result(result, "tier1")
    return result


def telemetry_status_for(*, records: int, captcha_hits: int) -> str:
    """Status string written to scraper telemetry.

    ``CAPTCHA`` is already a failure classification. ``PARTIAL`` is not: a
    challenge with no fares must not land there.
    """
    if captcha_hits > 0 and records == 0:
        return TELEMETRY_STATUS
    if records > 0:
        return "SUCCESS"
    return "PARTIAL"
