"""Crawlers and scrapers subpackage for APIx Ingestion."""

from ingestion.crawlers.easemytrip import EaseMyTripScraper
from ingestion.crawlers.synthetic import SyntheticCrawler, SyntheticFlightGenerator

__all__ = ["SyntheticFlightGenerator", "SyntheticCrawler", "EaseMyTripScraper"]
