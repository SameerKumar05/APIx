"""Master Pytest Fixtures and Configuration for APIx Test Suite.

Provides:
- In-memory SQLite isolated database engines and sessions with SQLite foreign keys.
- Pre-seeded database session fixture with standard DGCA routes and airline carriers.
- Mock database sessions for fast unit testing.
- Sample flight fare fixtures across Ingestion, Database, and API representations.
- Synthetic batch generators for high-throughput pipeline testing.
- FastAPI test client fixtures.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Generator, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# Ensure repository root is on sys.path
TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.db.seed import seed_all
from backend.app.db.session import Base
from backend.app.models.raw_fare import RawFare
from backend.app.schemas.ingestion import IngestionBatchRequest
from backend.app.schemas.ingestion import RawFareRecord as ApiRawFareRecord
from backend.app.services.index_engine import FlightQuote
from ingestion.base import RawFareRecord as IngestionRawFareRecord

# ---------------------------------------------------------------------------
# Database Fixtures: In-Memory SQLite & Mock Sessions
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def in_memory_engine() -> Generator[Engine, None, None]:
    """Provides an isolated SQLite in-memory database engine with foreign key enforcement."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def db_session(in_memory_engine: Engine) -> Generator[Session, None, None]:
    """Yields a clean, isolated SQLAlchemy session with fresh schema."""
    SessionTesting = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=in_memory_engine,
        expire_on_commit=False,
    )
    session = SessionTesting()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="function")
def seeded_db_session(db_session: Session) -> Session:
    """Yields an in-memory database session pre-populated with DGCA routes and airlines."""
    seed_all(db_session)
    return db_session


@pytest.fixture(scope="function")
def mock_db_session() -> MagicMock:
    """Provides a MagicMock mimicking a SQLAlchemy Session for unit tests."""
    mock = MagicMock(spec=Session)
    mock.commit.return_value = None
    mock.rollback.return_value = None
    mock.close.return_value = None
    mock.add.return_value = None
    mock.flush.return_value = None
    return mock


# ---------------------------------------------------------------------------
# Sample Flight Fare Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_raw_fare_dict() -> dict[str, Any]:
    """Standard dictionary payload representing a raw airfare quote."""
    return {
        "airline_code": "6E",
        "flight_number": "6E-205",
        "origin": "DEL",
        "destination": "BOM",
        "departure_datetime": "2026-10-01T08:00:00",
        "arrival_datetime": "2026-10-01T10:15:00",
        "booking_datetime": "2026-09-24T06:00:00",
        "fare_inr": 5420.0,
        "cabin_class": "economy",
        "stops": 0,
        "source": "synthetic",
        "booking_window": "T+7",
    }


@pytest.fixture
def sample_ingestion_record(
    sample_raw_fare_dict: dict[str, Any],
) -> IngestionRawFareRecord:
    """Ingestion framework RawFareRecord dataclass instance."""
    return IngestionRawFareRecord(**sample_raw_fare_dict)


@pytest.fixture
def sample_api_record(sample_raw_fare_dict: dict[str, Any]) -> ApiRawFareRecord:
    """FastAPI Pydantic v2 RawFareRecord model instance."""
    data = dict(sample_raw_fare_dict)
    data["departure_datetime"] = datetime.fromisoformat(data["departure_datetime"])
    data["arrival_datetime"] = datetime.fromisoformat(data["arrival_datetime"])
    data["booking_datetime"] = datetime.fromisoformat(data["booking_datetime"])
    data["booking_window"] = 7
    return ApiRawFareRecord(**data)


@pytest.fixture
def sample_db_raw_fare(sample_ingestion_record: IngestionRawFareRecord) -> RawFare:
    """Database SQLAlchemy RawFare model instance derived from sample ingestion record."""
    flight_date_obj = date.fromisoformat(
        sample_ingestion_record.flight_date
        or sample_ingestion_record.departure_datetime[:10]
    )
    dep_dt = datetime.fromisoformat(sample_ingestion_record.departure_datetime).replace(
        tzinfo=UTC
    )
    arr_dt = (
        datetime.fromisoformat(sample_ingestion_record.arrival_datetime).replace(
            tzinfo=UTC
        )
        if sample_ingestion_record.arrival_datetime
        else None
    )
    booking_dt = datetime.fromisoformat(
        sample_ingestion_record.booking_datetime
    ).replace(tzinfo=UTC)

    return RawFare(
        batch_id="batch-test-001",
        origin=sample_ingestion_record.origin,
        destination=sample_ingestion_record.destination,
        flight_date=flight_date_obj,
        booking_window=sample_ingestion_record.booking_window or "T+7",
        airline_code=sample_ingestion_record.airline_code,
        flight_number=sample_ingestion_record.flight_number,
        departure_time=dep_dt,
        arrival_time=arr_dt,
        duration_minutes=sample_ingestion_record.duration_minutes or 135,
        stops=sample_ingestion_record.stops,
        fare_class="Economy",
        base_fare=sample_ingestion_record.base_fare
        or (sample_ingestion_record.fare_inr * 0.78),
        taxes_and_fees=sample_ingestion_record.taxes_and_fees
        or (sample_ingestion_record.fare_inr * 0.22),
        total_fare=sample_ingestion_record.fare_inr,
        source_platform=sample_ingestion_record.source,
        scraped_at=booking_dt,
        hash_id=sample_ingestion_record.generate_dedup_hash(),
        is_synthetic=True,
    )


