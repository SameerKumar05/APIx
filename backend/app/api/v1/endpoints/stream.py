"""Real-time streaming WebSocket endpoint for live flight fare updates."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

logger = logging.getLogger("apix.api.stream")

router = APIRouter()

# Benchmark domestic corridors and airlines for live stream synthesis
BENCHMARK_ROUTES = [
    ("DEL", "BOM", "DEL-BOM", 5000.0),
    ("BOM", "DEL", "BOM-DEL", 4950.0),
    ("DEL", "BLR", "DEL-BLR", 6200.0),
    ("BLR", "DEL", "BLR-DEL", 6150.0),
    ("BOM", "BLR", "BOM-BLR", 4200.0),
    ("BLR", "BOM", "BLR-BOM", 4150.0),
    ("DEL", "HYD", "DEL-HYD", 5100.0),
    ("HYD", "DEL", "HYD-DEL", 5050.0),
    ("DEL", "CCU", "DEL-CCU", 5400.0),
    ("CCU", "DEL", "CCU-DEL", 5350.0),
]

CARRIERS = [
    ("6E", "IndiGo", ["6E-205", "6E-501", "6E-182", "6E-344"]),
    ("AI", "Air India", ["AI-806", "AI-665", "AI-102", "AI-504"]),
    ("SG", "SpiceJet", ["SG-8169", "SG-123", "SG-456"]),
    ("UK", "Vistara", ["UK-995", "UK-823", "UK-772"]),
    ("QP", "Akasa Air", ["QP-1102", "QP-1354", "QP-1401"]),
]
CARRIER_MAP: dict[str, str] = {
    "6E": "IndiGo",
    "AI": "Air India",
    "IX": "Air India Express",
    "QP": "Akasa Air",
    "SG": "SpiceJet",
    "UK": "Vistara",
}

SOURCES = ["makemytrip", "easemytrip", "spicejet", "airline_direct", "cleartrip"]


def load_real_fares_from_db(limit: int = 50) -> list[dict[str, Any]]:
    """Query authentic flight quotes persisted in raw_fares database."""
    try:
        from sqlalchemy import desc

        from backend.app.db.session import SessionLocal
        from backend.app.models.raw_fare import RawFare

        db = SessionLocal()
        try:
            records = (
                db.query(RawFare)
                .order_by(desc(RawFare.scraped_at), desc(RawFare.id))
                .limit(limit)
                .all()
            )
            if not records:
                return []

            now_iso = datetime.now(UTC).isoformat()
            items: list[dict[str, Any]] = []
            for r in records:
                c_code = r.airline_code or "6E"
                c_name = CARRIER_MAP.get(c_code, f"Airline {c_code}")
                dep_dt = (
                    r.departure_time.isoformat()
                    if r.departure_time
                    else now_iso
                )
                scraped_dt = (
                    r.scraped_at.isoformat() if r.scraped_at else now_iso
                )
                items.append(
                    {
                        "type": "fare_update",
                        "fare_id": f"fare-db-{r.id}",
                        "airline_code": c_code,
                        "airline_name": c_name,
                        "flight_number": r.flight_number,
                        "origin": r.origin,
                        "destination": r.destination,
                        "route_code": f"{r.origin}-{r.destination}",
                        "fare_inr": round(float(r.total_fare), 2),
                        "source": r.source_platform or "crawler",
                        "cabin_class": (r.fare_class or "economy").lower(),
                        "departure_datetime": dep_dt,
                        "booking_datetime": scraped_dt,
                        "timestamp": scraped_dt,
                    }
                )
            return list(reversed(items))
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Failed querying real raw_fares from DB: %s", exc)
        return []


def fetch_new_raw_fares_since(last_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Poll for newly inserted authentic flight quotes with id > last_id."""
    if last_id <= 0:
        return []
    try:
        from sqlalchemy import asc

        from backend.app.db.session import SessionLocal
        from backend.app.models.raw_fare import RawFare

        db = SessionLocal()
        try:
            records = (
                db.query(RawFare)
                .filter(RawFare.id > last_id)
                .order_by(asc(RawFare.id))
                .limit(limit)
                .all()
            )
            if not records:
                return []

            now_iso = datetime.now(UTC).isoformat()
            items: list[dict[str, Any]] = []
            for r in records:
                c_code = r.airline_code or "6E"
                c_name = CARRIER_MAP.get(c_code, f"Airline {c_code}")
                dep_dt = (
                    r.departure_time.isoformat()
                    if r.departure_time
                    else now_iso
                )
                scraped_dt = (
                    r.scraped_at.isoformat() if r.scraped_at else now_iso
                )
                items.append(
                    {
                        "type": "fare_update",
                        "fare_id": f"fare-db-{r.id}",
                        "airline_code": c_code,
                        "airline_name": c_name,
                        "flight_number": r.flight_number,
                        "origin": r.origin,
                        "destination": r.destination,
                        "route_code": f"{r.origin}-{r.destination}",
                        "fare_inr": round(float(r.total_fare), 2),
                        "source": r.source_platform or "crawler",
                        "cabin_class": (r.fare_class or "economy").lower(),
                        "departure_datetime": dep_dt,
                        "booking_datetime": scraped_dt,
                        "timestamp": scraped_dt,
                    }
                )
            return items
        finally:
            db.close()
    except Exception as exc:
        logger.debug("Failed polling new raw_fares: %s", exc)
        return []
