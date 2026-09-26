"""Crawlers and scrapers subpackage for APIx Ingestion."""

from ingestion.crawlers.airindia import AirIndiaScraper
from ingestion.crawlers.airindia_express import AirIndiaExpressScraper
from ingestion.crawlers.akasa import AkasaScraper
from ingestion.crawlers.amadeus import AmadeusFlightClient
from ingestion.crawlers.cleartrip import CleartripScraper
from ingestion.crawlers.easemytrip import EaseMyTripScraper
from ingestion.crawlers.goibibo import GoibiboScraper
from ingestion.crawlers.indigo import IndiGoScraper
from ingestion.crawlers.ixigo import IxigoScraper
from ingestion.crawlers.makemytrip import MakeMyTripScraper
from ingestion.crawlers.spicejet import SpiceJetScraper
from ingestion.crawlers.synthetic import SyntheticCrawler, SyntheticFlightGenerator
from ingestion.crawlers.yatra import YatraScraper

__all__ = [
    "SyntheticFlightGenerator",
    "SyntheticCrawler",
    "EaseMyTripScraper",
    "MakeMyTripScraper",
    "SpiceJetScraper",
    "AmadeusFlightClient",
    "IndiGoScraper",
    "AirIndiaScraper",
    "AirIndiaExpressScraper",
    "AkasaScraper",
    "YatraScraper",
    "CleartripScraper",
    "IxigoScraper",
    "GoibiboScraper",
]
