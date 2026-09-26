"""IndiGo (6E) portal scraper. Search page: /booking/flight-select.html."""

from __future__ import annotations

from datetime import date

from ingestion.crawlers.portal import PortalScraper


class IndiGoScraper(PortalScraper):
    """Direct IndiGo booking search. robots.txt on this host currently times out."""

    BASE_URL = "https://www.goindigo.in"
    SOURCE_NAME = "indigo"
    SOURCE_TYPE = "airline_direct"
    AIRLINE_CODE = "6E"
    API_URL_PATTERNS = (
        r"/api/.*flight",
        r"/availability",
        r"flight-select",
        r"/v1/.*search",
    )

    def build_search_url(
        self,
        origin: str,
        destination: str,
        flight_date: date,
        adults: int = 1,
    ) -> str:
        """Public IndiGo flight-select URL. Query carries the route and date."""
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        date_str = flight_date.strftime("%Y-%m-%d")
        return (
            f"{self.BASE_URL}/booking/flight-select.html"
            f"?origin={norm_orig}&destination={norm_dest}"
            f"&departureDate={date_str}&adults={adults}&tripType=oneWay"
        )
