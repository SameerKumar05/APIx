"""robots.txt compliance gate for tier 1 OTA scraping.

The problem statement grades ethical scraping, so the policy is enforced in code
rather than asserted in prose. Semantics follow RFC 9309: the most specific
matching rule wins, and for equal length an ``Allow`` beats a ``Disallow``.

An unreachable robots.txt fails closed. A crawler that cannot read the rules
must not decide for itself that it may proceed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from ingestion.config import IngestionConfig

DEFAULT_USER_AGENT = "APIxBot"


@dataclass
class _Rule:
    pattern: str
    allow: bool

    def matches(self, target: str) -> bool:
        """Only ``*`` and ``$`` are special in a robots.txt pattern.

        fnmatch is deliberately not used: it also treats ``?`` and ``[...]`` as
        wildcards, so a rule containing a literal query separator such as
        ``/search?`` would be silently reinterpreted as a character class.
        """
        anchored = self.pattern.endswith("$")
        body = self.pattern[:-1] if anchored else self.pattern
        regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
        if anchored:
            return re.fullmatch(regex, target) is not None
        return re.search(regex, target) is not None


@dataclass
class _Group:
    agents: List[str] = field(default_factory=list)
    rules: List[_Rule] = field(default_factory=list)
    crawl_delay: Optional[float] = None


class RobotsPolicy:
    """Parsed robots.txt for one origin, resolved for one user agent."""

    def __init__(
        self,
        robots_url: str,
        groups: List[_Group],
        sitemaps: List[str],
        denied: bool = False,
        reason: str = "",
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.robots_url = robots_url
        self._groups = groups
        self._sitemaps = sitemaps
        self._denied = denied
        self._reason = reason
        # A policy is resolved for one agent, so its accessors default to that
        # agent rather than re-resolving against a module-level constant.
        self.user_agent = user_agent

    @property
    def is_deny_all(self) -> bool:
        """True only when the policy could not be established. A robots.txt that
        was fetched successfully and simply lists no rules is not a denial."""
        return self._denied

    @property
    def denial_reason(self) -> str:
        return self._reason

    @classmethod
    def deny_all(cls, robots_url: str, reason: str) -> "RobotsPolicy":
        return cls(robots_url, [], [], denied=True, reason=reason)

    def _agent_groups(self, user_agent: str) -> List[_Group]:
        """Rules from a specifically named group and from the wildcard group are merged.

        RFC 9309 lets a crawler pick the single most specific group. For a
        compliance gate that is too permissive in practice: a site that writes
        ``Disallow: /api/`` for ``*`` and omits it from a named group clearly
        intends the path to stay closed. Merging means a named group can only add
        restrictions, never remove one, so ignoring a published Disallow is not
        reachable through this code.
        """
        agent = user_agent.split("/")[0].strip().lower()
        groups: List[_Group] = []
        named = [g for g in self._groups if any(a != "*" and a in agent for a in g.agents)]
        groups.extend(named)
        groups.extend(g for g in self._groups if "*" in g.agents)
        return groups

    def can_fetch(self, url: str, user_agent: Optional[str] = None) -> bool:
        if user_agent is None:
            user_agent = self.user_agent
        if self.is_deny_all:
            return False
        groups = self._agent_groups(user_agent)
        if not groups:
            return True
        # RFC 9309 matches the path together with the query component, so a rule
        # such as "Disallow: /*?sort=" is reachable. Matching .path alone would
        # silently never apply such a rule.
        parsed = urlparse(url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        best: Optional[_Rule] = None
        best_len = -1
        for group in groups:
            for rule in group.rules:
                if not rule.matches(path):
                    continue
                length = len(rule.pattern.rstrip("*").rstrip("$"))
                if length > best_len or (length == best_len and rule.allow and not (best and best.allow)):
                    best, best_len = rule, length
        if best is None:
            return True
        return best.allow

    def crawl_delay(self, user_agent: Optional[str] = None) -> Optional[float]:
        if user_agent is None:
            user_agent = self.user_agent
        for group in self._agent_groups(user_agent):
            if group.crawl_delay is not None:
                return group.crawl_delay
        return None

    def effective_delay(self, config: IngestionConfig, user_agent: Optional[str] = None) -> float:
        """Crawl delay with the configured floor applied, so a permissive or absent
        directive still cannot drive a crawl faster than our own ethics baseline."""
        if user_agent is None:
            user_agent = self.user_agent
        published = self.crawl_delay(user_agent)
        if published is None:
            return config.robots_min_delay_seconds
        return max(float(published), config.robots_min_delay_seconds)

    def sitemaps(self) -> List[str]:
        return list(self._sitemaps)


def parse_robots_txt(robots_url: str, text: str, user_agent: str = DEFAULT_USER_AGENT) -> RobotsPolicy:
    groups: List[_Group] = []
    sitemaps: List[str] = []
    current: Optional[_Group] = None
    expecting_agent = False

    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            if not expecting_agent:
                current = _Group()
                groups.append(current)
                expecting_agent = True
            if current is not None and value:
                current.agents.append(value.lower())
        elif key == "disallow":
            expecting_agent = False
            if current is not None and value:
                current.rules.append(_Rule(pattern=value, allow=False))
        elif key == "allow":
            expecting_agent = False
            if current is not None and value:
                current.rules.append(_Rule(pattern=value, allow=True))
        elif key == "crawl-delay":
            expecting_agent = False
            if current is not None:
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    current.crawl_delay = None
        elif key == "sitemap":
            sitemaps.append(value)

    return RobotsPolicy(robots_url, [g for g in groups if g.agents], sitemaps, user_agent=user_agent)


def robots_url_for(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def load_policy(
    base_url: str,
    config: IngestionConfig,
    user_agent: str = DEFAULT_USER_AGENT,
    fetcher: Optional[Any] = None,
) -> RobotsPolicy:
    """Fetch and parse the origin's robots.txt.

    ``fetcher`` is any callable taking a URL and returning a response object with
    ``status_code`` and ``text``. It exists so tests and offline runs can supply
    bytes without network access.
    """
    url = robots_url_for(base_url)
    if not config.respect_robots_txt:
        return parse_robots_txt(url, "", user_agent)

    try:
        if fetcher is not None:
            response = fetcher(url)
        else:
            import httpx

            with httpx.Client(timeout=config.robots_fetch_timeout_seconds) as client:
                response = client.get(url, headers={"User-Agent": user_agent})
        status = int(getattr(response, "status_code", 0))
        if status >= 400:
            return RobotsPolicy.deny_all(url, f"robots.txt returned HTTP {status}")
        return parse_robots_txt(url, getattr(response, "text", "") or "", user_agent)
    except Exception as exc:  # noqa: BLE001 - any failure must fail closed
        return RobotsPolicy.deny_all(url, f"{type(exc).__name__}: {exc}")


_POLICY_CACHE: Dict[str, RobotsPolicy] = {}


def cached_policy(base_url: str, config: IngestionConfig, user_agent: str = DEFAULT_USER_AGENT) -> RobotsPolicy:
    key = f"{base_url}|{user_agent}|{config.respect_robots_txt}"
    if key not in _POLICY_CACHE:
        _POLICY_CACHE[key] = load_policy(base_url, config, user_agent)
    return _POLICY_CACHE[key]


def clear_policy_cache() -> None:
    _POLICY_CACHE.clear()
