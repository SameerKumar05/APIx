"""Air India (AI) portal scraper."""

from __future__ import annotations

from datetime import date

from ingestion.crawlers.portal import PortalScraper


class AirIndiaScraper(PortalScraper):
    """Direct Air India booking search. robots.txt on this host currently times out."""

    BASE_URL = "https://www.airindia.com"
    SOURCE_NAME = "airindia"
    SOURCE_TYPE = "airline_direct"
    AIRLINE_CODE = "AI"
    API_URL_PATTERNS = (
        r"/api/.*flight",
        r"/availability",
        r"search-flights",
        r"/shopping/flight",
    )

    def build_search_url(
        self,
        origin: str,
        destination: str,
        flight_date: date,
        adults: int = 1,
    ) -> str:
        """Public Air India book-flights URL with the route in the query."""
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        date_str = flight_date.strftime("%Y-%m-%d")
        return (
            f"{self.BASE_URL}/in/en/book-flights"
            f"?origin={norm_orig}&destination={norm_dest}"
            f"&departureDate={date_str}&adults={adults}&cabin=ECONOMY&tripType=O"
        )
