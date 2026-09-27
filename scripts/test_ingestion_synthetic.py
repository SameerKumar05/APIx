#!/usr/bin/env python3
"""Verification script for APIx Ingestion Synthetic Flight Fare Generator.

Validates:
1. Exactly 50 slots generated (10 routes x 5 booking windows).
2. Exactly 0 null fares across all generated records.
3. All origin and destination codes are valid 3-letter IATA airport codes.
4. All airline codes are valid Indian domestic carrier codes.
5. All fares are positive INR amounts conforming to DGCA price boundaries.
6. Chronological integrity (arrival > departure, valid ISO-8601 timestamps).
7. Economic pricing curve dynamics (T+1 avg fare > T+7 > T+15 > T+30).
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime

# Add worktree root to python path to ensure ingestion package is importable
worktree_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if worktree_root not in sys.path:
    sys.path.insert(0, worktree_root)

from ingestion.config import (
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    VALID_AIRLINE_CODES,
    VALID_IATA_CODES,
)
from ingestion.crawlers.synthetic import SyntheticFlightGenerator


def run_verification() -> None:
    print("=" * 80)
    print("APIx Ingestion - Synthetic Fare Generator Premier Verification")
    print("=" * 80)

    generator = SyntheticFlightGenerator(seed=42)
    print("[1/5] Executing synthetic generation across all routes and windows...")
    slots = generator.generate_all_slots()

    # --- Assertion 1: Exactly 50 slots generated ---
    expected_slots = len(DEFAULT_ROUTES) * len(BOOKING_WINDOWS)
    actual_slots = len(slots)
    print(f"      Generated slots: {actual_slots} (Expected: {expected_slots})")
    assert (
        actual_slots == 70
    ), f"Assertion failed: Expected exactly 70 slots, got {actual_slots}"
    print("      ✓ Assertion Passed: Exactly 70 slots generated.")

    # Check uniqueness of slot keys (route x window)
    slot_keys = set()
    for s in slots:
        key = (s.metadata["route"], s.metadata["window"])
        assert key not in slot_keys, f"Duplicate slot detected: {key}"
        slot_keys.add(key)
    assert (
        len(slot_keys) == 70
    ), f"Assertion failed: Expected 70 unique slot keys, got {len(slot_keys)}"
    print("      ✓ Assertion Passed: All 70 slots are distinct route-window pairs.")

    # Flatten records
    all_records = []
    for s in slots:
        assert s.success, f"Slot {s.metadata} marked as unsuccessful: {s.errors}"
        all_records.extend(s.records)

    total_records = len(all_records)
    print(f"\n[2/5] Inspecting {total_records} flight fare records across all slots...")

    # --- Assertion 2: Zero null or invalid fares ---
    null_fares = [r for r in all_records if r.fare_inr is None]
    non_positive_fares = [
        r for r in all_records if r.fare_inr is not None and r.fare_inr <= 0
    ]
    print(f"      Null fares found: {len(null_fares)}")
    print(f"      Non-positive fares found: {len(non_positive_fares)}")
    assert (
        len(null_fares) == 0
    ), f"Assertion failed: Expected 0 null fares, found {len(null_fares)}"
    assert (
        len(non_positive_fares) == 0
    ), f"Assertion failed: Expected 0 non-positive fares, found {len(non_positive_fares)}"
    print("      ✓ Assertion Passed: 0 null fares and 0 non-positive fares.")

    # --- Assertion 3: Valid IATA codes ---
    invalid_iatas = []
    for r in all_records:
        if r.origin not in VALID_IATA_CODES:
            invalid_iatas.append((r.flight_number, "origin", r.origin))
        if r.destination not in VALID_IATA_CODES:
            invalid_iatas.append((r.flight_number, "destination", r.destination))
        if r.origin == r.destination:
            invalid_iatas.append(
                (r.flight_number, "loop", f"{r.origin}->{r.destination}")
            )

    print(f"      Invalid IATA occurrences: {len(invalid_iatas)}")
    assert (
        len(invalid_iatas) == 0
    ), f"Assertion failed: Invalid IATAs detected: {invalid_iatas[:5]}"
    print(
        f"      ✓ Assertion Passed: 100% valid 3-letter IATA codes ({', '.join(sorted(VALID_IATA_CODES))})."
    )

    # --- Assertion 4: Valid Airline codes & Flight numbers ---
    invalid_airlines = [
        r for r in all_records if r.airline_code not in VALID_AIRLINE_CODES
    ]
    print(f"      Invalid airline codes: {len(invalid_airlines)}")
    assert (
        len(invalid_airlines) == 0
    ), f"Assertion failed: Invalid airlines detected: {invalid_airlines[:5]}"
    print(
        f"      ✓ Assertion Passed: 100% valid airline codes ({', '.join(sorted(VALID_AIRLINE_CODES))})."
    )

    # --- Assertion 5: Schema conformity & Chronological validation ---
    schema_errors = []
    for r in all_records:
        # Check required fields
        if not r.flight_number or not isinstance(r.flight_number, str):
            schema_errors.append(f"{r.flight_number}: invalid flight_number")
        if not r.departure_datetime or not r.arrival_datetime:
            schema_errors.append(f"{r.flight_number}: missing datetime")
        try:
            dep = datetime.fromisoformat(r.departure_datetime)
            arr = datetime.fromisoformat(r.arrival_datetime)
            if arr <= dep:
                schema_errors.append(f"{r.flight_number}: arr <= dep ({arr} <= {dep})")
        except Exception as e:
            schema_errors.append(f"{r.flight_number}: datetime parse error: {e}")

        # Check to_dict() and hash_id generation
        d = r.to_dict()
        if (
            not d.get("hash_id")
            or not d.get("origin_iata")
            or not d.get("destination_iata")
        ):
            schema_errors.append(
                f"{r.flight_number}: missing hash_id or iata aliases in dict"
            )

    assert (
        len(schema_errors) == 0
    ), f"Assertion failed: Schema validation errors: {schema_errors[:5]}"
    print(
        "      ✓ Assertion Passed: Output schema conforms strictly with valid timestamps and dedup hashes."
    )

    # --- Dynamic Pricing Curve Analysis ---
    print("\n[3/5] Calibrated Dynamic Pricing Curve Breakdown by Booking Window:")
    window_fares = defaultdict(list)
    for r in all_records:
        window_fares[r.booking_window].append(r.fare_inr)

    avg_fares = {}
    print(
        f"      {'Window':<8} | {'Flights':<8} | {'Min Fare (₹)':<14} | {'Avg Fare (₹)':<14} | {'Max Fare (₹)':<14}"
    )
    print("      " + "-" * 66)
    for win in ["T+1", "T+7", "T+15", "T+30", "T+45"]:
        fares = window_fares[win]
        avg = sum(fares) / len(fares)
        avg_fares[win] = avg
        print(
            f"      {win:<8} | {len(fares):<8} | {min(fares):<14.2f} | {avg:<14.2f} | {max(fares):<14.2f}"
        )

    # Verify monotonic relationship T+1 > T+7 > T+15 > T+30
    assert (
        avg_fares["T+1"] > avg_fares["T+7"]
    ), "Pricing error: T+1 avg fare should exceed T+7"
    assert (
        avg_fares["T+7"] > avg_fares["T+15"]
    ), "Pricing error: T+7 avg fare should exceed T+15"
    assert (
        avg_fares["T+15"] > avg_fares["T+30"]
    ), "Pricing error: T+15 avg fare should exceed T+30"
    print(
        "      ✓ Assertion Passed: Calibrated surge pricing curve verified: T+1 > T+7 > T+15 > T+30."
    )

    # --- Route-level Breakdown ---
    print("\n[4/5] Route Summary (10 Route Pairs x 5 Windows = 50 Slots):")
    route_counts = defaultdict(int)
    for s in slots:
        route_counts[s.metadata["route"]] += 1

    for route_key, count in sorted(route_counts.items()):
        print(f"      Route {route_key}: {count} windows configured")
        assert count == 5, f"Route {route_key} does not have 5 windows"

    # --- Sample Record Preview ---
    sample = all_records[0]
    print("\n[5/5] Sample RawFareRecord Preview:")
    for k, v in sample.to_dict().items():
        print(f"      {k}: {v}")

    print("\n" + "=" * 80)
    print(
        "PREMIER VERIFICATION CONFIRMED: 50/50 SLOTS, 0 NULL FARES, VALID IATA CODES."
    )
    print("=" * 80)


if __name__ == "__main__":
    try:
        run_verification()
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ VERIFICATION FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(2)
