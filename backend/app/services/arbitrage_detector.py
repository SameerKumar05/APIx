"""APIx Cross-Platform Arbitrage Detection Service.

Detects price discrepancies between direct airline portals (IndiGo, SpiceJet, Air India)
and Online Travel Agencies (MakeMyTrip, EaseMyTrip, Amadeus) for identical flights.
Calculates directional spread in INR and percentage, tracks buy/sell venues,
and flags actionable arbitrage opportunities with threshold filtering and edge-case safety.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
from backend.app.services.index_engine import (
    FlightQuote,
    _extract_field,
    _normalize_code,
    _normalize_date,
    _normalize_departure_time,
    _normalize_flight_number,
)

logger = logging.getLogger("apix.services.arbitrage_detector")

# Known direct airline booking platforms and abbreviations
DEFAULT_DIRECT_PLATFORMS: Set[str] = {
    "indigo",
    "spicejet",
    "airindia",
    "air_india",
    "akasa",
    "akasa_air",
    "vistara",
    "6e",
    "sg",
    "ai",
    "qp",
    "uk",
    "airline_direct",
    "direct",
    "carrier_direct",
}

# Known Online Travel Agencies (OTAs)
DEFAULT_OTA_PLATFORMS: Set[str] = {
    "makemytrip",
    "mmt",
    "easemytrip",
    "emt",
    "yatra",
    "cleartrip",
    "ixigo",
    "goibibo",
    "amadeus",
    "ota_scraper",
    "ota",
}

# Airline code to canonical direct portal name mapping
AIRLINE_DIRECT_NAMES: Dict[str, str] = {
    "6E": "indigo",
    "SG": "spicejet",
    "AI": "air_india",
    "QP": "akasa",
    "UK": "vistara",
}


@dataclass
class ArbitrageOpportunity:
    """Discovered price discrepancy between direct airline site and OTA portal for an identical flight."""

    flight_key: str
    airline_code: str
    flight_number: str
    origin: str
    destination: str
    departure_datetime: str
    direct_platform: Optional[str]
    direct_fare: Optional[float]
    ota_platform: Optional[str]
    ota_fare: Optional[float]
    buy_venue: str
    buy_fare: float
    sell_venue: str
    sell_fare: float
    spread_inr: float
    spread_pct: float
    direction: str  # "direct_cheaper", "ota_cheaper", "neutral", "invalid"
    is_arbitrage: bool
    is_negative_spread: bool
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cabin_class: str = "economy"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def spread_percentage(self) -> float:
        """Alias for spread_pct."""
        return self.spread_pct

    @property
    def actionable(self) -> bool:
        """Alias for is_arbitrage."""
        return self.is_arbitrage

    @property
    def net_profit_inr(self) -> float:
        """Gross margin between sell and buy venue."""
        return round(self.sell_fare - self.buy_fare, 2)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to serializable dictionary."""
        return {
            "flight_key": self.flight_key,
            "airline_code": self.airline_code,
            "flight_number": self.flight_number,
            "origin": self.origin,
            "destination": self.destination,
            "departure_datetime": self.departure_datetime,
            "cabin_class": self.cabin_class,
            "direct_platform": self.direct_platform,
            "direct_fare": self.direct_fare,
            "ota_platform": self.ota_platform,
            "ota_fare": self.ota_fare,
            "buy_venue": self.buy_venue,
            "buy_fare": self.buy_fare,
            "sell_venue": self.sell_venue,
            "sell_fare": self.sell_fare,
            "spread_inr": self.spread_inr,
            "spread_pct": self.spread_pct,
            "spread_percentage": self.spread_percentage,
            "net_profit_inr": self.net_profit_inr,
            "direction": self.direction,
            "is_arbitrage": self.is_arbitrage,
            "actionable": self.actionable,
            "is_negative_spread": self.is_negative_spread,
            "detected_at": self.detected_at.isoformat() if isinstance(self.detected_at, datetime) else str(self.detected_at),
            "metadata": self.metadata,
        }


