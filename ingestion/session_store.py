"""Per-origin Playwright storage_state, off unless explicitly enabled.

Reuse does not authorise a request. Callers still run robots_gate and the rate
limiter before opening a context. A denied path stays denied.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypedDict
from urllib.parse import urlparse

DEFAULT_MAX_AGE_SECONDS: Final = 43_200
DEFAULT_MAX_BYTES: Final = 262_144


class StoredCookie(TypedDict, total=False):
    name: str
    value: str
    domain: str
    path: str
    expires: float
    httpOnly: bool
    secure: bool
    sameSite: str


class StoredItem(TypedDict):
    name: str
    value: str


class StoredOrigin(TypedDict):
    origin: str
    localStorage: list[StoredItem]


class StorageState(TypedDict):
    cookies: list[StoredCookie]
    origins: list[StoredOrigin]


@dataclass(frozen=True, slots=True)
class SessionSettings:
    """Boundary-parsed session configuration."""

    enabled: bool
    directory: Path
    max_age_seconds: int
    max_bytes: int


@dataclass(frozen=True, slots=True)
class InvalidOrigin(Exception):
    """Raised when a session key is not a hostname."""

    raw: str

    def __str__(self) -> str:
        return f"invalid origin: {self.raw}"


@dataclass(frozen=True, slots=True)
class InvalidStorageState(Exception):
    """Raised when persisted JSON is not a Playwright storage_state document."""

    reason: str

    def __str__(self) -> str:
        return self.reason


def _env_flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def session_settings_from_env() -> SessionSettings:
    """Read session settings once at the process boundary.

    Reuse defaults off. A stale cookie jar is a liability on airline portals,
    and nothing here has shown that reuse improves a permitted fetch.
    """
    return SessionSettings(
        enabled=_env_flag("SCRAPER_SESSION_REUSE", "0"),
        directory=Path(os.getenv("SCRAPER_SESSION_DIR", "artifacts/scraper-sessions")),
        max_age_seconds=_env_int(
            "SCRAPER_SESSION_MAX_AGE_SECONDS", DEFAULT_MAX_AGE_SECONDS
        ),
        max_bytes=_env_int("SCRAPER_SESSION_MAX_BYTES", DEFAULT_MAX_BYTES),
    )


def origin_host(value: str) -> str:
    """Normalise a URL or host to a lowercase hostname."""
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").lower()
    if not host or host in {".", ".."}:
        raise InvalidOrigin(value)
    return host


def parse_storage_state(payload: Mapping[str, Any]) -> StorageState:
    """Accept a Playwright storage_state document or raise."""
    cookies = payload["cookies"]
    origins = payload["origins"]
    if not isinstance(cookies, list) or not isinstance(origins, list):
        raise InvalidStorageState("storage_state cookies and origins must be lists")
    return StorageState(cookies=cookies, origins=origins)


class SessionStore:
    """Save and load one storage_state file per origin.

    A second save overwrites. A crashed write leaves a ``.tmp`` file, which load
    ignores and startup deletes.
    """

    def __init__(self, settings: SessionSettings) -> None:
        self._settings = settings
        if settings.enabled:
            settings.directory.mkdir(parents=True, exist_ok=True)
            self._drop_partial_writes()

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    def _path(self, host: str) -> Path:
        digest = hashlib.sha256(host.encode("utf-8")).hexdigest()[:16]
        return self._settings.directory / f"{digest}.json"

    def _drop_partial_writes(self) -> None:
        for leftover in self._settings.directory.glob("*.tmp"):
            leftover.unlink()

    def load(self, origin: str) -> StorageState | None:
        """Return a fresh state, or None when reuse is off, missing, stale, or oversized."""
        if not self._settings.enabled:
            return None
        host = origin_host(origin)
        path = self._path(host)
        if not path.is_file():
            return None
        if path.stat().st_size > self._settings.max_bytes:
            path.unlink()
            return None
        if time.time() - path.stat().st_mtime > self._settings.max_age_seconds:
            path.unlink()
            return None
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError):
            path.unlink()
            return None
        if not isinstance(parsed, dict):
            path.unlink()
            return None
        try:
            return parse_storage_state(parsed)
        except (InvalidStorageState, KeyError):
            path.unlink()
            return None

    def save(self, origin: str, state: StorageState) -> bool:
        """Atomically replace the origin file. False when reuse is off or over the cap."""
        if not self._settings.enabled:
            return False
        host = origin_host(origin)
        encoded = json.dumps(state, separators=(",", ":")).encode("utf-8")
        if len(encoded) > self._settings.max_bytes:
            return False
        self._settings.directory.mkdir(parents=True, exist_ok=True)
        target = self._path(host)
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(target)
        return True

    def discard(self, origin: str) -> None:
        """Drop a jar. A challenge page must not be reused as a session."""
        if not self._settings.enabled:
            return
        path = self._path(origin_host(origin))
        if path.is_file():
            path.unlink()


def cookies_for_host(state: StorageState, host: str) -> list[StoredCookie]:
    """Cookies whose domain matches the host about to be fetched."""
    matched: list[StoredCookie] = []
    for cookie in state["cookies"]:
        domain = str(cookie.get("domain", "")).lstrip(".").lower()
        if not domain:
            continue
        if host == domain or host.endswith("." + domain):
            matched.append(cookie)
    return matched