@pytest.fixture
def sample_flight_quotes() -> list[FlightQuote]:
    """Collection of FlightQuote instances for quant and index calculation testing."""
    return [
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-01",
            airline_code="6E",
            flight_number="6E-204",
            departure_time="08:00",
            fare=5200.0,
        ),
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-01",
            airline_code="AI",
            flight_number="AI-805",
            departure_time="08:30",
            fare=5600.0,
        ),
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-01",
            airline_code="IX",
            flight_number="IX-112",
            departure_time="09:00",
            fare=4900.0,
        ),
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-01",
            airline_code="QP",
            flight_number="QP-1301",
            departure_time="09:30",
            fare=4800.0,
        ),
        FlightQuote(
            origin="DEL",
            destination="BOM",
            flight_date="2026-10-01",
            airline_code="SG",
            flight_number="SG-8169",
            departure_time="10:00",
            fare=5100.0,
        ),
    ]


@pytest.fixture
def sample_batch_request(sample_api_record: ApiRawFareRecord) -> IngestionBatchRequest:
    """Pre-built IngestionBatchRequest instance for testing API ingestion endpoints."""
    return IngestionBatchRequest(
        batch_id="test-batch-uuid-001",
        source="qa_test_suite",
        scraped_at=datetime.now(UTC),
        records=[sample_api_record],
    )


# ---------------------------------------------------------------------------
# Synthetic Batch Generator Fixtures & Factories
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_fare_factory() -> Callable[..., list[IngestionRawFareRecord]]:
    """Factory fixture generating configurable lists of synthetic RawFareRecords.

    Args:
        count: Number of records to generate.
        route: City pair string, e.g. 'DEL-BOM'.
        window: Booking window tag ('T+1', 'T+7', 'T+15', 'T+30').
        base_fare: Nominal base ticket fare in INR.
        airlines: Optional sequence of airline codes to cycle through.

    Returns:
        List of IngestionRawFareRecord objects.
    """

    def _generator(
        count: int = 10,
        route: str = "DEL-BOM",
        window: str = "T+7",
        base_fare: float = 5000.0,
        airlines: Sequence[str] | None = None,
    ) -> list[IngestionRawFareRecord]:
        origin, destination = route.split("-")
        carrier_list = list(airlines or ["6E", "AI", "IX", "QP", "SG"])

        # Window multiplier calibration
        window_multipliers = {
            "T+1": 1.85,
            "T+7": 1.25,
            "T+15": 1.00,
            "T+30": 0.82,
        }
        multiplier = window_multipliers.get(window, 1.0)

        now = datetime.now(UTC).replace(microsecond=0)
        records: list[IngestionRawFareRecord] = []

        for i in range(count):
            airline = carrier_list[i % len(carrier_list)]
            flight_no = f"{airline}-{100 + i}"
            dep_dt = now + timedelta(days=7, hours=i % 12, minutes=(i * 15) % 60)
            arr_dt = dep_dt + timedelta(hours=2, minutes=15)
            fare_val = round(base_fare * multiplier * (1.0 + (i * 0.03)), 2)

            rec = IngestionRawFareRecord(
                airline_code=airline,
                flight_number=flight_no,
                origin=origin,
                destination=destination,
                departure_datetime=dep_dt.isoformat(),
                arrival_datetime=arr_dt.isoformat(),
                booking_datetime=now.isoformat(),
                fare_inr=fare_val,
                cabin_class="economy",
                stops=0,
                source="synthetic_qa",
                booking_window=window,
                flight_date=dep_dt.date().isoformat(),
                duration_minutes=135,
                base_fare=round(fare_val * 0.78, 2),
                taxes_and_fees=round(fare_val * 0.22, 2),
                total_fare=fare_val,
                is_synthetic=True,
                source_platform="synthetic_qa",
            )
            records.append(rec)

        return records

    return _generator


@pytest.fixture
def multi_window_fares_factory() -> (
    Callable[[str, float], dict[str, list[FlightQuote]]]
):
    """Generates FlightQuote collections across all 4 booking horizons (T+1, T+7, T+15, T+30)."""

    def _factory(
        route: str = "DEL-BOM", nominal_fare: float = 5000.0
    ) -> dict[str, list[FlightQuote]]:
        origin, destination = route.split("-")
        carriers = ["6E", "AI", "IX", "QP", "SG"]
        window_factors = {
            "T+1": 1.80,
            "T+7": 1.25,
            "T+15": 1.00,
            "T+30": 0.85,
        }

        result: dict[str, list[FlightQuote]] = {}
        for win, factor in window_factors.items():
            quotes: list[FlightQuote] = []
            for idx, airline in enumerate(carriers):
                fare_val = round(nominal_fare * factor * (1.0 + (idx * 0.04)), 2)
                quotes.append(
                    FlightQuote(
                        origin=origin,
                        destination=destination,
                        flight_date="2026-10-15",
                        airline_code=airline,
                        flight_number=f"{airline}-{200 + idx}",
                        departure_time=f"{8 + idx:02d}:00",
                        fare=fare_val,
                    )
                )
            result[win] = quotes

        return result

    return _factory
