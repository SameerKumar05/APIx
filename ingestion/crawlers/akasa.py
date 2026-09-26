"""Akasa Air (QP) portal scraper.

robots.txt publishes no Disallow. The booking widget lives on the homepage
and does not expose a separate results URL, so the search is that page plus
the route query. A response with no fare is reported, not filled in.
"""

from __future__ import annotations

from datetime import date

from ingestion.crawlers.portal import PortalScraper


class AkasaScraper(PortalScraper):
    """Direct Akasa search. robots.txt allows the origin; a fare still has to be read."""

    BASE_URL = "https://www.akasaair.com"
    SOURCE_NAME = "akasa"
    SOURCE_TYPE = "airline_direct"
    AIRLINE_CODE = "QP"
    API_URL_PATTERNS = (
        r"/api/.*flight",
        r"/availability",
        r"/v1/.*search",
        r"flight/search",
    )

    def build_search_url(
        self,
        origin: str,
        destination: str,
        flight_date: date,
        adults: int = 1,
    ) -> str:
        """Homepage booking widget with the route and date in the query."""
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        date_str = flight_date.strftime("%Y-%m-%d")
        return (
            f"{self.BASE_URL}/"
            f"?origin={norm_orig}&destination={norm_dest}"
            f"&departureDate={date_str}&adults={adults}&tripType=oneWay"
        )
