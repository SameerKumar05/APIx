from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class LeadTimeCurvePoint(BaseModel):
    days_before_departure: int = Field(..., description="Days remaining until flight departure (D-90 to D-0)")
    avg_fare_inr: float = Field(..., description="Average fare observed at this advance purchase horizon")
    median_fare_inr: float = Field(..., description="Median fare observed")
    p10_fare_inr: float = Field(..., description="10th percentile fare (budget/promotional tier)")
    p90_fare_inr: float = Field(..., description="90th percentile fare (peak/last-minute tier)")
    elasticity_factor: float = Field(..., description="Price sensitivity / elasticity multiplier relative to baseline")


class LeadTimeCurveResponse(BaseModel):
    route_code: Optional[str] = Field(None, description="Route code analyzed, or 'NATIONAL' for nationwide aggregate")
    curve_points: List[LeadTimeCurvePoint] = Field(..., description="Advance booking window fare curve points")
    generated_at: datetime = Field(..., description="Timestamp of analytical curve computation")


class HeatmapCell(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6, description="Day of week (0=Monday, 6=Sunday)")
    hour_of_day: int = Field(..., ge=0, le=23, description="Hour of departure (0-23 in IST)")
    fare_index: float = Field(..., description="Normalized relative price index for this temporal slot")
    avg_fare_inr: float = Field(..., description="Average economy fare in INR for this temporal slot")


class HeatmapMatrixResponse(BaseModel):
    route_code: Optional[str] = Field("NATIONAL", description="Route identifier or 'NATIONAL'")
    metric: str = Field("avg_fare", description="Metric represented in matrix ('avg_fare', 'index_ratio')")
    matrix: List[HeatmapCell] = Field(..., description="Full 7x24 grid cells of temporal demand/pricing")
    min_val: float = Field(..., description="Minimum value in the matrix for color scale calibration")
    max_val: float = Field(..., description="Maximum value in the matrix for color scale calibration")


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
    route_code: str = Field(..., description="Route code evaluated against DGCA statutory guidelines")
    statutory_band_cap_inr: float = Field(..., description="Regulatory upper ceiling fare prescribed by DGCA")
    observed_max_fare_inr: float = Field(..., description="Maximum recorded fare on route during audit period")
    violations_count: int = Field(..., description="Number of individual flight instances breaching fare cap")
    compliance_status: str = Field(..., description="'COMPLIANT' or 'BREACH_DETECTED'")


class DGCAValidationResponse(BaseModel):
    checked_at: datetime = Field(..., description="Audit run timestamp")
    total_routes_evaluated: int = Field(..., description="Total routes audited against regulatory bands")
    total_violations: int = Field(..., description="Total cap violations identified")
    violations: List[DGCAValidationItem] = Field(..., description="Route-by-route regulatory audit findings")
