"""Cleartrip OTA scraper.

robots.txt Disallow: /flights/search* for User-agent: *. The search URL uses
that path, so robots_gate declines it.
"""

from __future__ import annotations

from datetime import date

from ingestion.crawlers.portal import PortalScraper


class CleartripScraper(PortalScraper):
    """Cleartrip flight search. The published search path is disallowed."""

    BASE_URL = "https://www.cleartrip.com"
    SOURCE_NAME = "cleartrip"
    SOURCE_TYPE = "ota"
    API_URL_PATTERNS = (
        r"/flights/search",
        r"/api/.*flight",
        r"airjson",
    )

    def build_search_url(
        self,
        origin: str,
        destination: str,
        flight_date: date,
        adults: int = 1,
    ) -> str:
        """Cleartrip search path named in robots.txt."""
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        date_str = flight_date.strftime("%d/%m/%Y")
        return (
            f"{self.BASE_URL}/flights/search?from={norm_orig}&to={norm_dest}"
            f"&depart_date={date_str}&adults={adults}&childs=0&infants=0"
            f"&class=Economy&intl=n"
        )
