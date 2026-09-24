/**
 * Project APIx - Mock Data Provider
 * Realistic simulation of India's domestic aviation market (DGCA / CPI context).
 */

import {
  NationalIndexLatestResponse,
  NationalIndexPoint,
  RouteOverviewItem,
  LeadTimeCurveResponse,
  HeatmapMatrixResponse,
  AnomalyAlertItem,
  DGCAValidationResponse,
  SystemHealthResponse,
  DashboardSummaryData,
  TelemetryResponse,
  ArbitrageResponse,
  LiveFareUpdate,
} from '../types/api';

// ---------------------------------------------------------------------------
// 1. National Index Data
// ---------------------------------------------------------------------------

export const mockNationalLatest: NationalIndexLatestResponse = {
  timestamp: new Date().toISOString(),
  index_value: 118.65,
  change_24h: 1.42,
  change_7d: 3.78,
  sample_size: 48290,
  base_period: '2026-01=100',
  confidence_interval_lower: 117.82,
  confidence_interval_upper: 119.48,
  status: 'OFFICIAL',
  weighted_median_fare_inr: 5480,
  mospi_cpi: 107.40,
  mospi_cpi_divergence: 11.25,
  t1_index: 154.20,
  t7_index: 128.60,
  t15_index: 114.10,
  t30_index: 99.40,
};
export const generateMockNationalHistory = (days: number = 30): NationalIndexPoint[] => {
  const points: NationalIndexPoint[] = [];
  const baseValue = 108.5;
  const mospiBase = 105.8;
  const now = new Date();

  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    d.setHours(12, 0, 0, 0);

    // Realistic seasonal walk with weekend bumps (day 5, 6)
    const dayOfWeek = d.getDay();
    const weekendFactor = dayOfWeek === 5 || dayOfWeek === 0 ? 2.5 : 0.8;
    const trend = (days - i) * 0.32;
    const noise = Math.sin(i * 0.7) * 1.8 + (Math.random() - 0.48) * 1.2;
    const index_value = Number((baseValue + trend + weekendFactor + noise).toFixed(2));
    const moving_avg_7d = Number((index_value * 0.98 + (baseValue + trend) * 0.02).toFixed(2));

    // MoSPI Transport CPI: smooth monthly official index with conservative slope
    const mospi_cpi = Number((mospiBase + (days - i) * 0.055 + Math.sin(i * 0.2) * 0.15).toFixed(2));

    // Booking window sub-indices illustrating dynamic surge behavior
    // T+1: high volatility emergency bookings (140 - 165)
    const t1_index = Number((index_value * 1.30 + weekendFactor * 3.2 + Math.sin(i * 1.1) * 3.5).toFixed(2));
    // T+7: near-term booking window (120 - 135)
    const t7_index = Number((index_value * 1.08 + weekendFactor * 1.4 + Math.cos(i * 0.9) * 1.8).toFixed(2));
    // T+15: mid-term planning window (110 - 118)
    const t15_index = Number((index_value * 0.96 + Math.sin(i * 0.5) * 1.2).toFixed(2));
    // T+30: advance baseline booking window (96 - 103)
    const t30_index = Number((index_value * 0.84 + Math.cos(i * 0.4) * 0.9).toFixed(2));

    points.push({
      timestamp: d.toISOString(),
      index_value,
      moving_avg_7d,
      sample_size: Math.floor(42000 + Math.random() * 8000),
      base_period: '2026-01=100',
      confidence_interval_lower: Number((index_value - 0.95).toFixed(2)),
      confidence_interval_upper: Number((index_value + 0.95).toFixed(2)),
      mospi_cpi,
      t1_index,
      t7_index,
      t15_index,
      t30_index,
    });
  }

  return points;
};

export const mockNationalHistory = generateMockNationalHistory(30);

// ---------------------------------------------------------------------------
// 2. 10 High-Density Indian Domestic Routes
// ---------------------------------------------------------------------------

