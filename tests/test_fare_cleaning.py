"""Data-cleaning policy: outliers, non-payable flights, and missing values.

Given / When / Then against the ingest write and the daily index, not against
private call counts.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.cleaning import (
    OUTLIER_LOOKBACK_DAYS,
    outlier_against_peers,
    resolve_duration_minutes,
)
from backend.app.core.fare_components import (
    ESTIMATED_BASE_FARE_RATIO,
    classify_fare_split,
)
from backend.app.db.ingestion_repo import bulk_insert_raw_fares
from backend.app.models.index import RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.services.index_pipeline import run_daily_index_pipeline
from ingestion.base import RawFareRecord
from ingestion.crawlers.easemytrip import EaseMyTripScraper
from ingestion.crawlers.makemytrip import MakeMyTripScraper
from ingestion.crawlers.spicejet import SpiceJetScraper


def test_tukey_flags_an_extreme_fare_only_when_peers_exist() -> None:
    """Given six equal peers, 25000 is outside the fence; two peers are not enough."""
    peers = [4200.0, 4200.0, 4200.0, 4200.0, 4200.0, 4200.0]

    assert outlier_against_peers(25000.0, peers) is True
    assert outlier_against_peers(4200.0, peers) is False
    assert outlier_against_peers(25000.0, [4200.0, 4300.0]) is False
    assert OUTLIER_LOOKBACK_DAYS == 30


def test_one_supplied_component_is_a_residual_not_the_ratio() -> None:
    """A source that gave only the base keeps that base. The tax is the remainder."""
    split = classify_fare_split(1000.0, 640.0, None)

    assert split.basis.value == "residual"
    assert split.base_fare == 640.0
    assert split.taxes_and_fees == 360.0


def test_missing_departure_does_not_become_a_zero_duration() -> None:
    """A missing clock stays NULL. A supplied positive duration is kept."""
    assert resolve_duration_minutes(0, None, None) is None
    assert resolve_duration_minutes(120, None, None) is None
    departure = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    arrival = datetime(2026, 10, 1, 10, 15, tzinfo=UTC)
    assert resolve_duration_minutes(None, departure, arrival) == 135
    assert resolve_duration_minutes(90, departure, arrival) == 90


def test_ingest_persists_outlier_and_index_uses_only_the_normal_fare(
    db_session: Session,
) -> None:
    """A 25000 fare is stored, flagged, and absent from the representative fare.

    Peers sit inside the lookback but on an earlier flight date, so the day's
    Tukey trim has too few points to hide the outlier by itself. Exclusion has
    to come from the ingest flag.
    """
    calc_date = date(2026, 9, 26)
    peer_date = calc_date - timedelta(days=5)
    peer_scraped = datetime.combine(peer_date, time(12, 0), tzinfo=UTC)
    today_scraped = datetime.combine(calc_date, time(8, 0), tzinfo=UTC)

    peers = [
        _fare(
            flight_number=f"6E-10{index}",
            total_fare=4200.0,
            flight_date=peer_date,
            scraped_at=peer_scraped,
            departure=f"{peer_date.isoformat()}T08:00:00",
        )
        for index in range(6)
    ]
    bulk_insert_raw_fares(db_session, peers, batch_id="peers")

    today = [
        _fare(
            flight_number="6E-2001",
            total_fare=4200.0,
            flight_date=calc_date,
            scraped_at=today_scraped,
            flight_status="scheduled",
        ),
        _fare(
            flight_number="6E-2002",
            total_fare=25000.0,
            flight_date=calc_date,
            scraped_at=today_scraped,
            flight_status="scheduled",
        ),
        _fare(
            flight_number="6E-2003",
            total_fare=4100.0,
            flight_date=calc_date,
            scraped_at=today_scraped,
            flight_status="cancelled",
        ),
        _fare(
            flight_number="6E-2004",
            total_fare=4300.0,
            flight_date=calc_date,
            scraped_at=today_scraped,
            flight_status="sold_out",
        ),
    ]
    inserted = bulk_insert_raw_fares(db_session, today, batch_id="today")

    assert inserted["inserted"] == 4
    rows = {row.flight_number: row for row in db_session.scalars(select(RawFare)).all()}
    assert rows["6E-2002"].total_fare == 25000.0
    assert rows["6E-2002"].index_exclusion_reason == "outlier"
    assert rows["6E-2003"].index_exclusion_reason == "cancelled"
    assert rows["6E-2003"].total_fare == 4100.0
    assert rows["6E-2004"].index_exclusion_reason == "sold_out"
    assert rows["6E-2001"].index_exclusion_reason is None
    assert rows["6E-2001"].total_fare == 4200.0

    # A cancelled row that bypassed classification must still miss the index.
    db_session.add(
        RawFare(
            batch_id="direct",
            origin="DEL",
            destination="BOM",
            flight_date=calc_date,
            booking_window="T+7",
            airline_code="6E",
            flight_number="6E-2099",
            departure_time=today_scraped,
            stops=0,
            fare_class="Economy",
            base_fare=3999.0,
            taxes_and_fees=0.0,
            total_fare=3999.0,
            source_platform="synthetic",
            scraped_at=today_scraped,
            hash_id="direct-cancelled-3999",
            is_synthetic=True,
            flight_status="cancelled",
            index_exclusion_reason=None,
        )
    )
    db_session.commit()

    result = run_daily_index_pipeline(db=db_session, calculation_date=calc_date)

    assert result["status"] == "success"
    window = db_session.scalars(
        select(RouteDailyIndex).where(
            RouteDailyIndex.origin == "DEL",
            RouteDailyIndex.destination == "BOM",
            RouteDailyIndex.index_date == calc_date,
            RouteDailyIndex.booking_window == "T+7",
        )
    ).one()
    assert window.sample_size == 1
    assert window.median_fare == 4200.0
    assert window.min_fare == 4200.0
    assert window.max_fare == 4200.0
    assert (
        db_session.scalars(select(RawFare).where(RawFare.flight_number == "6E-2002"))
        .one()
        .total_fare
        == 25000.0
    )


def test_missing_split_is_marked_estimated_and_supplied_split_is_measured(
    db_session: Session,
) -> None:
    """The ratio is calibrated when carrier/route are known. A source-supplied split is not rewritten."""
    total = 1000.0
    expected_base = round(total * ESTIMATED_BASE_FARE_RATIO, 2)
    omitted = RawFareRecord(
        airline_code="6E",
        flight_number="6E-5001",
        origin="DEL",
        destination="BOM",
        departure_datetime="2026-10-01T08:00:00",
        arrival_datetime="2026-10-01T10:15:00",
        booking_datetime="2026-09-24T06:00:00",
        fare_inr=total,
        booking_window="T+7",
        source="makemytrip",
    )
    supplied = RawFareRecord(
        airline_code="6E",
        flight_number="6E-5002",
        origin="DEL",
        destination="BOM",
        departure_datetime="2026-10-01T09:00:00",
        arrival_datetime="2026-10-01T11:15:00",
        booking_datetime="2026-09-24T06:00:00",
        fare_inr=total,
        booking_window="T+7",
        source="makemytrip",
        base_fare=640.0,
        taxes_and_fees=360.0,
        udf_fee=None,
        convenience_fee=None,
    )

    assert omitted.fare_split_basis == "calibrated"
    assert omitted.base_fare == expected_base
    assert supplied.fare_split_basis == "measured"
    assert supplied.udf_fee is None

    bulk_insert_raw_fares(db_session, [omitted, supplied], batch_id="split")
    rows = {row.flight_number: row for row in db_session.scalars(select(RawFare)).all()}
    assert rows["6E-5001"].fare_split_basis == "calibrated"
    assert rows["6E-5001"].base_fare == expected_base
    assert rows["6E-5001"].udf_fee is None
    assert rows["6E-5001"].convenience_fee is None
    assert rows["6E-5002"].fare_split_basis == "measured"
    assert rows["6E-5002"].base_fare == 640.0
    assert rows["6E-5002"].taxes_and_fees == 360.0


def test_missing_departure_persists_null_duration(db_session: Session) -> None:
    """A zero duration supplied without a departure clock is not stored as zero."""
    bulk_insert_raw_fares(
        db_session,
        [
            {
                "origin": "DEL",
                "destination": "BOM",
                "flight_date": date(2026, 10, 1),
                "booking_window": "T+7",
                "airline_code": "6E",
                "flight_number": "6E-6001",
                "total_fare": 4200.0,
                "source_platform": "makemytrip",
                "duration_minutes": 0,
            }
        ],
        batch_id="no-departure",
    )

    row = db_session.scalars(select(RawFare)).one()
    assert row.departure_time is None
    assert row.duration_minutes is None


def test_crawlers_report_status_the_source_showed_and_do_not_invent_one() -> None:
    """soldOut and a cancelled token are stored; an unrelated status is not."""
    mmt = MakeMyTripScraper().parse_flight_json(
        {
            "flights": [
                _mmt_item("6E-7001", soldOut=True),
                _mmt_item("AI-7002", flightStatus="cancelled"),
                _mmt_item("SG-7003", status="available"),
            ]
        },
        "DEL",
        "BOM",
        "T+7",
    )
    by_flight = {record.flight_number: record.flight_status for record in mmt}
    assert by_flight == {
        "6E-7001": "sold_out",
        "AI-7002": "cancelled",
        "SG-7003": None,
    }

    spice = SpiceJetScraper().parse_flight_json(
        {
            "trips": [
                {
                    "journeys": [
                        {
                            "segments": [
                                {
                                    "airlineCode": "SG",
                                    "flightNumber": "815",
                                    "departureTime": "2026-09-25T09:50:00",
                                    "arrivalTime": "2026-09-25T12:25:00",
                                }
                            ],
                            "totalFare": 4800.0,
                            "soldOut": True,
                        }
                    ]
                }
            ]
        },
        "DEL",
        "BOM",
        "T+7",
    )
    assert len(spice) == 1
    assert spice[0].flight_status == "sold_out"

    emt = EaseMyTripScraper().parse_flight_json(
        {
            "Flights": [
                {
                    "AirlineCode": "6E",
                    "FlightNo": "301",
                    "DepTime": "2026-09-25T06:00:00",
                    "ArrTime": "2026-09-25T08:15:00",
                    "TotalFare": 4500.0,
                    "FlightStatus": "Canceled",
                }
            ]
        },
        "DEL",
        "BOM",
        "T+7",
    )
    assert len(emt) == 1
    assert emt[0].flight_status == "cancelled"
    assert emt[0].udf_fee is None
    assert emt[0].convenience_fee is None


def _fare(
    *,
    flight_number: str,
    total_fare: float,
    flight_date: date,
    scraped_at: datetime,
    flight_status: str | None = "scheduled",
    departure: str | None = None,
) -> dict[str, object]:
    return {
        "origin": "DEL",
        "destination": "BOM",
        "flight_date": flight_date,
        "booking_window": "T+7",
        "airline_code": "6E",
        "flight_number": flight_number,
        "departure_time": departure or f"{flight_date.isoformat()}T08:00:00",
        "total_fare": total_fare,
        "source_platform": "synthetic",
        "scraped_at": scraped_at,
        "flight_status": flight_status,
        "is_synthetic": True,
    }


def _mmt_item(flight_number: str, **extra: object) -> dict[str, object]:
    airline, number = flight_number.split("-")
    item: dict[str, object] = {
        "airlineCode": airline,
        "flightNumber": flight_number,
        "departureTime": "2026-09-25T06:00:00",
        "arrivalTime": "2026-09-25T08:15:00",
        "totalFare": 4500.0,
        "duration": 135,
        "stops": 0,
    }
    item.update(extra)
    return item


def test_raw_fare_record_measured_splits_preserved(db_session: Session) -> None:
    from backend.app.schemas.ingestion import RawFareRecord

    record = RawFareRecord(
        airline_code="6E",
        flight_number="6E-101",
        origin="DEL",
        destination="BOM",
        departure_datetime=datetime(2026, 9, 28, 6, 0, tzinfo=UTC),
        booking_datetime=datetime(2026, 9, 27, 6, 0, tzinfo=UTC),
        fare_inr=5000.0,
        base_fare=3800.0,
        taxes_and_fees=1200.0,
        booking_window="T+1",
    )
    data = record.model_dump()
    assert data["base_fare"] == 3800.0
    assert data["taxes_and_fees"] == 1200.0

    inserted = bulk_insert_raw_fares(db_session, [data])
    assert inserted["inserted"] == 1

    row = db_session.scalars(
        select(RawFare).where(RawFare.flight_number == "6E-101")
    ).one()
    assert row.total_fare == 5000.0
    assert row.base_fare == 3800.0
    assert row.taxes_and_fees == 1200.0
    assert row.fare_split_basis == "measured"


def test_classify_fare_split_residual_taxes_and_measured() -> None:
    """classify_fare_split handles residual from tax, explicit measured, and fallback estimate."""
    from backend.app.core.fare_components import (
        FareSplitBasis,
        split_base_and_taxes,
    )

    # 1. Tax supplied only -> base is residual
    split_tax_only = classify_fare_split(1000.0, None, 350.0)
    assert split_tax_only.basis == FareSplitBasis.RESIDUAL
    assert split_tax_only.base_fare == 650.0
    assert split_tax_only.taxes_and_fees == 350.0

    # 2. Both supplied -> measured
    split_measured = classify_fare_split(1200.0, 900.0, 300.0)
    assert split_measured.basis == FareSplitBasis.MEASURED
    assert split_measured.base_fare == 900.0
    assert split_measured.taxes_and_fees == 300.0

    # 3. Neither supplied -> estimated
    split_est = classify_fare_split(1000.0, None, None)
    assert split_est.basis == FareSplitBasis.ESTIMATED
    assert split_est.base_fare == round(1000.0 * ESTIMATED_BASE_FARE_RATIO, 2)
    assert split_est.taxes_and_fees == round(1000.0 - split_est.base_fare, 2)

    # 4. split_base_and_taxes returns (base, tax)
    b, t = split_base_and_taxes(1200.0, 900.0, 300.0)
    assert b == 900.0
    assert t == 300.0


def test_canonical_flight_status_and_booking_class_helpers() -> None:
    """Verify normalisation of flight status tokens and RBD booking codes."""
    from backend.app.core.fare_components import (
        canonical_booking_class,
        canonical_flight_status,
    )

    # Flight status aliases
    assert canonical_flight_status("cancelled") == "cancelled"
    assert canonical_flight_status("canceled") == "cancelled"
    assert canonical_flight_status("sold_out") == "sold_out"
    assert canonical_flight_status("sold-out") == "sold_out"
    assert canonical_flight_status("soldout") == "sold_out"
    assert canonical_flight_status("scheduled") == "scheduled"
    assert canonical_flight_status("schedule") == "scheduled"
    assert canonical_flight_status("DELAYED") == "delayed"
    assert canonical_flight_status(None) is None
    assert canonical_flight_status("   ") is None

    # Booking class
    assert canonical_booking_class("  y  ") == "Y"
    assert canonical_booking_class("j") == "J"
    assert canonical_booking_class(None) is None
    assert canonical_booking_class("   ") is None


def test_optional_amount_parsing_edge_cases() -> None:
    """Verify optional_amount correctly parses numbers, ignores booleans, and treats blanks as None."""
    from backend.app.core.fare_components import optional_amount

    assert optional_amount(150) == 150.0
    assert optional_amount(250.75) == 250.75
    assert optional_amount(" 300.50 ") == 300.5
    assert optional_amount(0) == 0.0
    assert optional_amount(0.0) == 0.0
    assert optional_amount(None) is None
    assert optional_amount(True) is None
    assert optional_amount(False) is None
    assert optional_amount("") is None
    assert optional_amount("   ") is None


def test_calibrated_carrier_and_route_fare_splitting() -> None:
    """Verify carrier- and route-aware calibrated base ratios and basis classification."""
    from backend.app.core.fare_components import (
        DEFAULT_BASE_FARE_RATIO,
        FareSplitBasis,
        classify_fare_split,
        get_calibrated_base_fare_ratio,
        get_calibrated_base_fare_ratio_and_basis,
    )

    total = 10000.0

    # 1. Carrier calibration without route: Air India (FSC) ~0.81, SpiceJet (LCC) ~0.74
    ai_split = classify_fare_split(total, airline_code="AI")
    assert ai_split.basis == FareSplitBasis.CALIBRATED
    assert ai_split.base_fare == 8100.0
    assert ai_split.taxes_and_fees == 1900.0

    sg_split = classify_fare_split(total, airline_code="SG")
    assert sg_split.basis == FareSplitBasis.CALIBRATED
    assert sg_split.base_fare == 7400.0
    assert sg_split.taxes_and_fees == 2600.0

    # 2. Route calibration without carrier: long-haul (DEL-BLR, 1740km) 0.81 vs short-haul (BLR-HYD, 500km) 0.72
    long_haul = classify_fare_split(total, origin="DEL", destination="BLR")
    assert long_haul.basis == FareSplitBasis.CALIBRATED
    assert long_haul.base_fare == 8100.0

    short_haul = classify_fare_split(total, origin="BLR", destination="HYD")
    assert short_haul.basis == FareSplitBasis.CALIBRATED
    assert short_haul.base_fare == 7200.0

    # 3. Joint carrier and route calibration: Air India (+0.03 offset) on DEL-BLR (0.81 baseline) -> 0.84
    ai_long = classify_fare_split(
        total, airline_code="AI", origin="DEL", destination="BLR"
    )
    assert ai_long.basis == FareSplitBasis.CALIBRATED
    assert ai_long.base_fare == 8400.0
    assert ai_long.taxes_and_fees == 1600.0

    # 4. Joint carrier and route calibration: SpiceJet (-0.04 offset) on BLR-HYD (0.72 baseline) -> 0.68
    sg_short = classify_fare_split(
        total, airline_code="SG", origin="BLR", destination="HYD"
    )
    assert sg_short.basis == FareSplitBasis.CALIBRATED
    assert sg_short.base_fare == 6800.0
    assert sg_short.taxes_and_fees == 3200.0

    # 5. Generic fallback when neither carrier nor route is recognized: 0.78, basis ESTIMATED
    fallback = classify_fare_split(
        total, airline_code="UNKNOWN", origin="XXX", destination="YYY"
    )
    assert fallback.basis == FareSplitBasis.ESTIMATED
    assert fallback.base_fare == round(total * DEFAULT_BASE_FARE_RATIO, 2)


def test_total_recomposition_integrity_check() -> None:
    """Verify check_fare_recomposition enforces total ≈ base + taxes + UDF + convenience."""
    from backend.app.core.fare_components import check_fare_recomposition

    # 1. Exact match when all components exist
    assert (
        check_fare_recomposition(
            total_fare=5000.0,
            base_fare=3500.0,
            taxes_and_fees=1000.0,
            udf_fee=300.0,
            convenience_fee=200.0,
        )
        is True
    )

    # 2. Within relative tolerance (0.5% of 5000 is 25 INR): delta = 15 INR -> True
    assert (
        check_fare_recomposition(
            total_fare=5000.0,
            base_fare=3500.0,
            taxes_and_fees=1000.0,
            udf_fee=315.0,
            convenience_fee=200.0,
        )
        is True
    )

    # 3. Beyond relative tolerance: delta = 50 INR (> 25 INR) -> False
    assert (
        check_fare_recomposition(
            total_fare=5000.0,
            base_fare=3500.0,
            taxes_and_fees=1000.0,
            udf_fee=350.0,
            convenience_fee=200.0,
        )
        is False
    )

    # 4. Small fare governed by absolute tolerance (1.0 INR): delta = 0.75 INR -> True, 2.0 INR -> False
    assert (
        check_fare_recomposition(
            total_fare=100.0,
            base_fare=70.0,
            taxes_and_fees=30.75,
        )
        is True
    )
    assert (
        check_fare_recomposition(
            total_fare=100.0,
            base_fare=70.0,
            taxes_and_fees=32.0,
        )
        is False
    )

    # 5. Incomplete components (None) do not false-alarm
    assert (
        check_fare_recomposition(
            total_fare=5000.0,
            base_fare=None,
            taxes_and_fees=None,
        )
        is True
    )


def test_recomposition_mismatch_quarantined_at_ingestion(db_session: Session) -> None:
    """Verify bulk_insert_raw_fares quarantines split recomposition mismatches."""
    from backend.app.core.cleaning import EXCLUSION_RECOMPOSITION_MISMATCH

    valid_quote = {
        "origin": "DEL",
        "destination": "BOM",
        "flight_date": date(2026, 10, 5),
        "booking_window": "T+7",
        "airline_code": "6E",
        "flight_number": "6E-7001",
        "departure_time": "2026-10-05T08:00:00",
        "total_fare": 5000.0,
        "base_fare": 3500.0,
        "taxes_and_fees": 1000.0,
        "udf_fee": 300.0,
        "convenience_fee": 200.0,
        "fare_split_basis": "measured",
        "source_platform": "makemytrip",
    }

    # Corrupted quote: components sum to 3700 != 5000 (mismatch by 1300 INR)
    corrupted_quote = {
        "origin": "DEL",
        "destination": "BOM",
        "flight_date": date(2026, 10, 5),
        "booking_window": "T+7",
        "airline_code": "6E",
        "flight_number": "6E-7002",
        "departure_time": "2026-10-05T09:00:00",
        "total_fare": 5000.0,
        "base_fare": 2000.0,
        "taxes_and_fees": 1000.0,
        "udf_fee": 500.0,
        "convenience_fee": 200.0,
        "fare_split_basis": "measured",
        "source_platform": "makemytrip",
    }

    result = bulk_insert_raw_fares(
        db_session, [valid_quote, corrupted_quote], batch_id="recomp_batch"
    )
    assert result["inserted"] == 2

    rows = {row.flight_number: row for row in db_session.scalars(select(RawFare)).all()}
    assert rows["6E-7001"].index_exclusion_reason is None
    assert rows["6E-7002"].index_exclusion_reason == EXCLUSION_RECOMPOSITION_MISMATCH
    assert rows["6E-7002"].index_exclusion_reason == "split_recomposition_mismatch"


def test_sparse_window_policy_preserves_quotes_unless_recomposition_fails(
    db_session: Session,
) -> None:
    """Verify sparse windows (<4 peers) keep payable quotes, but quarantine recomposition errors."""
    from backend.app.core.cleaning import EXCLUSION_RECOMPOSITION_MISMATCH

    # Only 2 peers on this corridor (MAA-DEL) in this window (sparse: < 4 Tukey peers)
    sparse_quotes = [
        {
            "origin": "MAA",
            "destination": "DEL",
            "flight_date": date(2026, 10, 10),
            "booking_window": "T+15",
            "airline_code": "AI",
            "flight_number": "AI-9001",
            "departure_time": "2026-10-10T06:00:00",
            "total_fare": 4500.0,
            "source_platform": "air_india",
        },
        # High fare: would be an outlier if peer fence existed, but with <4 peers it must be kept
        {
            "origin": "MAA",
            "destination": "DEL",
            "flight_date": date(2026, 10, 10),
            "booking_window": "T+15",
            "airline_code": "AI",
            "flight_number": "AI-9002",
            "departure_time": "2026-10-10T12:00:00",
            "total_fare": 18000.0,
            "source_platform": "air_india",
        },
        # Third quote in same sparse window with recomposition mismatch
        {
            "origin": "MAA",
            "destination": "DEL",
            "flight_date": date(2026, 10, 10),
            "booking_window": "T+15",
            "airline_code": "AI",
            "flight_number": "AI-9003",
            "departure_time": "2026-10-10T18:00:00",
            "total_fare": 6000.0,
            "base_fare": 2000.0,
            "taxes_and_fees": 1000.0,
            "udf_fee": 300.0,
            "convenience_fee": 100.0,
            "fare_split_basis": "measured",
            "source_platform": "air_india",
        },
    ]

    bulk_insert_raw_fares(db_session, sparse_quotes, batch_id="sparse_batch")
    rows = {row.flight_number: row for row in db_session.scalars(select(RawFare)).all()}

    # Sparse policy: AI-9001 and AI-9002 are not outliers because peer count < 4
    assert rows["AI-9001"].index_exclusion_reason is None
    assert rows["AI-9002"].index_exclusion_reason is None

    # Structural check still applies: AI-9003 has recomposition error (3400 != 6000)
    assert rows["AI-9003"].index_exclusion_reason == EXCLUSION_RECOMPOSITION_MISMATCH
