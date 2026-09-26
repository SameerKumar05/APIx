from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class LeadTimeCurvePoint(BaseModel):
    days_before_departure: int = Field(..., description="Days remaining until flight departure (D-90 to D-0)")
    avg_fare_inr: float = Field(..., description="Average fare observed at this advance purchase horizon")
    median_fare_inr: float = Field(..., description="Median fare observed")
    p10_fare_inr: float = Field(..., description="10th percentile fare (budget/promotional tier)")
    p90_fare_inr: float = Field(..., description="90th percentile fare (peak/last-minute tier)")
    elasticity_factor: Optional[float] = Field(
        None,
        description="Median at this window divided by the longest observed window's median. Null when that baseline is zero.",
    )


class LeadTimeCurveResponse(BaseModel):
    route_code: Optional[str] = Field(None, description="Route code analyzed, or 'NATIONAL' for nationwide aggregate")
    curve_points: List[LeadTimeCurvePoint] = Field(..., description="Advance booking window fare curve points")
    generated_at: datetime = Field(..., description="Timestamp of analytical curve computation")
    data_available: bool = Field(
        False,
        description="False when no raw fare observations exist for the requested route. An empty curve is missing data, not a flat price.",
    )


class HeatmapCell(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6, description="Day of week (0=Monday, 6=Sunday)")
    hour_of_day: int = Field(..., ge=0, le=23, description="Hour of departure (0-23 in IST)")
    fare_index: Optional[float] = Field(
        None,
        description="Cell average divided by the observed overall average, times 100. Null when the overall average is zero.",
    )
    avg_fare_inr: float = Field(..., description="Average economy fare in INR for this temporal slot")


class HeatmapMatrixResponse(BaseModel):
    route_code: Optional[str] = Field("NATIONAL", description="Route identifier or 'NATIONAL'")
    metric: str = Field("avg_fare", description="Metric represented in matrix ('avg_fare', 'fare_index')")
    matrix: List[HeatmapCell] = Field(..., description="Observed day-of-week and hour cells. Missing slots are omitted.")
    min_val: Optional[float] = Field(None, description="Minimum observed value of the selected metric. Null when the matrix is empty.")
    max_val: Optional[float] = Field(None, description="Maximum observed value of the selected metric. Null when the matrix is empty.")
    data_available: bool = Field(
        False,
        description="False when no departure-timed fare observations exist. An empty matrix is missing data, not a zero fare.",
    )


class AnomalyAlertItem(BaseModel):
    id: str = Field(..., description="Unique anomaly detection event identifier")
    route_code: str = Field(..., description="Route where anomaly was detected (e.g. DEL-BOM)")
    airline_code: str = Field(..., description="Operating airline code (e.g. 6E, AI)")
    flight_number: Optional[str] = Field(None, description="Specific flight number, if isolated")
    detected_at: datetime = Field(..., description="Timestamp when the statistical anomaly was flagged")
    anomaly_type: str = Field(..., description="Type: 'SURGE', 'PRICE_CRASH', 'DGCA_CAP_EXCEEDED', 'FLASH_SALE'")
    severity: str = Field(..., description="Severity level: 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'")
    observed_fare_inr: float = Field(..., description="Actual recorded ticket price in INR")
    expected_fare_inr: float = Field(..., description="Expected baseline fair price from rolling statistical model")
    deviation_percent: float = Field(..., description="Percentage deviation from expected normal pricing")
    status: str = Field("ACTIVE", description="Alert status: 'ACTIVE', 'INVESTIGATING', 'RESOLVED', 'DISMISSED'")


class AnomalyAlertsResponse(BaseModel):
    alerts: List[AnomalyAlertItem] = Field(..., description="List of detected anomaly alerts")
    total_alerts: int = Field(..., description="Total count of alerts matching filters")


class DGCAValidationItem(BaseModel):
    route_code: str = Field(..., description="Route code with at least one stored dgca_violations row")
    statutory_band_cap_inr: float = Field(
        ...,
        description="Baseline fare recorded on the peak violation row (median_baseline_fare), not a separately published gazette cap",
    )
    observed_max_fare_inr: float = Field(..., description="Maximum fare_inr among stored violation rows for this route")
    violations_count: int = Field(..., description="Count of stored violation rows for this route")
    compliance_status: str = Field(..., description="BREACH_DETECTED when a non-dismissed violation row exists")


class DGCAValidationResponse(BaseModel):
    checked_at: datetime = Field(..., description="Audit run timestamp")
    total_routes_evaluated: int = Field(..., description="Distinct routes with stored violation rows. Zero when the ledger is empty.")
    total_violations: int = Field(..., description="Count of stored violation rows included in this response")
    violations: List[DGCAValidationItem] = Field(..., description="Routes that have stored violation rows")
    data_available: bool = Field(
        False,
        description="False when dgca_violations has no rows. That is not a clean audit.",
    )
    evaluation_status: str = Field(
        "not_evaluated",
        description="'not_evaluated' when the ledger is empty; 'evaluated' when rows were read",
    )
