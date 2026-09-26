"""Regression for websocket-idle-8014.json.

An idle hold on /api/v1/stream/fares must not present generated fare-* packets
as live quotes when raw_fares is unchanged.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.testclient import WebSocketTestSession

from backend.app.api.v1.endpoints import stream as stream_mod
from backend.app.core.config import settings
from backend.app.db.session import Base
from backend.app.main import app
from backend.app.models.raw_fare import RawFare
from backend.app.schemas.ingestion import RawFareRecord

PERSISTED_FLIGHT = "6E-IDLE-8014"
PERSISTED_FARE_INR = 4242.42
IDLE_TICKS_TO_OBSERVE = 2
INGEST_STREAM_LIMIT = 12
DUPLICATE_FLIGHT = "6E-8801"
INGESTED_QUOTES = (
    (DUPLICATE_FLIGHT, 4101.0),
    ("6E-8802", 4202.0),
    ("6E-8803", 4303.0),
)


def _persist_quote(
    session: Session,
    *,
    flight_number: str,
    total_fare: float,
) -> int:
    row = RawFare(
        batch_id="websocket-idle-8014",
        origin="DEL",
        destination="BOM",
        flight_date=date(2026, 10, 2),
        booking_window="T+7",
        airline_code="6E",
        flight_number=flight_number,
        departure_time=datetime(2026, 10, 2, 8, 0, tzinfo=UTC),
        stops=0,
        fare_class="Economy",
        base_fare=round(total_fare * 0.78, 2),
        taxes_and_fees=round(total_fare * 0.22, 2),
        total_fare=total_fare,
        source_platform="verification",
        scraped_at=datetime(2026, 9, 25, 14, 44, 44, tzinfo=UTC),
        hash_id=f"idle-8014-{uuid.uuid4().hex}",
        is_synthetic=False,
    )
    session.add(row)
    session.commit()
    row_id = row.id
    if not isinstance(row_id, int):
        raise RuntimeError("persisted raw fare did not receive an integer id")
    return row_id


@pytest.fixture
def idle_stream_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Session]:
    """Disposable SQLite bound to the stream poller, isolated from apix.db."""
    engine: Engine = create_engine(
        f"sqlite:///{tmp_path / 'websocket-idle-8014.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    monkeypatch.setattr("backend.app.db.session.SessionLocal", session_factory)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _raw_fare_count(session: Session) -> int:
    counted = session.scalar(select(func.count()).select_from(RawFare))
    return int(counted or 0)


def test_idle_hold_does_not_emit_generated_fares_when_raw_fares_unchanged(
    idle_stream_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """websocket-idle-8014.json: DB count stayed flat while fare-86360-style ticks arrived.

    Given persisted RawFare rows and no further inserts,
    When a client holds /api/v1/stream/fares across idle polls,
    Then connection and persisted initial-buffer quotes still arrive,
    idle packets are an explicit no-update rather than a live fare,
    and raw_fares is not written.
    """
    persisted_id = _persist_quote(
        idle_stream_db,
        flight_number=PERSISTED_FLIGHT,
        total_fare=PERSISTED_FARE_INR,
    )
    count_before = _raw_fare_count(idle_stream_db)
    monkeypatch.setattr(stream_mod, "manager", stream_mod.ConnectionManager())

    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/fares") as websocket:
        connected = websocket.receive_json()
        initial = websocket.receive_json()
        idle_packets = [websocket.receive_json() for _ in range(IDLE_TICKS_TO_OBSERVE)]

    count_after = _raw_fare_count(idle_stream_db)

    assert connected["type"] == "connected"
    assert connected["message"] == "Connected to APIx real-time airfare streaming feed"
    assert initial["type"] == "initial_buffer"
    persisted_quotes = [
        fare
        for fare in initial["fares"]
        if fare.get("fare_id") == f"fare-db-{persisted_id}"
    ]
    assert len(persisted_quotes) == 1
    quote = persisted_quotes[0]
    assert quote["fare_id"] == f"fare-db-{persisted_id}"
    assert quote["flight_number"] == PERSISTED_FLIGHT
    assert quote["fare_inr"] == PERSISTED_FARE_INR
    assert quote["type"] == "fare_update"
    assert quote["origin"] == "DEL"
    assert quote["destination"] == "BOM"
    assert count_after == count_before == 1
    assert idle_packets
    for packet in idle_packets:
        assert packet.get("type") == "no_update", packet
        assert "fare_id" not in packet
        assert "fare_inr" not in packet


def test_idle_poll_emits_a_newly_persisted_raw_fare(
    idle_stream_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row committed during the hold is the only fare the next poll may emit."""
    _persist_quote(
        idle_stream_db,
        flight_number=PERSISTED_FLIGHT,
        total_fare=PERSISTED_FARE_INR,
    )
    monkeypatch.setattr(stream_mod, "manager", stream_mod.ConnectionManager())
    count_before = _raw_fare_count(idle_stream_db)

    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/fares") as websocket:
        assert websocket.receive_json()["type"] == "connected"
        assert websocket.receive_json()["type"] == "initial_buffer"
        new_id = _persist_quote(
            idle_stream_db,
            flight_number="6E-IDLE-8014-NEW",
            total_fare=5151.51,
        )
        observed = [websocket.receive_json() for _ in range(IDLE_TICKS_TO_OBSERVE)]

    live_fares = [packet for packet in observed if packet.get("type") == "fare_update"]
    assert [fare["fare_id"] for fare in live_fares] == [f"fare-db-{new_id}"]
    assert live_fares[0]["flight_number"] == "6E-IDLE-8014-NEW"
    assert live_fares[0]["fare_inr"] == 5151.51
    assert _raw_fare_count(idle_stream_db) == count_before + 1


