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
};

export const generateMockNationalHistory = (days: number = 30): NationalIndexPoint[] => {
  const points: NationalIndexPoint[] = [];
  const baseValue = 108.5;
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

    points.push({
      timestamp: d.toISOString(),
      index_value,
      moving_avg_7d,
      sample_size: Math.floor(42000 + Math.random() * 8000),
      base_period: '2026-01=100',
      confidence_interval_lower: Number((index_value - 0.95).toFixed(2)),
      confidence_interval_upper: Number((index_value + 0.95).toFixed(2)),
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
    deviation_percent: 92.2,
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
    deviation_percent: 121.8,
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
    deviation_percent: 59.2,
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
    deviation_percent: 40.7,
    status: 'ACKNOWLEDGED',
    booking_window: 'T+7',
    description: 'High price variance (>₹3,200) observed between airline direct portal and OTA listings.',
    recommended_action: 'Monitor aggregator scrape feeds for cache latency or convenience fee bundling.',
  },
  {
    id: 'ALT-2026-9045',
    route_code: 'BLR-HYD',
    airline_code: '6E',
    flight_number: '6E-441',
    detected_at: new Date(Date.now() - 420 * 60 * 1000).toISOString(),
    anomaly_type: 'FLASH_DROP',
    severity: 'LOW',
    observed_fare_inr: 2100,
    expected_fare_inr: 3400,
    deviation_percent: -38.2,
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
});
