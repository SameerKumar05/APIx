"""Once-per-day sweep gate and the UTC cron next-run calculation.

Two schedulers must not both extract. The process lock is an flock held for the
life of the daemon; the kernel drops it when the process dies, including a
container whose pid is always 1. A completion marker stops a second ``--run-once``
on the same UTC day. A per-slot marker stops a misfired job from enqueueing twice.
"""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import TextIO, cast

from apscheduler.triggers.cron import CronTrigger


@dataclass(frozen=True, slots=True)
class SweepClaim:
    acquired: bool
    day: str
    reason: str


class DispatchMode(StrEnum):
    """How a scheduled slot is executed."""

    DIRECT = "direct"
    ENQUEUE = "enqueue"


@dataclass(frozen=True, slots=True)
class ScheduleError(Exception):
    cron_expr: str

    def __str__(self) -> str:
        return f"cron produced no next run: {self.cron_expr}"


@dataclass(frozen=True, slots=True)
class UnknownDispatch(Exception):
    raw: str

    def __str__(self) -> str:
        return f"unknown dispatch: {self.raw}"


def parse_dispatch(raw: str) -> DispatchMode:
    """Parse the process-boundary dispatch token."""
    token = raw.strip().lower()
    match token:
        case "direct":
            return DispatchMode.DIRECT
        case "enqueue":
            return DispatchMode.ENQUEUE
        case _:
            raise UnknownDispatch(raw)


def next_daily_run(cron_expr: str, now: datetime) -> datetime:
    """Next fire time of a UTC cron. ``now`` must be timezone-aware."""
    trigger = CronTrigger.from_crontab(cron_expr, timezone=UTC)
    nxt = trigger.get_next_fire_time(None, now)
    if nxt is None:
        raise ScheduleError(cron_expr)
    return cast("datetime", nxt)


def normalize_scraper_source(raw: str) -> str:
    """Map the workflow's historical ``all`` token onto the orchestrator source."""
    token = raw.strip().lower()
    if token in {"all", "sources"}:
        return "multi_source"
    return token


class SweepGate:
    """File-backed mutual exclusion for the daily sweep.

    Holds an flock fd for the process lifetime. Not a dataclass: the open file
    is the lock, and closing it is the release.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock_file: TextIO | None = None

    def _ensure(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)

    def claim_process(self) -> SweepClaim:
        """Take the daemon lock. A live holder blocks; a dead holder does not."""
        self._ensure()
        path = self._directory / "scheduler.lock"
        handle = path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return SweepClaim(acquired=False, day="", reason="lock_held")
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        self._lock_file = handle
        return SweepClaim(acquired=True, day="", reason="acquired")

    def release(self) -> None:
        handle = self._lock_file
        self._lock_file = None
        if handle is None:
            return
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

    def claim_run_once(self, day: date) -> SweepClaim:
        """Acquire the process lock unless this UTC day already completed."""
        self._ensure()
        marker = self._completed_path(day)
        if marker.is_file():
            return SweepClaim(
                acquired=False, day=day.isoformat(), reason="already_completed"
            )
        held = self.claim_process()
        if not held.acquired:
            return SweepClaim(acquired=False, day=day.isoformat(), reason=held.reason)
        if marker.is_file():
            self.release()
            return SweepClaim(
                acquired=False, day=day.isoformat(), reason="already_completed"
            )
        return SweepClaim(acquired=True, day=day.isoformat(), reason="acquired")

    def complete(self, day: date) -> None:
        """Record a finished sweep. A second complete of the same day is a no-op."""
        self._ensure()
        self._completed_path(day).write_text(day.isoformat(), encoding="utf-8")

    def claim_slot(self, day: date, job_id: str) -> bool:
        """Exclusive create. False means this slot already ran today."""
        self._ensure()
        path = self._slot_path(day, job_id)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        os.write(fd, b"1")
        os.close(fd)
        return True

    def release_slot(self, day: date, job_id: str) -> None:
        """Drop a slot marker so a failed enqueue can be retried."""
        path = self._slot_path(day, job_id)
        if path.is_file():
            path.unlink()

    def _completed_path(self, day: date) -> Path:
        return self._directory / f"completed-{day.isoformat()}"

    def _slot_path(self, day: date, job_id: str) -> Path:
        safe = job_id.replace("/", "_")
        return self._directory / f"slot-{day.isoformat()}-{safe}"
