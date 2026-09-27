"""Every weight table in the system must agree and sum to exactly 1.0.

Three separate "DGCA" weight tables had drifted apart: the index engine's
airline shares summed to 0.99 while claiming to be official, its booking-window
table omitted the T+45 window entirely, and three different route-weight tables
carried different values. None of that failed a test, because each table was
only ever checked in isolation.

These tests compare the tables against each other, which is the only way a drift
between them can be caught.
"""

from __future__ import annotations

import pytest

from backend.app.services.econometric_engine import DEFAULT_LEAD_TIME_PAX_SHARES
from backend.app.services.index_engine import (
    DEFAULT_AIRLINE_MARKET_SHARES,
    DEFAULT_BOOKING_WINDOW_WEIGHTS,
    DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
)
from ingestion.config import AIRLINES, BOOKING_WINDOWS

TABLES = {
    "airline market shares": DEFAULT_AIRLINE_MARKET_SHARES,
    "booking window weights": DEFAULT_BOOKING_WINDOW_WEIGHTS,
    "route traffic shares": DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
    "canonical lead-time shares": DEFAULT_LEAD_TIME_PAX_SHARES,
}


@pytest.mark.parametrize("name,table", sorted(TABLES.items()))
def test_every_weight_table_sums_to_one(name: str, table: dict) -> None:
    total = sum(table.values())
    assert total == pytest.approx(1.0, abs=1e-9), f"{name} sums to {total}, not 1.0"


def test_index_airline_shares_match_the_airline_master_data() -> None:
    master = {airline.code: airline.market_share for airline in AIRLINES}
    assert DEFAULT_AIRLINE_MARKET_SHARES == pytest.approx(master)


def test_booking_window_weights_cover_every_configured_window() -> None:
    configured = {w.code.replace("+", "") for w in BOOKING_WINDOWS}
    assert set(DEFAULT_BOOKING_WINDOW_WEIGHTS) == configured


def test_booking_window_weights_match_the_canonical_lead_time_shares() -> None:
    canonical = {
        code.replace("+", ""): share
        for code, share in DEFAULT_LEAD_TIME_PAX_SHARES.items()
    }
    assert DEFAULT_BOOKING_WINDOW_WEIGHTS == pytest.approx(canonical)


def test_no_table_is_labelled_as_an_official_dgca_release() -> None:
    """These are modelled. A future edit must not reintroduce the false claim."""
    import inspect

    import backend.app.services.index_engine as engine

    source = inspect.getsource(engine)
    assert "Official DGCA" not in source


def test_seed_airline_shares_sum_to_one_hundred_percent() -> None:
    from backend.app.db.seed import INITIAL_AIRLINES

    total = sum(a["market_share_pct"] for a in INITIAL_AIRLINES)
    assert total == pytest.approx(100.0, abs=1e-9)
    for a in INITIAL_AIRLINES:
        assert a["market_share_pct"] == pytest.approx(
            DEFAULT_AIRLINE_MARKET_SHARES[a["code"]] * 100.0
        )


def test_pipeline_window_weights_match_index_engine() -> None:
    from backend.app.services.index_pipeline import (
        CANONICAL_WINDOWS,
        DEFAULT_WINDOW_WEIGHTS as PIPELINE_WINDOW_WEIGHTS,
    )

    canonical_weights = {
        code: weight
        for code, weight in PIPELINE_WINDOW_WEIGHTS.items()
        if "+" in code
    }
    assert sum(canonical_weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert set(canonical_weights.keys()) == set(CANONICAL_WINDOWS)
    for code, weight in DEFAULT_BOOKING_WINDOW_WEIGHTS.items():
        assert PIPELINE_WINDOW_WEIGHTS[code] == pytest.approx(weight)
        assert PIPELINE_WINDOW_WEIGHTS[f"T+{code[1:]}"] == pytest.approx(weight)

