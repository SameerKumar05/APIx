"""Strict Pydantic schemas for Cycle 4 Econometrics, CPI Gap Analytics,
Lead-Time Elasticity, and DGCA Tariff Surveillance APIs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ==============================================================================
# 1. Econometric Axiomatic Indices (Laspeyres, Paasche, Fisher, Substitution Bias)
# ==============================================================================

class EconometricIndexPoint(BaseModel):
    """Single temporal observation of axiomatic price indices."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    date: str = Field(..., description="Observation date (YYYY-MM-DD)")
    laspeyres: float = Field(..., description="Laspeyres base-weighted price index")
    paasche: float = Field(..., description="Paasche current-weighted price index")
    fisher: float = Field(..., description="Fisher Ideal geometric mean index sqrt(L * P)")
    mospi_cpi: float | None = Field(None, description="Official MoSPI CPI benchmark for the matching period")
    substitution_bias: float | None = Field(None, description="Substitution bias (Laspeyres - Fisher or Laspeyres - Paasche)")
    route_code: str | None = Field("NATIONAL", description="Route corridor code or 'NATIONAL'")
    calculation_method: str | None = Field("chain_weighted", description="Index methodology: chain_weighted, fixed_base")


class EconometricIndicesSummary(BaseModel):
    """Aggregate statistics for econometric index series."""
    model_config = ConfigDict(from_attributes=True)

    current_fisher: float = Field(..., description="Latest Fisher Ideal index point")
    current_laspeyres: float = Field(..., description="Latest Laspeyres index point")
    current_paasche: float = Field(..., description="Latest Paasche index point")
    avg_substitution_bias: float = Field(..., description="Mean substitution bias across observation window")
    max_substitution_bias: float | None = Field(None, description="Peak substitution bias observed")
    total_observations: int = Field(..., description="Count of daily index observations returned")


class EconometricIndicesResponse(BaseModel):
    """Complete response payload for GET /api/v1/econometrics/indices."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    base_period: str | None = Field(None, description="Earliest observation date in the returned series")
    laspeyres_index: float | None = Field(None, description="Current Laspeyres index value, or null when no rows exist")
    paasche_index: float | None = Field(None, description="Current Paasche index value, or null when no rows exist")
    fisher_index: float | None = Field(None, description="Current Fisher Ideal index value, or null when no rows exist")
    substitution_bias: float | None = Field(None, description="Current substitution bias in index points, or null when no rows exist")
    series: list[EconometricIndexPoint] = Field(default_factory=list, description="Historical time-series of daily index points")
    items: list[EconometricIndexPoint] | None = Field(None, description="Alias for series list for standard table views")
    total: int | None = Field(None, description="Total count of index points")
    summary: EconometricIndicesSummary | None = Field(None, description="Statistical summary metrics")
    data_available: bool = Field(False, description="False when the database has no index rows for the query")


# ==============================================================================
# 2. MoSPI CPI Transport Sub-Index Divergence & Lead-Lag Correlation
# ==============================================================================

class CpiDivergencePoint(BaseModel):
    """Monthly observation point comparing APIx Airfare Index against MoSPI official CPI."""
    model_config = ConfigDict(from_attributes=True)

    date: str = Field(..., description="Reporting month (YYYY-MM or YYYY-MM-DD)")
    apix_index: float = Field(..., description="APIx Real-time Domestic Airfare Price Index")
    mospi_cpi: float = Field(..., description="Official MoSPI Consumer Price Index (Transport sub-index)")
    gap: float = Field(..., description="Spread in index points (apix_index - mospi_cpi)")
    airfare_subindex: float | None = Field(None, description="Official MoSPI domestic airfare sub-component index")
    headline_cpi: float | None = Field(None, description="All-India Headline CPI Combined")
    divergence_pct: float | None = Field(None, description="Percentage deviation ((apix - mospi) / mospi) * 100")


class CpiDivergenceSummary(BaseModel):
    """Statistical metrics of real-time airfare index divergence from official MoSPI CPI."""
    model_config = ConfigDict(from_attributes=True)

    mean_divergence: float | None = Field(None, description="Average spread in index points over the evaluation window")
    tracking_error: float | None = Field(None, description="Standard deviation of monthly index point differences")
    correlation: float | None = Field(None, description="Pearson correlation, or null when it cannot be computed")
    lead_lag_days: int | None = Field(None, description="Estimated lead in days, or null when a lead cannot be identified")
    optimal_lead_days: int | None = Field(None, description="Lead in days that maximizes cross-correlation, or null")
    reason: str | None = Field(None, description="Why correlation or lead is null")
    last_updated: str | None = Field(None, description="ISO timestamp of divergence computation")


class CpiDivergenceResponse(BaseModel):
    """Complete response payload for GET /api/v1/econometrics/cpi-divergence and /cpi-gap."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    current_divergence_pts: float | None = Field(None, description="Latest divergence spread in index points")
    inflation_lead_days: int | None = Field(None, description="Days by which APIx leads MoSPI, or null when unidentified")
    correlation_coefficient: float | None = Field(None, description="Pearson correlation, or null when it cannot be computed")
    divergence_series: list[CpiDivergencePoint] = Field(default_factory=list, description="Historical series of monthly divergence points")
    series: list[CpiDivergencePoint] | None = Field(None, description="Alias for divergence_series")
    summary: CpiDivergenceSummary | None = Field(None, description="High-level divergence and correlation statistics")
    data_available: bool = Field(False, description="False when no overlapping APIx and MoSPI observations exist")
    reason: str | None = Field(None, description="Why correlation or lead is null")