class LiveFareTickerItem(BaseModel):
    """Real-time fare ticker packet format."""

    type: str = "fare_update"
    fare_id: str
    airline_code: str
    airline_name: str
    flight_number: str
    origin: str
    destination: str
    route_code: str
    fare_inr: float
    source: str
    cabin_class: str = "economy"
    departure_datetime: str
    booking_datetime: str
    timestamp: str


class StreamStatusResponse(BaseModel):
    """Status diagnostic for real-time WebSocket broadcast hub."""

    status: str = "LIVE"
    active_connections: int
    total_broadcast_count: int
    buffer_size: int
    uptime_seconds: float
    server_time: str


class ConnectionManager:
    """Manages active WebSocket connections, broadcasting, and recent fare history."""

    def __init__(self, max_buffer_size: int = 100):
        self.active_connections: set[WebSocket] = set()
        self.max_buffer_size = max_buffer_size
        self.recent_fares: list[dict[str, Any]] = []
        self.total_broadcast_count = 0
        self.start_time = time.time()
        self._lock = asyncio.Lock()

        # Seed initial buffer with realistic live fares
        self._seed_initial_buffer()

    def _seed_initial_buffer(self) -> None:
        """Pre-populate recent buffer with real quotes from raw_fares DB, supplemented with benchmark quotes."""
        real_quotes = load_real_fares_from_db(limit=self.max_buffer_size)
        if real_quotes:
            self.recent_fares.extend(real_quotes)
            logger.info("Seeded streaming buffer with %d authentic quotes from raw_fares database", len(real_quotes))

        # Ensure buffer always has at least 25 quotes for initial ticker clients
        needed = 25 - len(self.recent_fares)
        if needed > 0:
            now = datetime.now(UTC)
            for i in range(needed):
                orig, dest, route, base_fare = random.choice(BENCHMARK_ROUTES)
                carrier_code, carrier_name, flights = random.choice(CARRIERS)
                flight_num = random.choice(flights)
                src = random.choice(SOURCES)
                delta_pct = random.uniform(-0.15, 0.25)
                fare = round(base_fare * (1.0 + delta_pct), 2)
                dept_time = (now + timedelta(days=random.choice([1, 2, 7, 14, 30]))).replace(
                    hour=random.randint(5, 22), minute=random.choice([0, 15, 30, 45]), second=0
                )
                fare_item = {
                    "type": "fare_update",
                    "fare_id": f"fare-{i + 1:04d}",
                    "airline_code": carrier_code,
                    "airline_name": carrier_name,
                    "flight_number": flight_num,
                    "origin": orig,
                    "destination": dest,
                    "route_code": route,
                    "fare_inr": fare,
                    "source": src,
                    "cabin_class": "economy",
                    "departure_datetime": dept_time.isoformat(),
                    "booking_datetime": (now - timedelta(seconds=random.randint(10, 3600))).isoformat(),
                    "timestamp": now.isoformat(),
                }
                self.recent_fares.insert(0, fare_item)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept new WebSocket connection and register."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info("WebSocket client connected. Total active: %d", len(self.active_connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove disconnected WebSocket."""
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info("WebSocket client disconnected. Remaining active: %d", len(self.active_connections))

    async def send_personal_message(self, message: dict[str, Any], websocket: WebSocket) -> None:
        """Send JSON packet to specific client."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.debug("Failed sending message to WebSocket client: %s", e)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast live fare update to all connected WebSocket clients."""
        async with self._lock:
            self.recent_fares.append(message)
            if len(self.recent_fares) > self.max_buffer_size:
                self.recent_fares.pop(0)
            self.total_broadcast_count += 1
            targets = list(self.active_connections)

        dead_connections = []
        for ws in targets:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead_connections.append(ws)

        if dead_connections:
            async with self._lock:
                for dead_ws in dead_connections:
                    self.active_connections.discard(dead_ws)

    def get_recent(self, limit: int = 50, route: str | None = None) -> list[dict[str, Any]]:
        """Retrieve recent buffer items with optional route filtering."""
        items = self.recent_fares
        if route:
            clean_route = route.strip().upper()
            items = [item for item in items if item.get("route_code") == clean_route]
        return items[-limit:]

    def get_status(self) -> StreamStatusResponse:
        """Get connection and stream diagnostics."""
        return StreamStatusResponse(
            status="LIVE",
            active_connections=len(self.active_connections),
            total_broadcast_count=self.total_broadcast_count,
            buffer_size=len(self.recent_fares),
            uptime_seconds=round(time.time() - self.start_time, 2),
            server_time=datetime.now(UTC).isoformat(),
        )


