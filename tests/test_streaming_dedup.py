#!/usr/bin/env python3
"""Premier Verification Test Suite for Streaming Dedup Engine and Arbitrage Detector.

Tests:
1. Exact hash deduplication across multiple portals for identical flights.
2. Real-time minimum consumer price resolution in sub-millisecond latency.
3. High-throughput latency benchmark (< 1.0 ms average latency per quote).
4. Sliding window buffer management with out-of-order timestamp tolerance.
5. Strict LRU memory bounding to guarantee O(1) memory safety under continuous streams.
6. Cross-platform arbitrage detection (positive spread, negative spread, buy/sell venue logic).
7. Threshold filtering, zero-volume/zero-fare edge cases, and empty input handling.
8. End-to-end integration with daily index pipeline and database models.
"""

from __future__ import annotations

import logging
import math
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

# Add project root to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
try:
    import sqlalchemy
except ImportError:
    for candidate in [
        PROJECT_ROOT.parent.parent / ".venv" / "bin" / "python",
        PROJECT_ROOT / ".venv" / "bin" / "python",
    ]:
        if candidate.exists() and sys.executable != str(candidate):
            os.execv(str(candidate), [str(candidate)] + sys.argv)
    raise


from backend.app.services.arbitrage_detector import (
    ArbitrageDetector,
    ArbitrageOpportunity,
    calculate_spread,
    get_current_arbitrage_opportunities,
)
from backend.app.services.index_engine import FlightQuote
from backend.app.services.index_pipeline import (
    run_daily_index_pipeline,
    run_streaming_dedup_and_arbitrage,
)
from backend.app.services.streaming_dedup import (
    DedupResult,
    FlightBufferState,
    StreamingDedupEngine,
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("test_streaming_dedup")


def print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def test_exact_hash_deduplication() -> None:
    """Test 1: Verify deterministic canonical key and exact SHA-256 hash generation."""
    print("\n[Test 1] Exact Hash Deduplication & Flight Key Generation")

    engine = StreamingDedupEngine(window_seconds=600.0)

    # Identical flight represented across different portals with slightly different formats
    quote_mmt = {
        "airline_code": "6E",
        "flight_number": "6E-204",
        "origin": "del",
        "destination": "bom",
        "flight_date": "2026-10-15",
        "departure_time": "08:00:00",
        "fare": 5400.0,
        "source_portal": "makemytrip",
        "cabin_class": "economy",
    }
    quote_emt = {
        "airline_code": "6E",
        "flight_number": "204",  # Should normalize to 6E204
        "origin": "DEL",
        "destination": "BOM",
        "departure_datetime": "2026-10-15T08:00:00Z",
        "fare": 5150.0,
        "source_portal": "easemytrip",
        "cabin_class": "Economy",
    }
    quote_direct = {
        "airline_code": "6E",
        "flight_number": "6E 204",
        "origin": "DEL",
        "destination": "BOM",
        "flight_date": "2026-10-15",
        "departure_time": "08:00",
        "fare": 4900.0,
        "source_portal": "indigo",
        "cabin_class": "economy",
    }

    key1, hash1 = engine.generate_flight_key(quote_mmt)
    key2, hash2 = engine.generate_flight_key(quote_emt)
    key3, hash3 = engine.generate_flight_key(quote_direct)

    assert key1 == key2 == key3, f"Canonical keys must match: {key1} vs {key2}"
    assert hash1 == hash2 == hash3, f"SHA-256 hashes must match: {hash1} vs {hash2}"
    assert len(hash1) == 64, "SHA-256 hash must be 64 hexadecimal characters"

    print(f"  ✓ Canonical Key: {key1}")
    print(f"  ✓ Deterministic SHA-256 Hash: {hash1}")
    print(
        "  ✓ PASSED: All portal variations resolve to identical canonical key and hash."
    )


def test_minimum_consumer_price_resolution() -> None:
    """Test 2: Verify real-time resolution of lowest price across competing platforms."""
    print("\n[Test 2] Real-Time Minimum Consumer Price Resolution")

    engine = StreamingDedupEngine(window_seconds=300.0)

    # Ingest MMT quote at INR 5,400
    res1 = engine.ingest(
        {
            "airline_code": "SG",
            "flight_number": "SG-8169",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-20",
            "departure_time": "14:30",
            "fare": 5400.0,
            "source_portal": "makemytrip",
        }
    )
    assert res1.is_new_flight is True
    assert res1.is_new_minimum is True
    assert res1.min_fare == 5400.0
    assert res1.portal_count == 1
    assert (
        res1.latency_us < 1000.0
    ), f"Latency {res1.latency_us} us must be sub-millisecond"

    # Ingest EaseMyTrip quote at INR 5,150 (new minimum)
    res2 = engine.ingest(
        {
            "airline_code": "SG",
            "flight_number": "SG-8169",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-20",
            "departure_time": "14:30",
            "fare": 5150.0,
            "source_portal": "easemytrip",
        }
    )
    assert res2.is_new_flight is False
    assert res2.is_new_minimum is True
    assert res2.min_fare == 5150.0
    assert res2.portal_count == 2
    assert res2.previous_min_fare == 5400.0

    # Ingest SpiceJet direct quote at INR 4,800 (new minimum from direct carrier)
    res3 = engine.ingest(
        {
            "airline_code": "SG",
            "flight_number": "SG-8169",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-20",
            "departure_time": "14:30",
            "fare": 4800.0,
            "source_portal": "spicejet",
        }
    )
    assert res3.is_new_minimum is True
    assert res3.min_fare == 4800.0
    assert res3.portal_count == 3
    assert res3.best_quote.source_portal == "spicejet"
    assert res3.spread_inr == 600.0  # 5400 - 4800
    assert res3.spread_pct == round((600.0 / 4800.0) * 100.0, 4)

    # Ingest another OTA quote at higher price INR 5,600 (should NOT lower min_fare)
    res4 = engine.ingest(
        {
            "airline_code": "SG",
            "flight_number": "SG-8169",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-20",
            "departure_time": "14:30",
            "fare": 5600.0,
            "source_portal": "yatra",
        }
    )
    assert res4.is_new_minimum is False
    assert res4.min_fare == 4800.0
    assert res4.portal_count == 4
    assert res4.best_quote.source_portal == "spicejet"

    # Query best quote
    best = engine.get_best_quote(res1.flight_key)
    assert best is not None
    assert best.fare == 4800.0
    assert best.source_portal == "spicejet"

    print(f"  ✓ Best Quote Resolved: Fare=INR {best.fare} via {best.source_portal}")
    print(
        f"  ✓ Portals Tracked: {res4.portal_count} ({list(res4.portal_fares.keys())})"
    )
    print(f"  ✓ Cross-Portal Fare Spread: INR {res4.spread_inr} ({res4.spread_pct}%)")
    print("  ✓ PASSED: Minimum consumer price resolved across 4 portals accurately.")


def test_sub_millisecond_latency_benchmark() -> None:
    """Test 3: Benchmark latency across 5,000 quotes to prove sub-millisecond execution."""
    print("\n[Test 3] High-Throughput Sub-Millisecond Latency Benchmark")

    engine = StreamingDedupEngine(window_seconds=600.0, max_buffer_size=50_000)

    # Generate 5,000 diverse flight quotes across 1,000 unique flights and 5 portals
    portals = ["makemytrip", "easemytrip", "spicejet", "indigo", "airindia"]
    routes = [
        ("DEL", "BOM"),
        ("BLR", "DEL"),
        ("BOM", "GOI"),
        ("MAA", "CCU"),
        ("HYD", "DEL"),
    ]
    airlines = ["6E", "SG", "AI", "UK", "QP"]

    quotes = []
    for i in range(5000):
        flight_idx = i % 1000
        orig, dest = routes[flight_idx % len(routes)]
        airline = airlines[flight_idx % len(airlines)]
        portal = portals[i % len(portals)]
        base_p = 3500 + (flight_idx * 7) % 4000
        # Varied fare per portal
        fare = base_p + ((i * 37) % 500)
        quotes.append(
            {
                "airline_code": airline,
                "flight_number": f"{airline}-{100 + (flight_idx % 300)}",
                "origin": orig,
                "destination": dest,
                "flight_date": "2026-11-01",
                "departure_time": f"{(flight_idx % 24):02d}:00",
                "fare": float(fare),
                "source_portal": portal,
                "cabin_class": "economy",
                "booking_datetime": "2026-09-24T12:00:00Z",
            }
        )

    # Benchmark ingestion loop
    start_total = time.perf_counter_ns()
    engine.ingest_batch(quotes)
    total_elapsed_ms = (time.perf_counter_ns() - start_total) / 1_000_000.0

    stats = engine.stats()
    avg_latency_us = stats["avg_latency_us"]
    avg_latency_ms = avg_latency_us / 1000.0
    throughput_qps = len(quotes) / (total_elapsed_ms / 1000.0)

    print(f"  ✓ Processed Quotes: {len(quotes):,} quotes in {total_elapsed_ms:.2f} ms")
    print(
        f"  ✓ Average Latency: {avg_latency_us:.2f} µs ({avg_latency_ms:.4f} ms per quote)"
    )
    print(f"  ✓ Max Recorded Latency: {stats['max_latency_us']:.2f} µs")
    print(f"  ✓ Engine Throughput: {throughput_qps:,.0f} quotes/second")
    print(f"  ✓ Sub-Millisecond Compliant: {stats['sub_millisecond_compliant']}")

    assert (
        avg_latency_ms < 1.0
    ), f"Average latency {avg_latency_ms} ms exceeds 1.0 ms threshold!"
    assert stats["sub_millisecond_compliant"] is True
    print(
        "  ✓ PASSED: Sub-millisecond latency requirement verified with premier margin."
    )


def test_sliding_window_and_out_of_order() -> None:
    """Test 4: Sliding window retention and out-of-order arrival tolerance."""
    print("\n[Test 4] Sliding Window & Out-of-Order Timestamp Handling")

    window_sec = 60.0  # 60 second sliding window
    engine = StreamingDedupEngine(window_seconds=window_sec)

    base_time = datetime(2026, 9, 24, 10, 0, 0, tzinfo=UTC)

    # Ingest quote at T = 10:00:30
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

    # Ingest OUT-OF-ORDER quote for same flight with older timestamp T = 10:00:10 (within window)
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
    assert res_ooo.out_of_order is True, "Must detect out-of-order timestamp"
    assert res_ooo.min_fare == 5500.0, "Out-of-order lower price must update min_fare"
    assert res_ooo.portal_count == 2

    # Ingest another flight at T = 10:00:40
    engine.ingest(
        {
            "airline_code": "AI",
            "flight_number": "AI-806",
            "origin": "BOM",
            "destination": "DEL",
            "flight_date": "2026-10-10",
            "departure_time": "11:00",
            "fare": 7000.0,
            "source_portal": "airindia",
            "booking_datetime": (base_time + timedelta(seconds=40)).isoformat(),
        },
        arrival_time=base_time + timedelta(seconds=40),
    )

    assert len(engine._buffer) == 2

    # Prune at T = 10:01:10 (35 seconds after last update of 6E-501, window=60s -> should NOT expire yet)
    pruned_early = engine.prune_expired(current_time=base_time + timedelta(seconds=70))
    assert pruned_early == 0
    assert len(engine._buffer) == 2

    # Prune at T = 10:01:45 (70 seconds after 6E-501 was updated at T=35 -> 6E-501 expires, AI-806 at T=40 expires)
    pruned_late = engine.prune_expired(current_time=base_time + timedelta(seconds=105))
    assert pruned_late == 2
    assert len(engine._buffer) == 0

    print("  ✓ Out-of-order arrival correctly flagged and resolved lower price.")
    print(f"  ✓ Sliding window expiration pruned {pruned_late} records precisely.")
    print("  ✓ PASSED: Sliding window and out-of-order timestamp handling verified.")


def test_lru_memory_bounding() -> None:
    """Test 5: Verify strict LRU memory bounding under load."""
    print("\n[Test 5] Strict LRU Memory Bounding")

    max_buf = 50
    engine = StreamingDedupEngine(max_buffer_size=max_buf)

    # Ingest 200 distinct flights
    for i in range(200):
        engine.ingest(
            {
                "airline_code": "6E",
                "flight_number": f"6E-{i}",
                "origin": "DEL",
                "destination": "BOM",
                "flight_date": "2026-10-01",
                "departure_time": "08:00",
                "fare": 5000.0 + i,
                "source_portal": "makemytrip",
            }
        )

    stats = engine.stats()
    assert (
        len(engine._buffer) == max_buf
    ), f"Buffer size {len(engine._buffer)} must equal max_buf {max_buf}"
    assert stats["active_buffer_size"] == max_buf
    assert stats["lru_evictions_count"] == 150  # 200 - 50 = 150 evicted

    # The most recent 50 flights (i = 150 to 199) must be retained
    for i in range(150, 200):
        key, _ = engine.generate_flight_key(
            {
                "airline_code": "6E",
                "flight_number": f"6E-{i}",
                "origin": "DEL",
                "destination": "BOM",
                "flight_date": "2026-10-01",
                "departure_time": "08:00",
            }
        )
        assert engine.get_best_quote(key) is not None

    # Flight 0 should have been evicted
    key_old, _ = engine.generate_flight_key(
        {
            "airline_code": "6E",
            "flight_number": "6E-0",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-01",
            "departure_time": "08:00",
        }
    )
    assert engine.get_best_quote(key_old) is None

    print(f"  ✓ Buffer capped at: {len(engine._buffer)} records (max={max_buf})")
    print(f"  ✓ LRU Evictions executed: {stats['lru_evictions_count']} records")
    print("  ✓ PASSED: LRU memory bounding guarantees bounded memory footprint.")


def test_cross_platform_arbitrage_detector() -> None:
    """Test 6: Cross-platform arbitrage detection (positive, negative, venue logic, thresholds)."""
    print("\n[Test 6] Cross-Platform Arbitrage Detection")

    detector = ArbitrageDetector(min_spread_pct=3.0, allow_reverse_arbitrage=True)

    # 1. Spread Calculation Function Test
    spread_inr, spread_pct, direction, is_neg = calculate_spread(
        direct_fare=4500.0, ota_fare=5000.0
    )
    assert spread_inr == 500.0
    assert spread_pct == round((500.0 / 4500.0) * 100.0, 4)  # ~11.1111%
    assert direction == "direct_cheaper"
    assert is_neg is False

    # Negative spread (OTA is cheaper)
    spread_neg_inr, spread_neg_pct, dir_neg, is_neg_flag = calculate_spread(
        direct_fare=6000.0, ota_fare=5400.0
    )
    assert spread_neg_inr == -600.0
    assert spread_neg_pct == round((-600.0 / 6000.0) * 100.0, 4)  # -10.0%
    assert dir_neg == "ota_cheaper"
    assert is_neg_flag is True

    # 2. Positive Arbitrage: Direct Carrier Cheaper than OTA
    # Carrier (SpiceJet) = 4,500 INR, MMT = 5,100 INR, EaseMyTrip = 5,000 INR
    flight_quotes_pos = [
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
            fare=5100.0,
            source_portal="makemytrip",
        ),
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-25",
            airline_code="SG",
            flight_number="SG8169",
            departure_time="10:00",
            fare=5000.0,
            source_portal="easemytrip",
        ),
    ]

    opp_pos = detector.detect_flight_arbitrage(flight_quotes_pos)
    assert opp_pos is not None
    assert opp_pos.direct_platform == "spicejet"
    assert opp_pos.direct_fare == 4500.0
    assert opp_pos.ota_platform == "easemytrip"  # lowest OTA
    assert opp_pos.ota_fare == 5000.0
    assert opp_pos.buy_venue == "spicejet"
    assert opp_pos.sell_venue == "easemytrip"
    assert opp_pos.spread_inr == 500.0
    assert opp_pos.direction == "direct_cheaper"
    assert opp_pos.is_arbitrage is True
    assert opp_pos.actionable is True
    assert opp_pos.is_negative_spread is False

    # 3. Negative Arbitrage: OTA Cheaper than Direct Carrier (Reverse Arbitrage)
    # Carrier (IndiGo) = 5,800 INR, MMT = 5,200 INR
    flight_quotes_neg = [
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

    opp_neg = detector.detect_flight_arbitrage(flight_quotes_neg)
    assert opp_neg is not None
    assert opp_neg.direct_fare == 5800.0
    assert opp_neg.ota_fare == 5200.0
    assert opp_neg.buy_venue == "makemytrip"  # Buy at cheaper OTA
    assert opp_neg.sell_venue == "indigo"
    assert opp_neg.spread_inr == -600.0
    assert opp_neg.is_negative_spread is True
    assert opp_neg.direction == "ota_cheaper"
    assert opp_neg.is_arbitrage is True  # actionable reverse arbitrage
    assert opp_neg.net_profit_inr == 600.0

    # 4. Threshold Filtering
    # Threshold = 15.0%: opp_pos spread_pct = 11.11% (< 15%), should NOT be actionable if min_spread_pct=15.0
    detector_strict = ArbitrageDetector(min_spread_pct=15.0)
    opp_pos_strict = detector_strict.detect_flight_arbitrage(flight_quotes_pos)
    assert opp_pos_strict is not None
    assert opp_pos_strict.is_arbitrage is False
    assert opp_pos_strict.actionable is False

    # 5. Batch Detection from mixed quotes
    all_quotes = flight_quotes_pos + flight_quotes_neg
    batch_opps = detector.detect_from_quotes(all_quotes)
    assert len(batch_opps) == 2
    # Verify sorting by absolute spread percentage descending
    assert abs(batch_opps[0].spread_pct) >= abs(batch_opps[1].spread_pct)

    print(
        f"  ✓ Direct Cheaper Arbitrage: Buy={opp_pos.buy_venue} (INR {opp_pos.buy_fare}), "
        f"Sell={opp_pos.sell_venue} (INR {opp_pos.sell_fare}), Spread=+{opp_pos.spread_pct}%"
    )
    print(
        f"  ✓ OTA Cheaper Arbitrage: Buy={opp_neg.buy_venue} (INR {opp_neg.buy_fare}), "
        f"Sell={opp_neg.sell_venue} (INR {opp_neg.sell_fare}), Spread={opp_neg.spread_pct}%"
    )
    print("  ✓ Threshold filtering & sorting verified.")
    print("  ✓ PASSED: Arbitrage detection and spread calculations verified.")


def test_arbitrage_edge_cases() -> None:
    """Test 7: Zero-volume, zero-fare, empty quotes, and single platform edge cases."""
    print("\n[Test 7] Arbitrage Edge Cases & Zero-Division Safety")

    detector = ArbitrageDetector()

    # Empty quotes
    assert detector.detect_from_quotes([]) == []
    assert detector.detect_flight_arbitrage([]) is None

    # Single quote only (no cross-platform comparison possible)
    single_quote = [
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
    assert detector.detect_flight_arbitrage(single_quote) is None

    # Quotes from OTAs only (no direct carrier portal)
    ota_only_quotes = [
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-25",
            airline_code="6E",
            flight_number="6E204",
            departure_time="08:00",
            fare=5200.0,
            source_portal="makemytrip",
        ),
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-25",
            airline_code="6E",
            flight_number="6E204",
            departure_time="08:00",
            fare=5100.0,
            source_portal="easemytrip",
        ),
    ]
    assert detector.detect_flight_arbitrage(ota_only_quotes) is None

    # Zero or negative fare edge cases (must never raise ZeroDivisionError)
    spread_inr, spread_pct, direction, is_neg = calculate_spread(
        direct_fare=0.0, ota_fare=5000.0
    )
    assert spread_inr == 0.0
    assert spread_pct == 0.0
    assert direction == "invalid"
    assert is_neg is False

    spread_inr, spread_pct, direction, is_neg = calculate_spread(
        direct_fare=-100.0, ota_fare=5000.0
    )
    assert spread_pct == 0.0
    assert direction == "invalid"

    # Flight quotes with zero fare
    zero_fare_quotes = [
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-25",
            airline_code="6E",
            flight_number="6E204",
            departure_time="08:00",
            fare=0.0,
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
    assert detector.detect_flight_arbitrage(zero_fare_quotes) is None

    # Identical prices (neutral spread)
    neutral_quotes = [
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
    opp_neutral = detector.detect_flight_arbitrage(neutral_quotes)
    assert opp_neutral is not None
    assert opp_neutral.spread_inr == 0.0
    assert opp_neutral.spread_pct == 0.0
    assert opp_neutral.direction == "neutral"
    assert opp_neutral.is_arbitrage is False

    print("  ✓ Empty inputs, single portal, and zero fare handled without errors.")
    print("  ✓ ZeroDivisionError eliminated across all zero/negative edge cases.")
    print("  ✓ PASSED: Arbitrage edge cases and mathematical boundaries verified.")


def test_index_pipeline_and_db_integration() -> None:
    """Test 8: Verify end-to-end integration with database session and daily index pipeline."""
    print("\n[Test 8] Index Pipeline & DB Integration")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.db.seed import seed_all
    from backend.app.db.session import Base
    from backend.app.models.raw_fare import RawFare

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        seed_all(session)
        calc_date = date(2026, 9, 24)

        # Seed realistic raw fares including direct vs OTA quotes for arbitrage
        fares_to_seed = [
            # DEL-BOM 6E-204 (Direct vs MMT vs EMT)
            RawFare(
                batch_id="test-batch-1",
                airline_code="6E",
                flight_number="6E-204",
                origin="DEL",
                destination="BOM",
                flight_date=calc_date,
                departure_time=datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
                scraped_at=datetime(2026, 9, 24, 7, 0, tzinfo=UTC),
                total_fare=4800.0,
                base_fare=3800.0,
                taxes_and_fees=1000.0,
                source_platform="indigo",
                booking_window="T+1",
                hash_id="hash-6e-204-indigo",
            ),
            RawFare(
                batch_id="test-batch-1",
                airline_code="6E",
                flight_number="6E-204",
                origin="DEL",
                destination="BOM",
                flight_date=calc_date,
                departure_time=datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
                scraped_at=datetime(2026, 9, 24, 7, 5, tzinfo=UTC),
                total_fare=5400.0,
                base_fare=4200.0,
                taxes_and_fees=1200.0,
                source_platform="makemytrip",
                booking_window="T+1",
                hash_id="hash-6e-204-mmt",
            ),
            RawFare(
                batch_id="test-batch-1",
                airline_code="6E",
                flight_number="6E-204",
                origin="DEL",
                destination="BOM",
                flight_date=calc_date,
                departure_time=datetime(2026, 9, 24, 8, 0, tzinfo=UTC),
                scraped_at=datetime(2026, 9, 24, 7, 10, tzinfo=UTC),
                total_fare=5200.0,
                base_fare=4100.0,
                taxes_and_fees=1100.0,
                source_platform="easemytrip",
                booking_window="T+1",
                hash_id="hash-6e-204-emt",
            ),
            # BLR-DEL SG-8169 (Direct vs MMT)
            RawFare(
                batch_id="test-batch-1",
                airline_code="SG",
                flight_number="SG-8169",
                origin="BLR",
                destination="DEL",
                flight_date=calc_date,
                departure_time=datetime(2026, 9, 24, 14, 0, tzinfo=UTC),
                scraped_at=datetime(2026, 9, 24, 10, 0, tzinfo=UTC),
                total_fare=4200.0,
                base_fare=3200.0,
                taxes_and_fees=1000.0,
                source_platform="spicejet",
                booking_window="T+7",
                hash_id="hash-sg-8169-spicejet",
            ),
            RawFare(
                batch_id="test-batch-1",
                airline_code="SG",
                flight_number="SG-8169",
                origin="BLR",
                destination="DEL",
                flight_date=calc_date,
                departure_time=datetime(2026, 9, 24, 14, 0, tzinfo=UTC),
                scraped_at=datetime(2026, 9, 24, 10, 5, tzinfo=UTC),
                total_fare=4950.0,
                base_fare=3900.0,
                taxes_and_fees=1050.0,
                source_platform="makemytrip",
                booking_window="T+7",
                hash_id="hash-sg-8169-mmt",
            ),
        ]
        session.add_all(fares_to_seed)
        session.commit()

        # Test get_current_arbitrage_opportunities with db session
        db_opps = get_current_arbitrage_opportunities(
            session, min_spread_pct=5.0, target_date=calc_date
        )
        assert (
            len(db_opps) == 2
        ), f"Expected 2 arbitrage opportunities, got {len(db_opps)}"
        assert db_opps[0].airline_code in ("6E", "SG")
        assert db_opps[0].is_arbitrage is True

        # Test run_daily_index_pipeline with streaming dedup & arbitrage integration
        res = run_daily_index_pipeline(db=session, calculation_date=calc_date)
        assert res["status"] == "success"
        assert "streaming_dedup_stats" in res
        assert "arbitrage_count" in res
        assert "arbitrage_opportunities" in res

        stats = res["streaming_dedup_stats"]
        assert stats["total_processed"] == 5
        assert stats["sub_millisecond_compliant"] is True
        assert res["arbitrage_count"] == 2

        print(f"  ✓ DB Arbitrage Query returned {len(db_opps)} opportunities.")
        print(
            f"  ✓ Pipeline executed with streaming dedup: {stats['total_processed']} quotes, "
            f"avg latency={stats['avg_latency_us']:.2f} µs."
        )
        print(
            f"  ✓ Arbitrage Opportunities in Pipeline Summary: {res['arbitrage_count']}"
        )
        print("  ✓ PASSED: End-to-end integration verified successfully.")


def test_streaming_dedup_excludes_cancelled_and_sold_out_quotes() -> None:
    """Test 9: Verify cancelled and sold-out quotes are strictly excluded from minimum consumer price."""
    print("\n[Test 9] Exclusion of Cancelled and Sold-Out Quotes from Minimum Price")

    engine = StreamingDedupEngine(window_seconds=300.0)

    # 1. Ingest valid scheduled quote at 5000
    res1 = engine.ingest(
        {
            "airline_code": "6E",
            "flight_number": "6E-551",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-25",
            "departure_time": "09:00",
            "fare": 5000.0,
            "source_portal": "makemytrip",
            "flight_status": "scheduled",
        }
    )
    assert res1.is_new_minimum is True
    assert res1.min_fare == 5000.0

    # 2. Ingest cheaper cancelled quote at 3000
    res2 = engine.ingest(
        {
            "airline_code": "6E",
            "flight_number": "6E-551",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-25",
            "departure_time": "09:00",
            "fare": 3000.0,
            "source_portal": "easemytrip",
            "flight_status": "cancelled",
        }
    )
    assert res2.is_new_minimum is False
    assert res2.min_fare == 5000.0

    # 3. Ingest even cheaper sold_out quote at 2500
    res3 = engine.ingest(
        {
            "airline_code": "6E",
            "flight_number": "6E-551",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-25",
            "departure_time": "09:00",
            "fare": 2500.0,
            "source_portal": "cleartrip",
            "flight_status": "sold_out",
        }
    )
    assert res3.is_new_minimum is False
    assert res3.min_fare == 5000.0

    # 4. Ingest genuinely lower scheduled quote at 4500
    res4 = engine.ingest(
        {
            "airline_code": "6E",
            "flight_number": "6E-551",
            "origin": "DEL",
            "destination": "BOM",
            "flight_date": "2026-10-25",
            "departure_time": "09:00",
            "fare": 4500.0,
            "source_portal": "indigo",
            "flight_status": "scheduled",
        }
    )
    assert res4.is_new_minimum is True
    assert res4.min_fare == 4500.0

    # 5. Flight where ALL quotes are cancelled / sold out
    engine_cancelled = StreamingDedupEngine(window_seconds=300.0)
    ai_item = {
        "airline_code": "AI",
        "flight_number": "AI-801",
        "origin": "BOM",
        "destination": "DEL",
        "flight_date": "2026-10-25",
        "departure_time": "12:00",
        "fare": 4000.0,
        "source_portal": "airindia",
        "flight_status": "cancelled",
    }
    res_canc = engine_cancelled.ingest(ai_item)
    assert res_canc.min_fare == float("inf")
    key_canc, _ = engine_cancelled.generate_flight_key(ai_item)
    state_canc = engine_cancelled.get_flight_state(key_canc)
    assert state_canc is not None
    assert state_canc.best_quote is None
    assert state_canc.best_source_portal == "unknown"

    print(
        "  ✓ Cancelled & sold-out quotes safely bypassed when evaluating best consumer price."
    )


def test_streaming_dedup_preserves_fare_components() -> None:
    """Test 10: Verify fare component splits and fees are preserved in quote ingestion."""
    print("\n[Test 10] Preservation of Fare Component Splits & Fees")

    engine = StreamingDedupEngine(window_seconds=300.0)
    item = {
        "airline_code": "6E",
        "flight_number": "6E-333",
        "origin": "DEL",
        "destination": "BOM",
        "flight_date": "2026-10-22",
        "departure_time": "07:30",
        "fare": 5500.0,
        "base_fare": 4100.0,
        "taxes_and_fees": 1400.0,
        "udf_fee": 300.0,
        "convenience_fee": 150.0,
        "source_portal": "indigo",
        "flight_status": "scheduled",
        "fare_split_basis": "measured",
    }
    res = engine.ingest(item)
    assert res.is_new_flight is True
    assert res.min_fare == 5500.0
    key, _ = engine.generate_flight_key(item)
    state = engine.get_flight_state(key)
    assert state is not None
    quote = state.quotes_by_portal["indigo"]
    assert quote.base_fare == 4100.0
    assert quote.taxes_and_fees == 1400.0
    assert quote.udf_fee == 300.0
    assert quote.convenience_fee == 150.0
    assert quote.flight_status == "scheduled"
    assert quote.fare_split_basis == "measured"
    assert state.best_quote is not None
    assert state.best_quote.base_fare == 4100.0

    print(
        "  ✓ Fare splits (base, taxes, udf, convenience) fully preserved on FlightQuote."
    )


def main() -> int:
    print_header("APIx Streaming Dedup & Arbitrage Engine - Verification Test Suite")
    try:
        test_exact_hash_deduplication()
        test_minimum_consumer_price_resolution()
        test_sub_millisecond_latency_benchmark()
        test_sliding_window_and_out_of_order()
        test_lru_memory_bounding()
        test_cross_platform_arbitrage_detector()
        test_arbitrage_edge_cases()
        test_index_pipeline_and_db_integration()
        test_streaming_dedup_excludes_cancelled_and_sold_out_quotes()
        test_streaming_dedup_preserves_fare_components()

        print_header("ALL 10 VERIFICATION TESTS PASSED SUCCESSFULLY (10/10)")
        return 0
    except Exception as exc:
        logger.exception("Verification test failed: %s", exc)
        print(f"\n❌ FAILED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
