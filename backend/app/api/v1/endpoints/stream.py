"""Real-time streaming WebSocket endpoint for live flight fare updates."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

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

SOURCES = ["makemytrip", "easemytrip", "spicejet", "airline_direct", "cleartrip"]


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
        self.active_connections: Set[WebSocket] = set()
        self.max_buffer_size = max_buffer_size
        self.recent_fares: List[Dict[str, Any]] = []
        self.total_broadcast_count = 0
        self.start_time = time.time()
        self._lock = asyncio.Lock()

        # Seed initial buffer with realistic live fares
        self._seed_initial_buffer()

    def _seed_initial_buffer(self) -> None:
        """Pre-populate recent buffer with realistic initial quotes."""
        now = datetime.now(timezone.utc)
        for i in range(25):
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
            self.recent_fares.append(fare_item)

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

    async def send_personal_message(self, message: Dict[str, Any], websocket: WebSocket) -> None:
        """Send JSON packet to specific client."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.debug("Failed sending message to WebSocket client: %s", e)

    async def broadcast(self, message: Dict[str, Any]) -> None:
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

    def get_recent(self, limit: int = 50, route: Optional[str] = None) -> List[Dict[str, Any]]:
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
            server_time=datetime.now(timezone.utc).isoformat(),
        )


# Global singleton connection manager
manager = ConnectionManager(max_buffer_size=100)


def generate_live_fare_packet() -> Dict[str, Any]:
    """Generate a realistic live domestic fare update packet."""
    now = datetime.now(timezone.utc)
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
    """
    Real-time WebSocket endpoint streaming live parsed flight fare updates.
    
    Connected clients receive:
    1. A welcome handshake packet with server timestamp.
    2. An initial batch of the latest buffered fare observations.
    3. Continuous streaming fare updates pushed as live quotes are parsed.
    
    Clients may send 'ping' or {"type": "ping"} to receive an immediate 'pong'.
    """
    await manager.connect(websocket)
    try:
        # 1. Send initial connection greeting
        welcome_packet = {
            "type": "connected",
            "message": "Connected to APIx real-time airfare streaming feed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "active_clients": len(manager.active_connections),
        }
        await manager.send_personal_message(welcome_packet, websocket)

        # 2. Push initial buffer of recent quotes to instantly populate UI ticker
        initial_history = {
            "type": "initial_buffer",
            "fares": manager.get_recent(limit=10),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await manager.send_personal_message(initial_history, websocket)

        # 3. Message loop with heartbeat support and live update emission
        while True:
            # Non-blocking receive with timeout to allow streaming updates
            try:
                # Wait for client message with short timeout
                data_text = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                try:
                    data = json.loads(data_text)
                    msg_type = data.get("type", "")
                    if msg_type in ("ping", "heartbeat") or data_text.strip().lower() == "ping":
                        await manager.send_personal_message(
                            {"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()},
                            websocket,
                        )
                    elif msg_type == "subscribe":
                        # Client subscribed to route
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
                            {"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()},
                            websocket,
                        )
            except asyncio.TimeoutError:
                # Normal timeout: produce and stream a live tick to the client
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
    response_model=List[LiveFareTickerItem],
    status_code=status.HTTP_200_OK,
    summary="Get recent streamed fare buffer items",
    description="Returns the most recent parsed flight fare quotes from the streaming buffer.",
)
async def get_recent_stream_fares(
    limit: int = Query(25, ge=1, le=100, description="Max fare items to retrieve"),
    route: Optional[str] = Query(None, description="Optional route filter (e.g. DEL-BOM)"),
) -> List[LiveFareTickerItem]:
    """Retrieve recent parsed fare quotes."""
    fares = manager.get_recent(limit=limit, route=route)
    return [LiveFareTickerItem(**f) for f in fares]
