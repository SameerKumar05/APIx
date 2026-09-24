"""SQLAlchemy models package for APIx."""

from backend.app.models.airline import Airline
from backend.app.models.anomaly import AnomalyAlert
from backend.app.models.index import NationalDailyIndex, RouteDailyIndex
from backend.app.models.raw_fare import RawFare
from backend.app.models.route import Route
from backend.app.models.scraping import ScrapingRun
from backend.app.models.telemetry import ProxyHealthRecord, ScraperTelemetry

__all__ = [
    "Route",
    "Airline",
    "RawFare",
    "RouteDailyIndex",
    "NationalDailyIndex",
    "AnomalyAlert",
    "ScrapingRun",
    "ScraperTelemetry",
    "ProxyHealthRecord",
]