def calculate_spread(
    direct_fare: float,
    ota_fare: float,
) -> Tuple[float, float, str, bool]:
    """Calculates spread in INR, spread percentage, direction, and negative spread flag.

    Formula:
        spread_inr = ota_fare - direct_fare
        spread_pct = ((ota_fare - direct_fare) / direct_fare) * 100.0

    Returns:
        Tuple of (spread_inr, spread_pct, direction, is_negative_spread)
        where direction is 'direct_cheaper', 'ota_cheaper', 'neutral', or 'invalid'.
    """
    if direct_fare <= 0 or ota_fare <= 0:
        # Zero-volume or invalid fare edge case
        return 0.0, 0.0, "invalid", False

    spread_inr = round(ota_fare - direct_fare, 2)
    spread_pct = round((spread_inr / direct_fare) * 100.0, 4)

    if spread_inr > 1e-4:
        # OTA is more expensive, direct is cheaper
        return spread_inr, spread_pct, "direct_cheaper", False
    elif spread_inr < -1e-4:
        # OTA is cheaper than direct airline (negative spread relative to direct)
        return spread_inr, spread_pct, "ota_cheaper", True
    else:
        return 0.0, 0.0, "neutral", False


class ArbitrageDetector:
    """Detects price discrepancies between direct airline channels and OTAs for identical flights."""

    def __init__(
        self,
        direct_platforms: Optional[Set[str]] = None,
        ota_platforms: Optional[Set[str]] = None,
        min_spread_pct: float = 0.0,
        min_spread_inr: float = 0.0,
        include_negative: bool = True,
        allow_reverse_arbitrage: bool = True,
    ) -> None:
        """Initialize ArbitrageDetector.

        Args:
            direct_platforms: Set of platform names classified as direct airline sites.
            ota_platforms: Set of platform names classified as OTAs.
            min_spread_pct: Minimum percentage spread threshold to flag as actionable arbitrage.
            min_spread_inr: Minimum absolute INR spread threshold.
            include_negative: Whether to include negative spread instances (OTA cheaper than direct).
            allow_reverse_arbitrage: When True, considers OTA cheaper than direct as actionable arbitrage
                                     with buy_venue=OTA and sell_venue=direct.
        """
        self.direct_platforms = set(direct_platforms) if direct_platforms is not None else set(DEFAULT_DIRECT_PLATFORMS)
        self.ota_platforms = set(ota_platforms) if ota_platforms is not None else set(DEFAULT_OTA_PLATFORMS)
        self.min_spread_pct = float(min_spread_pct)
        self.min_spread_inr = float(min_spread_inr)
        self.include_negative = bool(include_negative)
        self.allow_reverse_arbitrage = bool(allow_reverse_arbitrage)

    def is_direct_platform(self, portal_name: str, airline_code: str = "") -> bool:
        """Determines if a portal name represents a direct airline booking channel."""
        clean_portal = str(portal_name).strip().lower()
        if clean_portal in self.direct_platforms:
            return True
        clean_code = airline_code.strip().upper()
        if clean_code:
            expected_name = AIRLINE_DIRECT_NAMES.get(clean_code, "").lower()
            if expected_name and expected_name in clean_portal:
                return True
            if clean_code.lower() in clean_portal:
                return True
        return False

    def is_ota_platform(self, portal_name: str) -> bool:
        """Determines if a portal name represents an Online Travel Agency (OTA)."""
        clean_portal = str(portal_name).strip().lower()
        if clean_portal in self.ota_platforms:
            return True
        for ota in self.ota_platforms:
            if ota in clean_portal:
                return True
        return False

    def detect_flight_arbitrage(
        self,
        flight_quotes: Sequence[Union[FlightQuote, Mapping[str, Any], Any]],
    ) -> Optional[ArbitrageOpportunity]:
        """Evaluates quotes for a single identical flight across platforms to detect arbitrage.

        Args:
            flight_quotes: List of quotes for the exact same flight.

        Returns:
            ArbitrageOpportunity if direct vs OTA quotes exist, else None.
        """
        if not flight_quotes or len(flight_quotes) < 2:
            return None

        direct_quotes: List[Tuple[str, float, Any]] = []
        ota_quotes: List[Tuple[str, float, Any]] = []

        ref_quote = flight_quotes[0]
        airline_code = _normalize_code(_extract_field(ref_quote, "airline_code"))
        raw_flight_num = _extract_field(ref_quote, "flight_number")
        flight_number = _normalize_flight_number(raw_flight_num, airline_code)
        origin = _normalize_code(_extract_field(ref_quote, "origin"))
        destination = _normalize_code(_extract_field(ref_quote, "destination"))
        flight_date = _normalize_date(_extract_field(ref_quote, "flight_date"))
        departure_time = _normalize_departure_time(_extract_field(ref_quote, "departure_time"))
        cabin_class = str(_extract_field(ref_quote, "cabin_class", "economy")).strip().lower() or "economy"

        dep_dt_raw = _extract_field(ref_quote, "departure_datetime")
        if dep_dt_raw:
            if not flight_date:
                flight_date = _normalize_date(dep_dt_raw)
            if not departure_time:
                departure_time = _normalize_departure_time(dep_dt_raw)
            dep_dt_str = str(dep_dt_raw)
        else:
            dep_dt_str = f"{flight_date}T{departure_time}:00" if flight_date and departure_time else ""

        flight_key = f"{airline_code}:{flight_number}:{origin}:{destination}:{flight_date}:{departure_time}:{cabin_class}"

        for q in flight_quotes:
            portal = str(_extract_field(q, "source_portal", "")).strip().lower()
            if not portal:
                portal = str(_extract_field(q, "source", "unknown")).strip().lower()

            try:
                fare = float(_extract_field(q, "fare", 0.0))
            except (ValueError, TypeError):
                continue

            if fare <= 0.0:
                continue

            if self.is_direct_platform(portal, airline_code):
                direct_quotes.append((portal, fare, q))
            else:
                # Treat any non-direct portal or explicit OTA as OTA platform
                ota_quotes.append((portal, fare, q))

        if not direct_quotes or not ota_quotes:
            return None

        # Best (lowest) direct fare vs Best (lowest) OTA fare
        best_direct_portal, best_direct_fare, _ = min(direct_quotes, key=lambda x: x[1])
        best_ota_portal, best_ota_fare, _ = min(ota_quotes, key=lambda x: x[1])

        # Zero-volume check
        if best_direct_fare <= 0 or best_ota_fare <= 0:
            return None

        spread_inr, spread_pct, direction, is_negative = calculate_spread(
            best_direct_fare, best_ota_fare
        )

        if not self.include_negative and is_negative:
            return None

        # Determine buy and sell venues
        if direction in ("neutral", "invalid"):
            buy_venue = best_direct_portal
            buy_fare = best_direct_fare
            sell_venue = best_ota_portal
            sell_fare = best_ota_fare
            is_arb = False
        elif not is_negative:
            # Direct is cheaper: buy at direct, sell/compare at OTA
            buy_venue = best_direct_portal
            buy_fare = best_direct_fare
            sell_venue = best_ota_portal
            sell_fare = best_ota_fare
            is_arb = (spread_pct >= self.min_spread_pct) and (spread_inr >= self.min_spread_inr)
        else:
            # OTA is cheaper than direct: buy at OTA, sell/compare at direct
            buy_venue = best_ota_portal
            buy_fare = best_ota_fare
            sell_venue = best_direct_portal
            sell_fare = best_direct_fare
            if self.allow_reverse_arbitrage:
                # Spread magnitude exceeds threshold
                abs_pct = abs(spread_pct)
                abs_inr = abs(spread_inr)
                is_arb = (abs_pct >= self.min_spread_pct) and (abs_inr >= self.min_spread_inr)
            else:
                is_arb = False

        return ArbitrageOpportunity(
            flight_key=flight_key,
            airline_code=airline_code,
            flight_number=flight_number,
            origin=origin,
            destination=destination,
            departure_datetime=dep_dt_str,
            cabin_class=cabin_class,
            direct_platform=best_direct_portal,
            direct_fare=best_direct_fare,
            ota_platform=best_ota_portal,
            ota_fare=best_ota_fare,
            buy_venue=buy_venue,
            buy_fare=buy_fare,
            sell_venue=sell_venue,
            sell_fare=sell_fare,
            spread_inr=spread_inr,
            spread_pct=spread_pct,
            direction=direction,
            is_arbitrage=is_arb,
            is_negative_spread=is_negative,
            detected_at=datetime.now(timezone.utc),
            metadata={
                "direct_candidates_count": len(direct_quotes),
                "ota_candidates_count": len(ota_quotes),
            },
        )

    def detect_from_quotes(
        self,
        quotes: Sequence[Union[FlightQuote, Mapping[str, Any], Any]],
        min_spread_pct: Optional[float] = None,
    ) -> List[ArbitrageOpportunity]:
        """Groups quotes by identical flight and detects all arbitrage opportunities.

        Args:
            quotes: Sequence of raw or canonical flight quotes across portals.
            min_spread_pct: Optional override for minimum spread percentage filter.

        Returns:
            List of detected ArbitrageOpportunity objects.
        """
        if not quotes:
            return []

        threshold = min_spread_pct if min_spread_pct is not None else self.min_spread_pct

        # Group by canonical flight key
        groups: Dict[str, List[Any]] = {}
        for q in quotes:
            airline_code = _normalize_code(_extract_field(q, "airline_code"))
            raw_flight_num = _extract_field(q, "flight_number")
            flight_number = _normalize_flight_number(raw_flight_num, airline_code)
            origin = _normalize_code(_extract_field(q, "origin"))
            destination = _normalize_code(_extract_field(q, "destination"))
            flight_date = _normalize_date(_extract_field(q, "flight_date"))
            departure_time = _normalize_departure_time(_extract_field(q, "departure_time"))
            cabin_class = str(_extract_field(q, "cabin_class", "economy")).strip().lower() or "economy"

            dep_dt_raw = _extract_field(q, "departure_datetime")
            if dep_dt_raw:
                if not flight_date:
                    flight_date = _normalize_date(dep_dt_raw)
                if not departure_time:
                    departure_time = _normalize_departure_time(dep_dt_raw)

            key = f"{airline_code}:{flight_number}:{origin}:{destination}:{flight_date}:{departure_time}:{cabin_class}"
            if key not in groups:
                groups[key] = []
            groups[key].append(q)

        opportunities: List[ArbitrageOpportunity] = []
        for _flight_key, flight_quotes in groups.items():
            if len(flight_quotes) >= 2:
                opp = self.detect_flight_arbitrage(flight_quotes)
                if opp is not None:
                    # Filter by requested threshold if needed
                    if threshold > 0:
                        eval_pct = abs(opp.spread_pct) if opp.is_negative_spread and self.allow_reverse_arbitrage else opp.spread_pct
                        if eval_pct >= threshold:
                            opportunities.append(opp)
                    else:
                        opportunities.append(opp)

        # Sort opportunities by absolute spread percentage descending
        opportunities.sort(key=lambda o: abs(o.spread_pct), reverse=True)
        return opportunities


