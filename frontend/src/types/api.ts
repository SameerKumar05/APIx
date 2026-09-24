/**
 * Project APIx - Airfare Price Index for India (SIH 2026 PS 26056)
 * Core API Schema definitions mirroring BackendApiDev specifications.
 */

export type SeverityLevel = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';

export type ComplianceStatus = 'COMPLIANT' | 'WARNING' | 'BREACH' | 'PENDING';

export type SystemStatus = 'HEALTHY' | 'DEGRADED' | 'MAINTENANCE' | 'SYNCING';

// ---------------------------------------------------------------------------
// 1. National Index
// ---------------------------------------------------------------------------

export interface NationalIndexPoint {
  timestamp: string; // ISO 8601 string
  index_value: number; // e.g. 118.42 (base 100)
  sample_size?: number;
  base_period?: string; // e.g. "2026-01=100"
  moving_avg_7d?: number;
  confidence_interval_lower?: number;
  confidence_interval_upper?: number;
}

export interface NationalIndexLatestResponse {
  timestamp: string;
  index_value: number;
  change_24h: number; // percentage change e.g. +1.85
  change_7d: number; // percentage change e.g. +4.12
  sample_size: number; // total flight observations in window
  base_period: string; // "2026-01=100"
  confidence_interval_lower?: number;
  confidence_interval_upper?: number;
  status: string; // "OFFICIAL" | "PRELIMINARY"
  weighted_median_fare_inr?: number;
}

export interface NationalIndexHistoryResponse {
  points: NationalIndexPoint[];
  total_points: number;
}

// ---------------------------------------------------------------------------
// 2. Routes & Route Specific Indexes
// ---------------------------------------------------------------------------

export interface RouteOverviewItem {
  route_code: string; // e.g. "DEL-BOM"
  origin: string; // "DEL"
  destination: string; // "BOM"
  origin_city: string; // "Delhi"
  destination_city: string; // "Mumbai"
  current_index: number; // e.g. 124.5
  change_24h: number; // e.g. -0.8
  change_7d: number; // e.g. +3.2
  median_fare_inr: number; // representative fare in INR
  min_fare_inr?: number;
  max_fare_inr?: number;
  weight: number; // DGCA traffic passenger share (0-1), e.g. 0.142
  sample_size: number;
  status: string; // "ACTIVE" | "MONITORED"
  active_airlines_count?: number;
  distance_km?: number;
}

export interface RoutesOverviewResponse {
  routes: RouteOverviewItem[];
  total_routes: number;
}

export interface RouteHistoryResponse {
  route_code: string;
  origin: string;
  destination: string;
  points: NationalIndexPoint[];
}

// ---------------------------------------------------------------------------
// 3. Analytics & Lead-Time Elasticity
// ---------------------------------------------------------------------------

export interface LeadTimeCurvePoint {
  days_before_departure: number; // e.g. 1, 3, 7, 14, 21, 30, 45, 60
  avg_fare_inr: number;
  median_fare_inr: number;
  p10_fare_inr: number; // 10th percentile
  p90_fare_inr: number; // 90th percentile
  elasticity_factor: number; // price ratio relative to 30d baseline
  booking_window_label?: string; // "T+1", "T+3", "T+7", "T+15", "T+30"
  sample_count?: number;
}

export interface LeadTimeCurveResponse {
  route_code?: string;
  curve_points: LeadTimeCurvePoint[];
  generated_at: string;
}

export interface HeatmapCell {
  day_of_week: number; // 0 = Sunday, 1 = Monday, ... 6 = Saturday
  hour_of_day: number; // 0 to 23
  fare_index: number;
  avg_fare_inr: number;
}

export interface HeatmapMatrixResponse {
  route_code?: string;
  metric: string;
  matrix: HeatmapCell[];
  min_val: number;
  max_val: number;
}

// ---------------------------------------------------------------------------
// 4. Anomaly Alerts & DGCA Compliance Monitoring
// ---------------------------------------------------------------------------

export interface AnomalyAlertItem {
  id: string;
  route_code: string;
  airline_code: string; // e.g. "6E", "AI", "SG", "QP"
  flight_number?: string;
  detected_at: string;
  anomaly_type: 'SURGE_SPIKE' | 'PRICE_GOUGING' | 'FLASH_DROP' | 'DISPERSION_SPIKE' | string;
  severity: SeverityLevel;
  observed_fare_inr: number;
  expected_fare_inr: number;
  deviation_percent: number; // e.g. +78.4%
  status: 'ACTIVE' | 'ACKNOWLEDGED' | 'INVESTIGATING' | 'RESOLVED';
  description?: string;
  recommended_action?: string;
  booking_window?: string; // "T+1", "T+7", etc.
}

export interface AnomalyAlertsResponse {
  alerts: AnomalyAlertItem[];
  total_alerts: number;
}

export interface DGCAValidationViolation {
  route_code: string;
  statutory_band_cap_inr: number;
  observed_max_fare_inr: number;
  violations_count: number;
  compliance_status: ComplianceStatus;
}

export interface DGCAValidationResponse {
  checked_at: string;
  total_routes_evaluated: number;
  total_violations: number;
  violations: DGCAValidationViolation[];
}

// ---------------------------------------------------------------------------
// 5. System Health & Scraping Pipeline Telemetry
// ---------------------------------------------------------------------------

export interface SystemHealthResponse {
  status: SystemStatus;
  active_scrapers: number;
  records_ingested_today: number;
  last_sync_timestamp: string;
  supported_airlines: string[];
  supported_otas: string[];
  latency_ms: number;
}

// ---------------------------------------------------------------------------
// 6. Generic UI / API State
// ---------------------------------------------------------------------------

export type ActiveTab = 'overview' | 'routes' | 'elasticity' | 'anomalies';

export interface DashboardSummaryData {
  nationalLatest: NationalIndexLatestResponse;
  nationalHistory: NationalIndexPoint[];
  routes: RouteOverviewItem[];
  leadTimeCurve: LeadTimeCurveResponse;
  heatmap: HeatmapMatrixResponse;
  anomalies: AnomalyAlertItem[];
  dgcaValidation: DGCAValidationResponse;
  systemHealth: SystemHealthResponse;
}
