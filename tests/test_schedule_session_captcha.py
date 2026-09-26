"""Daily schedule, session jars, and challenge classification.

Given a challenge page, the scrape outcome is blocked_by_captcha and no records
remain. Given a saved storage_state, load returns the same cookie. Given a UTC
cron and a fixed now, the next run is that clock time.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ingestion.base import RawFareRecord, ScrapeResult
from ingestion.captcha import (
    consume_challenge,
    detect_challenge,
    note_challenge,
    telemetry_status_for,
)
from ingestion.config import BOOKING_WINDOWS, DEFAULT_ROUTES
from ingestion.robots import parse_robots_txt
from ingestion.schedule_gate import SweepGate, next_daily_run, normalize_scraper_source
from ingestion.scheduler import IngestionScheduler, SchedulerConfig
from ingestion.session_store import SessionSettings, SessionStore, StorageState


def _fare() -> RawFareRecord:
    return RawFareRecord(
        airline_code="SG",
        flight_number="SG-815",
        origin="DEL",
        destination="BOM",
        departure_datetime="2026-09-27T09:50:00",
        arrival_datetime="2026-09-27T12:25:00",
        booking_datetime="2026-09-26T02:00:00",
        fare_inr=4200.0,
        is_synthetic=True,
        source="spicejet",
    )


def _settings(directory: Path, *, enabled: bool = True) -> SessionSettings:
    return SessionSettings(
        enabled=enabled,
        directory=directory,
        max_age_seconds=43200,
        max_bytes=262144,
    )


def _state() -> StorageState:
    return {
        "cookies": [{"name": "sid", "value": "abc", "domain": ".spicejet.com", "path": "/"}],
        "origins": [],
    }


def test_captcha_page_is_blocked_by_captcha_and_keeps_no_records() -> None:
    html = '<html><title>Just a moment...</title><div class="cf-turnstile"></div></html>'
    marker = detect_challenge(html, "Just a moment...")
    assert marker == "just a moment"
    note_challenge("www.spicejet.com", marker or "")
    blocked = consume_challenge(
        ScrapeResult(
            source="spicejet",
            success=True,
            records=[_fare()],
            metadata={"tier": 3, "is_live": True},
        )
    )
    assert blocked.metadata["outcome"] == "blocked_by_captcha"
    assert blocked.records == []
    assert blocked.success is False
    assert blocked.metadata["is_live"] is False
    assert telemetry_status_for(records=0, captcha_hits=1) == "CAPTCHA"


def test_synthetic_fallback_after_captcha_is_dropped() -> None:
    blocked = consume_challenge(
        ScrapeResult(
            source="spicejet",
            success=True,
            records=[_fare()],
            metadata={
                "tier": 3,
                "tier1_errors": ["Tier 1 SpiceJet failure: blocked_by_captcha:www.spicejet.com"],
            },
        )
    )
    assert blocked.metadata["outcome"] == "blocked_by_captcha"
    assert blocked.records == []
    assert blocked.success is False


def test_long_page_with_a_captcha_script_is_not_a_challenge() -> None:
    html = "x" * 80_000 + '<script src="https://www.google.com/recaptcha/api.js"></script>'
    assert detect_challenge(html, "SpiceJet flights") is None


def test_session_state_round_trips_through_save_and_load(tmp_path: Path) -> None:
    store = SessionStore(_settings(tmp_path))
    assert store.save("https://www.spicejet.com/search", _state()) is True
    loaded = store.load("www.spicejet.com")
    assert loaded is not None
    assert loaded["cookies"][0]["name"] == "sid"
    assert loaded["cookies"][0]["value"] == "abc"


def test_expired_session_is_not_loaded(tmp_path: Path) -> None:
    store = SessionStore(_settings(tmp_path))
    assert store.save("www.spicejet.com", _state()) is True
    path = next(tmp_path.glob("*.json"))
    stale = time.time() - 43201
    path.touch()
    import os

    os.utime(path, (stale, stale))
    assert store.load("www.spicejet.com") is None


def test_oversized_session_is_refused(tmp_path: Path) -> None:
    store = SessionStore(_settings(tmp_path))
    huge: StorageState = {
        "cookies": [{"name": "sid", "value": "x" * 262145, "domain": ".spicejet.com", "path": "/"}],
        "origins": [],
    }
    assert store.save("www.spicejet.com", huge) is False
    assert store.load("www.spicejet.com") is None


def test_session_reuse_off_does_not_load(tmp_path: Path) -> None:
    SessionStore(_settings(tmp_path, enabled=True)).save("www.spicejet.com", _state())
    disabled = SessionStore(_settings(tmp_path, enabled=False))
    assert disabled.save("www.spicejet.com", _state()) is False
    assert disabled.load("www.spicejet.com") is None


def test_saved_session_does_not_authorise_a_denied_path(tmp_path: Path) -> None:
    policy = parse_robots_txt(
        "https://www.makemytrip.com/robots.txt",
        "User-agent: *\nDisallow: /flight/search\n",
        user_agent="APIxBot",
    )
    store = SessionStore(_settings(tmp_path))
    saved = store.save(
        "www.makemytrip.com",
        {
            "cookies": [{"name": "sid", "value": "abc", "domain": ".makemytrip.com", "path": "/"}],
            "origins": [],
        },
    )
    assert saved is True
    assert store.load("www.makemytrip.com") is not None
    assert policy.can_fetch("https://www.makemytrip.com/flight/search") is False


def test_scheduler_next_run_is_0200_utc() -> None:
    nxt = next_daily_run("0 2 * * *", datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc))
    assert nxt == datetime(2026, 9, 26, 2, 0, tzinfo=timezone.utc)


def test_second_run_once_same_day_is_already_completed(tmp_path: Path) -> None:
    gate = SweepGate(tmp_path)
    day = date(2026, 9, 26)
    first = gate.claim_run_once(day)
    assert first.acquired is True
    assert first.reason == "acquired"
    gate.complete(day)
    gate.release()
    second = gate.claim_run_once(day)
    assert second.acquired is False
    assert second.reason == "already_completed"


def test_slot_claim_is_exclusive(tmp_path: Path) -> None:
    gate = SweepGate(tmp_path)
    assert gate.claim_slot(date(2026, 9, 26), "slot_DEL_BOM_T+1") is True
    assert gate.claim_slot(date(2026, 9, 26), "slot_DEL_BOM_T+1") is False


def test_second_process_lock_is_held(tmp_path: Path) -> None:
    first = SweepGate(tmp_path)
    second = SweepGate(tmp_path)
    assert first.claim_process().acquired is True
    held = second.claim_process()
    assert held.acquired is False
    assert held.reason == "lock_held"
    first.release()
    assert second.claim_process().acquired is True
    second.release()


def test_all_source_token_maps_to_multi_source() -> None:
    assert normalize_scraper_source("all") == "multi_source"
    assert normalize_scraper_source("easemytrip") == "easemytrip"


@pytest.mark.asyncio
async def test_paused_scheduler_exposes_0200_next_run() -> None:
    sched = IngestionScheduler(
        config=SchedulerConfig(cron_expr="0 2 * * *", jitter_min_seconds=0, jitter_max_seconds=0),
        routes=[DEFAULT_ROUTES[0]],
        windows=[BOOKING_WINDOWS[0]],
    )
    sched.start(paused=True)
    try:
        job = sched.scheduler.get_jobs()[0]
        assert job.next_run_time == next_daily_run("0 2 * * *", datetime.now(timezone.utc))
        assert job.next_run_time.hour == 2
        assert job.next_run_time.minute == 0
    finally:
        sched.shutdown()
