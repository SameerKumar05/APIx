/**
 * Project APIx - Airfare Price Index for India (SIH 2026 PS 26056)
 * Core API Schema definitions mirroring BackendApiDev specifications.
 */

export type SeverityLevel = 'CRITICAL' | 'HIGH' | 'WARNING' | 'MEDIUM' | 'LOW' | 'INFO';

export type ComplianceStatus = 'COMPLIANT' | 'WARNING' | 'BREACH' | 'BREACH_DETECTED' | 'PENDING';

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
  mospi_cpi?: number; // MoSPI Consumer Price Index (Transport) benchmark
  t1_index?: number; // T+1 Booking window sub-index
  t7_index?: number; // T+7 Booking window sub-index
  t15_index?: number; // T+15 Booking window sub-index
  t30_index?: number; // T+30 Booking window sub-index
  t45_index?: number; // T+45 Booking window sub-index
}

export interface NationalIndexLatestResponse {
  timestamp: string;
  index_value: number;
  change_24h: number; // percentage change e.g. +1.85
  change_7d: number | null; // null when no observation exists 7 days earlier
  sample_size: number; // total flight observations in window
  base_period: string; // "2026-01=100"
  confidence_interval_lower?: number;
  confidence_interval_upper?: number;
  status: string; // "OFFICIAL" | "PRELIMINARY"
  weighted_median_fare_inr?: number;
  mospi_cpi?: number;
  mospi_cpi_divergence?: number;
  t1_index?: number;
  t7_index?: number;
  t15_index?: number;
  t30_index?: number;
  t45_index?: number;
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
  origin_city?: string; // "Delhi"
  destination_city?: string; // "Mumbai"
  current_index: number; // e.g. 124.5
  change_24h: number | null; // null when no prior observation exists
  change_7d?: number; // e.g. +3.2
  avg_fare_inr?: number; // representative average economy fare in INR
  median_fare_inr?: number; // representative median fare in INR
  min_fare_inr?: number;
  max_fare_inr?: number;
  weight?: number; // DGCA traffic passenger share (0-1), e.g. 0.142
  sample_size?: number;
  active_flights_tracked?: number;
  volatility_score?: number;
  status?: string; // "ACTIVE" | "MONITORED"
  active_airlines_count?: number;
  distance_km?: number;
  sparkline_7d?: number[]; // 7-day median fare trend
  anomaly_count?: number;
  max_severity?: SeverityLevel;
}

export interface RoutesOverviewResponse {
  routes: RouteOverviewItem[];
  total_routes: number;
  data_available?: boolean;
}

export interface RouteHistoryResponse {
  route_code: string;
  origin: string;
  destination: string;
  points: NationalIndexPoint[];
  data_available?: boolean;
  frequency?: string;
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
  elasticity_factor: number | null;
  booking_window_label?: string; // "T+1", "T+3", "T+7", "T+15", "T+30"
  sample_count?: number;
}

export interface LeadTimeCurveResponse {
  route_code?: string;
  curve_points: LeadTimeCurvePoint[];
  generated_at: string;
  data_available?: boolean;
}

export interface HeatmapCell {
  day_of_week: number; // 0 = Monday, 1 = Tuesday, ... 6 = Sunday (Backend schema)
  hour_of_day: number; // 0 to 23
  fare_index: number | null;
  avg_fare_inr: number;
}

export interface HeatmapMatrixResponse {
  route_code?: string;
  metric: string;
  matrix: HeatmapCell[];
  min_val: number | null;
  max_val: number | null;
  data_available?: boolean;
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
  anomaly_type: 'SURGE_PRICING' | 'SURGE' | 'DGCA_CAP_EXCEEDED' | 'PRICE_CRASH' | 'FLASH_SALE' | 'SPIKE' | 'DROP' | 'VOLATILITY' | 'PRICE_GOUGING' | 'DISPERSION_SPIKE' | 'FLASH_DROP' | string;
  severity: SeverityLevel;
  observed_fare_inr: number;
  expected_fare_inr: number;
  baseline_fare_inr?: number; // baseline comparison fare
  deviation_percent: number; // e.g. +78.4%
  z_score?: number; // statistical surge Z-score (e.g. 3.42, 2.15)
  status: 'ACTIVE' | 'OPEN' | 'ACKNOWLEDGED' | 'INVESTIGATING' | 'RESOLVED' | 'FALSE_POSITIVE' | string;
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
  data_available?: boolean;
  evaluation_status?: 'not_evaluated' | 'evaluated';
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
  /** Scraper classes that exist. Implemented is not the same as a live fare. */
  supported_sources: string[];
  source_types: Record<string, 'ota' | 'airline_direct'>;
  ps_named_sources_total: number;
  ps_named_sources_implemented: number;
  live_verified_sources: string[];
  produces_live_fares: boolean;
  latency_ms: number;
}

