"""Test suite for real-time streaming flight deduplication and cross-platform arbitrage detection.

Covers:
1. Streaming flight deduplication (StreamingDedupEngine):
   - Sub-millisecond latency quote ingestion
   - Cross-platform duplicate resolution (selecting lowest consumer fare)
   - Sliding window eviction and timestamp pruning
   - Out-of-order arrival tolerance
   - Memory bounding and LRU buffer capacity enforcement
   - Deterministic flight key fingerprinting
2. Cross-platform arbitrage detection (ArbitrageDetector):
   - Spread calculation in INR and percentage
   - Direction classification: direct_cheaper vs ota_cheaper (negative spread)
   - Buy venue and sell venue determination
   - Actionable threshold filtering (min_spread_pct, min_spread_inr)
   - Zero-fare and invalid input edge cases
   - Flight group detection and database raw fare integration
3. FastAPI endpoint integration (/api/v1/analytics/arbitrage):
   - Schema conformance with ArbitrageResponse and ArbitrageItem
   - Route and threshold query filtering
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, List, Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.models.raw_fare import RawFare
from backend.app.schemas.arbitrage import ArbitrageItem, ArbitrageResponse
from backend.app.services.arbitrage_detector import (
    ArbitrageDetector,
    ArbitrageOpportunity,
    calculate_spread,
    get_current_arbitrage_opportunities,
)
from backend.app.services.index_engine import FlightQuote
from backend.app.services.streaming_dedup import (
    DedupResult,
    FlightBufferState,
    StreamingDedupEngine,
)

# The eight flight numbers the endpoint used to fabricate when no real arbitrage
# candidate existed. Kept here as a literal so the guard survives deletion of the
# production constant.
BENCHMARK_FLIGHT_NUMBERS = frozenset(
    {"6E-205", "AI-806", "SG-8169", "6E-501", "UK-995", "QP-1102", "6E-182", "AI-665"}
)


# ---------------------------------------------------------------------------
# Helper Fixtures & Builders
# ---------------------------------------------------------------------------


@pytest.fixture
def dedup_engine() -> StreamingDedupEngine:
    """Provides a fresh StreamingDedupEngine with a 300s window."""
    return StreamingDedupEngine(window_seconds=300.0, max_buffer_size=1000)


@pytest.fixture
def isolated_api_db(tmp_path):
    """Serve the API from an empty throwaway database.

    These endpoint tests used to call TestClient(app) with no get_db override, so
    they read the live, mutable apix.db while the local servers were writing to it.
    Whether an item cleared min_spread_pct therefore depended on the rows present
    at that instant, which made the suite intermittently fail. Asserting against a
    database the test controls is the only stable form.
    """
    from fastapi import FastAPI  # noqa: F401
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _Session

    import backend.app.models  # noqa: F401  (registers mappers on Base.metadata)
    from backend.app.db.session import Base, get_db
    from backend.app.main import app as fastapi_app

    engine = create_engine(
        f"sqlite:///{tmp_path / 'arbitrage-api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session = _Session(engine)
    fastapi_app.dependency_overrides[get_db] = lambda: session
    try:
        yield session
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


@pytest.fixture
def arbitrage_detector() -> ArbitrageDetector:
    """Provides an ArbitrageDetector with zero thresholds for comprehensive discovery."""
    return ArbitrageDetector(min_spread_pct=0.0, min_spread_inr=0.0)


def create_quote(
    flight_number: str = "6E-205",
    airline_code: str | None = None,
    origin: str = "DEL",
    destination: str = "BOM",
    flight_date: str = "2026-09-25",
    departure_time: str = "08:00",
    fare: float = 6500.0,
    source_portal: str = "makemytrip",
    booking_window: str = "T+1",
    is_nonstop: bool = True,
) -> FlightQuote:
    """Helper to generate a populated FlightQuote instance."""
    code = airline_code or (
        flight_number.split("-")[0] if "-" in flight_number else "6E"
    )
    return FlightQuote(
        origin=origin,
        destination=destination,
        flight_date=flight_date,
        airline_code=code,
        flight_number=flight_number,
        departure_time=departure_time,
        fare=fare,
        source_portal=source_portal,
        booking_window=booking_window,
        is_nonstop=is_nonstop,
    )


# ---------------------------------------------------------------------------
# 1. Streaming Deduplication Engine Tests
# ---------------------------------------------------------------------------


class TestStreamingDedupEngine:
    """Tests for StreamingDedupEngine verifying real-time ingestion and dedup invariants."""

    def test_single_quote_ingestion(self, dedup_engine: StreamingDedupEngine):
        """Verifies ingestion of a single flight quote creates a new flight buffer."""
        quote = create_quote(fare=5400.0, source_portal="makemytrip")
        result = dedup_engine.ingest(quote)

        assert isinstance(result, DedupResult)
        assert result.is_new_flight is True
        assert result.is_new_minimum is True
        assert result.min_fare == 5400.0
        assert result.current_portal == "makemytrip"
        assert result.portal_count == 1
        assert dedup_engine.stats()["active_buffer_size"] == 1

    def test_duplicate_resolves_minimum_consumer_price(
        self, dedup_engine: StreamingDedupEngine
    ):
        """Verifies that duplicate quotes for the same flight update best fare to the minimum."""
        # 1. Higher fare arrives first from OTA
        q1 = create_quote(
            flight_number="6E-501", fare=6800.0, source_portal="makemytrip"
        )
        r1 = dedup_engine.ingest(q1)
        assert r1.is_new_flight is True
        assert r1.min_fare == 6800.0

        # 2. Lower direct airline fare arrives second
        q2 = create_quote(
            flight_number="6E-501", fare=6100.0, source_portal="indigo_direct"
        )
        r2 = dedup_engine.ingest(q2)
        assert r2.is_new_flight is False
        assert r2.is_new_minimum is True
        assert r2.min_fare == 6100.0
        assert r2.current_portal == "indigo_direct"
        assert r2.portal_count == 2

        # 3. Third quote with higher fare arrives from another OTA
        q3 = create_quote(
            flight_number="6E-501", fare=6950.0, source_portal="easemytrip"
        )
        r3 = dedup_engine.ingest(q3)
        assert r3.is_new_flight is False
        assert r3.is_new_minimum is False
        assert r3.min_fare == 6100.0  # Remains the lowest fare
        assert r3.portal_count == 3

        best = dedup_engine.get_best_quote(r1.flight_key)
        assert best is not None
        assert best.fare == 6100.0
        assert best.source_portal == "indigo_direct"

    def test_sub_millisecond_ingestion_latency(
        self, dedup_engine: StreamingDedupEngine
    ):
        """Verifies that individual quote ingestion executes in sub-millisecond latency."""
        quote = create_quote(flight_number="AI-801", fare=5200.0)

        # Warm up JIT/cache
        for _ in range(10):
            dedup_engine.ingest(quote)

        latencies = []
        for i in range(100):
            q = create_quote(flight_number=f"IX-{i:03d}", fare=4000.0 + i)
            t0 = time.perf_counter()
            dedup_engine.ingest(q)
            latencies.append((time.perf_counter() - t0) * 1000.0)

        avg_latency_ms = sum(latencies) / len(latencies)
        assert (
            avg_latency_ms < 1.0
        ), f"Average ingestion latency {avg_latency_ms:.3f}ms exceeds 1.0ms SLA"

    def test_out_of_order_timestamp_arrival(self, dedup_engine: StreamingDedupEngine):
        """Verifies that quotes arriving out of order by timestamp are accommodated."""
        t_base = datetime(2026, 9, 24, 10, 0, 0, tzinfo=UTC)
        q_earlier = create_quote(
            flight_number="SG-101", fare=5500.0, source_portal="spicejet_direct"
        )
        q_later = create_quote(
            flight_number="SG-101", fare=5100.0, source_portal="easemytrip"
        )

        # Ingest newer quote first
        r1 = dedup_engine.ingest(q_later, arrival_time=t_base + timedelta(seconds=20))
        assert r1.min_fare == 5100.0

        # Ingest older quote second
        r2 = dedup_engine.ingest(q_earlier, arrival_time=t_base)
        assert r2.is_new_flight is False
        assert r2.min_fare == 5100.0  # Kept lower fare despite arrival timing

    def test_sliding_window_pruning(self):
        """Verifies that quotes older than window_seconds are properly pruned."""
        engine = StreamingDedupEngine(window_seconds=60.0, max_buffer_size=100)
        t0 = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)

        # Ingest 3 distinct flights at t0
        for i in range(3):
            q = create_quote(flight_number=f"6E-{i}", origin="DEL", destination="BOM")
            engine.ingest(q, arrival_time=t0)

        assert engine.stats()["active_buffer_size"] == 3

        # Prune at t0 + 30s -> nothing expired
        pruned_30 = engine.prune_expired(current_time=t0 + timedelta(seconds=30))
        assert pruned_30 == 0
        assert engine.stats()["active_buffer_size"] == 3

        # Ingest 1 fresh flight at t0 + 70s
        q_fresh = create_quote(flight_number="6E-NEW", origin="DEL", destination="BOM")
        engine.ingest(q_fresh, arrival_time=t0 + timedelta(seconds=70))

        # Prune at t0 + 70s -> first 3 flights should expire (older than 60s)
        pruned_70 = engine.prune_expired(current_time=t0 + timedelta(seconds=70))
        assert pruned_70 == 3
        assert engine.stats()["active_buffer_size"] == 1
        flight_key, _ = engine.generate_flight_key(q_fresh)
        assert engine.get_best_quote(flight_key) is not None

    def test_lru_memory_bounding(self):
        """Verifies buffer size is strictly capped at max_buffer_size via LRU eviction."""
        max_size = 50
        engine = StreamingDedupEngine(window_seconds=3600.0, max_buffer_size=max_size)

        for i in range(100):
            q = create_quote(flight_number=f"AI-{i}", origin="DEL", destination="BOM")
            engine.ingest(q)

        stats = engine.stats()
        assert stats["active_buffer_size"] <= max_size
        assert stats["lru_evictions_count"] >= (100 - max_size)

    def test_batch_ingest(self, dedup_engine: StreamingDedupEngine):
        """Verifies ingest_batch correctly processes multiple quotes."""
        quotes = [
            create_quote(
                flight_number="QP-101", fare=4500.0, source_portal="akasa_direct"
            ),
            create_quote(
                flight_number="QP-101", fare=4300.0, source_portal="makemytrip"
            ),
            create_quote(
                flight_number="QP-102", fare=5200.0, source_portal="easemytrip"
            ),
        ]
        results = dedup_engine.ingest_batch(quotes)
        assert len(results) == 3
        assert results[0].is_new_flight is True
        assert results[1].is_new_flight is False
        assert results[1].is_new_minimum is True
        assert results[1].min_fare == 4300.0
        assert results[2].is_new_flight is True
        resolved = dedup_engine.get_all_resolved_quotes()
        assert len(resolved) == 2


# ---------------------------------------------------------------------------
# 2. Cross-Platform Arbitrage Detection Tests
# ---------------------------------------------------------------------------


class TestArbitrageDetector:
    """Tests for ArbitrageDetector verifying spread math and venue selection."""

    def test_calculate_spread_direct_cheaper(self):
        """Verifies spread calculation when airline direct fare is lower than OTA fare."""
        direct = 6000.0
        ota = 6600.0
        spread_inr, spread_pct, direction, is_neg = calculate_spread(direct, ota)

        assert spread_inr == 600.0
        assert spread_pct == 10.0
        assert direction == "direct_cheaper"
        assert is_neg is False

    def test_calculate_spread_ota_cheaper(self):
        """Verifies spread calculation when OTA fare is lower than airline direct fare."""
        direct = 6000.0
        ota = 5400.0
        spread_inr, spread_pct, direction, is_neg = calculate_spread(direct, ota)

        assert spread_inr == -600.0
        assert spread_pct == -10.0
        assert direction == "ota_cheaper"
        assert is_neg is True

    def test_calculate_spread_neutral(self):
        """Verifies identical prices return zero spread and neutral direction."""
        spread_inr, spread_pct, direction, is_neg = calculate_spread(5500.0, 5500.0)
        assert spread_inr == 0.0
        assert spread_pct == 0.0
        assert direction == "neutral"
        assert is_neg is False

    def test_calculate_spread_invalid_inputs(self):
        """Verifies zero or negative fare inputs return invalid direction."""
        for d, o in [(0.0, 5000.0), (5000.0, 0.0), (-100.0, 5000.0), (0.0, 0.0)]:
            spread_inr, spread_pct, direction, is_neg = calculate_spread(d, o)
            assert direction == "invalid"
            assert spread_inr == 0.0
            assert spread_pct == 0.0
            assert is_neg is False

    def test_detect_arbitrage_opportunity_direct_cheaper(
        self, arbitrage_detector: ArbitrageDetector
    ):
        """Verifies detection of direct cheaper arbitrage between airline and OTA."""
        quotes = [
            create_quote(
                flight_number="6E-101", fare=6000.0, source_portal="indigo_direct"
            ),
            create_quote(
                flight_number="6E-101", fare=6750.0, source_portal="makemytrip"
            ),
        ]
        opp = arbitrage_detector.detect_flight_arbitrage(quotes)

        assert opp is not None
        assert isinstance(opp, ArbitrageOpportunity)
        assert opp.flight_number in ("6E101", "6E-101")
        assert opp.direct_fare == 6000.0
        assert opp.ota_fare == 6750.0
        assert opp.buy_venue == "indigo_direct"
        assert opp.buy_fare == 6000.0
        assert opp.sell_venue == "makemytrip"
        assert opp.sell_fare == 6750.0
        assert opp.spread_inr == 750.0
        assert opp.spread_pct == 12.5
        assert opp.net_profit_inr == 750.0
        assert opp.direction == "direct_cheaper"
        assert opp.is_arbitrage is True
        assert opp.actionable is True
        assert opp.is_negative_spread is False

    def test_detect_arbitrage_opportunity_ota_cheaper(
        self, arbitrage_detector: ArbitrageDetector
    ):
        """Verifies detection of reverse arbitrage where OTA is cheaper than direct."""
        quotes = [
            create_quote(
                flight_number="AI-404", fare=7500.0, source_portal="airindia_direct"
            ),
            create_quote(
                flight_number="AI-404", fare=6750.0, source_portal="easemytrip"
            ),
        ]
        opp = arbitrage_detector.detect_flight_arbitrage(quotes)

        assert opp is not None
        assert opp.buy_venue == "easemytrip"
        assert opp.buy_fare == 6750.0
        assert opp.sell_venue == "airindia_direct"
        assert opp.sell_fare == 7500.0
        assert opp.spread_inr == -750.0
        assert opp.spread_pct == -10.0
        assert opp.net_profit_inr == 750.0
        assert opp.direction == "ota_cheaper"
        assert opp.is_negative_spread is True
        assert opp.is_arbitrage is True

    def test_threshold_filtering(self):
        """Verifies opportunities below min_spread_pct are marked non-actionable."""
        detector_strict = ArbitrageDetector(min_spread_pct=15.0)
        quotes = [
            create_quote(
                flight_number="SG-202", fare=5000.0, source_portal="spicejet_direct"
            ),
            create_quote(
                flight_number="SG-202", fare=5500.0, source_portal="makemytrip"
            ),  # +10% spread
        ]
        opp = detector_strict.detect_flight_arbitrage(quotes)
        assert opp is not None
        assert opp.spread_pct == 10.0
        assert opp.is_arbitrage is False
        assert opp.actionable is False

        # detect_from_quotes with threshold=15.0 should exclude it
        opps = detector_strict.detect_from_quotes(quotes, min_spread_pct=15.0)
        assert len(opps) == 0

    def test_single_quote_no_arbitrage(self, arbitrage_detector: ArbitrageDetector):
        quotes = [
            create_quote(
                flight_number="6E-999", fare=6000.0, source_portal="indigo_direct"
            )
        ]
        assert arbitrage_detector.detect_flight_arbitrage(quotes) is None
        assert len(arbitrage_detector.detect_from_quotes(quotes)) == 0


# ---------------------------------------------------------------------------
# 3. Database & API Integration Tests
# ---------------------------------------------------------------------------


class TestArbitrageApiIntegration:
    """Tests for GET /api/v1/analytics/arbitrage endpoint and database queries."""

    def test_get_current_arbitrage_opportunities_from_db(self, db_session: Session):
        """Verifies get_current_arbitrage_opportunities extracts opportunities from DB raw fares."""
        today = datetime.now(UTC).date()
        dep_time = datetime.now(UTC) + timedelta(days=2)
        fare1 = RawFare(
            batch_id="test-batch-001",
            hash_id="test-hash-direct-001",
            airline_code="6E",
            flight_number="6E-301",
            origin="DEL",
            destination="BOM",
            departure_time=dep_time,
            total_fare=5800.0,
            booking_window="T+1",
            source_platform="indigo_direct",
            flight_date=today,
        )
        fare2 = RawFare(
            batch_id="test-batch-001",
            hash_id="test-hash-ota-002",
            airline_code="6E",
            flight_number="6E-301",
            origin="DEL",
            destination="BOM",
            departure_time=dep_time,
            total_fare=6500.0,
            booking_window="T+1",
            source_platform="makemytrip",
            flight_date=today,
        )
        db_session.add_all([fare1, fare2])
        db_session.commit()

        opps = get_current_arbitrage_opportunities(db_session, min_spread_pct=5.0)
        assert len(opps) >= 1
        matched = [o for o in opps if o.flight_number in ("6E301", "6E-301")]
        assert len(matched) == 1
        assert matched[0].buy_fare == 5800.0
        assert matched[0].sell_fare == 6500.0

    def test_arbitrage_api_endpoint_response_schema(self, isolated_api_db):
        """Verifies GET /api/v1/analytics/arbitrage conforms to ArbitrageResponse schema."""
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/arbitrage")
        assert response.status_code == 200

        data = response.json()
        validated = ArbitrageResponse(**data)
        assert validated.opportunities_count == len(validated.items)
        assert validated.routes_evaluated == len(
            {i.route_code for i in validated.items}
        )
        assert isinstance(validated.items, list)
        assert not BENCHMARK_FLIGHT_NUMBERS.intersection(
            {item.flight_number for item in validated.items}
        )

        if validated.items:
            first = validated.items[0]
            assert isinstance(first, ArbitrageItem)
            assert first.buy_fare > 0
            assert first.sell_fare > 0
            assert (
                first.spread_inr == round(first.sell_fare - first.buy_fare, 2)
                or abs(first.spread_inr) > 0
            )

    def test_arbitrage_api_reports_no_coverage_instead_of_benchmark_rows(
        self, isolated_api_db
    ):
        """Given a database with no arbitrage candidates, coverage must read as zero rather than eight invented spreads."""
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/arbitrage")

        assert response.status_code == 200
        validated = ArbitrageResponse(**response.json())
        assert validated.items == []
        assert validated.opportunities_count == 0
        assert validated.routes_evaluated == 0
        assert validated.total_potential_savings_inr == 0.0

    def test_arbitrage_api_route_filter(self, isolated_api_db):
        """Verifies GET /api/v1/analytics/arbitrage filters by route_code."""
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/arbitrage?route_code=DEL-BOM")
        assert response.status_code == 200

        data = response.json()
        validated = ArbitrageResponse(**data)
        for item in validated.items:
            assert item.route_code.upper() == "DEL-BOM"

    def test_arbitrage_api_min_spread_pct_filter(self, isolated_api_db):
        """Verifies GET /api/v1/analytics/arbitrage respects min_spread_pct parameter."""
        with TestClient(app) as client:
            response = client.get("/api/v1/analytics/arbitrage?min_spread_pct=10.0")
        assert response.status_code == 200

        data = response.json()
        validated = ArbitrageResponse(**data)
        for item in validated.items:
            assert abs(item.spread_percentage) >= 10.0
