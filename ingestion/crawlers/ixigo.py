"""Ixigo OTA scraper.

robots.txt Disallow: /search/result/ and Disallow: /flights/search. The search
URL uses /search/result/flight, so robots_gate declines it.
"""

from __future__ import annotations

from datetime import date

from ingestion.crawlers.portal import PortalScraper


class IxigoScraper(PortalScraper):
    """Ixigo flight search. The published results path is disallowed."""

    BASE_URL = "https://www.ixigo.com"
    SOURCE_NAME = "ixigo"
    SOURCE_TYPE = "ota"
    API_URL_PATTERNS = (
        r"/search/result/flight",
        r"/flights/search",
        r"/api/.*flight",
    )

    def build_search_url(
        self,
        origin: str,
        destination: str,
        flight_date: date,
        adults: int = 1,
    ) -> str:
        """Ixigo results path named in robots.txt."""
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        date_str = flight_date.strftime("%d%m%Y")
        return (
            f"{self.BASE_URL}/search/result/flight?from={norm_orig}&to={norm_dest}"
            f"&date={date_str}&adults={adults}&children=0&infants=0&class=e"
        )