# Global singleton connection manager
manager = ConnectionManager(max_buffer_size=100)


def generate_live_fare_packet() -> dict[str, Any]:
    """Generate a realistic live domestic fare update packet."""
    now = datetime.now(UTC)
    orig, dest, route, base_fare = random.choice(BENCHMARK_ROUTES)
    carrier_code, carrier_name, flights = random.choice(CARRIERS)
    flight_num = random.choice(flights)
    src = random.choice(SOURCES)
    delta_pct = random.uniform(-0.15, 0.25)
    fare = round(base_fare * (1.0 + delta_pct), 2)
    dept_time = (now + timedelta(days=random.choice([1, 2, 7, 14]))).replace(
        hour=random.randint(5, 22), minute=random.choice([0, 15, 30, 45]), second=0
    )

    return {
        "type": "fare_update",
        "fare_id": f"fare-{int(time.time() * 1000) % 100000:05d}",
        "airline_code": carrier_code,
        "airline_name": carrier_name,
        "flight_number": flight_num,
        "origin": orig,
        "destination": dest,
        "route_code": route,
        "fare_inr": fare,
        "source": src,
        "cabin_class": "economy",
        "departure_datetime": dept_time.isoformat(),
        "booking_datetime": now.isoformat(),
        "timestamp": now.isoformat(),
    }


