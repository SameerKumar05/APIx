from datetime import datetime

from pydantic import BaseModel, Field


class NationalIndexPoint(BaseModel):
    timestamp: datetime = Field(
        ..., description="Timestamp of the index observation point"
    )
    index_value: float = Field(
        ..., description="Calculated Fisher/Jevons weighted index (Base 100.0)"
    )
    change_24h: float | None = Field(
        None,
        description="Percentage change versus the previous observation. Null when no prior point exists.",
    )
    change_7d: float | None = Field(
        None,
        description="Percentage change versus the observation 7 days earlier. Null when that observation is absent.",
    )
    sample_size: int = Field(
        ...,
        description="Number of unique flight fare observations in the computation window",
    )
    base_period: str = Field("2026-01-01", description="Baseline benchmark period")


class NationalIndexLatestResponse(BaseModel):
    timestamp: datetime = Field(
        ..., description="Timestamp of the latest computed index"
    )
    index_value: float = Field(
        ..., description="Current National Airfare Price Index value (Base 100)"
    )
    change_24h: float = Field(
        ..., description="Stored day-over-day inflation rate (percentage)"
    )
    change_7d: float | None = Field(
        None,
        description="Percent change versus the same series 7 days earlier. Null when that observation is absent.",
    )
    sample_size: int = Field(
        ..., description="Count of flight observations included in calculation"
    )
    base_period: str = Field("2026-01-01", description="Baseline reference date")
    confidence_interval_lower: float | None = Field(
        None, description="95% confidence interval lower bound"
    )
    confidence_interval_upper: float | None = Field(
        None, description="95% confidence interval upper bound"
    )
    status: str = Field(
        "published", description="Index publication status ('published', 'provisional')"
    )
    mospi_cpi: float | None = Field(
        None, description="Latest MoSPI transport CPI benchmark, when a series exists"
    )
    mospi_cpi_divergence: float | None = Field(
        None, description="Airfare index minus the MoSPI transport benchmark"
    )
    mospi_source: str | None = Field(
        None, description="Provenance of the MoSPI benchmark values"
    )
    weighted_median_fare_inr: float | None = Field(
        None, description="DGCA-weighted median fare across corridors"
    )
    t1_index: float | None = Field(
        None, description="Advance-horizon index at T+1, on the national index scale"
    )
    t30_index: float | None = Field(
        None, description="Advance-horizon index at T+30, on the national index scale"
    )


class NationalIndexHistoryResponse(BaseModel):
    points: list[NationalIndexPoint] = Field(
        ..., description="Historical chronological series of index points"
    )
    total_points: int = Field(..., description="Total points in this response window")
    frequency: str = Field(
        "daily", description="Aggregation frequency of the returned series"
    )
    data_available: bool = Field(
        ...,
        description=(
            "False when no index has been computed for the requested window. Callers must "
            "treat an empty series as missing data, never as a flat price trend."
        ),
    )


class RouteOverviewItem(BaseModel):
    route_code: str = Field(
        ..., description="Unique city-pair identifier (e.g., DEL-BOM)"
    )
    origin: str = Field(..., description="Origin 3-letter IATA code")
    destination: str = Field(..., description="Destination 3-letter IATA code")
    current_index: float = Field(
        ..., description="Current route-level fare index (Base 100)"
    )
    change_24h: float | None = Field(
        None,
        description="Percent change versus the previous route index. Null when no prior observation exists.",
    )
    avg_fare_inr: float = Field(..., description="Average observed economy fare in INR")
    min_fare_inr: float = Field(
        ..., description="Lowest available fare on the route in INR"
    )
    active_flights_tracked: int = Field(
        ..., description="Count of daily tracked scheduled flights"
    )
    volatility_score: float | None = Field(
        None,
        description="std_dev divided by mean_fare. Null when mean_fare is zero.",
    )


class RouteListResponse(BaseModel):
    routes: list[RouteOverviewItem] = Field(
        ...,
        description="Routes that have a stored daily index. Routes with no observation are omitted.",
    )
    total_routes: int = Field(
        ..., description="Count of routes included in this response"
    )
    data_available: bool = Field(
        False,
        description="False when no route has a stored daily index. An empty list is missing data, not a zero-fare network.",
    )


class RouteHistoryResponse(BaseModel):
    route_code: str = Field(..., description="Route code (e.g., DEL-BOM)")
    origin: str = Field(..., description="Origin airport code")
    destination: str = Field(..., description="Destination airport code")
    points: list[NationalIndexPoint] = Field(
        ..., description="Historical time-series points for the route"
    )
    data_available: bool = Field(
        False,
        description="False when this route has no stored daily index. An empty series is missing data, not a flat trend.",
    )
    frequency: str = Field(
        "daily",
        description="Aggregation frequency of the returned series (daily, weekly, monthly)",
    )
