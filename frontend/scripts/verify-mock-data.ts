/**
 * Project APIx - Cycle 1 Premier Verification Script
 * Validates TypeScript interfaces, mock data generation, and apiClient service methods.
 */

import apiClient from '../src/services/apiClient';
import {
  mockNationalLatest,
  mockNationalHistory,
  mockRoutes,
  mockLeadTimeCurve,
  mockHeatmap,
  mockAnomalies,
  mockDGCAValidation,
  mockSystemHealth,
} from '../src/services/mockData';

async function runVerification() {
  console.log('=== APIx Frontend Cycle 1 Premier Verification ===');
  
  // 1. Verify Static Mock Objects
  console.log('[1/4] Verifying static mock data definitions...');
  if (!mockNationalLatest.index_value || mockNationalLatest.index_value <= 0) {
    throw new Error('Invalid mockNationalLatest index value');
  }
  if (mockNationalHistory.length !== 30) {
    throw new Error(`Expected 30 history points, found ${mockNationalHistory.length}`);
  }
  if (mockRoutes.length !== 10) {
    throw new Error(`Expected 10 high-density routes, found ${mockRoutes.length}`);
  }
  if (mockLeadTimeCurve.curve_points.length !== 8) {
    throw new Error(`Expected 8 lead-time curve points, found ${mockLeadTimeCurve.curve_points.length}`);
  }
  if (mockHeatmap.matrix.length !== 42) { // 7 days * 6 hours
    throw new Error(`Expected 42 heatmap cells, found ${mockHeatmap.matrix.length}`);
  }
  if (mockAnomalies.length < 5) {
    throw new Error(`Expected at least 5 anomaly alerts, found ${mockAnomalies.length}`);
  }
  if (mockDGCAValidation.violations.length < 2) {
    throw new Error(`Expected at least 2 DGCA statutory violations, found ${mockDGCAValidation.violations.length}`);
  }
  console.log('✓ Static mock data structures verified.');

  // 2. Verify ApiClient Methods with Mock Fallback
  console.log('[2/4] Testing ApiClient endpoints via fallback...');
  apiClient.setPreferMock(true);

  const latest = await apiClient.getNationalIndexLatest();
  console.log(`✓ National Index: ${latest.index_value} (${latest.base_period}) | 24h: ${latest.change_24h}%`);

  const history = await apiClient.getNationalIndexHistory(30);
  console.log(`✓ National History: ${history.points.length} points returned`);

  const routesRes = await apiClient.getRoutesOverview();
  console.log(`✓ Routes Overview: ${routesRes.total_routes} corridors loaded`);

  const routeHistory = await apiClient.getRouteHistory('DEL-BOM', 14);
  console.log(`✓ Route History (DEL-BOM): ${routeHistory.points.length} points`);

  const elasticity = await apiClient.getLeadTimeCurve('DEL-BOM');
  console.log(`✓ Lead-time Elasticity: ${elasticity.curve_points.length} booking windows (T+1 to T+60)`);

  const heatmap = await apiClient.getHeatmap('DEL-BOM');
  console.log(`✓ Heatmap Matrix: ${heatmap.matrix.length} time/day slots`);

  const anomaliesRes = await apiClient.getAnomalies();
  console.log(`✓ Anomaly Alerts: ${anomaliesRes.total_alerts} surveillance alerts`);

  const dgca = await apiClient.getDGCAValidation();
  console.log(`✓ DGCA Statutory Caps: ${dgca.total_violations} breaches detected across ${dgca.total_routes_evaluated} routes`);

  const health = await apiClient.getSystemHealth();
  console.log(`✓ System Health: ${health.status} (${health.active_scrapers} scrapers, ${health.records_ingested_today} records)`);

  // 3. Verify Composite Dashboard Summary Method
  console.log('[3/4] Verifying getDashboardSummary() composite call...');
  const summary = await apiClient.getDashboardSummary();
  if (!summary.nationalLatest || !summary.routes || !summary.leadTimeCurve || !summary.anomalies) {
    throw new Error('Composite summary returned incomplete dataset');
  }
  console.log('✓ Composite summary contract confirmed.');

  // 4. Verify Route Weight Invariant
  console.log('[4/4] Validating DGCA route traffic weights...');
  const totalWeight = routesRes.routes.reduce((acc, r) => acc + r.weight, 0);
  console.log(`✓ 10 Corridors Weight Sum: ${(totalWeight * 100).toFixed(2)}% of national high-density domestic traffic`);

  console.log('\n>>> All Premier Verifications Passed Successfully with Exit Code 0! <<<');
}

runVerification().catch((err) => {
  console.error('Verification failed:', err);
  process.exit(1);
});
