"""Goibibo OTA scraper.

The public search URL matches Goibibo's flight/search itinerary form.
robots.txt on this host currently times out, so the gate fails closed.
"""

from __future__ import annotations

from datetime import date

from ingestion.crawlers.portal import PortalScraper


class GoibiboScraper(PortalScraper):
    """Goibibo flight search. robots.txt on this host currently times out."""

    BASE_URL = "https://www.goibibo.com"
    SOURCE_NAME = "goibibo"
    SOURCE_TYPE = "ota"
    API_URL_PATTERNS = (
        r"/flight/search",
        r"/api/.*flight",
        r"air-search",
    )

    def build_search_url(
        self,
        origin: str,
        destination: str,
        flight_date: date,
        adults: int = 1,
    ) -> str:
        """Goibibo flight/search itinerary URL."""
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        date_str = flight_date.strftime("%d/%m/%Y")
        return (
            f"{self.BASE_URL}/flight/search?itinerary={norm_orig}-{norm_dest}-{date_str}"
            f"&tripType=O&paxType=A-{adults}_C-0_I-0&cabinClass=E&intl=false"
        )
