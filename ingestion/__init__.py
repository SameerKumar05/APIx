"""APIx Ingestion Package.

Real-time Airfare Price Index data ingestion engine for domestic Indian routes.
"""

from ingestion.base import BaseScraper, RawFareRecord, ScrapeResult
from ingestion.client import IngestionClient
from ingestion.config import (
    AIRLINE_MAP,
    AIRLINES,
    BOOKING_WINDOW_MAP,
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    DEFAULT_USER_AGENTS,
    VALID_AIRLINE_CODES,
    VALID_IATA_CODES,
    Airline,
    BookingWindow,
    IngestionConfig,
    Route,
)
from ingestion.crawlers.easemytrip import EaseMyTripScraper
from ingestion.crawlers.synthetic import SyntheticFlightGenerator
from ingestion.loaders import (
    DgcaTrafficLoader,
    DgcaTrafficRecord,
    MospiCpiLoader,
    MospiCpiRecord,
)
__all__ = [
    # Configuration & domain entities
    "Route",
    "BookingWindow",
    "Airline",
    "IngestionConfig",
    "DEFAULT_ROUTES",
    "BOOKING_WINDOWS",
    "BOOKING_WINDOW_MAP",
    "AIRLINES",
    "AIRLINE_MAP",
    "VALID_IATA_CODES",
    "VALID_AIRLINE_CODES",
    "DEFAULT_USER_AGENTS",
    # Base abstractions & schemas
    "BaseScraper",
    "RawFareRecord",
    "ScrapeResult",
    # Crawlers & generators
    "SyntheticFlightGenerator",
    "EaseMyTripScraper",
    # Client
    "IngestionClient",
    # Benchmark loaders
    "MospiCpiLoader",
    "MospiCpiRecord",
    "DgcaTrafficLoader",
    "DgcaTrafficRecord",
]
