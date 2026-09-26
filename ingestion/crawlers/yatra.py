"""Yatra OTA scraper. Search host is flight.yatra.com."""

from __future__ import annotations

from datetime import date

from ingestion.crawlers.portal import PortalScraper


class YatraScraper(PortalScraper):
    """Yatra domestic search UI. robots.txt on this host currently times out."""

    BASE_URL = "https://flight.yatra.com"
    SOURCE_NAME = "yatra"
    SOURCE_TYPE = "ota"
    API_URL_PATTERNS = (
        r"air-search",
        r"/air-service/",
        r"/api/.*flight",
        r"flightsapi",
    )

    def build_search_url(
        self,
        origin: str,
        destination: str,
        flight_date: date,
        adults: int = 1,
    ) -> str:
        """Published Yatra dom2 trigger URL."""
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)
        date_str = flight_date.strftime("%d/%m/%Y")
        return (
            f"{self.BASE_URL}/air-search-ui/dom2/trigger?type=O&viewName=normal"
            f"&flexi=0&noOfSegments=1&origin={norm_orig}&originCountry=IN"
            f"&destination={norm_dest}&destinationCountry=IN"
            f"&flight_depart_date={date_str}&ADT={adults}&CHD=0&INF=0&class=Economy&hb=0"
        )
