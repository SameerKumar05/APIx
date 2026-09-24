from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class NationalIndexPoint(BaseModel):
    timestamp: datetime = Field(..., description="Timestamp of the index observation point")
    index_value: float = Field(..., description="Calculated Fisher/Jevons weighted index (Base 100.0)")
    change_24h: float = Field(..., description="Percentage change over the past 24 hours")
    change_7d: float = Field(0.0, description="Percentage change over the past 7 days")
    sample_size: int = Field(..., description="Number of unique flight fare observations in the computation window")
    base_period: str = Field("2026-01-01", description="Baseline benchmark period")


class NationalIndexLatestResponse(BaseModel):
    timestamp: datetime = Field(..., description="Timestamp of the latest computed index")
    index_value: float = Field(..., description="Current National Airfare Price Index value (Base 100)")
    change_24h: float = Field(..., description="24-hour rate of change (percentage)")
    change_7d: float = Field(..., description="7-day rate of change (percentage)")
    sample_size: int = Field(..., description="Count of flight observations included in calculation")
    base_period: str = Field("2026-01-01", description="Baseline reference date")
    confidence_interval_lower: Optional[float] = Field(None, description="95% confidence interval lower bound")
    confidence_interval_upper: Optional[float] = Field(None, description="95% confidence interval upper bound")
    status: str = Field("published", description="Index publication status ('published', 'provisional')")


class NationalIndexHistoryResponse(BaseModel):
    points: List[NationalIndexPoint] = Field(..., description="Historical chronological series of index points")
    total_points: int = Field(..., description="Total points in this response window")


class RouteOverviewItem(BaseModel):
    route_code: str = Field(..., description="Unique city-pair identifier (e.g., DEL-BOM)")
    origin: str = Field(..., description="Origin 3-letter IATA code")
    destination: str = Field(..., description="Destination 3-letter IATA code")
    current_index: float = Field(..., description="Current route-level fare index (Base 100)")
    change_24h: float = Field(..., description="24-hour price trend percentage")
    avg_fare_inr: float = Field(..., description="Average observed economy fare in INR")
    min_fare_inr: float = Field(..., description="Lowest available fare on the route in INR")
    active_flights_tracked: int = Field(..., description="Count of daily tracked scheduled flights")
    volatility_score: float = Field(..., description="Price dispersion volatility coefficient (0.0 to 1.0)")


class RouteListResponse(BaseModel):
    routes: List[RouteOverviewItem] = Field(..., description="List of domestic route summary overviews")
    total_routes: int = Field(..., description="Total tracked routes")


class RouteHistoryResponse(BaseModel):
    route_code: str = Field(..., description="Route code (e.g., DEL-BOM)")
    origin: str = Field(..., description="Origin airport code")
    destination: str = Field(..., description="Destination airport code")
    points: List[NationalIndexPoint] = Field(..., description="Historical time-series points for the route")
