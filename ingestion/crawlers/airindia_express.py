"""Air India Express (IX) portal scraper.

robots.txt Disallow: /flight-availability for User-agent: *. The search URL
uses that path, so robots_gate declines it.
"""

from __future__ import annotations

from datetime import date

from ingestion.crawlers.portal import PortalScraper


class AirIndiaExpressScraper(PortalScraper):
    """Direct Air India Express search. The published search path is disallowed."""

    BASE_URL = "https://www.airindiaexpress.com"
    SOURCE_NAME = "airindiaexpress"
    SOURCE_TYPE = "airline_direct"
    AIRLINE_CODE = "IX"
    API_URL_PATTERNS = (
        r"/flight-availability",
        r"/api/.*flight",
        r"/availability",
    )

    def build_search_url(
        self,
        origin: str,
        destination: str,
        flight_date: date,
        adults: int = 1,
    ) -> str:
        """The booking path robots.txt names: /flight-availability."""
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        date_str = flight_date.strftime("%Y-%m-%d")
        return (
            f"{self.BASE_URL}/flight-availability"
            f"?origin={norm_orig}&destination={norm_dest}"
            f"&departureDate={date_str}&adult={adults}&child=0&infant=0&tripType=oneWay"
        )
