"""Rate limiting on the API surface the PS wants NSO and RBI to consume.

That surface was unauthenticated and unthrottled, so a single client could
exhaust it. These tests pin the limiter's contract.

The middleware is exercised on a bare app rather than the real one. Reloading
backend.app.main would replace the module-level app that other test modules
imported, so their dependency_overrides would silently apply to a different
object. Building a throwaway app keeps this test hermetic.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.main import RateLimitMiddleware


def _app(limit: int, window: int = 60) -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(RateLimitMiddleware, requests=limit, window_seconds=window)
    return app


def test_requests_beyond_the_limit_return_429_with_retry_headers() -> None:
    with TestClient(_app(limit=3)) as client:
        codes = [client.get("/ping").status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200]
        assert codes[3:] == [429, 429]

        blocked = client.get("/ping")
        assert int(blocked.headers["Retry-After"]) >= 1
        assert blocked.headers["X-RateLimit-Limit"] == "3"
        assert blocked.headers["X-RateLimit-Remaining"] == "0"


def test_allowed_responses_advertise_remaining_budget() -> None:
    with TestClient(_app(limit=3)) as client:
        assert client.get("/ping").headers["X-RateLimit-Remaining"] == "2"
        client.get("/ping")
        assert client.get("/ping").headers["X-RateLimit-Remaining"] == "0"


def test_limit_of_zero_disables_throttling() -> None:
    with TestClient(_app(limit=0)) as client:
        assert all(client.get("/ping").status_code == 200 for _ in range(10))


def test_window_expiry_restores_budget() -> None:
    import time

    with TestClient(_app(limit=2, window=1)) as client:
        assert [client.get("/ping").status_code for _ in range(3)] == [200, 200, 429]
        time.sleep(1.1)
        assert client.get("/ping").status_code == 200


def test_real_app_exposes_rate_limit_headers() -> None:
    """The deployed app, not a stand-in, must actually be limited."""
    from backend.app.main import app

    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert "X-RateLimit-Limit" in response.headers
        assert int(response.headers["X-RateLimit-Limit"]) > 0