export type CrawlerName = 'easemytrip' | 'makemytrip' | 'spicejet' | 'amadeus' | string;
export type CrawlerStatusType = 'ACTIVE' | 'HEALTHY' | 'ONLINE' | 'RUNNING' | 'IDLE' | 'DEGRADED' | 'OFFLINE' | 'ERROR' | string;

export interface CrawlerStatus {
  crawler_name: CrawlerName;
  platform: string;
  status: CrawlerStatusType;
  uptime_pct: number;
  success_count: number;
  error_count: number;
  error_rate_pct: number;
  last_run_at: string;
  fares_collected: number;
  avg_response_time_ms?: number;
  rate_limit_rpm?: number;
  consecutive_failures?: number;
  target_routes?: string[];
}

export interface ProxyExitNode {
  region: string;
  ip_prefix: string;
  latency_ms: number;
  status: 'OPTIMAL' | 'DEGRADED' | 'BLOCKED';
}

export interface ProxyPoolSummary {
  total_proxies: number;
  active_proxies: number;
  blacklisted_proxies: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  healthy_pct?: number;
  bandwidth_mb_today?: number;
  top_exit_nodes?: ProxyExitNode[];
}

export interface CrawlerErrorItem {
  id: string;
  crawler_name: CrawlerName;
  error_type: 'HTTP_TIMEOUT' | 'CAPTCHA_CHALLENGE' | 'RATE_LIMIT_EXCEEDED' | 'DOM_PARSE_ERROR' | 'PROXY_RESET' | 'SCHEMA_MISMATCH' | string;
  route_code?: string;
  status_code?: number;
  message: string;
  occurred_at: string;
  retry_count: number;
  recovered: boolean;
}

export interface CrawlerErrorBreakdown {
  total_errors: number;
  by_type: Record<string, number>;
  by_crawler: Record<string, number>;
  recent_errors: CrawlerErrorItem[];
}

export interface TelemetryResponse {
  scrapers: CrawlerStatus[];
  proxy_pool: ProxyPoolSummary;
  system_health: SystemStatus;
  generated_at: string;
  error_breakdown?: CrawlerErrorBreakdown;
  schedule_interval_minutes?: number;
  active_workers?: number;
}

export interface CrawlerTriggerRequest {
  crawler_name?: string;
  route_code?: string;
  source?: string;
}

export interface CrawlerTriggerResponse {
  task_id: string;
  status: 'QUEUED' | 'TRIGGERED' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  message: string;
  triggered_at: string;
}

// ---------------------------------------------------------------------------
// 6. Real-Time Streaming Fare Feed
// ---------------------------------------------------------------------------

export interface LiveFareUpdate {
  type: 'fare_update';
  is_synthetic?: boolean;
  airline_code: string;
  airline_name: string;
  flight_number: string;
  origin: string;
  destination: string;
  fare_inr: number;
  source: string;
  cabin_class: string;
  departure_datetime: string;
  booking_datetime: string;
  timestamp: string;
  is_anomaly?: boolean;
  prev_fare_inr?: number;
  fare_change_pct?: number;
}

export interface WebSocketFareMessage {
  type: 'fare_update' | 'ping' | 'pong' | 'buffer_dump';
  data?: LiveFareUpdate | LiveFareUpdate[];
}

// ---------------------------------------------------------------------------
// 7. Direct Airline vs OTA Arbitrage Surveillance
// ---------------------------------------------------------------------------

export type ArbitrageDirection = 'OTA_CHEAPER' | 'AIRLINE_CHEAPER';

export interface ArbitrageOpportunity {
  route_code: string;
  airline_code: string;
  airline_name?: string;
  airline_direct_fare?: number;
  direct_fare?: number;
  direct_platform?: string;
  ota_name?: string;
  ota_platform?: string;
  ota_fare: number;
  spread_inr?: number;
  spread_amount?: number;
  spread_percentage: number;
  direction: ArbitrageDirection;
  actionable: boolean;
  flight_number?: string;
  departure_datetime?: string;
  sample_timestamp?: string;
  origin?: string;
  destination?: string;
  buy_venue?: string;
  buy_fare?: number;
  sell_venue?: string;
  sell_fare?: number;
  net_profit_inr?: number;
}