export const mockRoutes: RouteOverviewItem[] = [
  {
    route_code: 'DEL-BOM',
    origin: 'DEL',
    destination: 'BOM',
    origin_city: 'Delhi',
    destination_city: 'Mumbai',
    current_index: 121.4,
    change_24h: 1.85,
    change_7d: 4.1,
    median_fare_inr: 5850,
    min_fare_inr: 3999,
    max_fare_inr: 16500,
    weight: 0.148,
    sample_size: 9420,
    status: 'ACTIVE',
    active_airlines_count: 5,
    distance_km: 1148,
    sparkline_7d: [5620, 5680, 5710, 5690, 5750, 5810, 5850],
    anomaly_count: 2,
    max_severity: 'CRITICAL',
  },
  {
    route_code: 'DEL-BLR',
    origin: 'DEL',
    destination: 'BLR',
    origin_city: 'Delhi',
    destination_city: 'Bengaluru',
    current_index: 124.8,
    change_24h: 2.15,
    change_7d: 5.4,
    median_fare_inr: 7200,
    min_fare_inr: 4799,
    max_fare_inr: 19800,
    weight: 0.112,
    sample_size: 7850,
    status: 'ACTIVE',
    active_airlines_count: 5,
    distance_km: 1740,
    sparkline_7d: [6830, 6890, 6940, 7020, 7080, 7150, 7200],
    anomaly_count: 1,
    max_severity: 'HIGH',
  },
  {
    route_code: 'BOM-BLR',
    origin: 'BOM',
    destination: 'BLR',
    origin_city: 'Mumbai',
    destination_city: 'Bengaluru',
    current_index: 115.2,
    change_24h: -0.65,
    change_7d: 2.3,
    median_fare_inr: 4600,
    min_fare_inr: 2899,
    max_fare_inr: 12500,
    weight: 0.104,
    sample_size: 6980,
    status: 'ACTIVE',
    active_airlines_count: 4,
    distance_km: 842,
    sparkline_7d: [4490, 4520, 4550, 4610, 4580, 4630, 4600],
    anomaly_count: 0,
  },
  {
    route_code: 'DEL-CCU',
    origin: 'DEL',
    destination: 'CCU',
    origin_city: 'Delhi',
    destination_city: 'Kolkata',
    current_index: 117.9,
    change_24h: 0.9,
    change_7d: 3.8,
    median_fare_inr: 5600,
    min_fare_inr: 3499,
    max_fare_inr: 14200,
    weight: 0.084,
    sample_size: 5120,
    status: 'ACTIVE',
    active_airlines_count: 4,
    distance_km: 1305,
    sparkline_7d: [5390, 5420, 5460, 5510, 5540, 5580, 5600],
    anomaly_count: 0,
  },
  {
    route_code: 'DEL-HYD',
    origin: 'DEL',
    destination: 'HYD',
    origin_city: 'Delhi',
    destination_city: 'Hyderabad',
    current_index: 114.6,
    change_24h: -0.3,
    change_7d: 1.9,
    median_fare_inr: 5350,
    min_fare_inr: 3699,
    max_fare_inr: 13900,
    weight: 0.082,
    sample_size: 4890,
    status: 'ACTIVE',
    active_airlines_count: 4,
    distance_km: 1253,
    sparkline_7d: [5250, 5280, 5310, 5340, 5390, 5370, 5350],
    anomaly_count: 0,
  },
  {
    route_code: 'DEL-MAA',
    origin: 'DEL',
    destination: 'MAA',
    origin_city: 'Delhi',
    destination_city: 'Chennai',
    current_index: 119.1,
    change_24h: 1.4,
    change_7d: 3.5,
    median_fare_inr: 6750,
    min_fare_inr: 4299,
    max_fare_inr: 18200,
    weight: 0.076,
    sample_size: 4320,
    status: 'ACTIVE',
    active_airlines_count: 4,
    distance_km: 1760,
    sparkline_7d: [6520, 6580, 6610, 6640, 6690, 6720, 6750],
    anomaly_count: 1,
    max_severity: 'MEDIUM',
  },
  {
    route_code: 'MAA-BOM',
    origin: 'MAA',
    destination: 'BOM',
    origin_city: 'Chennai',
    destination_city: 'Mumbai',
    current_index: 113.4,
    change_24h: 0.45,
    change_7d: 2.1,
    median_fare_inr: 4800,
    min_fare_inr: 3199,
    max_fare_inr: 13100,
    weight: 0.072,
    sample_size: 3950,
    status: 'ACTIVE',
    active_airlines_count: 4,
    distance_km: 1030,
    sparkline_7d: [4700, 4720, 4740, 4770, 4780, 4810, 4800],
    anomaly_count: 0,
  },
  {
    route_code: 'BOM-CCU',
    origin: 'BOM',
    destination: 'CCU',
    origin_city: 'Mumbai',
    destination_city: 'Kolkata',
    current_index: 116.8,
    change_24h: 1.1,
    change_7d: 3.2,
    median_fare_inr: 6900,
    min_fare_inr: 4399,
    max_fare_inr: 17800,
    weight: 0.068,
    sample_size: 3410,
    status: 'ACTIVE',
    active_airlines_count: 3,
    distance_km: 1660,
    sparkline_7d: [6680, 6720, 6760, 6810, 6840, 6880, 6900],
    anomaly_count: 1,
    max_severity: 'MEDIUM',
  },
  {
    route_code: 'BLR-HYD',
    origin: 'BLR',
    destination: 'HYD',
    origin_city: 'Bengaluru',
    destination_city: 'Hyderabad',
    current_index: 109.8,
    change_24h: -1.2,
    change_7d: 0.8,
    median_fare_inr: 3400,
    min_fare_inr: 2199,
    max_fare_inr: 9600,
    weight: 0.062,
    sample_size: 3280,
    status: 'ACTIVE',
    active_airlines_count: 4,
    distance_km: 505,
    sparkline_7d: [3370, 3390, 3420, 3450, 3440, 3420, 3400],
    anomaly_count: 1,
    max_severity: 'LOW',
  },
  {
    route_code: 'BOM-GOI',
    origin: 'BOM',
    destination: 'GOI',
    origin_city: 'Mumbai',
    destination_city: 'Goa',
    current_index: 132.5,
    change_24h: 3.8,
    change_7d: 8.6,
    median_fare_inr: 4250,
    min_fare_inr: 2499,
    max_fare_inr: 14800,
    weight: 0.058,
    sample_size: 3100,
    status: 'ACTIVE',
    active_airlines_count: 4,
    distance_km: 435,
    sparkline_7d: [3910, 3960, 4020, 4080, 4140, 4190, 4250],
    anomaly_count: 1,
    max_severity: 'CRITICAL',
  },
];

