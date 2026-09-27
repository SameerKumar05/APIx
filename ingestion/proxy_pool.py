"""Distributed Proxy Pool Manager for APIx Ingestion Subsystem.

Provides dynamic proxy rotation, health checking, EWMA-based latency scoring,
automatic blacklisting with cooldown recovery, and seamless integration with
both Playwright browser automation and HTTP clients (httpx, requests).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("ingestion.proxy_pool")


@dataclass
class Proxy:
    """Represents a single proxy endpoint in the ingestion rotation pool."""

    ip: str
    port: int
    protocol: str = "http"  # "http", "https", "socks5"
    username: str | None = None
    password: str | None = field(default=None, repr=False)
    status: str = "active"  # "active", "degraded", "blacklisted", "testing"
    latency_ms: float = 0.0
    score: float = 100.0  # EWMA latency score (lower is better)
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    last_checked_at: datetime | None = None
    last_used_at: datetime | None = None
    blacklisted_until: datetime | None = None
    error_message: str | None = None

    def __str__(self) -> str:
        """String representation returns the safe endpoint identifier without credentials."""
        return self.identifier

    @property
    def identifier(self) -> str:
        """Unique key for this proxy endpoint."""
        return f"{self.protocol.lower()}://{self.ip}:{self.port}"

    @property
    def url(self) -> str:
        """Full URL representation including credentials if present."""
        if self.username and self.password:
            return f"{self.protocol.lower()}://{self.username}:{self.password}@{self.ip}:{self.port}"
        return f"{self.protocol.lower()}://{self.ip}:{self.port}"

    def to_dict(self) -> dict[str, Any]:
        """Serializes proxy attributes to a dictionary."""
        d = asdict(self)
        if self.last_checked_at:
            d["last_checked_at"] = self.last_checked_at.isoformat()
        if self.last_used_at:
            d["last_used_at"] = self.last_used_at.isoformat()
        if self.blacklisted_until:
            d["blacklisted_until"] = self.blacklisted_until.isoformat()
        d["identifier"] = self.identifier
        d["url"] = self.url
        return d

    def to_dict_safe(self) -> dict[str, Any]:
        """Serializes proxy attributes with sensitive credentials redacted."""
        d = self.to_dict()
        if d.get("password"):
            d["password"] = "***"
        if self.username or self.password:
            user_part = f"{self.username}:***@" if self.username else ":***@"
            d["url"] = f"{self.protocol.lower()}://{user_part}{self.ip}:{self.port}"
        return d

    def to_playwright_proxy(self) -> dict[str, str]:
        """Formats proxy options for Playwright browser.new_context(proxy=...)."""
        server = f"{self.protocol.lower()}://{self.ip}:{self.port}"
        cfg: dict[str, str] = {"server": server}
        if self.username:
            cfg["username"] = self.username
        if self.password:
            cfg["password"] = self.password
        return cfg

    def to_httpx_proxy(self) -> str:
        """Returns proxy URL suitable for httpx.Client(proxy=...)."""
        return self.url

    def is_available(self, current_time: datetime | None = None) -> bool:
        """Checks if the proxy is available for assignment, evaluating cooldowns."""
        now = current_time or datetime.now(UTC)
        if self.status == "blacklisted":
            if self.blacklisted_until and now >= self.blacklisted_until:
                # Cooldown expired, transition to testing/active
                self.status = "testing"
                self.consecutive_failures = 0
                self.blacklisted_until = None
                return True
            return False
        return self.status in ("active", "degraded", "testing")


@dataclass
class ProxyPoolConfig:
    """Configuration governing proxy health checking and blacklisting policies."""

    max_consecutive_failures: int = 3
    cooldown_seconds: float = 300.0  # 5 minutes
    degraded_latency_threshold_ms: float = 2500.0  # 2.5 seconds
    ewma_alpha: float = 0.3  # Recency weight for latency scoring
    latency_penalty_on_failure_ms: float = 1000.0
    default_timeout_seconds: float = 5.0
    health_check_url: str = "https://httpbin.org/ip"
    default_test_urls: list[str] = field(
        default_factory=lambda: [
            "https://httpbin.org/ip",
            "https://api.ipify.org?format=json",
        ]
    )


# Default synthetic / demo proxy seeds for development and testing environments
DEFAULT_DEMO_PROXIES = [
    "http://103.151.125.10:8080",
    "http://103.151.125.11:8080",
    "http://103.151.125.12:8080",
    "http://103.151.125.13:8080",
    "http://103.151.125.14:8080",
    "http://103.151.125.15:8080",
]


class ProxyPoolManager:
    """Thread-safe and async-safe proxy pool manager with EWMA latency scoring and auto-blacklisting."""

    def __init__(
        self,
        proxies: list[str | Proxy | dict[str, Any]] | None = None,
        config: ProxyPoolConfig | None = None,
        auto_seed: bool = True,
    ) -> None:
        self.config = config or ProxyPoolConfig()
        self._proxies: dict[str, Proxy] = {}
        self._lock = threading.RLock()
        self._rr_index = 0

        # Load initial proxies
        initial_list = proxies or []
        if not initial_list and auto_seed:
            env_proxies = os.getenv("APIX_PROXIES")
            if env_proxies:
                initial_list = [p.strip() for p in env_proxies.split(",") if p.strip()]
            else:
                initial_list = list(DEFAULT_DEMO_PROXIES)

        for p in initial_list:
            self.add_proxy(p)

    def __len__(self) -> int:
        with self._lock:
            return len(self._proxies)

    def _parse_proxy_input(self, proxy_in: str | Proxy | dict[str, Any]) -> Proxy:
        """Parses various proxy input representations into a standard Proxy dataclass."""
        if isinstance(proxy_in, Proxy):
            return proxy_in

        if isinstance(proxy_in, dict):
            # Parse from dictionary
            ip = str(proxy_in.get("ip", "127.0.0.1"))
            port = int(proxy_in.get("port", 8080))
            protocol = str(proxy_in.get("protocol", "http"))
            username = proxy_in.get("username")
            password = proxy_in.get("password")
            status = str(proxy_in.get("status", "active"))
            latency_ms = float(proxy_in.get("latency_ms", 100.0))
            return Proxy(
                ip=ip,
                port=port,
                protocol=protocol,
                username=username,
                password=password,
                status=status,
                latency_ms=latency_ms,
                score=latency_ms,
            )

        if isinstance(proxy_in, str):
            raw = proxy_in.strip()
            if not raw.startswith(("http://", "https://", "socks5://")):
                raw = f"http://{raw}"

            parsed = urlparse(raw)
            protocol = parsed.scheme or "http"
            ip = parsed.hostname or "127.0.0.1"
            port = parsed.port or (443 if protocol == "https" else 8080)
            username = parsed.username
            password = parsed.password
            return Proxy(
                ip=ip,
                port=port,
                protocol=protocol,
                username=username,
                password=password,
                status="active",
                latency_ms=100.0,
                score=100.0,
            )

        raise ValueError(f"Unsupported proxy input type: {type(proxy_in)}")

    def add_proxy(self, proxy_in: str | Proxy | dict[str, Any]) -> Proxy:
        """Adds or updates a proxy endpoint in the pool."""
        proxy = self._parse_proxy_input(proxy_in)
        with self._lock:
            key = proxy.identifier
            if key in self._proxies:
                # Merge existing statistics if already present
                existing = self._proxies[key]
                existing.username = proxy.username or existing.username
                existing.password = proxy.password or existing.password
                existing.protocol = proxy.protocol or existing.protocol
                return existing
            self._proxies[key] = proxy
            logger.debug("Added proxy to pool: %s", key)
            return proxy

    def remove_proxy(self, ip_or_identifier: str, port: int | None = None) -> bool:
        """Removes a proxy endpoint from the pool by identifier or ip:port."""
        with self._lock:
            if port is not None:
                key_pattern = f"://{ip_or_identifier}:{port}"
                matched_key = next(
                    (k for k in self._proxies if k.endswith(key_pattern)), None
                )
                if matched_key:
                    del self._proxies[matched_key]
                    return True
                return False

            # Try direct identifier or ip matching
            if ip_or_identifier in self._proxies:
                del self._proxies[ip_or_identifier]
                return True

            matched_key = next(
                (k for k in self._proxies if ip_or_identifier in k), None
            )
            if matched_key:
                del self._proxies[matched_key]
                return True

            return False

    def check_cooldowns(self) -> list[Proxy]:
        """Scans blacklisted proxies and restores those whose quarantine period has elapsed."""
        now = datetime.now(UTC)
        recovered: list[Proxy] = []
        with self._lock:
            for proxy in self._proxies.values():
                if proxy.status == "blacklisted":
                    if proxy.blacklisted_until and now >= proxy.blacklisted_until:
                        proxy.status = "testing"
                        proxy.consecutive_failures = 0
                        proxy.blacklisted_until = None
                        proxy.error_message = None
                        recovered.append(proxy)
                        logger.info(
                            "Proxy %s cooldown elapsed; restored to testing status",
                            proxy.identifier,
                        )
        return recovered

    def get_proxy(self, strategy: str = "best_score") -> Proxy | None:
        """Selects an available proxy from the pool according to the specified strategy.

        Strategies:
        - "best_score": Selects candidate with the lowest EWMA score.
        - "round_robin": Sequentially cycles across available candidates.
        - "random": Uniformly selects from available candidates.
        - "lowest_latency": Selects candidate with the absolute lowest raw latency.
        """
        now = datetime.now(UTC)
        with self._lock:
            # First check and recover any expired cooldowns
            self.check_cooldowns()

            available = [p for p in self._proxies.values() if p.is_available(now)]
            if not available:
                # If all proxies are blacklisted, fallback to testing candidates or the oldest blacklisted
                blacklisted = [
                    p for p in self._proxies.values() if p.status == "blacklisted"
                ]
                if blacklisted:
                    # Emergency unblacklist of the oldest blacklisted proxy to prevent complete starvation
                    emergency_candidate = min(
                        blacklisted,
                        key=lambda p: p.blacklisted_until or now,
                    )
                    emergency_candidate.status = "testing"
                    emergency_candidate.consecutive_failures = 0
                    emergency_candidate.blacklisted_until = None
                    available = [emergency_candidate]
                    logger.warning(
                        "All proxies were blacklisted! Emergency recovery applied to %s",
                        emergency_candidate.identifier,
                    )
                else:
                    return None

            selected: Proxy | None = None

            if strategy == "round_robin":
                self._rr_index = (self._rr_index + 1) % len(available)
                selected = available[self._rr_index]

            elif strategy == "random":
                selected = random.choice(available)

            elif strategy == "lowest_latency":
                selected = min(available, key=lambda p: p.latency_ms)

            else:  # Default: "best_score"
                selected = min(available, key=lambda p: p.score)

            if selected:
                selected.last_used_at = now

            return selected

    def report_success(self, proxy_ref: str | Proxy, latency_ms: float) -> None:
        """Records a successful request using the specified proxy, updating latency and EWMA score."""
        with self._lock:
            proxy = self._resolve_proxy(proxy_ref)
            if not proxy:
                return

            now = datetime.now(UTC)
            proxy.success_count += 1
            proxy.consecutive_failures = 0
            proxy.latency_ms = latency_ms
            proxy.last_used_at = now
            proxy.last_checked_at = now

            # EWMA Score Calculation: score_t = alpha * latency + (1 - alpha) * score_{t-1}
            alpha = self.config.ewma_alpha
            proxy.score = (alpha * latency_ms) + ((1.0 - alpha) * proxy.score)

            # Update status based on latency threshold
            if proxy.status in ("degraded", "testing"):
                if latency_ms <= self.config.degraded_latency_threshold_ms:
                    proxy.status = "active"
            elif proxy.status == "active":
                if latency_ms > self.config.degraded_latency_threshold_ms:
                    proxy.status = "degraded"

            logger.debug(
                "Reported success for proxy %s: latency=%.1fms, score=%.1f, status=%s",
                proxy.identifier,
                latency_ms,
                proxy.score,
                proxy.status,
            )

    def report_failure(
        self,
        proxy_ref: str | Proxy,
        error: str | None = None,
        status_code: int | None = None,
    ) -> None:
        """Records a failed request or network error, applying penalty and auto-blacklisting if warranted."""
        with self._lock:
            proxy = self._resolve_proxy(proxy_ref)
            if not proxy:
                return

            now = datetime.now(UTC)
            proxy.failure_count += 1
            proxy.consecutive_failures += 1
            proxy.last_used_at = now
            proxy.last_checked_at = now
            msg = error or (
                f"HTTP status {status_code}" if status_code else "Unknown error"
            )
            if proxy.password and proxy.password in msg:
                msg = msg.replace(proxy.password, "***")
            proxy.error_message = msg

            # Apply latency penalty to EWMA score
            proxy.score += self.config.latency_penalty_on_failure_ms

            # Check consecutive failure threshold for blacklisting
            if proxy.consecutive_failures >= self.config.max_consecutive_failures:
                self.blacklist_proxy(
                    proxy,
                    reason=f"Exceeded max consecutive failures ({proxy.consecutive_failures})",
                    cooldown_seconds=self.config.cooldown_seconds,
                )
            else:
                proxy.status = "degraded"
                logger.warning(
                    "Proxy %s failure recorded (%d/%d consecutive): %s",
                    proxy.identifier,
                    proxy.consecutive_failures,
                    self.config.max_consecutive_failures,
                    proxy.error_message,
                )

    def blacklist_proxy(
        self,
        proxy_ref: str | Proxy,
        reason: str = "Manual blacklisting",
        cooldown_seconds: float | None = None,
    ) -> None:
        """Explicitly blacklists a proxy with an optional quarantine cooldown duration."""
        with self._lock:
            proxy = self._resolve_proxy(proxy_ref)
            if not proxy:
                return

            cooldown = (
                cooldown_seconds
                if cooldown_seconds is not None
                else self.config.cooldown_seconds
            )
            now = datetime.now(UTC)
            proxy.status = "blacklisted"
            proxy.blacklisted_until = now + timedelta(seconds=cooldown)
            if proxy.password and proxy.password in reason:
                reason = reason.replace(proxy.password, "***")
            proxy.error_message = reason
            logger.warning(
                "Proxy %s blacklisted for %.0fs: %s",
                proxy.identifier,
                cooldown,
                reason,
            )

    def unblacklist_proxy(self, proxy_ref: str | Proxy) -> None:
        """Re-activates a blacklisted proxy and resets its consecutive failure count."""
        with self._lock:
            proxy = self._resolve_proxy(proxy_ref)
            if not proxy:
                return

            proxy.status = "active"
            proxy.consecutive_failures = 0
            proxy.blacklisted_until = None
            proxy.error_message = None
            logger.info("Proxy %s manually unblacklisted", proxy.identifier)

    def _resolve_proxy(self, proxy_ref: str | Proxy) -> Proxy | None:
        """Resolves a Proxy instance from either an object, identifier, or ip string."""
        if isinstance(proxy_ref, Proxy):
            return self._proxies.get(proxy_ref.identifier, proxy_ref)

        if proxy_ref in self._proxies:
            return self._proxies[proxy_ref]

        for k, p in self._proxies.items():
            if proxy_ref in (p.ip, k, p.url):
                return p

        return None

    async def health_check_proxy(
        self,
        proxy: Proxy,
        target_url: str | None = None,
        timeout: float | None = None,
    ) -> bool:
        """Performs an asynchronous health probe against a target test endpoint."""
        import httpx

        url = target_url or self.config.health_check_url
        to_sec = timeout or self.config.default_timeout_seconds
        start = time.perf_counter()

        try:
            proxy_url = proxy.to_httpx_proxy()
            async with httpx.AsyncClient(proxy=proxy_url, timeout=to_sec) as client:
                resp = await client.get(url)
                latency_ms = (time.perf_counter() - start) * 1000.0

                if resp.status_code in (200, 204):
                    self.report_success(proxy, latency_ms)
                    return True
                else:
                    self.report_failure(
                        proxy,
                        error=f"HTTP {resp.status_code}",
                        status_code=resp.status_code,
                    )
                    return False

        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            self.report_failure(proxy, error=str(exc))
            return False

    async def health_check_all(
        self,
        target_url: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Runs concurrent health checks across all registered proxies in the pool."""
        with self._lock:
            proxy_list = list(self._proxies.values())

        tasks = [
            self.health_check_proxy(p, target_url=target_url, timeout=timeout)
            for p in proxy_list
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        healthy_count = sum(1 for r in results if r is True)
        return {
            "total_tested": len(proxy_list),
            "healthy_count": healthy_count,
            "failed_count": len(proxy_list) - healthy_count,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_pool_status(self) -> dict[str, Any]:
        """Provides a statistical summary of the proxy pool for monitoring and API endpoints."""
        now = datetime.now(UTC)
        with self._lock:
            self.check_cooldowns()

            total = len(self._proxies)
            active = sum(1 for p in self._proxies.values() if p.status == "active")
            degraded = sum(1 for p in self._proxies.values() if p.status == "degraded")
            blacklisted = sum(
                1 for p in self._proxies.values() if p.status == "blacklisted"
            )
            testing = sum(1 for p in self._proxies.values() if p.status == "testing")

            active_proxies = [p for p in self._proxies.values() if p.is_available(now)]
            avg_latency = (
                sum(p.latency_ms for p in active_proxies) / len(active_proxies)
                if active_proxies
                else 0.0
            )
            avg_score = (
                sum(p.score for p in active_proxies) / len(active_proxies)
                if active_proxies
                else 0.0
            )

            return {
                "total": total,
                "active": active,
                "degraded": degraded,
                "blacklisted": blacklisted,
                "testing": testing,
                "available_count": len(active_proxies),
                "avg_latency_ms": round(avg_latency, 2),
                "avg_score": round(avg_score, 2),
                "proxies": [p.to_dict_safe() for p in self._proxies.values()],
            }

    def get_active_proxies(self) -> list[Proxy]:
        """Returns all currently available active and degraded proxies."""
        now = datetime.now(UTC)
        with self._lock:
            self.check_cooldowns()
            return [p for p in self._proxies.values() if p.is_available(now)]

    def reset_metrics(self) -> None:
        """Resets success, failure, and score statistics for all proxies."""
        with self._lock:
            for p in self._proxies.values():
                p.success_count = 0
                p.failure_count = 0
                p.consecutive_failures = 0
                p.latency_ms = 100.0
                p.score = 100.0
                p.status = "active"
                p.blacklisted_until = None
                p.error_message = None


# Singleton instance container
_GLOBAL_PROXY_POOL: ProxyPoolManager | None = None
_GLOBAL_POOL_LOCK = threading.Lock()


def get_proxy_pool(
    config: ProxyPoolConfig | None = None,
    initial_proxies: list[str | Proxy | dict[str, Any]] | None = None,
) -> ProxyPoolManager:
    """Returns the process-wide singleton ProxyPoolManager instance."""
    global _GLOBAL_PROXY_POOL
    with _GLOBAL_POOL_LOCK:
        if _GLOBAL_PROXY_POOL is None:
            _GLOBAL_PROXY_POOL = ProxyPoolManager(
                proxies=initial_proxies,
                config=config,
            )
        return _GLOBAL_PROXY_POOL