export interface ArbitrageResponse {
  generated_at: string;
  routes_evaluated: number;
  opportunities_count: number;
  items: ArbitrageOpportunity[];
  max_spread_percentage?: number;
  avg_spread_percentage?: number;
  total_savings_potential_inr?: number;
  total_potential_savings_inr?: number;
}

// ---------------------------------------------------------------------------
// 8. Generic UI / API State
// ---------------------------------------------------------------------------

export type ActiveTab = 'overview' | 'econometrics' | 'dgca' | 'routes' | 'elasticity' | 'anomalies' | 'telemetry' | 'arbitrage';

export interface DashboardSummaryData {
  nationalLatest: NationalIndexLatestResponse;
  nationalHistory: NationalIndexPoint[];
  routes: RouteOverviewItem[];
  leadTimeCurve: LeadTimeCurveResponse;
  heatmap: HeatmapMatrixResponse;
  anomalies: AnomalyAlertItem[];
  dgcaValidation: DGCAValidationResponse;
  systemHealth: SystemHealthResponse;
  telemetry: TelemetryResponse;
  arbitrage: ArbitrageResponse;
  econometricIndices: EconometricIndicesResponse;
  cpiDivergence: CpiDivergenceResponse;
  priceElasticity: PriceElasticityResponse;
  dgcaSurveillance: DgcaSurveillanceResponse;
}

// ---------------------------------------------------------------------------
// 9. Econometric Engine & MoSPI CPI Gap Analytics (Cycle 4)
// ---------------------------------------------------------------------------

export interface EconometricIndexPoint {
  date: string;
  laspeyres: number;
  paasche: number;
  fisher: number;
  mospi_cpi: number;
  route_code?: string;
  substitution_bias?: number;
  bias_pct?: number;
}

export interface EconometricIndicesResponse {
  base_period: string;
  laspeyres_index: number;
  paasche_index: number;
  fisher_index: number;
  substitution_bias: number;
  series: EconometricIndexPoint[];
  summary?: {
    current_fisher: number;
    current_laspeyres: number;
    current_paasche: number;
    avg_substitution_bias: number;
  };
}

export interface CpiDivergencePoint {
  date: string;
  apix_index: number;
  mospi_cpi: number;
  gap: number;
}

export interface CpiDivergenceResponse {
  current_divergence_pts: number;
  inflation_lead_days: number;
  correlation_coefficient: number;
  divergence_series: CpiDivergencePoint[];
  summary?: {
    mean_divergence: number;
    tracking_error: number;
    correlation: number;
    lead_lag_days: number;
    optimal_lead_days: number;
  };
}

export interface PriceElasticityGradientPoint {
  lead_window: 'T+45' | 'T+30' | 'T+15' | 'T+7' | 'T+1' | string;
  days_before_departure: number;
  surge_multiplier: number;
  avg_fare_inr: number;
  price_elasticity: number;
  demand_index?: number;
}

export interface PriceElasticityResponse {
  route_code?: string;
  as_of_date?: string;
  gradient_points: PriceElasticityGradientPoint[];
  segments?: {
    t1_t7?: number;
    t7_t15?: number;
    t15_t30?: number;
    avg_lead_time_decay?: number;
    confidence_score?: number;
  };
}

// ---------------------------------------------------------------------------
// 10. DGCA Regulatory Surveillance & Price Gouging Audits (Cycle 4)
// ---------------------------------------------------------------------------

export type DgcaViolationSeverity = 'WARNING' | 'CRITICAL' | 'SEVERE';

export interface DgcaViolationRecord {
  id: string;
  route_code: string;
  carrier_code: string;
  carrier_name: string;
  flight_number: string;
  flight_date?: string;
  window?: string;
  observed_fare_inr: number;
  statutory_band_cap_inr: number;
  surge_multiplier: number;
  severity: DgcaViolationSeverity;
  compliance_status: 'COMPLIANT' | 'WARNING' | 'BREACH' | 'PENDING';
  detected_at: string;
  description: string;
  violation_code?: string;
  status?: string;
}

export interface DgcaCarrierDistribution {
  carrier_code: string;
  carrier_name: string;
  avg_surge_multiplier: number;
  violations_count: number;
  compliance_rate: number;
}

export interface DgcaSurveillanceResponse {
  total_evaluated: number;
  total_violations: number;
  violations: DgcaViolationRecord[];
  carrier_distribution: DgcaCarrierDistribution[];
  summary?: {
    total_violations: number;
    severe_count: number;
    critical_count: number;
    warning_count: number;
    top_violating_carriers?: Array<{
      airline_code: string;
      count: number;
    }>;
  };
}