def get_current_arbitrage_opportunities(
    db: Session,
    min_spread_pct: float = 0.0,
    limit: int = 100,
    target_date: Optional[date] = None,
) -> List[ArbitrageOpportunity]:
    """Retrieves current price arbitrage opportunities directly from database raw fares.

    Used by API endpoints (e.g. GET /api/v1/analytics/arbitrage).

    Args:
        db: SQLAlchemy database session.
        min_spread_pct: Minimum spread threshold filter.
        limit: Maximum number of opportunities to return.
        target_date: Observation date filter (defaults to today UTC).

    Returns:
        List of ArbitrageOpportunity dataclasses.
    """
    from backend.app.models.raw_fare import RawFare

    query_date = target_date or datetime.now(timezone.utc).date()

    # Query raw fare records for the calculation date with defensive column check
    query = db.query(RawFare).filter(RawFare.flight_date == query_date)
    if hasattr(RawFare, "is_active"):
        query = query.filter(getattr(RawFare, "is_active").is_(True))
    records = query.limit(10_000).all()

    if not records:
        # Fallback to recent raw fares regardless of date if target date has no scrapes
        fallback_query = db.query(RawFare)
        if hasattr(RawFare, "is_active"):
            fallback_query = fallback_query.filter(getattr(RawFare, "is_active").is_(True))
        records = (
            fallback_query
            .order_by(RawFare.scraped_at.desc())
            .limit(5_000)
            .all()
        )

    detector = ArbitrageDetector(min_spread_pct=min_spread_pct)
    opportunities = detector.detect_from_quotes(records, min_spread_pct=min_spread_pct)
    return opportunities[:limit]