// ---------------------------------------------------------------------------
// 3. Lead-Time Elasticity Curve
// ---------------------------------------------------------------------------

export const mockLeadTimeCurve: LeadTimeCurveResponse = {
  route_code: 'DEL-BOM',
  generated_at: new Date().toISOString(),
  curve_points: [
    {
      days_before_departure: 1,
      booking_window_label: 'T+1',
      avg_fare_inr: 11450,
      median_fare_inr: 10900,
      p10_fare_inr: 8400,
      p90_fare_inr: 16800,
      elasticity_factor: 2.42,
      sample_count: 1420,
    },
    {
      days_before_departure: 3,
      booking_window_label: 'T+3',
      avg_fare_inr: 8950,
      median_fare_inr: 8500,
      p10_fare_inr: 6800,
      p90_fare_inr: 12400,
      elasticity_factor: 1.89,
      sample_count: 1890,
    },
    {
      days_before_departure: 7,
      booking_window_label: 'T+7',
      avg_fare_inr: 6920,
      median_fare_inr: 6500,
      p10_fare_inr: 5100,
      p90_fare_inr: 9600,
      elasticity_factor: 1.44,
      sample_count: 2450,
    },
    {
      days_before_departure: 14,
      booking_window_label: 'T+14',
      avg_fare_inr: 5550,
      median_fare_inr: 5300,
      p10_fare_inr: 4250,
      p90_fare_inr: 7400,
      elasticity_factor: 1.18,
      sample_count: 2880,
    },
    {
      days_before_departure: 21,
      booking_window_label: 'T+21',
      avg_fare_inr: 4980,
      median_fare_inr: 4800,
      p10_fare_inr: 3900,
      p90_fare_inr: 6300,
      elasticity_factor: 1.07,
      sample_count: 3120,
    },
    {
      days_before_departure: 30,
      booking_window_label: 'T+30',
      avg_fare_inr: 4720,
      median_fare_inr: 4500,
      p10_fare_inr: 3700,
      p90_fare_inr: 5800,
      elasticity_factor: 1.0,
      sample_count: 3450,
    },
    {
      days_before_departure: 45,
      booking_window_label: 'T+45',
      avg_fare_inr: 4560,
      median_fare_inr: 4380,
      p10_fare_inr: 3550,
      p90_fare_inr: 5500,
      elasticity_factor: 0.97,
      sample_count: 2980,
    },
    {
      days_before_departure: 60,
      booking_window_label: 'T+60',
      avg_fare_inr: 4490,
      median_fare_inr: 4320,
      p10_fare_inr: 3480,
      p90_fare_inr: 5400,
      elasticity_factor: 0.96,
      sample_count: 2410,
    },
  ],
};

// ---------------------------------------------------------------------------
// 4. Heatmap Matrix Data (Day of week vs time of day)
// ---------------------------------------------------------------------------

