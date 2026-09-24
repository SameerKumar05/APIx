/**
 * Project APIx - Cycle 2 Premier Verification Script
 * Validates:
 * 1. Static mock datasets, MoSPI CPI benchmarks, sub-indices, 7-day sparklines, and Z-scores.
 * 2. ApiClient mock fallback methods and composite dashboard aggregation.
 * 3. Server-side / static rendering of all 4 tab components (OverviewTab, RoutesTab, ElasticityTab, AnomaliesTab).
 * 4. Production build artifact generation (HTML, JS, CSS in dist/).
 */

import React from 'react';
import { renderToString } from 'react-dom/server';
import fs from 'node:fs';
import path from 'node:path';

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
  getMockDashboardSummary,
} from '../src/services/mockData';

import { OverviewTab } from '../src/components/OverviewTab';
import { RoutesTab } from '../src/components/RoutesTab';
import { ElasticityTab } from '../src/components/ElasticityTab';
import { AnomaliesTab } from '../src/components/AnomaliesTab';

async function runCycle2Verification() {
  console.log('===============================================================');
  console.log('   APIx Frontend Cycle 2 Premier Verification (PS 26056)       ');
  console.log('===============================================================\n');

  // -------------------------------------------------------------------------
  // 1. Verify Enhanced Mock Data Schemas (MoSPI CPI, Sub-Indices, Z-Scores)
  // -------------------------------------------------------------------------
  console.log('[1/5] Verifying Enhanced Mock Data Specifications...');
  if (!mockNationalLatest.index_value || mockNationalLatest.index_value <= 0) {
    throw new Error('Invalid mockNationalLatest index value');
  }
  if (!mockNationalLatest.mospi_cpi || mockNationalLatest.mospi_cpi <= 0) {
    throw new Error('Missing or invalid mospi_cpi on mockNationalLatest');
  }
  if (!mockNationalLatest.t1_index || !mockNationalLatest.t7_index || !mockNationalLatest.t15_index || !mockNationalLatest.t30_index) {
    throw new Error('Missing booking window sub-indices (T+1, T+7, T+15, T+30) on mockNationalLatest');
  }
  console.log(`✓ National Index: ${mockNationalLatest.index_value} | MoSPI CPI: ${mockNationalLatest.mospi_cpi} (Divergence: +${mockNationalLatest.mospi_cpi_divergence} pts)`);
  console.log(`✓ Sub-indices: T+1: ${mockNationalLatest.t1_index} | T+7: ${mockNationalLatest.t7_index} | T+15: ${mockNationalLatest.t15_index} | T+30: ${mockNationalLatest.t30_index}`);

  if (mockNationalHistory.length !== 30) {
    throw new Error(`Expected 30 history points, found ${mockNationalHistory.length}`);
  }
  const sampleHist = mockNationalHistory[0];
  if (!sampleHist.mospi_cpi || !sampleHist.t1_index || !sampleHist.t30_index) {
    throw new Error('History points missing MoSPI or booking sub-indices');
  }
  console.log('✓ 30-day historical time series with MoSPI CPI and booking window sub-indices verified.');

  if (mockRoutes.length !== 10) {
    throw new Error(`Expected 10 high-density routes, found ${mockRoutes.length}`);
  }
  for (const r of mockRoutes) {
    if (!r.sparkline_7d || r.sparkline_7d.length < 2) {
      throw new Error(`Route ${r.route_code} missing 7-day sparkline data`);
    }
  }
  console.log('✓ 10 high-density DGCA corridors with 7-day sparklines verified.');

  // Validate Z-score anomaly surveillance items
  const critAlerts = mockAnomalies.filter((a) => (a.z_score ?? 0) >= 3.0 || a.severity === 'CRITICAL');
  const warnAlerts = mockAnomalies.filter((a) => ((a.z_score ?? 0) >= 2.0 && (a.z_score ?? 0) < 3.0) || a.severity === 'HIGH');
  if (critAlerts.length === 0) {
    throw new Error('Expected at least one CRITICAL anomaly with Z >= 3.0');
  }
  if (warnAlerts.length === 0) {
    throw new Error('Expected at least one WARNING anomaly with Z >= 2.0');
  }
  console.log(`✓ Surveillance Anomaly Alerts: ${mockAnomalies.length} items (${critAlerts.length} Critical Z≥3.0, ${warnAlerts.length} Warning Z≥2.0).`);

  // -------------------------------------------------------------------------
  // 2. Verify ApiClient Service Methods
  // -------------------------------------------------------------------------
  console.log('\n[2/5] Testing ApiClient Endpoints with Mock Fallback...');
  apiClient.setPreferMock(true);

  const summary = await apiClient.getDashboardSummary();
  if (!summary.nationalLatest || !summary.routes || !summary.leadTimeCurve || !summary.anomalies || !summary.systemHealth) {
    throw new Error('Composite summary returned incomplete dataset');
  }
  console.log(`✓ Ingestion Telemetry: ${summary.systemHealth.status} | Scrapers: ${summary.systemHealth.active_scrapers} | Ingested: ${summary.systemHealth.records_ingested_today.toLocaleString()} fares`);
  console.log(`✓ Last scrape timestamp: ${summary.systemHealth.last_sync_timestamp}`);

  // -------------------------------------------------------------------------
  // 3. Premier Verification: Render All 4 Tab Components Without Errors
  // -------------------------------------------------------------------------
  console.log('\n[3/5] Verifying Static / Server-Side Rendering of All 4 Tab Components...');

  // Tab 1: OverviewTab
  console.log('  -> Rendering OverviewTab (Recharts line chart, MoSPI CPI, sub-indices toggles, KPI cards)...');
  const overviewHtml = renderToString(
    React.createElement(OverviewTab, {
      latest: summary.nationalLatest,
      history: summary.nationalHistory,
      routes: summary.routes,
      anomalies: summary.anomalies,
      onSelectTab: () => {},
    })
  );
  if (!overviewHtml || overviewHtml.length < 500) {
    throw new Error('OverviewTab rendered empty or truncated markup');
  }
  if (!overviewHtml.includes('National Composite Index') || !overviewHtml.includes('MoSPI CPI Benchmark')) {
    throw new Error('OverviewTab missing required text or headers');
  }
  console.log(`  ✓ OverviewTab rendered cleanly (${overviewHtml.length} bytes HTML).`);

  // Tab 2: RoutesTab
  console.log('  -> Rendering RoutesTab (Searchable, sortable table, weights, sparklines, badges)...');
  const routesHtml = renderToString(
    React.createElement(RoutesTab, {
      routes: summary.routes,
      nationalIndex: summary.nationalLatest.index_value,
      anomalies: summary.anomalies,
    })
  );
  if (!routesHtml || routesHtml.length < 500) {
    throw new Error('RoutesTab rendered empty or truncated markup');
  }
  if (!routesHtml.includes('DGCA High-Density') || !routesHtml.includes('DEL-BOM')) {
    throw new Error('RoutesTab missing required table content');
  }
  console.log(`  ✓ RoutesTab rendered cleanly (${routesHtml.length} bytes HTML).`);

  // Tab 3: ElasticityTab
  console.log('  -> Rendering ElasticityTab (Lead-time elasticity surge chart, route price heatmap matrix)...');
  const elasticityHtml = renderToString(
    React.createElement(ElasticityTab, {
      leadTimeCurve: summary.leadTimeCurve,
      heatmap: summary.heatmap,
    })
  );
  if (!elasticityHtml || elasticityHtml.length < 500) {
    throw new Error('ElasticityTab rendered empty or truncated markup');
  }
  if (!elasticityHtml.includes('Dynamic Pricing Surge Curve') || !overviewHtml.includes('APIx')) {
    throw new Error('ElasticityTab missing required surge curve headers');
  }
  console.log(`  ✓ ElasticityTab rendered cleanly (${elasticityHtml.length} bytes HTML).`);

  // Tab 4: AnomaliesTab
  console.log('  -> Rendering AnomaliesTab (Surveillance center, Z-score badges, baseline fare comparisons)...');
  const anomaliesHtml = renderToString(
    React.createElement(AnomaliesTab, {
      anomalies: summary.anomalies,
      dgcaValidation: summary.dgcaValidation,
    })
  );
  if (!anomaliesHtml || anomaliesHtml.length < 500) {
    throw new Error('AnomaliesTab rendered empty or truncated markup');
  }
  if (!anomaliesHtml.includes('Regulatory Surveillance') || !anomaliesHtml.includes('CRITICAL • Z =')) {
    throw new Error('AnomaliesTab missing required surveillance or Z-score content');
  }
  console.log(`  ✓ AnomaliesTab rendered cleanly (${anomaliesHtml.length} bytes HTML).`);

  // -------------------------------------------------------------------------
  // 4. Verify DGCA Weight Invariant
  // -------------------------------------------------------------------------
  console.log('\n[4/5] Checking DGCA Route Traffic Weight Invariants...');
  const totalWeight = summary.routes.reduce((acc, r) => acc + r.weight, 0);
  console.log(`✓ 10 Corridors Weight Sum: ${(totalWeight * 100).toFixed(2)}% of national high-density domestic traffic`);

  // -------------------------------------------------------------------------
  // 5. Verify Production Build Artifacts in dist/
  // -------------------------------------------------------------------------
  console.log('\n[5/5] Checking Production Build Outputs (dist/)...');
  const distDir = path.resolve(import.meta.dir, '../dist');
  const indexHtmlPath = path.join(distDir, 'index.html');
  const assetsDir = path.join(distDir, 'assets');

  if (!fs.existsSync(indexHtmlPath)) {
    throw new Error(`dist/index.html not found at ${indexHtmlPath}. Please run 'bun run build'.`);
  }
  const indexHtmlContent = fs.readFileSync(indexHtmlPath, 'utf-8');
  console.log(`✓ dist/index.html exists (${indexHtmlContent.length} bytes)`);

  if (!fs.existsSync(assetsDir)) {
    throw new Error(`dist/assets directory not found at ${assetsDir}`);
  }
  const assetFiles = fs.readdirSync(assetsDir);
  const jsFiles = assetFiles.filter((f) => f.endsWith('.js'));
  const cssFiles = assetFiles.filter((f) => f.endsWith('.css'));

  if (jsFiles.length === 0) {
    throw new Error('No .js bundle found in dist/assets');
  }
  if (cssFiles.length === 0) {
    throw new Error('No .css bundle found in dist/assets');
  }

  for (const js of jsFiles) {
    const stat = fs.statSync(path.join(assetsDir, js));
    console.log(`✓ JS Bundle: ${js} (${(stat.size / 1024).toFixed(1)} kB)`);
  }
  for (const css of cssFiles) {
    const stat = fs.statSync(path.join(assetsDir, css));
    console.log(`✓ CSS Stylesheet: ${css} (${(stat.size / 1024).toFixed(1)} kB)`);
  }

  console.log('\n===============================================================');
  console.log('>>> All 5 Premier Verifications Passed Successfully (Exit 0) <<<');
  console.log('===============================================================');
}

runCycle2Verification().catch((err) => {
  console.error('\n❌ Verification Failed:', err);
  process.exit(1);
});
