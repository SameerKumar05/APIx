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

from backend.app.db.seed import INITIAL_AIRLINES
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
    "seed airline market shares": {
        a["code"]: a["market_share_pct"] / 100.0 for a in INITIAL_AIRLINES
    },
}


@pytest.mark.parametrize("name,table", sorted(TABLES.items()))
def test_every_weight_table_sums_to_one(name: str, table: dict) -> None:
    total = sum(table.values())
    assert total == pytest.approx(1.0, abs=1e-9), f"{name} sums to {total}, not 1.0"


def test_index_airline_shares_match_the_airline_master_data() -> None:
    master = {airline.code: airline.market_share for airline in AIRLINES}
    assert DEFAULT_AIRLINE_MARKET_SHARES == pytest.approx(master)


def test_seed_airline_shares_match_index_engine_and_ingestion() -> None:
    seed_shares = {a["code"]: a["market_share_pct"] / 100.0 for a in INITIAL_AIRLINES}
    assert seed_shares == pytest.approx(DEFAULT_AIRLINE_MARKET_SHARES)
    master = {airline.code: airline.market_share for airline in AIRLINES}
    assert seed_shares == pytest.approx(master)


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
    )
    from backend.app.services.index_pipeline import (
        DEFAULT_WINDOW_WEIGHTS as PIPELINE_WINDOW_WEIGHTS,
    )

    canonical_weights = {
        code: weight for code, weight in PIPELINE_WINDOW_WEIGHTS.items() if "+" in code
    }
    assert sum(canonical_weights.values()) == pytest.approx(1.0, abs=1e-9)
    assert set(canonical_weights.keys()) == set(CANONICAL_WINDOWS)
    for code, weight in DEFAULT_BOOKING_WINDOW_WEIGHTS.items():
        assert PIPELINE_WINDOW_WEIGHTS[code] == pytest.approx(weight)
        assert PIPELINE_WINDOW_WEIGHTS[f"T+{code[1:]}"] == pytest.approx(weight)


def test_pipeline_and_index_engine_route_weights_match() -> None:
    from backend.app.services.index_pipeline import DEFAULT_ROUTE_WEIGHTS

    assert sum(DEFAULT_ROUTE_WEIGHTS.values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES.values()) == pytest.approx(
        1.0, abs=1e-9
    )
    for route_code, weight in DEFAULT_ROUTE_WEIGHTS.items():
        assert DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES[route_code] == pytest.approx(
            weight, abs=1e-9
        )


def test_base_period_fares_defined_for_all_corridors() -> None:
    from backend.app.services.index_pipeline import (
        DEFAULT_BASE_FARES,
        DEFAULT_ROUTE_WEIGHTS,
    )

    for route_code in DEFAULT_ROUTE_WEIGHTS:
        assert route_code in DEFAULT_BASE_FARES
        assert DEFAULT_BASE_FARES[route_code] > 0

    for corridor in ["DEL-MAA", "MAA-DEL", "BLR-HYD", "HYD-BLR"]:
        assert corridor in DEFAULT_BASE_FARES
        assert DEFAULT_BASE_FARES[corridor] > 0


def test_dgca_traffic_weights_table_provenance() -> None:
    from pathlib import Path
    from ingestion.loaders.dgca_traffic_loader import DgcaTrafficLoader

    data_dir = Path(__file__).resolve().parents[1] / "data"
    csv_path = data_dir / "dgca_passenger_traffic_weights.csv"
    json_path = data_dir / "dgca_passenger_traffic_weights.json"

    assert csv_path.exists(), "CSV weights table missing"
    assert json_path.exists(), "JSON weights table missing"

    for path in [csv_path, json_path]:
        loader = DgcaTrafficLoader(data_path=path)
        prov = loader.provenance
        assert prov["is_synthetic"] is True, f"{path.name} not marked synthetic"
        assert prov["record_count"] >= 270
        assert len(loader._records) >= 270

        first_rec = loader._records[0]
        assert first_rec.is_synthetic is True
        assert first_rec.provenance in ("calibrated_baseline", "modelled_dgca_proxy")
        assert first_rec.source_url.startswith("https://www.dgca.gov.in")
        assert first_rec.release_date
        assert first_rec.pax_volume > 0
        assert first_rec.share_weight > 0