export const generateMockHeatmap = (routeCode: string = 'DEL-BOM'): HeatmapMatrixResponse => {
  const matrix = [];
  const hours = [6, 9, 12, 15, 18, 21]; // key sample hours

  for (let dow = 0; dow < 7; dow++) {
    for (const hr of hours) {
      // Morning (6, 9) and Evening (18, 21) peak on Mon (1), Fri (5), Sun (0)
      const isPeakHour = hr === 6 || hr === 9 || hr === 18 || hr === 21;
      const isPeakDay = dow === 0 || dow === 1 || dow === 5;
      const baseFare = 4800;
      const multiplier = (isPeakDay ? 1.25 : 1.0) * (isPeakHour ? 1.28 : 0.95);
      const avg_fare_inr = Math.round(baseFare * multiplier + (Math.random() - 0.5) * 300);
      const fare_index = Number(((avg_fare_inr / 4500) * 100).toFixed(1));

      matrix.push({
        day_of_week: dow,
        hour_of_day: hr,
        fare_index,
        avg_fare_inr,
      });
    }
  }

  return {
    route_code: routeCode,
    metric: 'fare_index',
    matrix,
    min_val: 88.0,
    max_val: 165.0,
  };
};

export const mockHeatmap = generateMockHeatmap('DEL-BOM');

// ---------------------------------------------------------------------------
// 5. Anomaly Alerts (DGCA Regulatory Monitoring)
// ---------------------------------------------------------------------------

export const mockAnomalies: AnomalyAlertItem[] = [
  {
    id: 'ALT-2026-9041',
    route_code: 'DEL-BOM',
    airline_code: '6E',
    flight_number: '6E-2051',
    detected_at: new Date(Date.now() - 25 * 60 * 1000).toISOString(),
    anomaly_type: 'SURGE_SPIKE',
    severity: 'CRITICAL',
    observed_fare_inr: 18450,
    expected_fare_inr: 9600,
    baseline_fare_inr: 9600,
    deviation_percent: 92.2,
    z_score: 3.68,
    status: 'ACTIVE',
    booking_window: 'T+1',
    description: 'Rapid fare surge detected within T+1 window exceeding 3-sigma historical threshold.',
    recommended_action: 'Flag for DGCA fare cap compliance review and request inventory breakdown.',
  },
  {
    id: 'ALT-2026-9042',
    route_code: 'BOM-GOI',
    airline_code: 'SG',
    flight_number: 'SG-8164',
    detected_at: new Date(Date.now() - 75 * 60 * 1000).toISOString(),
    anomaly_type: 'PRICE_GOUGING',
    severity: 'CRITICAL',
    observed_fare_inr: 14200,
    expected_fare_inr: 6400,
    baseline_fare_inr: 6400,
    deviation_percent: 121.8,
    z_score: 4.15,
    status: 'ACTIVE',
    booking_window: 'T+3',
    description: 'Weekend tourist corridor surge across online aggregators showing uniform price escalation.',
    recommended_action: 'Cross-check DGCA statutory dynamic pricing limits for sub-500km routes.',
  },
  {
    id: 'ALT-2026-9043',
    route_code: 'DEL-BLR',
    airline_code: 'AI',
    flight_number: 'AI-506',
    detected_at: new Date(Date.now() - 140 * 60 * 1000).toISOString(),
    anomaly_type: 'SURGE_SPIKE',
    severity: 'HIGH',
    observed_fare_inr: 15600,
    expected_fare_inr: 9800,
    baseline_fare_inr: 9800,
    deviation_percent: 59.2,
    z_score: 2.45,
    status: 'INVESTIGATING',
    booking_window: 'T+3',
    description: 'Sudden price spike detected across peak evening departure slots.',
    recommended_action: 'Verify if schedule reduction or aircraft swap triggered seat class limitation.',
  },
  {
    id: 'ALT-2026-9044',
    route_code: 'BOM-CCU',
    airline_code: 'QP',
    flight_number: 'QP-1302',
    detected_at: new Date(Date.now() - 280 * 60 * 1000).toISOString(),
    anomaly_type: 'DISPERSION_SPIKE',
    severity: 'MEDIUM',
    observed_fare_inr: 11400,
    expected_fare_inr: 8100,
    baseline_fare_inr: 8100,
    deviation_percent: 40.7,
    z_score: 2.12,
    status: 'ACKNOWLEDGED',
    booking_window: 'T+7',
    description: 'High price variance (>₹3,200) observed between airline direct portal and OTA listings.',
    recommended_action: 'Monitor aggregator scrape feeds for cache latency or convenience fee bundling.',
  },
  {
    id: 'ALT-2026-9045',
    route_code: 'DEL-MAA',
    airline_code: '6E',
    flight_number: '6E-782',
    detected_at: new Date(Date.now() - 360 * 60 * 1000).toISOString(),
    anomaly_type: 'SURGE_SPIKE',
    severity: 'HIGH',
    observed_fare_inr: 14800,
    expected_fare_inr: 9400,
    baseline_fare_inr: 9400,
    deviation_percent: 57.4,
    z_score: 2.28,
    status: 'ACTIVE',
    booking_window: 'T+1',
    description: 'Near-departure business surge exceeding 2-sigma historical bounds.',
    recommended_action: 'Audit dynamic seat allocation buckets for anti-competitive signaling.',
  },
  {
    id: 'ALT-2026-9046',
    route_code: 'BLR-HYD',
    airline_code: '6E',
    flight_number: '6E-441',
    detected_at: new Date(Date.now() - 420 * 60 * 1000).toISOString(),
    anomaly_type: 'FLASH_DROP',
    severity: 'LOW',
    observed_fare_inr: 2100,
    expected_fare_inr: 3400,
    baseline_fare_inr: 3400,
    deviation_percent: -38.2,
    z_score: 1.55,
    status: 'RESOLVED',
    booking_window: 'T+14',
    description: 'Flash sale fare bucket release on mid-day flights.',
    recommended_action: 'Log promotional bucket release into CPI weight deflation model.',
  },
];

