"""Crawlers and scrapers subpackage for APIx Ingestion."""

from ingestion.crawlers.amadeus import AmadeusFlightClient
from ingestion.crawlers.easemytrip import EaseMyTripScraper
from ingestion.crawlers.makemytrip import MakeMyTripScraper
from ingestion.crawlers.spicejet import SpiceJetScraper
from ingestion.crawlers.synthetic import SyntheticCrawler, SyntheticFlightGenerator

__all__ = [
    "SyntheticFlightGenerator",
    "SyntheticCrawler",
    "EaseMyTripScraper",
    "MakeMyTripScraper",
    "SpiceJetScraper",
    "AmadeusFlightClient",
]
