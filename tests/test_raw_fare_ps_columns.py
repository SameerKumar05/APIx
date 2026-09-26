"""Round-trip of the problem-statement fare columns through both write paths."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.fare_components import ESTIMATED_BASE_FARE_RATIO
from backend.app.db.ingestion_repo import bulk_insert_raw_fares, compute_dedup_hash
from backend.app.models.raw_fare import RawFare
from ingestion.base import RawFareRecord


def _record(
    *,
    flight_number: str = "6E-2015",
    fare_inr: float = 5000.0,
    booking_class: str | None = None,
    udf_fee: float | None = None,
    convenience_fee: float | None = None,
    flight_status: str | None = None,
    base_fare: float | None = None,
    taxes_and_fees: float | None = None,
) -> RawFareRecord:
    return RawFareRecord(
        airline_code="6E",
        flight_number=flight_number,
        origin="DEL",
        destination="BOM",
        departure_datetime="2026-10-01T08:00:00",
        arrival_datetime="2026-10-01T10:15:00",
        booking_datetime="2026-09-24T06:00:00",
        fare_inr=fare_inr,
        cabin_class="economy",
        stops=0,
        source="makemytrip",
        booking_window="T+7",
        booking_class=booking_class,
        udf_fee=udf_fee,
        convenience_fee=convenience_fee,
        flight_status=flight_status,
        base_fare=base_fare,
        taxes_and_fees=taxes_and_fees,
    )


def _identity_dict(
    *,
    flight_number: str = "6E-2015",
    total_fare: float = 5000.0,
    booking_class: str | None = None,
    udf_fee: float | None = None,
    convenience_fee: float | None = None,
    flight_status: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "origin": "DEL",
        "destination": "BOM",
        "flight_date": date(2026, 10, 1),
        "booking_window": "T+7",
        "airline_code": "6E",
        "flight_number": flight_number,
        "departure_time": "2026-10-01T08:00:00",
        "total_fare": total_fare,
        "source_platform": "makemytrip",
        "fare_class": "Economy",
    }
    if booking_class is not None:
        payload["booking_class"] = booking_class
    if udf_fee is not None:
        payload["udf_fee"] = udf_fee
    if convenience_fee is not None:
        payload["convenience_fee"] = convenience_fee
    if flight_status is not None:
        payload["flight_status"] = flight_status
    return payload


def test_ps_fields_round_trip_with_exact_values(db_session: Session) -> None:
    """Given a record that supplies the four PS fields, they persist unchanged."""
    record = _record(
        booking_class="Y",
        udf_fee=150.0,
        convenience_fee=99.0,
        flight_status="scheduled",
        base_fare=4100.0,
        taxes_and_fees=900.0,
    )

    inserted = bulk_insert_raw_fares(db_session, [record], batch_id="ps-round-trip")

    assert inserted["inserted"] == 1
    row = db_session.scalars(select(RawFare)).one()
    assert row.booking_class == "Y"
    assert row.udf_fee == 150.0
    assert row.convenience_fee == 99.0
    assert row.flight_status == "scheduled"
    assert row.fare_class == "economy"
    assert row.base_fare == 4100.0
    assert row.taxes_and_fees == 900.0


def test_omitted_ps_fields_persist_as_null(db_session: Session) -> None:
    """Given no booking class, fees, or status, the row stores NULL rather than a guess."""
    record = _record()
    assert record.booking_class is None
    assert record.udf_fee is None
    assert record.convenience_fee is None
    assert record.flight_status is None

    bulk_insert_raw_fares(db_session, [record], batch_id="ps-omit-dataclass")
    bulk_insert_raw_fares(
        db_session,
        [_identity_dict(flight_number="6E-2016")],
        batch_id="ps-omit-dict",
    )

    rows = {row.flight_number: row for row in db_session.scalars(select(RawFare)).all()}
    for flight_number in ("6E-2015", "6E-2016"):
        row = rows[flight_number]
        assert row.booking_class is None
        assert row.udf_fee is None
        assert row.convenience_fee is None
        assert row.flight_status is None


def test_zero_fee_is_kept_and_missing_fee_is_not_copied(db_session: Session) -> None:
    """A supplied zero is a measurement. The other fee is not invented from it."""
    bulk_insert_raw_fares(
        db_session,
        [_identity_dict(udf_fee=0.0, flight_number="6E-3001")],
        batch_id="ps-zero-fee",
    )

    row = db_session.scalars(select(RawFare)).one()
    assert row.udf_fee == 0.0
    assert row.convenience_fee is None


def test_missing_split_uses_one_ratio_and_supplied_split_is_kept(
    db_session: Session,
) -> None:
    """Both write paths estimate with the same ratio, and only when the split is absent."""
    total = 1000.0
    expected_base = round(total * ESTIMATED_BASE_FARE_RATIO, 2)
    dataclass_record = _record(fare_inr=total, flight_number="6E-4001")
    assert dataclass_record.base_fare == expected_base
    assert dataclass_record.taxes_and_fees == round(total - expected_base, 2)

    supplied = _record(
        fare_inr=total,
        flight_number="6E-4002",
        base_fare=640.0,
        taxes_and_fees=360.0,
    )
    assert supplied.base_fare == 640.0
    assert supplied.taxes_and_fees == 360.0

    bulk_insert_raw_fares(
        db_session,
        [
            dataclass_record,
            _identity_dict(flight_number="6E-4003", total_fare=total),
            supplied,
        ],
        batch_id="ps-split",
    )
    rows = {row.flight_number: row for row in db_session.scalars(select(RawFare)).all()}
    assert rows["6E-4001"].base_fare == expected_base
    assert rows["6E-4003"].base_fare == expected_base
    assert rows["6E-4002"].base_fare == 640.0
    assert rows["6E-4002"].taxes_and_fees == 360.0
    assert rows["6E-4001"].udf_fee is None


def test_dedup_hash_ignores_ps_fields(db_session: Session) -> None:
    """A different booking class or status must not create a second raw fare."""
    first = _identity_dict(booking_class="Y", flight_status="scheduled", udf_fee=150.0)
    second = _identity_dict(
        booking_class="B",
        flight_status="cancelled",
        convenience_fee=99.0,
    )
    assert compute_dedup_hash(
        "6E", "6E-2015", "DEL", "BOM", "2026-10-01T08:00:00", "T+7"
    ) == compute_dedup_hash("6E", "6E-2015", "DEL", "BOM", "2026-10-01T08:00:00", "T+7")

    result = bulk_insert_raw_fares(db_session, [first, second], batch_id="ps-hash")

    assert result["inserted"] == 1
    assert result["duplicates"] == 1
    assert db_session.scalars(select(RawFare)).one().booking_class == "Y"


def test_model_columns_are_nullable_without_a_server_default() -> None:
    """The ORM columns match the migration: nullable, no invented default."""
    for name in ("booking_class", "udf_fee", "convenience_fee", "flight_status"):
        column = RawFare.__table__.columns[name]
        assert column.nullable is True
        assert column.server_default is None