// ---------------------------------------------------------------------------
// 6. DGCA Statutory Compliance
// ---------------------------------------------------------------------------

export const mockDGCAValidation: DGCAValidationResponse = {
  checked_at: new Date().toISOString(),
  total_routes_evaluated: 10,
  total_violations: 2,
  violations: [
    {
      route_code: 'DEL-BOM',
      statutory_band_cap_inr: 17500,
      observed_max_fare_inr: 18450,
      violations_count: 3,
      compliance_status: 'BREACH',
    },
    {
      route_code: 'BOM-GOI',
      statutory_band_cap_inr: 13000,
      observed_max_fare_inr: 14200,
      violations_count: 5,
      compliance_status: 'BREACH',
    },
    {
      route_code: 'DEL-BLR',
      statutory_band_cap_inr: 21000,
      observed_max_fare_inr: 19800,
      violations_count: 0,
      compliance_status: 'WARNING',
    },
    {
      route_code: 'DEL-CCU',
      statutory_band_cap_inr: 16500,
      observed_max_fare_inr: 14200,
      violations_count: 0,
      compliance_status: 'COMPLIANT',
    },
  ],
};

// ---------------------------------------------------------------------------
// 7. System Health & Telemetry
// ---------------------------------------------------------------------------

export const mockSystemHealth: SystemHealthResponse = {
  status: 'HEALTHY',
  active_scrapers: 8,
  records_ingested_today: 142850,
  last_sync_timestamp: new Date().toISOString(),
  supported_airlines: ['IndiGo (6E)', 'Air India (AI)', 'SpiceJet (SG)', 'Akasa Air (QP)'],
  supported_otas: ['MakeMyTrip', 'EaseMyTrip', 'Ixigo', 'Yatra'],
  latency_ms: 42,
};

// ---------------------------------------------------------------------------
// 8. Crawler Telemetry & Proxy Infrastructure
// ---------------------------------------------------------------------------