# ==============================================================================
# 3. Dynamic Lead-Time Price Elasticity Curves (T+1 -> T+30)
# ==============================================================================

class ElasticityGradientPoint(BaseModel):
    """Point on the advance booking horizon curve representing price elasticity."""
    model_config = ConfigDict(from_attributes=True)

    lead_window: str = Field(..., description="Advance booking window tag: 'T+30', 'T+15', 'T+7', 'T+1'")
    window: str | None = Field(None, description="Alias for lead_window")
    days_before_departure: int = Field(..., description="Days remaining until scheduled departure (1, 7, 15, 30)")
    surge_multiplier: float | None = Field(None, description="Fare divided by the observed T+30 fare, when both exist")
    avg_fare_inr: float = Field(..., description="Average observed fare in INR at this horizon")
    price_elasticity: float | None = Field(None, description="Stored segment elasticity for this window, when the row has one")
    arc_elasticity: float | None = Field(None, description="Midpoint arc elasticity relative to adjacent window")
    demand_index: float | None = Field(None, description="Normalized passenger booking intensity index")
    demand_type: str | None = Field(None, description="'inelastic' | 'elastic'")


class ElasticitySegments(BaseModel):
    """Segment-specific price elasticity ratios and decay coefficients."""
    model_config = ConfigDict(from_attributes=True)

    t1_t7: float = Field(..., description="Price gradient / elasticity between urgent T+1 and T+7 windows")
    t7_t15: float = Field(..., description="Price gradient / elasticity between T+7 and T+15 windows")
    t15_t30: float = Field(..., description="Price gradient / elasticity between T+15 and T+30 advance windows")
    avg_lead_time_decay: float = Field(..., description="Exponential rate parameter lambda for fare decay over days-to-departure")
    confidence_score: float = Field(..., description="Regression R-squared or confidence score (0.0 to 1.0)")


class ElasticityResponse(BaseModel):
    """Complete response payload for GET /api/v1/econometrics/elasticity."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    route_code: str | None = Field("NATIONAL", description="Evaluated corridor or 'NATIONAL'")
    as_of_date: str | None = Field(None, description="Date for which elasticity curve was evaluated")
    gradient_points: list[ElasticityGradientPoint] = Field(default_factory=list, description="Curve points from T+30 to T+1")
    curves: list[ElasticityGradientPoint] | None = Field(None, description="Alias for gradient_points")
    segments: ElasticitySegments | None = Field(None, description="Segment ratios and curve parameters")
    data_available: bool = Field(False, description="False when no route_elasticity row exists")


# ==============================================================================
# 4. DGCA Statutory Tariff Surveillance & Violation Audit Feed
# ==============================================================================

class DgcaViolationItem(BaseModel):
    """Detailed audit record for a statutory price gouging violation flagged by algorithmic oversight."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str = Field(..., description="Unique violation record identifier (string or integer-backed ID)")
    route_code: str = Field(..., description="Flight corridor code (e.g. DEL-BOM)")
    carrier_code: str = Field(..., description="IATA operating carrier code (e.g. '6E', 'AI')")
    carrier_name: str = Field(..., description="Full operating airline brand name (e.g. 'IndiGo')")
    flight_number: str = Field(..., description="Scheduled flight number (e.g. '6E-204')")
    flight_date: str | None = Field(None, description="Scheduled departure flight date (YYYY-MM-DD)")
    window: str | None = Field(None, description="Advance booking window (e.g. 'T+1', 'T+7')")
    observed_fare_inr: float = Field(..., description="Observed ticket fare in INR")
    statutory_band_cap_inr: float = Field(..., description="Statutory upper tariff cap or baseline benchmark in INR")
    surge_multiplier: float = Field(..., description="Surge multiple observed relative to median corridor fare")
    severity: str = Field(..., description="Violation severity level: 'WARNING', 'CRITICAL', 'SEVERE'")
    compliance_status: str = Field(..., description="Regulatory compliance status: 'COMPLIANT', 'WARNING', 'BREACH', 'PENDING'")
    violation_code: str | None = Field(None, description="Statutory rule violation code (e.g. 'DGCA-SURGE-3X')")
    detected_at: str = Field(..., description="ISO timestamp when algorithmic audit flagged the violation")
    description: str = Field(..., description="Human-readable regulatory audit explanation")
    status: str | None = Field("OPEN", description="Review status: 'OPEN', 'UNDER_REVIEW', 'CONFIRMED', 'DISMISSED'")
    fare_inr: float | None = Field(None, description="Alias for observed_fare_inr")
    median_baseline_fare: float | None = Field(None, description="Alias for statutory_band_cap_inr")
    surge_multiple: float | None = Field(None, description="Alias for surge_multiplier")
    airline_code: str | None = Field(None, description="Alias for carrier_code")


