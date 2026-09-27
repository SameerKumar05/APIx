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
    """The ratio is an estimate. A source-supplied split is not rewritten."""
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

    assert omitted.fare_split_basis == "estimated"
    assert omitted.base_fare == expected_base
    assert supplied.fare_split_basis == "measured"
    assert supplied.udf_fee is None

    bulk_insert_raw_fares(db_session, [omitted, supplied], batch_id="split")
    rows = {row.flight_number: row for row in db_session.scalars(select(RawFare)).all()}
    assert rows["6E-5001"].fare_split_basis == "estimated"
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