export const mockTelemetry: TelemetryResponse = {
  generated_at: new Date().toISOString(),
  system_health: 'HEALTHY',
  schedule_interval_minutes: 5,
  active_workers: 16,
  scrapers: [
    {
      crawler_name: 'easemytrip',
      platform: 'EaseMyTrip Web API',
      status: 'ONLINE',
      uptime_pct: 99.4,
      success_count: 14200,
      error_count: 58,
      error_rate_pct: 0.41,
      last_run_at: new Date(Date.now() - 14000).toISOString(),
      fares_collected: 42800,
      avg_response_time_ms: 340,
      rate_limit_rpm: 60,
      consecutive_failures: 0,
      target_routes: ['DEL-BOM', 'BLR-DEL', 'BOM-GOI', 'DEL-CCU', 'MAA-DEL'],
    },
    {
      crawler_name: 'makemytrip',
      platform: 'MakeMyTrip Mobile Gateway',
      status: 'ONLINE',
      uptime_pct: 98.9,
      success_count: 18450,
      error_count: 142,
      error_rate_pct: 0.76,
      last_run_at: new Date(Date.now() - 22000).toISOString(),
      fares_collected: 58120,
      avg_response_time_ms: 480,
      rate_limit_rpm: 45,
      consecutive_failures: 0,
      target_routes: ['DEL-BOM', 'BLR-DEL', 'BOM-BLR', 'MAA-DEL', 'DEL-HYD', 'BLR-BOM'],
    },
    {
      crawler_name: 'spicejet',
      platform: 'SpiceJet Direct Navitaire API',
      status: 'ONLINE',
      uptime_pct: 97.8,
      success_count: 6120,
      error_count: 75,
      error_rate_pct: 1.21,
      last_run_at: new Date(Date.now() - 45000).toISOString(),
      fares_collected: 18940,
      avg_response_time_ms: 610,
      rate_limit_rpm: 30,
      consecutive_failures: 0,
      target_routes: ['DEL-BOM', 'BOM-GOI', 'BLR-BOM', 'DEL-PNQ'],
    },
    {
      crawler_name: 'amadeus',
      platform: 'Amadeus GDS Enterprise',
      status: 'ONLINE',
      uptime_pct: 99.8,
      success_count: 22300,
      error_count: 22,
      error_rate_pct: 0.10,
      last_run_at: new Date(Date.now() - 8000).toISOString(),
      fares_collected: 74500,
      avg_response_time_ms: 195,
      rate_limit_rpm: 120,
      consecutive_failures: 0,
      target_routes: ['DEL-BOM', 'BLR-DEL', 'BOM-BLR', 'DEL-CCU', 'HYD-DEL', 'MAA-DEL', 'DEL-AMD', 'BOM-GOI'],
    },
  ],
  proxy_pool: {
    total_proxies: 64,
    active_proxies: 61,
    blacklisted_proxies: 3,
    avg_latency_ms: 142,
    p95_latency_ms: 285,
    healthy_pct: 95.3,
    bandwidth_mb_today: 1420,
    top_exit_nodes: [
      { region: 'IN-West (Mumbai)', ip_prefix: '103.21.58.x', latency_ms: 48, status: 'OPTIMAL' },
      { region: 'IN-North (Delhi-NCR)', ip_prefix: '103.45.12.x', latency_ms: 62, status: 'OPTIMAL' },
      { region: 'IN-South (Bengaluru)', ip_prefix: '49.207.180.x', latency_ms: 78, status: 'OPTIMAL' },
      { region: 'AP-Southeast (Singapore)', ip_prefix: '139.180.128.x', latency_ms: 185, status: 'OPTIMAL' },
      { region: 'EU-Central (Frankfurt)', ip_prefix: '159.69.110.x', latency_ms: 275, status: 'DEGRADED' },
    ],
  },
  error_breakdown: {
    total_errors: 297,
    by_type: {
      HTTP_TIMEOUT: 114,
      CAPTCHA_CHALLENGE: 68,
      RATE_LIMIT_EXCEEDED: 54,
      DOM_PARSE_ERROR: 38,
      PROXY_RESET: 23,
    },
    by_crawler: {
      makemytrip: 142,
      spicejet: 75,
      easemytrip: 58,
      amadeus: 22,
    },
    recent_errors: [
      {
        id: 'err-101',
        crawler_name: 'makemytrip',
        error_type: 'HTTP_TIMEOUT',
        route_code: 'DEL-BOM',
        status_code: 504,
        message: 'Gateway timeout after 5000ms waiting for fare cards response',
        occurred_at: new Date(Date.now() - 180000).toISOString(),
        retry_count: 2,
        recovered: true,
      },
      {
        id: 'err-102',
        crawler_name: 'spicejet',
        error_type: 'RATE_LIMIT_EXCEEDED',
        route_code: 'BOM-GOI',
        status_code: 429,
        message: 'Rate limit threshold hit (30 rpm reached), throttled for 15s',
        occurred_at: new Date(Date.now() - 360000).toISOString(),
        retry_count: 1,
        recovered: true,
      },
      {
        id: 'err-103',
        crawler_name: 'easemytrip',
        error_type: 'CAPTCHA_CHALLENGE',
        route_code: 'BLR-DEL',
        status_code: 403,
        message: 'Cloudflare Turnstile challenge intercepted; session refreshed via proxy rotation',
        occurred_at: new Date(Date.now() - 540000).toISOString(),
        retry_count: 3,
        recovered: true,
      },
      {
        id: 'err-104',
        crawler_name: 'makemytrip',
        error_type: 'DOM_PARSE_ERROR',
        route_code: 'DEL-CCU',
        status_code: 200,
        message: 'Flight price card selector missing in dynamic React hydration payload',
        occurred_at: new Date(Date.now() - 720000).toISOString(),
        retry_count: 1,
        recovered: true,
      },
      {
        id: 'err-105',
        crawler_name: 'spicejet',
        error_type: 'PROXY_RESET',
        route_code: 'DEL-PNQ',
        status_code: 502,
        message: 'Connection reset by Frankfurt peer exit node; rerouted to Mumbai node',
        occurred_at: new Date(Date.now() - 900000).toISOString(),
        retry_count: 1,
        recovered: true,
      },
    ],
  },
};