def test_empty_raw_fares_sends_empty_initial_buffer_and_idle_no_update(
    idle_stream_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty table must not be filled with fabricated fare-* ticker rows.

    Given no raw_fares rows,
    When a client connects and holds across idle polls,
    Then the initial buffer is explicitly empty, idle packets are no_update,
    the buffer is not polluted, and the table stays empty.
    """
    assert _raw_fare_count(idle_stream_db) == 0
    monkeypatch.setattr(stream_mod, "manager", stream_mod.ConnectionManager())

    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/fares") as websocket:
        connected = websocket.receive_json()
        initial = websocket.receive_json()
        idle_packets = [websocket.receive_json() for _ in range(IDLE_TICKS_TO_OBSERVE)]

    assert connected["type"] == "connected"
    assert connected["message"] == "Connected to APIx real-time airfare streaming feed"
    assert "active_clients" in connected
    assert initial["type"] == "initial_buffer"
    assert initial["fares"] == []
    assert "timestamp" in initial
    assert _raw_fare_count(idle_stream_db) == 0
    assert stream_mod.manager.total_broadcast_count == 0
    assert stream_mod.manager.recent_fares == []
    assert idle_packets
    for packet in idle_packets:
        assert packet.get("type") == "no_update", packet
        assert packet.get("message") == "No new persisted raw fare quotes"
        assert "fare_id" not in packet
        assert "fare_inr" not in packet


def test_row_committed_after_connect_on_empty_database_is_emitted(
    idle_stream_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client that connected to an empty table must still see a later insert.

    Given no raw_fares rows at connect time,
    When a row is committed during the hold,
    Then the next poll emits that persisted fare-db-* quote and only that quote.
    """
    assert _raw_fare_count(idle_stream_db) == 0
    monkeypatch.setattr(stream_mod, "manager", stream_mod.ConnectionManager())

    client = TestClient(app)
    with client.websocket_connect("/api/v1/stream/fares") as websocket:
        assert websocket.receive_json()["type"] == "connected"
        initial = websocket.receive_json()
        new_id = _persist_quote(
            idle_stream_db,
            flight_number="6E-EMPTY-AFTER-CONNECT",
            total_fare=3333.33,
        )
        observed = [websocket.receive_json() for _ in range(IDLE_TICKS_TO_OBSERVE)]

    assert initial["type"] == "initial_buffer"
    assert initial["fares"] == []
    live_fares = [packet for packet in observed if packet.get("type") == "fare_update"]
    assert [fare["fare_id"] for fare in live_fares] == [f"fare-db-{new_id}"]
    assert live_fares[0]["flight_number"] == "6E-EMPTY-AFTER-CONNECT"
    assert live_fares[0]["fare_inr"] == 3333.33
    assert live_fares[0]["origin"] == "DEL"
    assert live_fares[0]["destination"] == "BOM"
    assert _raw_fare_count(idle_stream_db) == 1


def _noop_index_pipeline() -> None:
    """Keep the ingest request from running the daily index job during stream checks."""


def _quote_payload(
    flight_number: str, fare_inr: float
) -> dict[str, str | int | float | None]:
    record = RawFareRecord(
        airline_code="6E",
        flight_number=flight_number,
        origin="DEL",
        destination="BOM",
        departure_datetime=datetime(2026, 10, 2, 8, 0, tzinfo=UTC),
        booking_datetime=datetime(2026, 9, 25, 14, 44, 44, tzinfo=UTC),
        fare_inr=fare_inr,
        cabin_class="economy",
        stops=0,
        source="verification",
        booking_window="T+7",
    )
    return record.model_dump(mode="json")


def _post_batch(
    client: TestClient,
    records: list[dict[str, str | int | float | None]],
) -> dict[str, str | int | float | list[str]]:
    response = client.post(
        "/api/v1/ingestion/batch",
        headers={"X-Ingestion-Key": settings.INGESTION_API_KEY},
        json={
            "batch_id": "stream-truthfulness",
            "source": "verification",
            "records": records,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


def _receive_until_idle(
    websocket: WebSocketTestSession,
    *,
    limit: int,
) -> list[dict[str, str | int | float | None]]:
    packets: list[dict[str, str | int | float | None]] = []
    for _ in range(limit):
        packet = websocket.receive_json()
        assert isinstance(packet, dict)
        packets.append(packet)
        if packet.get("type") == "no_update":
            return packets
    raise AssertionError(f"stream did not idle within {limit} packets: {packets}")


def _persisted_fare_ids(session: Session) -> list[str]:
    session.rollback()
    rows = session.scalars(select(RawFare).order_by(RawFare.id)).all()
    return [f"fare-db-{row.id}" for row in rows]


def test_ingested_batch_emits_each_persisted_fare_once(
    idle_stream_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connected client must see each newly inserted fare once, from the database.

    Given an empty raw_fares table and a connected /api/v1/stream/fares client,
    When POST /api/v1/ingestion/batch inserts 3 distinct records,
    Then the client receives exactly 3 fare_update packets, each fare-db-<rowid>,
    and none use the fare-live- prefix.
    """
    assert _raw_fare_count(idle_stream_db) == 0
    monkeypatch.setattr(
        "backend.app.api.v1.endpoints.ingestion.run_daily_index_pipeline",
        _noop_index_pipeline,
    )
    records = [
        _quote_payload(flight_number, fare_inr)
        for flight_number, fare_inr in INGESTED_QUOTES
    ]
    monkeypatch.setattr(stream_mod, "manager", stream_mod.ConnectionManager())

    with (
        TestClient(app) as client,
        client.websocket_connect("/api/v1/stream/fares") as websocket,
    ):
        assert websocket.receive_json()["type"] == "connected"
        initial = websocket.receive_json()
        body = _post_batch(client, records)
        observed = _receive_until_idle(websocket, limit=INGEST_STREAM_LIMIT)

    assert initial["type"] == "initial_buffer"
    assert initial["fares"] == []
    assert body["inserted_count"] == 3
    assert body["duplicate_count"] == 0
    live_fares = [packet for packet in observed if packet.get("type") == "fare_update"]
    assert len(live_fares) == 3
    assert [packet.get("fare_id") for packet in live_fares] == _persisted_fare_ids(
        idle_stream_db
    )
    assert [packet.get("flight_number") for packet in live_fares] == [
        flight_number for flight_number, _fare_inr in INGESTED_QUOTES
    ]
    assert [packet.get("fare_inr") for packet in live_fares] == [
        fare_inr for _flight_number, fare_inr in INGESTED_QUOTES
    ]
    for packet in observed:
        fare_id = packet.get("fare_id")
        assert not (isinstance(fare_id, str) and fare_id.startswith("fare-live-"))
        if packet.get("type") == "fare_update":
            assert isinstance(fare_id, str)
            assert fare_id.startswith("fare-db-")


def test_reposted_duplicate_emits_no_fare_update(
    idle_stream_db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A record that was not inserted must not appear on the live fare stream.

    Given 3 fares already stored and a client connected after that insert,
    When the same record is posted again and the batch reports inserted_count 0,
    Then the client receives no fare_update packet before the next idle tick.
    """
    monkeypatch.setattr(
        "backend.app.api.v1.endpoints.ingestion.run_daily_index_pipeline",
        _noop_index_pipeline,
    )
    records = [
        _quote_payload(flight_number, fare_inr)
        for flight_number, fare_inr in INGESTED_QUOTES
    ]
    duplicate = _quote_payload(DUPLICATE_FLIGHT, 4101.0)

    with TestClient(app) as client:
        seeded = _post_batch(client, records)
        assert seeded["inserted_count"] == 3
        assert seeded["duplicate_count"] == 0
        monkeypatch.setattr(stream_mod, "manager", stream_mod.ConnectionManager())
        with client.websocket_connect("/api/v1/stream/fares") as websocket:
            assert websocket.receive_json()["type"] == "connected"
            initial = websocket.receive_json()
            replay = _post_batch(client, [duplicate])
            observed = _receive_until_idle(websocket, limit=INGEST_STREAM_LIMIT)

    assert initial["type"] == "initial_buffer"
    assert sorted(fare["fare_id"] for fare in initial["fares"]) == _persisted_fare_ids(
        idle_stream_db
    )
    assert replay["inserted_count"] == 0
    assert replay["duplicate_count"] == 1
    live_fares = [packet for packet in observed if packet.get("type") == "fare_update"]
    assert live_fares == []
    for packet in observed:
        fare_id = packet.get("fare_id")
        assert not (isinstance(fare_id, str) and fare_id.startswith("fare-live-"))