class CarrierViolationDistribution(BaseModel):
    """Aggregate regulatory compliance and surge metrics for an individual carrier."""
    model_config = ConfigDict(from_attributes=True)

    carrier_code: str = Field(..., description="IATA operating airline code (e.g. '6E', 'AI')")
    carrier_name: str = Field(..., description="Airline brand name")
    avg_surge_multiplier: float = Field(..., description="Mean surge multiple observed on flagged routes")
    violations_count: int = Field(..., description="Count of flagged statutory violations")
    compliance_rate: float | None = Field(None, description="Compliance rate only when a quote denominator exists in the database")


class DgcaViolationsSummary(BaseModel):
    """Summary counts and carrier breakdowns for DGCA regulatory oversight."""
    model_config = ConfigDict(from_attributes=True)

    total_violations: int = Field(..., description="Total count of active violations")
    severe_count: int = Field(0, description="Count of SEVERE tier breaches (>3.0x or severe statutory cap gouging)")
    critical_count: int = Field(0, description="Count of CRITICAL tier breaches (2.5x - 3.0x surge)")
    warning_count: int = Field(0, description="Count of WARNING tier alerts (2.0x - 2.5x surge)")
    top_violating_carriers: list[dict[str, Any]] = Field(default_factory=list, description="Top carriers by violation count")


class DgcaViolationsResponse(BaseModel):
    """Complete response payload for GET /api/v1/econometrics/dgca-violations."""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    violations: list[DgcaViolationItem] = Field(default_factory=list, description="List of flagged statutory tariff violations")
    items: list[DgcaViolationItem] = Field(default_factory=list, description="Alias for violations")
    carrier_distribution: list[CarrierViolationDistribution] = Field(default_factory=list, description="Per-carrier statistics computed from stored rows")
    total_evaluated: int = Field(..., description="Count of matching violation rows. Zero when the table has none")
    total_violations: int = Field(..., description="Total statutory violations detected")
    summary: DgcaViolationsSummary | None = Field(None, description="Regulatory breakdown and severity summary")
    data_available: bool = Field(False, description="False when no matching violation rows exist")


# ==============================================================================
# 5. Administrative Actions & Recomputation
# ==============================================================================

class DgcaViolationStatusUpdateRequest(BaseModel):
    """Request payload to update review status of a DGCA violation."""
    status: str = Field(..., description="Target status: 'OPEN', 'UNDER_REVIEW', 'CONFIRMED', 'DISMISSED', 'REPORTED'")
    notes: str | None = Field(None, description="Auditor review notes or justification")


class EconometricRecalculateRequest(BaseModel):
    """Request payload to trigger recalculation of econometric indices."""
    route_code: str | None = Field("NATIONAL", description="Route corridor to recompute, or 'NATIONAL'")
    calculation_method: str | None = Field("chain_weighted", description="Target methodology: 'chain_weighted' or 'fixed_base'")


class EconometricRecalculateResponse(BaseModel):
    """Response payload for administrative econometric recomputation."""
    status: str = Field(..., description="Execution status e.g. 'SUCCESS' or 'TRIGGERED'")
    message: str = Field(..., description="Human-readable result summary")
    routes_processed: int = Field(..., description="Count of route corridors processed")
    indices_generated: int = Field(..., description="Count of econometric index records created or updated")
    timestamp: str = Field(..., description="ISO execution timestamp")
