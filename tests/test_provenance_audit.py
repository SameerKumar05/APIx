"""Tests for provenance audit logic in scripts/audit_provenance.py."""

from datetime import UTC, date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.db.session import Base
from backend.app.models.raw_fare import RawFare
from backend.app.models.telemetry import ProxyHealthRecord, ScraperTelemetry
from scripts.audit_provenance import audit


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_provenance_empty_db(db_session: Session):
    report = audit(db_session)
    assert report["verdict"] == "PASS"
    assert report["rows_claiming_live_total"] == 0
    assert len(report["violations"]) == 0


def test_provenance_synthetic_rows_pass_without_telemetry(db_session: Session):
    fare = RawFare(
        batch_id="batch-001",
        origin="DEL",
        destination="BOM",
        flight_date=date(2026, 10, 1),
        booking_window="T+7",
        flight_number="AI-101",
        airline_code="AI",
        departure_time=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        arrival_time=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        base_fare=5000.0,
        taxes_and_fees=500.0,
        total_fare=5500.0,
        source_platform="synthetic_generator",
        scraped_at=datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
        hash_id="synthetic-hash-001",
        is_synthetic=True,
    )
    db_session.add(fare)
    db_session.commit()

    report = audit(db_session)
    assert report["verdict"] == "PASS"
    assert report["rows_claiming_live_total"] == 0
    assert len(report["violations"]) == 0


def test_provenance_uncorroborated_live_row_fails(db_session: Session):
    fare = RawFare(
        batch_id="batch-002",
        origin="DEL",
        destination="BOM",
        flight_date=date(2026, 10, 1),
        booking_window="T+7",
        flight_number="6E-202",
        airline_code="6E",
        departure_time=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        arrival_time=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        base_fare=5000.0,
        taxes_and_fees=500.0,
        total_fare=5500.0,
        source_platform="indigo",
        scraped_at=datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
        hash_id="live-hash-001",
        is_synthetic=False,
    )
    db_session.add(fare)
    db_session.commit()

    report = audit(db_session)
    assert report["verdict"] == "FAIL"
    assert report["rows_claiming_live_total"] == 1
    assert len(report["violations"]) == 1
    assert report["violations"][0]["source_platform"] == "indigo"
    assert report["violations"][0]["verdict"] == "UNCORROBORATED"


def test_provenance_corroborated_live_row_passes(db_session: Session):
    fare1 = RawFare(
        batch_id="batch-003",
        origin="DEL",
        destination="BOM",
        flight_date=date(2026, 10, 1),
        booking_window="T+7",
        flight_number="6E-202",
        airline_code="6E",
        departure_time=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        arrival_time=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        base_fare=5000.0,
        taxes_and_fees=500.0,
        total_fare=5500.0,
        source_platform="indigo",
        scraped_at=datetime(2026, 9, 25, 12, 0, tzinfo=UTC),
        hash_id="live-hash-002",
        is_synthetic=False,
    )
    fare2 = RawFare(
        batch_id="batch-003",
        origin="DEL",
        destination="BOM",
        flight_date=date(2026, 10, 1),
        booking_window="T+7",
        flight_number="6E-203",
        airline_code="6E",
        departure_time=datetime(2026, 10, 1, 14, 0, tzinfo=UTC),
        arrival_time=datetime(2026, 10, 1, 16, 0, tzinfo=UTC),
        base_fare=5200.0,
        taxes_and_fees=500.0,
        total_fare=5700.0,
        source_platform="indigo",
        scraped_at=datetime(2026, 9, 25, 13, 0, tzinfo=UTC),
        hash_id="live-hash-003",
        is_synthetic=False,
    )
    db_session.add_all([fare1, fare2])

    proxy = ProxyHealthRecord(
        proxy_ip="192.168.1.1:8080",
        status="HEALTHY",
        latency_ms=120.0,
        success_count=10,
        failure_count=0,
        consecutive_failures=0,
        last_checked_at=datetime.now(UTC),
    )
    db_session.add(proxy)

    telemetry = ScraperTelemetry(
        crawler_name="indigo",
        route="DEL-BOM",
        booking_window="T+7",
        status="SUCCESS",
        response_time_ms=1200.0,
    )
    db_session.add(telemetry)

    db_session.commit()

    report = audit(db_session)
    assert report["verdict"] == "PASS"
    assert report["rows_claiming_live_total"] == 2
    assert len(report["violations"]) == 0
    assert report["per_source"][0]["verdict"] == "CORROBORATED"
