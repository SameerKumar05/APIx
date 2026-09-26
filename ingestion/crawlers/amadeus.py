"""Amadeus Flight Offers Search API Client (Tier 2 Fallback).

Implements the official Amadeus for Developers Flight Offers Search API (v2)
using httpx with OAuth2 Client Credentials authentication, automatic token
refresh, rate limiting, and canonical RawFareRecord normalization.

When live API credentials are not provided or the network is unreachable,
it provides realistic Amadeus schema simulation conforming strictly to
the official Amadeus Flight Offers Search API response contract.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore
    HAS_HTTPX = False

from backend.app.core.cleaning import reported_flight_status, sourced_duration_minutes
from backend.app.core.fare_components import ESTIMATED_BASE_FARE_RATIO
from ingestion.base import BaseScraper, RawFareRecord, ScrapeResult
from ingestion.config import (
    BOOKING_WINDOWS,
    DEFAULT_ROUTES,
    BookingWindow,
    IngestionConfig,
    Route,
)

logger = logging.getLogger("ingestion.crawlers.amadeus")


def parse_iso_duration(duration_str: str) -> int:
    """Parses ISO-8601 duration string (e.g. 'PT2H15M', 'PT1H', 'PT45M') into integer minutes."""
    if not duration_str:
        return 120
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration_str)
    if not match:
        return 120
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    return max(30, hours * 60 + minutes)


class AmadeusFlightClient(BaseScraper):
    """Amadeus Self-Service Flight Offers Search API Client (Tier 2 Fallback).

    Endpoints:
    - OAuth2 Token: POST https://{hostname}/v1/security/oauth2/token
    - Flight Search: GET https://{hostname}/v2/shopping/flight-offers
    """

    def __init__(
        self,
        config: IngestionConfig | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        hostname: str | None = None,
        mock_mode: bool | None = None,
    ) -> None:
        super().__init__(config)
        self.client_id = (
            client_id
            or self.config.amadeus_client_id
            or os.getenv("AMADEUS_CLIENT_ID", "")
        )
        self.client_secret = (
            client_secret
            or self.config.amadeus_client_secret
            or os.getenv("AMADEUS_CLIENT_SECRET", "")
        )
        self.hostname = (
            hostname
            or self.config.amadeus_hostname
            or os.getenv("AMADEUS_HOSTNAME", "test.api.amadeus.com")
        )
        self.mock_mode = (
            mock_mode
            if mock_mode is not None
            else (
                self.config.ingestion_mode in ("mock", "synthetic")
                or not (self.client_id and self.client_secret)
            )
        )

        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @property
    def token_endpoint(self) -> str:
        return f"https://{self.hostname}/v1/security/oauth2/token"

    @property
    def flight_offers_endpoint(self) -> str:
        return f"https://{self.hostname}/v2/shopping/flight-offers"

    def get_access_token(self) -> str | None:
        """Obtains or returns cached OAuth2 Bearer token using client_credentials grant."""
        if self.mock_mode or not (self.client_id and self.client_secret):
            return "mock-amadeus-bearer-token"

        now = time.time()
        if self._token and now < self._token_expires_at - 60.0:
            return self._token

        if not HAS_HTTPX:
            logger.warning(
                "httpx not installed; unable to execute live Amadeus OAuth2 request"
            )
            return None

        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                resp = client.post(
                    self.token_endpoint,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    self._token = payload.get("access_token")
                    expires_in = payload.get("expires_in", 1799)
                    self._token_expires_at = time.time() + float(expires_in)
                    logger.info("Successfully refreshed Amadeus OAuth2 access token")
                    return self._token
                else:
                    logger.error(
                        "Amadeus OAuth2 token request failed: %s %s",
                        resp.status_code,
                        resp.text,
                    )
                    return None
        except Exception as exc:
            logger.error("Error communicating with Amadeus OAuth2 service: %s", exc)
            return None

    async def get_access_token_async(
        self, client: httpx.AsyncClient | None = None
    ) -> str | None:
        """Asynchronously obtains or refreshes OAuth2 token."""
        if self.mock_mode or not (self.client_id and self.client_secret):
            return "mock-amadeus-bearer-token"

        now = time.time()
        if self._token and now < self._token_expires_at - 60.0:
            return self._token

        if not HAS_HTTPX:
            return None

        own_client = client is None
        async_client = client or httpx.AsyncClient(timeout=self.config.timeout_seconds)
        try:
            resp = await async_client.post(
                self.token_endpoint,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                payload = resp.json()
                self._token = payload.get("access_token")
                expires_in = payload.get("expires_in", 1799)
                self._token_expires_at = time.time() + float(expires_in)
                return self._token
            else:
                logger.error(
                    "Amadeus OAuth2 token async error: %s %s",
                    resp.status_code,
                    resp.text,
                )
                return None
        except Exception as exc:
            logger.error("Error obtaining Amadeus async token: %s", exc)
            return None
        finally:
            if own_client:
                await async_client.aclose()

    def parse_flight_offers(
        self,
        payload: dict[str, Any],
        origin: str,
        destination: str,
        window_code: str,
        capture_dt: datetime | None = None,
    ) -> list[RawFareRecord]:
        """Normalizes Amadeus v2 Flight Offers Search response into canonical RawFareRecords.

        Provenance follows the same condition that selects the payload: when the
        client is unauthenticated or in mock mode the payload comes from
        _generate_mock_amadeus_payload, so the records are generated and are
        labelled synthetic. Only a response actually returned by the Amadeus API
        is labelled real.
        """
        records: list[RawFareRecord] = []
        payload_is_generated = bool(
            self.mock_mode or not (self.client_id and self.client_secret)
        )
        capture_time = capture_dt or datetime.now(UTC)
        booking_dt_str = capture_time.strftime("%Y-%m-%dT%H:%M:%S")

        offers_data = payload.get("data", [])
        if not isinstance(offers_data, list):
            logger.warning(
                "Amadeus response payload 'data' is not a list: %s", type(offers_data)
            )
            return records

        for offer in offers_data:
            try:
                itineraries = offer.get("itineraries", [])
                if not itineraries:
                    continue

                primary_itinerary = itineraries[0]
                segments = primary_itinerary.get("segments", [])
                if not segments:
                    continue

                first_seg = segments[0]
                last_seg = segments[-1]

                carrier_code = self.normalize_airline_code(
                    first_seg.get("carrierCode")
                    or offer.get("validatingAirlineCodes", ["6E"])[0]
                )
                flight_no = str(first_seg.get("number", "101"))
                if not flight_no.startswith(carrier_code):
                    full_flight_no = f"{carrier_code}-{flight_no}"
                else:
                    full_flight_no = flight_no

                dep_info = first_seg.get("departure", {})
                arr_info = last_seg.get("arrival", {})

                dep_at_raw = dep_info.get("at")
                arr_at_raw = arr_info.get("at")
                if not dep_at_raw or not arr_at_raw:
                    continue

                dep_datetime_str = self.normalize_datetime(dep_at_raw)
                arr_datetime_str = self.normalize_datetime(arr_at_raw)

                # Duration in minutes
                duration_str = primary_itinerary.get("duration")
                if duration_str:
                    duration_minutes: int | None = parse_iso_duration(duration_str)
                else:
                    duration_minutes = sourced_duration_minutes(
                        None,
                        dep_datetime_str,
                        arr_datetime_str,
                    )
                flight_status = reported_flight_status(offer)

                # Number of stops
                num_stops = max(0, len(segments) - 1)

                # Pricing details
                price_data = offer.get("price", {})
                total_raw = (
                    price_data.get("grandTotal") or price_data.get("total") or 5000.0
                )
                fare_inr = self.normalize_fare(total_raw)
                supplied_base = price_data.get("base")
                base_fare_inr = (
                    self.normalize_fare(supplied_base)
                    if supplied_base not in (None, "")
                    else None
                )

                # Cabin class extraction
                cabin_class = "economy"
                traveler_pricings = offer.get("travelerPricings", [])
                if traveler_pricings:
                    fare_details = traveler_pricings[0].get("fareDetailsBySegment", [])
                    if fare_details:
                        cabin_raw = fare_details[0].get("cabin", "ECONOMY")
                        cabin_class = str(cabin_raw).strip().lower()

                # Segment airport codes
                seg_origin = self.normalize_iata(dep_info.get("iataCode") or origin)
                seg_destination = self.normalize_iata(
                    arr_info.get("iataCode") or destination
                )

                record = RawFareRecord(
                    airline_code=carrier_code,
                    flight_number=full_flight_no,
                    origin=seg_origin,
                    destination=seg_destination,
                    departure_datetime=dep_datetime_str,
                    arrival_datetime=arr_datetime_str,
                    booking_datetime=booking_dt_str,
                    fare_inr=fare_inr,
                    cabin_class=cabin_class,
                    stops=num_stops,
                    source="amadeus",
                    booking_window=window_code,
                    flight_date=dep_datetime_str.split("T")[0],
                    duration_minutes=duration_minutes,
                    flight_status=flight_status,
                    base_fare=base_fare_inr,
                    total_fare=fare_inr,
                    is_synthetic=payload_is_generated,
                    source_platform="amadeus",
                )

                is_valid, validation_errors = self.validate_record(record)
                if is_valid:
                    records.append(record)
                else:
                    logger.debug(
                        "Amadeus record validation failed: %s", validation_errors
                    )

            except Exception as item_err:
                logger.debug("Failed parsing Amadeus flight offer: %s", item_err)
                continue

        return records

    def _generate_mock_amadeus_payload(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
    ) -> dict[str, Any]:
        """Generates realistic Amadeus v2 flight offers JSON adhering to the official schema."""
        window_multiplier = {
            "T+1": 1.75,
            "T+7": 1.20,
            "T+15": 1.00,
            "T+30": 0.88,
        }.get(window_code, 1.0)

        # Baseline route pricing
        route_dist = 1150
        for r in DEFAULT_ROUTES:
            if r.origin == origin and r.destination == destination:
                route_dist = r.distance_km
                break
        route_base = (route_dist * 3.50) + 950.0

        # Standard airline schedules for Indian domestic corridors
        schedule_templates = [
            ("6E", 205, 6, 0, 8, 15, 0, 135, 1.00),
            ("6E", 342, 8, 30, 10, 45, 0, 135, 1.05),
            ("AI", 806, 7, 0, 9, 20, 0, 140, 1.15),
            ("AI", 665, 17, 45, 20, 0, 0, 135, 1.20),
            ("UK", 955, 9, 15, 11, 30, 0, 135, 1.18),
            ("UK", 981, 19, 0, 21, 15, 0, 135, 1.22),
            ("SG", 154, 11, 10, 13, 25, 0, 135, 0.95),
            ("QP", 1312, 14, 20, 16, 40, 0, 140, 0.92),
        ]

        flight_offers = []
        for idx, (
            carrier,
            f_num,
            d_h,
            d_m,
            _a_h,
            _a_m,
            stops,
            dur_m,
            carrier_mult,
        ) in enumerate(schedule_templates, start=1):
            dep_dt = datetime(
                target_date.year, target_date.month, target_date.day, d_h, d_m
            )
            arr_dt = dep_dt + timedelta(minutes=dur_m)

            final_fare = round(route_base * window_multiplier * carrier_mult, 2)
            base_fare = round(final_fare * ESTIMATED_BASE_FARE_RATIO, 2)

            dur_hours = dur_m // 60
            dur_mins = dur_m % 60
            dur_str = f"PT{dur_hours}H{dur_mins}M"

            offer_obj = {
                "type": "flight-offer",
                "id": str(idx),
                "source": "GDS",
                "instantTicketingRequired": False,
                "nonHomogeneous": False,
                "oneWay": True,
                "lastTicketingDate": target_date.strftime("%Y-%m-%d"),
                "numberOfBookableSeats": 9,
                "itineraries": [
                    {
                        "duration": dur_str,
                        "segments": [
                            {
                                "departure": {
                                    "iataCode": origin,
                                    "terminal": "3",
                                    "at": dep_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                                },
                                "arrival": {
                                    "iataCode": destination,
                                    "terminal": "2",
                                    "at": arr_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                                },
                                "carrierCode": carrier,
                                "number": str(f_num),
                                "aircraft": {"code": "320"},
                                "operating": {"carrierCode": carrier},
                                "duration": dur_str,
                                "id": f"{idx}-1",
                                "numberOfStops": stops,
                                "blacklistedInEU": False,
                            }
                        ],
                    }
                ],
                "price": {
                    "currency": "INR",
                    "total": f"{final_fare:.2f}",
                    "base": f"{base_fare:.2f}",
                    "grandTotal": f"{final_fare:.2f}",
                    "fees": [
                        {
                            "amount": f"{round(final_fare - base_fare, 2):.2f}",
                            "type": "SUPPLIER",
                        }
                    ],
                },
                "pricingOptions": {
                    "fareType": ["PUBLISHED"],
                    "includedCheckedBagsOnly": True,
                },
                "validatingAirlineCodes": [carrier],
                "travelerPricings": [
                    {
                        "travelerId": "1",
                        "fareOption": "STANDARD",
                        "travelerType": "ADULT",
                        "price": {
                            "currency": "INR",
                            "total": f"{final_fare:.2f}",
                            "base": f"{base_fare:.2f}",
                        },
                        "fareDetailsBySegment": [
                            {
                                "segmentId": f"{idx}-1",
                                "cabin": "ECONOMY",
                                "fareBasis": "EOWIND",
                                "class": "E",
                            }
                        ],
                    }
                ],
            }
            flight_offers.append(offer_obj)

        return {"data": flight_offers, "meta": {"count": len(flight_offers)}}

    def search_flights(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
        max_offers: int = 50,
    ) -> ScrapeResult:
        """Executes flight search via Amadeus v2 API with automatic fallback simulation."""
        start_time = time.time()
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)

        # Mock / Simulation path
        if self.mock_mode:
            mock_payload = self._generate_mock_amadeus_payload(
                origin=norm_orig,
                destination=norm_dest,
                target_date=target_date,
                window_code=window_code,
            )
            records = self.parse_flight_offers(
                payload=mock_payload,
                origin=norm_orig,
                destination=norm_dest,
                window_code=window_code,
            )
            elapsed_ms = (time.time() - start_time) * 1000.0
            return ScrapeResult(
                source="amadeus",
                success=True,
                records=records,
                errors=[],
                duration_ms=round(elapsed_ms, 2),
                metadata={
                    "mode": "mock",
                    "origin": norm_orig,
                    "destination": norm_dest,
                    "date": target_date.isoformat(),
                    "window": window_code,
                    "offers_returned": len(records),
                    "tier": 2,
                },
            )

        # Live API path
        token = self.get_access_token()
        if not token:
            logger.warning("No Amadeus access token available, aborting live API query")
            return ScrapeResult(
                source="amadeus",
                success=False,
                records=[],
                errors=["Failed to obtain Amadeus OAuth2 token"],
                duration_ms=round((time.time() - start_time) * 1000.0, 2),
                metadata={"tier": 2, "status": "auth_failure"},
            )

        if not HAS_HTTPX:
            return ScrapeResult(
                source="amadeus",
                success=False,
                records=[],
                errors=["httpx library not available"],
                duration_ms=0.0,
                metadata={"tier": 2},
            )

        params: dict[str, str | int | float | bool | None] = {
            "originLocationCode": norm_orig,
            "destinationLocationCode": norm_dest,
            "departureDate": target_date.strftime("%Y-%m-%d"),
            "adults": 1,
            "currencyCode": "INR",
            "max": max_offers,
            "travelClass": "ECONOMY",
            "nonStop": "false",
        }

        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                resp = client.get(
                    self.flight_offers_endpoint,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
                elapsed_ms = (time.time() - start_time) * 1000.0

                if resp.status_code == 200:
                    data = resp.json()
                    records = self.parse_flight_offers(
                        payload=data,
                        origin=norm_orig,
                        destination=norm_dest,
                        window_code=window_code,
                    )
                    return ScrapeResult(
                        source="amadeus",
                        success=True,
                        records=records,
                        errors=[],
                        duration_ms=round(elapsed_ms, 2),
                        metadata={
                            "mode": "live",
                            "origin": norm_orig,
                            "destination": norm_dest,
                            "date": target_date.isoformat(),
                            "window": window_code,
                            "offers_returned": len(records),
                            "tier": 2,
                        },
                    )
                else:
                    err_msg = f"Amadeus API returned status {resp.status_code}: {resp.text[:200]}"
                    logger.error(err_msg)
                    return ScrapeResult(
                        source="amadeus",
                        success=False,
                        records=[],
                        errors=[err_msg],
                        duration_ms=round(elapsed_ms, 2),
                        metadata={"tier": 2, "status_code": resp.status_code},
                    )
        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000.0
            logger.error("Exception during Amadeus flight search: %s", exc)
            return ScrapeResult(
                source="amadeus",
                success=False,
                records=[],
                errors=[str(exc)],
                duration_ms=round(elapsed_ms, 2),
                metadata={"tier": 2, "error": str(exc)},
            )

    async def search_flights_async(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
        client: httpx.AsyncClient | None = None,
        max_offers: int = 50,
    ) -> ScrapeResult:
        """Asynchronously executes flight search via Amadeus v2 API."""
        start_time = time.time()
        norm_orig = self.normalize_iata(origin)
        norm_dest = self.normalize_iata(destination)

        if self.mock_mode:
            mock_payload = self._generate_mock_amadeus_payload(
                origin=norm_orig,
                destination=norm_dest,
                target_date=target_date,
                window_code=window_code,
            )
            records = self.parse_flight_offers(
                payload=mock_payload,
                origin=norm_orig,
                destination=norm_dest,
                window_code=window_code,
            )
            elapsed_ms = (time.time() - start_time) * 1000.0
            return ScrapeResult(
                source="amadeus",
                success=True,
                records=records,
                errors=[],
                duration_ms=round(elapsed_ms, 2),
                metadata={"mode": "mock", "tier": 2, "offers_returned": len(records)},
            )

        token = await self.get_access_token_async(client=client)
        if not token:
            return ScrapeResult(
                source="amadeus",
                success=False,
                records=[],
                errors=["Failed to obtain Amadeus OAuth2 token"],
                duration_ms=round((time.time() - start_time) * 1000.0, 2),
                metadata={"tier": 2},
            )

        params: dict[str, str | int | float | bool | None] = {
            "originLocationCode": norm_orig,
            "destinationLocationCode": norm_dest,
            "departureDate": target_date.strftime("%Y-%m-%d"),
            "adults": 1,
            "currencyCode": "INR",
            "max": max_offers,
            "travelClass": "ECONOMY",
            "nonStop": "false",
        }

        own_client = client is None
        async_client = client or httpx.AsyncClient(timeout=self.config.timeout_seconds)
        try:
            resp = await async_client.get(
                self.flight_offers_endpoint,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            elapsed_ms = (time.time() - start_time) * 1000.0
            if resp.status_code == 200:
                data = resp.json()
                records = self.parse_flight_offers(
                    payload=data,
                    origin=norm_orig,
                    destination=norm_dest,
                    window_code=window_code,
                )
                return ScrapeResult(
                    source="amadeus",
                    success=True,
                    records=records,
                    errors=[],
                    duration_ms=round(elapsed_ms, 2),
                    metadata={
                        "mode": "live",
                        "tier": 2,
                        "offers_returned": len(records),
                    },
                )
            else:
                err_msg = f"Amadeus API returned {resp.status_code}"
                return ScrapeResult(
                    source="amadeus",
                    success=False,
                    records=[],
                    errors=[err_msg],
                    duration_ms=round(elapsed_ms, 2),
                    metadata={"tier": 2},
                )
        except Exception as exc:
            return ScrapeResult(
                source="amadeus",
                success=False,
                records=[],
                errors=[str(exc)],
                duration_ms=round((time.time() - start_time) * 1000.0, 2),
                metadata={"tier": 2},
            )
        finally:
            if own_client:
                await async_client.aclose()

    def scrape_route(
        self,
        origin: str,
        destination: str,
        target_date: date,
        window_code: str,
    ) -> ScrapeResult:
        """BaseScraper route entrypoint delegating to search_flights."""
        return self.search_flights(origin, destination, target_date, window_code)

    def scrape_all(
        self,
        routes: list[Route] | None = None,
        windows: list[BookingWindow] | None = None,
    ) -> list[ScrapeResult]:
        """Scrapes all 40 slots using Amadeus Flight Offers Search."""
        target_routes = routes or DEFAULT_ROUTES
        target_windows = windows or BOOKING_WINDOWS
        today = date.today()

        results: list[ScrapeResult] = []
        for route in target_routes:
            for window in target_windows:
                flight_date = today + timedelta(days=window.days_advance)
                result = self.scrape_route(
                    route.origin, route.destination, flight_date, window.code
                )
                results.append(result)
        return results
