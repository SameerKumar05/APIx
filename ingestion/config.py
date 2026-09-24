"""Ingestion configuration for APIx Airfare Price Index.

Defines route definitions (10 pairs calibrated against DGCA air traffic),
advance booking windows (T+1, T+7, T+15, T+30), airline market codes,
and scraping runtime parameters.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Route:
    """Represents a domestic flight route pair."""

    origin: str
    destination: str
    distance_km: int
    typical_duration_min: int
    dgca_weight: float  # DGCA domestic passenger traffic weight (sum = 1.0)

    @property
    def pair_key(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def reverse_pair_key(self) -> str:
        return f"{self.destination}-{self.origin}"


@dataclass(frozen=True)
class BookingWindow:
    """Advance booking purchase window."""

    code: str  # T+1, T+7, T+15, T+30
    days_advance: int
    description: str
    price_multiplier: float
    multiplier_range: Tuple[float, float]


@dataclass(frozen=True)
class Airline:
    """Domestic airline operating in the Indian market."""
    code: str  # 2-character IATA
    name: str
    market_share: float  # Calibrated DGCA market share
    fleet_type: str  # LCC (Low Cost Carrier) or FSC (Full Service Carrier)
    base_price_factor: float  # Multiplier relative to LCC baseline


# Top 10 domestic routes calibrated to DGCA air passenger traffic statistics
DEFAULT_ROUTES: List[Route] = [
    Route(origin="DEL", destination="BOM", distance_km=1148, typical_duration_min=130, dgca_weight=0.15),
    Route(origin="BOM", destination="DEL", distance_km=1148, typical_duration_min=130, dgca_weight=0.15),
    Route(origin="DEL", destination="BLR", distance_km=1740, typical_duration_min=165, dgca_weight=0.12),
    Route(origin="BLR", destination="DEL", distance_km=1740, typical_duration_min=165, dgca_weight=0.12),
    Route(origin="BOM", destination="BLR", distance_km=842, typical_duration_min=105, dgca_weight=0.10),
    Route(origin="BLR", destination="BOM", distance_km=842, typical_duration_min=105, dgca_weight=0.10),
    Route(origin="DEL", destination="HYD", distance_km=1253, typical_duration_min=135, dgca_weight=0.07),
    Route(origin="HYD", destination="DEL", distance_km=1253, typical_duration_min=135, dgca_weight=0.07),
    Route(origin="DEL", destination="CCU", distance_km=1305, typical_duration_min=135, dgca_weight=0.06),
    Route(origin="CCU", destination="DEL", distance_km=1305, typical_duration_min=135, dgca_weight=0.06),
]

# Set of valid IATA airport codes used in our routes
VALID_IATA_CODES = frozenset({"DEL", "BOM", "BLR", "HYD", "CCU"})

# 4 Standard purchase windows as required by SIH PS 26056
BOOKING_WINDOWS: List[BookingWindow] = [
    BookingWindow(
        code="T+1",
        days_advance=1,
        description="Last-minute / next-day departure (surge pricing)",
        price_multiplier=2.15,
        multiplier_range=(1.80, 2.50),
    ),
    BookingWindow(
        code="T+7",
        days_advance=7,
        description="1-week advance booking (near-term travel)",
        price_multiplier=1.45,
        multiplier_range=(1.30, 1.65),
    ),
    BookingWindow(
        code="T+15",
        days_advance=15,
        description="2-week advance booking (medium-term travel)",
        price_multiplier=1.18,
        multiplier_range=(1.10, 1.30),
    ),
    BookingWindow(
        code="T+30",
        days_advance=30,
        description="1-month advance booking (baseline index fare)",
        price_multiplier=1.00,
        multiplier_range=(0.95, 1.05),
    ),
]

# Mapping of window code -> BookingWindow
BOOKING_WINDOW_MAP: Dict[str, BookingWindow] = {w.code: w for w in BOOKING_WINDOWS}

# Major Indian domestic airlines with DGCA market share calibration
AIRLINES: List[Airline] = [
    Airline(code="6E", name="IndiGo", market_share=0.60, fleet_type="LCC", base_price_factor=1.00),
    Airline(code="AI", name="Air India", market_share=0.15, fleet_type="FSC", base_price_factor=1.18),
    Airline(code="IX", name="Air India Express", market_share=0.10, fleet_type="LCC", base_price_factor=0.98),
    Airline(code="QP", name="Akasa Air", market_share=0.10, fleet_type="LCC", base_price_factor=0.96),
    Airline(code="SG", name="SpiceJet", market_share=0.05, fleet_type="LCC", base_price_factor=0.95),
]

AIRLINE_MAP: Dict[str, Airline] = {a.code: a for a in AIRLINES}
VALID_AIRLINE_CODES = frozenset(AIRLINE_MAP.keys())

# Default User Agents for stealth scraping
DEFAULT_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:129.0) Gecko/20100101 Firefox/129.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


@dataclass
class IngestionConfig:
    """Runtime configuration for scrapers and ingestion clients."""

    api_base_url: str = field(
        default_factory=lambda: os.getenv("INGESTION_ENDPOINT_URL")
        or os.getenv("API_BASE_URL", "http://localhost:8000")
    )
    ingestion_key: str = field(
        default_factory=lambda: os.getenv("INGESTION_API_KEY", "apix-ingestion-secret-key-2026")
    )
    batch_size: int = field(
        default_factory=lambda: int(os.getenv("INGESTION_BATCH_SIZE", "100"))
    )
    timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("INGESTION_TIMEOUT_SECONDS", "30.0"))
    )
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("INGESTION_MAX_RETRIES", "3"))
    )
    retry_backoff_factor: float = field(
        default_factory=lambda: float(os.getenv("INGESTION_BACKOFF_FACTOR", "1.5"))
    )
    rate_limit_delay_seconds: float = field(
        default_factory=lambda: float(os.getenv("RATE_LIMIT_DELAY_SECONDS", "2.0"))
    )
    rate_limit_jitter_seconds: float = field(
        default_factory=lambda: float(os.getenv("RATE_LIMIT_JITTER_SECONDS", "1.0"))
    )
    playwright_headless: bool = field(
        default_factory=lambda: os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
    )
    amadeus_client_id: str = field(
        default_factory=lambda: os.getenv("AMADEUS_CLIENT_ID", "")
    )
    amadeus_client_secret: str = field(
        default_factory=lambda: os.getenv("AMADEUS_CLIENT_SECRET", "")
    )
    amadeus_hostname: str = field(
        default_factory=lambda: os.getenv("AMADEUS_HOSTNAME", "test.api.amadeus.com")
    )
    ingestion_mode: str = field(
        default_factory=lambda: os.getenv("INGESTION_MODE", "synthetic")
    )
    user_agents: List[str] = field(default_factory=lambda: list(DEFAULT_USER_AGENTS))