// ---------------------------------------------------------------------------
// 9. Direct Airline vs OTA Arbitrage Opportunities
// ---------------------------------------------------------------------------

export const mockArbitrage: ArbitrageResponse = {
  generated_at: new Date().toISOString(),
  routes_evaluated: 10,
  opportunities_count: 8,
  max_spread_percentage: 9.56,
  total_savings_potential_inr: 3460,
  items: [
    {
      route_code: 'BLR-DEL',
      airline_code: 'AI',
      airline_name: 'Air India',
      airline_direct_fare: 6800,
      ota_name: 'easemytrip',
      ota_fare: 6150,
      spread_inr: 650,
      spread_percentage: 9.56,
      direction: 'OTA_CHEAPER',
      actionable: true,
      flight_number: 'AI-804',
      departure_datetime: new Date(Date.now() + 86400000 * 2).toISOString(),
      sample_timestamp: new Date().toISOString(),
    },
    {
      route_code: 'DEL-BOM',
      airline_code: '6E',
      airline_name: 'IndiGo',
      airline_direct_fare: 5400,
      ota_name: 'makemytrip',
      ota_fare: 4890,
      spread_inr: 510,
      spread_percentage: 9.44,
      direction: 'OTA_CHEAPER',
      actionable: true,
      flight_number: '6E-205',
      departure_datetime: new Date(Date.now() + 86400000 * 1).toISOString(),
      sample_timestamp: new Date().toISOString(),
    },
    {
      route_code: 'BOM-GOI',
      airline_code: 'SG',
      airline_name: 'SpiceJet',
      airline_direct_fare: 3600,
      ota_name: 'amadeus',
      ota_fare: 3950,
      spread_inr: 350,
      spread_percentage: 8.86,
      direction: 'AIRLINE_CHEAPER',
      actionable: true,
      flight_number: 'SG-8169',
      departure_datetime: new Date(Date.now() + 86400000 * 3).toISOString(),
      sample_timestamp: new Date().toISOString(),
    },
    {
      route_code: 'DEL-CCU',
      airline_code: '6E',
      airline_name: 'IndiGo',
      airline_direct_fare: 6200,
      ota_name: 'makemytrip',
      ota_fare: 5680,
      spread_inr: 520,
      spread_percentage: 8.39,
      direction: 'OTA_CHEAPER',
      actionable: true,
      flight_number: '6E-318',
      departure_datetime: new Date(Date.now() + 86400000 * 4).toISOString(),
      sample_timestamp: new Date().toISOString(),
    },
    {
      route_code: 'HYD-DEL',
      airline_code: 'QP',
      airline_name: 'Akasa Air',
      airline_direct_fare: 4900,
      ota_name: 'easemytrip',
      ota_fare: 4500,
      spread_inr: 400,
      spread_percentage: 8.16,
      direction: 'OTA_CHEAPER',
      actionable: true,
      flight_number: 'QP-1342',
      departure_datetime: new Date(Date.now() + 86400000 * 2).toISOString(),
      sample_timestamp: new Date().toISOString(),
    },
    {
      route_code: 'BOM-BLR',
      airline_code: 'AI',
      airline_name: 'Air India',
      airline_direct_fare: 4400,
      ota_name: 'makemytrip',
      ota_fare: 4050,
      spread_inr: 350,
      spread_percentage: 7.95,
      direction: 'OTA_CHEAPER',
      actionable: true,
      flight_number: 'AI-607',
      departure_datetime: new Date(Date.now() + 86400000 * 1).toISOString(),
      sample_timestamp: new Date().toISOString(),
    },
    {
      route_code: 'DEL-BLR',
      airline_code: 'AI',
      airline_name: 'Air India',
      airline_direct_fare: 7100,
      ota_name: 'makemytrip',
      ota_fare: 6550,
      spread_inr: 550,
      spread_percentage: 7.75,
      direction: 'OTA_CHEAPER',
      actionable: true,
      flight_number: 'AI-506',
      departure_datetime: new Date(Date.now() + 86400000 * 5).toISOString(),
      sample_timestamp: new Date().toISOString(),
    },
    {
      route_code: 'BLR-BOM',
      airline_code: 'SG',
      airline_name: 'SpiceJet',
      airline_direct_fare: 3850,
      ota_name: 'makemytrip',
      ota_fare: 4150,
      spread_inr: 300,
      spread_percentage: 7.23,
      direction: 'AIRLINE_CHEAPER',
      actionable: true,
      flight_number: 'SG-302',
      departure_datetime: new Date(Date.now() + 86400000 * 3).toISOString(),
      sample_timestamp: new Date().toISOString(),
    },
  ],
};

