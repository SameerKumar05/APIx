"""Arbitrage schemas for airline direct vs OTA price spread analysis."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ArbitrageItem(BaseModel):
    """Price arbitrage opportunity between direct airline booking and OTA portals."""

    route_code: str = Field(..., description="Route code (e.g. DEL-BOM)")
    airline_code: str = Field(..., description="Operating airline code (e.g. 6E, AI, SG)")
    flight_number: str = Field(..., description="Flight number identifier (e.g. 6E-205)")
    origin: str = Field(..., description="Origin 3-letter IATA code")
    destination: str = Field(..., description="Destination 3-letter IATA code")
    departure_datetime: str = Field(..., description="Flight scheduled departure timestamp")
    cabin_class: str = Field("economy", description="Cabin class")
    direct_platform: Optional[str] = Field(None, description="Direct airline portal identifier (e.g. indigo_direct)")
    direct_fare: Optional[float] = Field(None, description="Direct carrier price in INR")
    ota_platform: Optional[str] = Field(None, description="OTA portal identifier (e.g. makemytrip, easemytrip)")
    ota_fare: Optional[float] = Field(None, description="OTA platform price in INR")
    buy_venue: str = Field(..., description="Cheapest booking channel for consumer")
    buy_fare: float = Field(..., gt=0, description="Lowest available consumer fare in INR")
    sell_venue: str = Field(..., description="Higher-priced comparison channel")
    sell_fare: float = Field(..., gt=0, description="Alternative higher channel fare in INR")
    spread_inr: float = Field(..., description="Absolute price spread in INR (sell_fare - buy_fare)")
    spread_percentage: float = Field(..., description="Percentage spread relative to direct or buy fare")
    direction: str = Field(..., description="Discrepancy direction: 'OTA_CHEAPER', 'AIRLINE_CHEAPER', 'NEUTRAL'")
    actionable: bool = Field(True, description="True if spread exceeds statutory and transaction friction threshold")
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Detection timestamp")
    net_profit_inr: Optional[float] = Field(None, description="Potential consumer savings margin in INR")


class ArbitrageResponse(BaseModel):
    """Analytical summary of price discrepancies and arbitrage spreads across domestic routes."""

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Report generation timestamp")
    routes_evaluated: int = Field(..., ge=0, description="Count of distinct route corridors evaluated")
    opportunities_count: int = Field(..., ge=0, description="Total arbitrage opportunities identified")
    total_potential_savings_inr: float = Field(0.0, description="Cumulative price spread savings across all opportunities")
    avg_spread_percentage: float = Field(0.0, description="Average percentage price discrepancy")
    items: List[ArbitrageItem] = Field(default_factory=list, description="List of detected arbitrage opportunities")
