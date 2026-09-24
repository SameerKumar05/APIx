"""Unit tests for StreamingDedupEngine and ArbitrageDetector.

Covers:
- Canonical flight key generation & SHA-256 fingerprinting
- Real-time minimum consumer price resolution across competing portals
- Sub-millisecond latency guarantees
- Sliding window retention and out-of-order arrival tolerance
- LRU memory bounding
- Arbitrage detection: positive spread, negative spread, buy/sell venue logic
- Arbitrage thresholding, zero-volume/zero-fare safety, and neutral spread handling
- End-to-end integration function run_streaming_dedup_and_arbitrage
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.services.arbitrage_detector import (
    ArbitrageDetector,
    ArbitrageOpportunity,
    calculate_spread,
)
from backend.app.services.index_engine import FlightQuote
from backend.app.services.index_pipeline import run_streaming_dedup_and_arbitrage
from backend.app.services.streaming_dedup import (
    DedupResult,
    FlightBufferState,
    StreamingDedupEngine,
)


class TestStreamingDedupEngine:
    def test_canonical_key_and_hash_deduplication(self) -> None:
        engine = StreamingDedupEngine(window_seconds=300.0)

        quote_mmt = {
            "airline_code": "6E",
            "flight_number": "6E-204",
            "origin": "del",
            "destination": "bom",
            "flight_date": "2026-10-15",
            "departure_time": "08:00:00",
            "fare": 5400.0,
            "source_portal": "makemytrip",
        }
        quote_emt = {
            "airline_code": "6E",
            "flight_number": "204",
            "origin": "DEL",
            "destination": "BOM",
            "departure_datetime": "2026-10-15T08:00:00Z",
            "fare": 5150.0,
            "source_portal": "easemytrip",
        }

        key1, hash1 = engine.generate_flight_key(quote_mmt)
        key2, hash2 = engine.generate_flight_key(quote_emt)

        assert key1 == key2
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_minimum_consumer_price_resolution(self) -> None:
        engine = StreamingDedupEngine(window_seconds=300.0)

        # First quote from MMT
        r1 = engine.ingest({
            "airline_code": "SG",
            "flight_number": "SG-8169",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-20",
            "departure_time": "14:30",
            "fare": 5400.0,
            "source_portal": "makemytrip",
        })
        assert r1.is_new_flight is True
        assert r1.is_new_minimum is True
        assert r1.min_fare == 5400.0

        # Cheaper quote from EaseMyTrip
        r2 = engine.ingest({
            "airline_code": "SG",
            "flight_number": "SG-8169",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-20",
            "departure_time": "14:30",
            "fare": 5150.0,
            "source_portal": "easemytrip",
        })
        assert r2.is_new_flight is False
        assert r2.is_new_minimum is True
        assert r2.min_fare == 5150.0
        assert r2.previous_min_fare == 5400.0

        # Even cheaper from airline direct
        r3 = engine.ingest({
            "airline_code": "SG",
            "flight_number": "SG-8169",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-20",
            "departure_time": "14:30",
            "fare": 4800.0,
            "source_portal": "spicejet",
        })
        assert r3.is_new_minimum is True
        assert r3.min_fare == 4800.0
        assert r3.best_quote.source_portal == "spicejet"

        # Higher price quote from Yatra should NOT update min_fare
        r4 = engine.ingest({
            "airline_code": "SG",
            "flight_number": "SG-8169",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-20",
            "departure_time": "14:30",
            "fare": 5600.0,
            "source_portal": "yatra",
        })
        assert r4.is_new_minimum is False
        assert r4.min_fare == 4800.0
        assert r4.portal_count == 4

        # Verify best quote retrieval
        best = engine.get_best_quote(r1.flight_key)
        assert best is not None
        assert best.fare == 4800.0
        assert best.source_portal == "spicejet"

    def test_sub_millisecond_latency(self) -> None:
        engine = StreamingDedupEngine(window_seconds=600.0)

        quotes = [
            {
                "airline_code": "6E",
                "flight_number": f"6E-{100 + (i % 50)}",
                "origin": "DEL",
                "destination": "BOM",
                "flight_date": "2026-11-01",
                "departure_time": "08:00",
                "fare": float(4000 + (i % 200)),
                "source_portal": f"portal_{i % 5}",
            }
            for i in range(1000)
        ]

        start_time = time.perf_counter_ns()
        results = engine.ingest_batch(quotes)
        elapsed_total_ms = (time.perf_counter_ns() - start_time) / 1_000_000.0

        stats = engine.stats()
        avg_latency_ms = stats["avg_latency_us"] / 1000.0

        assert len(results) == 1000
        assert avg_latency_ms < 1.0  # Sub-millisecond requirement
        assert stats["sub_millisecond_compliant"] is True

    def test_sliding_window_out_of_order_and_pruning(self) -> None:
        engine = StreamingDedupEngine(window_seconds=60.0)
        base_time = datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc)

        # Ingest quote at T = +30s
        engine.ingest(
            {
                "airline_code": "6E",
                "flight_number": "6E-501",
                "origin": "DEL",
                "destination": "BLR",
                "flight_date": "2026-10-10",
                "departure_time": "09:00",
                "fare": 6000.0,
                "source_portal": "makemytrip",
                "booking_datetime": (base_time + timedelta(seconds=30)).isoformat(),
            },
            arrival_time=base_time + timedelta(seconds=30),
        )

        # Out-of-order quote with older timestamp T = +10s
        res_ooo = engine.ingest(
            {
                "airline_code": "6E",
                "flight_number": "6E-501",
                "origin": "DEL",
                "destination": "BLR",
                "flight_date": "2026-10-10",
                "departure_time": "09:00",
                "fare": 5500.0,
                "source_portal": "indigo",
                "booking_datetime": (base_time + timedelta(seconds=10)).isoformat(),
            },
            arrival_time=base_time + timedelta(seconds=35),
        )
        assert res_ooo.out_of_order is True
        assert res_ooo.min_fare == 5500.0

        # Prune at T = +70s (not yet expired, age = 35s <= 60s)
        pruned_0 = engine.prune_expired(current_time=base_time + timedelta(seconds=70))
        assert pruned_0 == 0
        assert len(engine._buffer) == 1

        # Prune at T = +100s (expired, age = 65s > 60s)
        pruned_1 = engine.prune_expired(current_time=base_time + timedelta(seconds=100))
        assert pruned_1 == 1
        assert len(engine._buffer) == 0

    def test_lru_memory_bounding(self) -> None:
        max_buf = 30
        engine = StreamingDedupEngine(max_buffer_size=max_buf)

        for i in range(100):
            engine.ingest({
                "airline_code": "6E",
                "flight_number": f"6E-{i}",
                "origin": "DEL",
                "destination": "BOM",
                "flight_date": "2026-10-01",
                "departure_time": "08:00",
                "fare": 5000.0 + i,
                "source_portal": "makemytrip",
            })

        stats = engine.stats()
        assert len(engine._buffer) == max_buf
        assert stats["lru_evictions_count"] == 70


class TestArbitrageDetector:
    def test_calculate_spread_positive_and_negative(self) -> None:
        # Positive spread: direct cheaper, OTA higher
        spread_inr, spread_pct, direction, is_neg = calculate_spread(direct_fare=4500.0, ota_fare=5000.0)
        assert spread_inr == 500.0
        assert spread_pct == round((500.0 / 4500.0) * 100.0, 4)
        assert direction == "direct_cheaper"
        assert is_neg is False

        # Negative spread: OTA cheaper than direct
        spread_inr, spread_pct, direction, is_neg = calculate_spread(direct_fare=6000.0, ota_fare=5400.0)
        assert spread_inr == -600.0
        assert spread_pct == round((-600.0 / 6000.0) * 100.0, 4)
        assert direction == "ota_cheaper"
        assert is_neg is True

        # Neutral spread: identical prices
        spread_inr, spread_pct, direction, is_neg = calculate_spread(direct_fare=5000.0, ota_fare=5000.0)
        assert spread_inr == 0.0
        assert spread_pct == 0.0
        assert direction == "neutral"
        assert is_neg is False

    def test_detect_positive_arbitrage(self) -> None:
        detector = ArbitrageDetector(min_spread_pct=3.0)
        quotes = [
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-25",
                airline_code="SG",
                flight_number="SG8169",
                departure_time="10:00",
                fare=4500.0,
                source_portal="spicejet",
            ),
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-25",
                airline_code="SG",
                flight_number="SG8169",
                departure_time="10:00",
                fare=5000.0,
                source_portal="makemytrip",
            ),
        ]

        opp = detector.detect_flight_arbitrage(quotes)
        assert opp is not None
        assert opp.buy_venue == "spicejet"
        assert opp.sell_venue == "makemytrip"
        assert opp.direct_fare == 4500.0
        assert opp.ota_fare == 5000.0
        assert opp.spread_inr == 500.0
        assert opp.direction == "direct_cheaper"
        assert opp.is_arbitrage is True
        assert opp.net_profit_inr == 500.0

    def test_detect_negative_reverse_arbitrage(self) -> None:
        detector = ArbitrageDetector(min_spread_pct=3.0, allow_reverse_arbitrage=True)
        quotes = [
            FlightQuote(
                origin="BLR",
                destination="DEL",
                flight_date="2026-10-25",
                airline_code="6E",
                flight_number="6E205",
                departure_time="15:00",
                fare=5800.0,
                source_portal="indigo",
            ),
            FlightQuote(
                origin="BLR",
                destination="DEL",
                flight_date="2026-10-25",
                airline_code="6E",
                flight_number="6E205",
                departure_time="15:00",
                fare=5200.0,
                source_portal="makemytrip",
            ),
        ]

        opp = detector.detect_flight_arbitrage(quotes)
        assert opp is not None
        assert opp.buy_venue == "makemytrip"
        assert opp.sell_venue == "indigo"
        assert opp.is_negative_spread is True
        assert opp.direction == "ota_cheaper"
        assert opp.is_arbitrage is True
        assert opp.net_profit_inr == 600.0

    def test_arbitrage_edge_cases(self) -> None:
        detector = ArbitrageDetector()

        # Empty quotes list
        assert detector.detect_from_quotes([]) == []
        assert detector.detect_flight_arbitrage([]) is None

        # Zero or negative fare
        spread_inr, spread_pct, direction, is_neg = calculate_spread(direct_fare=0.0, ota_fare=5000.0)
        assert spread_pct == 0.0
        assert direction == "invalid"

        spread_inr, spread_pct, direction, is_neg = calculate_spread(direct_fare=-50.0, ota_fare=5000.0)
        assert spread_pct == 0.0
        assert direction == "invalid"

        # Single portal only
        single = [
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-25",
                airline_code="6E",
                flight_number="6E204",
                departure_time="08:00",
                fare=5000.0,
                source_portal="indigo",
            )
        ]
        assert detector.detect_flight_arbitrage(single) is None

        # Neutral identical price
        neutral = [
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-25",
                airline_code="6E",
                flight_number="6E204",
                departure_time="08:00",
                fare=5000.0,
                source_portal="indigo",
            ),
            FlightQuote(
                origin="DEL",
                destination="BOM",
                flight_date="2026-10-25",
                airline_code="6E",
                flight_number="6E204",
                departure_time="08:00",
                fare=5000.0,
                source_portal="makemytrip",
            ),
        ]
        opp_n = detector.detect_flight_arbitrage(neutral)
        assert opp_n is not None
        assert opp_n.spread_inr == 0.0
        assert opp_n.direction == "neutral"
        assert opp_n.is_arbitrage is False


class TestPipelineIntegration:
    def test_run_streaming_dedup_and_arbitrage(self) -> None:
        quotes = [
            {
                "airline_code": "6E",
                "flight_number": "6E-204",
                "origin": "DEL",
                "destination": "BOM",
                "flight_date": "2026-10-25",
                "departure_time": "08:00",
                "fare": 4800.0,
                "source_portal": "indigo",
            },
            {
                "airline_code": "6E",
                "flight_number": "6E-204",
                "origin": "DEL",
                "destination": "BOM",
                "flight_date": "2026-10-25",
                "departure_time": "08:00",
                "fare": 5400.0,
                "source_portal": "makemytrip",
            },
        ]

        engine, opps = run_streaming_dedup_and_arbitrage(quotes, min_spread_pct=5.0)
        assert len(opps) == 1
        assert opps[0].is_arbitrage is True
        assert opps[0].buy_venue == "indigo"
        assert opps[0].sell_venue == "makemytrip"

        stats = engine.stats()
        assert stats["total_processed"] == 2
        assert stats["active_buffer_size"] == 1