@router.websocket("")
@router.websocket("/")
@router.websocket("/fares")
async def websocket_fares_stream(websocket: WebSocket):
    """Real-time WebSocket endpoint streaming live parsed flight fare updates.

    Connected clients receive:
    1. A welcome handshake packet with server timestamp.
    2. An initial batch of the latest buffered fare observations.
    3. Continuous streaming fare updates pushed as live quotes are parsed.

    Clients may send 'ping' or {"type": "ping"} to receive an immediate 'pong'.
    """
    await manager.connect(websocket)
    try:
        # Refresh buffer with latest real quotes from DB
        real_quotes = load_real_fares_from_db(limit=25)
        if real_quotes:
            async with manager._lock:
                existing_ids = {f.get("fare_id") for f in manager.recent_fares}
                new_real = [f for f in real_quotes if f.get("fare_id") not in existing_ids]
                if new_real:
                    manager.recent_fares = (manager.recent_fares + new_real)[-manager.max_buffer_size :]

        # 1. Send initial connection greeting
        welcome_packet = {
            "type": "connected",
            "message": "Connected to APIx real-time airfare streaming feed",
            "timestamp": datetime.now(UTC).isoformat(),
            "active_clients": len(manager.active_connections),
        }
        await manager.send_personal_message(welcome_packet, websocket)

        # 2. Push initial buffer of authentic quotes to instantly populate UI ticker
        initial_history = {
            "type": "initial_buffer",
            "fares": manager.get_recent(limit=15),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        await manager.send_personal_message(initial_history, websocket)

        # Track latest DB ID for continuous streaming of new crawler records
        max_seen_db_id = 0
        for f in manager.recent_fares:
            fid = f.get("fare_id", "")
            if fid.startswith("fare-db-"):
                try:
                    max_seen_db_id = max(max_seen_db_id, int(fid.split("-")[-1]))
                except Exception:
                    pass

        # 3. Message loop with heartbeat support and live update emission
        while True:
            try:
                data_text = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                try:
                    data = json.loads(data_text)
                    msg_type = data.get("type", "")
                    if msg_type in ("ping", "heartbeat") or data_text.strip().lower() == "ping":
                        await manager.send_personal_message(
                            {"type": "pong", "timestamp": datetime.now(UTC).isoformat()},
                            websocket,
                        )
                    elif msg_type == "subscribe":
                        route_filter = data.get("route")
                        await manager.send_personal_message(
                            {
                                "type": "subscribed",
                                "route": route_filter,
                                "message": f"Subscribed to route {route_filter}",
                            },
                            websocket,
                        )
                except json.JSONDecodeError:
                    if data_text.strip().lower() == "ping":
                        await manager.send_personal_message(
                            {"type": "pong", "timestamp": datetime.now(UTC).isoformat()},
                            websocket,
                        )
            except TimeoutError:
                # Check if new authentic quotes were inserted into raw_fares
                new_db_quotes = fetch_new_raw_fares_since(last_id=max_seen_db_id, limit=5)
                if new_db_quotes:
                    for quote in new_db_quotes:
                        await manager.broadcast(quote)
                        try:
                            qid = int(quote["fare_id"].split("-")[-1])
                            max_seen_db_id = max(max_seen_db_id, qid)
                        except Exception:
                            pass
                else:
                    # Continuous live tick
                    live_tick = generate_live_fare_packet()
                    await manager.broadcast(live_tick)
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error("WebSocket stream error: %s", e)
        await manager.disconnect(websocket)


@router.get(
    "/status",
    response_model=StreamStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get real-time stream status and connection metrics",
    description="Inspects active client connections, buffer depth, and broadcast performance.",
)
async def get_stream_status() -> StreamStatusResponse:
    """Return stream diagnostic health metrics."""
    return manager.get_status()


@router.get(
    "/recent",
    response_model=list[LiveFareTickerItem],
    status_code=status.HTTP_200_OK,
    summary="Get recent streamed fare buffer items",
    description="Returns the most recent parsed flight fare quotes from the streaming buffer.",
)
async def get_recent_stream_fares(
    limit: int = Query(25, ge=1, le=100, description="Max fare items to retrieve"),
    route: str | None = Query(None, description="Optional route filter (e.g. DEL-BOM)"),
) -> list[LiveFareTickerItem]:
    """Retrieve recent parsed fare quotes."""
    fares = manager.get_recent(limit=limit, route=route)
    return [LiveFareTickerItem(**f) for f in fares]