// ---------------------------------------------------------------------------
// 10. Real-time Live Fare Stream Initial Seed
// ---------------------------------------------------------------------------

export const mockLiveFares: LiveFareUpdate[] = [
  {
    type: 'fare_update',
    airline_code: '6E',
    airline_name: 'IndiGo',
    flight_number: '6E-205',
    origin: 'DEL',
    destination: 'BOM',
    fare_inr: 4850,
    source: 'easemytrip',
    cabin_class: 'economy',
    departure_datetime: new Date(Date.now() + 86400000 * 2).toISOString(),
    booking_datetime: new Date().toISOString(),
    timestamp: new Date(Date.now() - 2000).toISOString(),
  },
  {
    type: 'fare_update',
    airline_code: 'AI',
    airline_name: 'Air India',
    flight_number: 'AI-804',
    origin: 'BLR',
    destination: 'DEL',
    fare_inr: 6150,
    source: 'makemytrip',
    cabin_class: 'economy',
    departure_datetime: new Date(Date.now() + 86400000 * 3).toISOString(),
    booking_datetime: new Date().toISOString(),
    timestamp: new Date(Date.now() - 5000).toISOString(),
  },
  {
    type: 'fare_update',
    airline_code: 'SG',
    airline_name: 'SpiceJet',
    flight_number: 'SG-8169',
    origin: 'BOM',
    destination: 'GOI',
    fare_inr: 3600,
    source: 'spicejet',
    cabin_class: 'economy',
    departure_datetime: new Date(Date.now() + 86400000 * 1).toISOString(),
    booking_datetime: new Date().toISOString(),
    timestamp: new Date(Date.now() - 9000).toISOString(),
  },
  {
    type: 'fare_update',
    airline_code: 'QP',
    airline_name: 'Akasa Air',
    flight_number: 'QP-1342',
    origin: 'HYD',
    destination: 'DEL',
    fare_inr: 4500,
    source: 'easemytrip',
    cabin_class: 'economy',
    departure_datetime: new Date(Date.now() + 86400000 * 2).toISOString(),
    booking_datetime: new Date().toISOString(),
    timestamp: new Date(Date.now() - 14000).toISOString(),
  },
  {
    type: 'fare_update',
    airline_code: '6E',
    airline_name: 'IndiGo',
    flight_number: '6E-512',
    origin: 'DEL',
    destination: 'BLR',
    fare_inr: 5950,
    source: 'amadeus',
    cabin_class: 'economy',
    departure_datetime: new Date(Date.now() + 86400000 * 4).toISOString(),
    booking_datetime: new Date().toISOString(),
    timestamp: new Date(Date.now() - 18000).toISOString(),
  },
  {
    type: 'fare_update',
    airline_code: 'AI',
    airline_name: 'Air India',
    flight_number: 'AI-607',
    origin: 'BOM',
    destination: 'BLR',
    fare_inr: 4050,
    source: 'makemytrip',
    cabin_class: 'economy',
    departure_datetime: new Date(Date.now() + 86400000 * 1).toISOString(),
    booking_datetime: new Date().toISOString(),
    timestamp: new Date(Date.now() - 24000).toISOString(),
  },
];

// ---------------------------------------------------------------------------
// Combined Snapshot Helper
// ---------------------------------------------------------------------------

export const getMockDashboardSummary = (): DashboardSummaryData => ({
  nationalLatest: mockNationalLatest,
  nationalHistory: mockNationalHistory,
  routes: mockRoutes,
  leadTimeCurve: mockLeadTimeCurve,
  heatmap: mockHeatmap,
  anomalies: mockAnomalies,
  dgcaValidation: mockDGCAValidation,
  systemHealth: mockSystemHealth,
  telemetry: mockTelemetry,
  arbitrage: mockArbitrage,
});
