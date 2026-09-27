"""Pytest test suite for Ingestion Scheduler and Proxy Pool.

Exercises the full 70-slot matrix (14 routes x 5 booking windows)
and proxy rotation, scoring, and lifecycle.
"""

from __future__ import annotations

import pytest

from scripts.test_scheduler_and_proxies import (
    test_proxy_pool_management,
    test_scheduler_orchestration,
)


@pytest.mark.asyncio
async def test_scheduler_orchestration_70_slots() -> None:
    """Validate scheduler job registration and execution across 70 slots."""
    await test_scheduler_orchestration()


def test_proxy_pool_scoring_and_rotation() -> None:
    """Validate proxy pool latency scoring and rotation."""
    test_proxy_pool_management()
