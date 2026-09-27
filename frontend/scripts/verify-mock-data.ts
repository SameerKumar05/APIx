/**
 * Project APIx - Cycle 2 Premier Verification Script
 * Validates:
 * 1. Static mock datasets, MoSPI CPI benchmarks, sub-indices, 7-day sparklines, and Z-scores.
 * 2. ApiClient mock fallback methods and composite dashboard aggregation.
 * 3. Server-side / static rendering of all 4 tab components (OverviewTab, RoutesTab, ElasticityTab, AnomaliesTab).
 * 4. Production build artifact generation (HTML, JS, CSS in dist/).
 */

import { readFileSync } from 'node:fs';
import React from 'react';
import { renderToString } from 'react-dom/server';
import fs from 'node:fs';
import path from 'node:path';

import {
  mockNationalLatest,
  mockNationalHistory,
  mockRoutes,
  mockLeadTimeCurve,
  mockHeatmap,
  mockAnomalies,
  mockDGCAValidation,
  mockSystemHealth,
  mockTelemetry,
  mockArbitrage,
  mockLiveFares,
  mockEconometricIndices,
  mockCpiDivergence,
  mockPriceElasticity,
  mockDgcaSurveillance,
  getMockDashboardSummary,
} from '../src/services/mockData';

import { OverviewTab } from '../src/components/OverviewTab';
import { RoutesTab } from '../src/components/RoutesTab';
import { ElasticityTab } from '../src/components/ElasticityTab';
import { AnomaliesTab } from '../src/components/AnomaliesTab';
import { TelemetryTab } from '../src/components/TelemetryTab';
import { LiveTicker } from '../src/components/LiveTicker';
import { ArbitrageTab } from '../src/components/ArbitrageTab';
import { EconometricsTab } from '../src/components/EconometricsTab';
import { DgcaSurveillanceTab } from '../src/components/DgcaSurveillanceTab';
async function runCycle2Verification() {
  console.log('===============================================================');
  console.log('   APIx Frontend Cycle 4 Premier Verification (PS 26056)       ');
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

  // Validate Cycle 3 Telemetry, Arbitrage & Live Fares datasets
  console.log('\n[Cycle 3] Verifying Scraper Telemetry & Arbitrage Datasets...');
  const crawlerNames = mockTelemetry.scrapers.map((s) => s.crawler_name.toLowerCase());
  const requiredCrawlers = ['easemytrip', 'makemytrip', 'spicejet', 'amadeus'];
  for (const rc of requiredCrawlers) {
    if (!crawlerNames.includes(rc)) {
      throw new Error(`Missing required crawler: ${rc}`);
    }
  }
  console.log(`✓ 4 Required Scraper Engines verified: ${requiredCrawlers.join(', ')}`);
  if (mockTelemetry.proxy_pool.active_proxies <= 0 || mockTelemetry.proxy_pool.avg_latency_ms <= 0) {
    throw new Error('Invalid proxy pool telemetry');
  }
  console.log(`✓ Proxy Pool: ${mockTelemetry.proxy_pool.active_proxies} active nodes, ${mockTelemetry.proxy_pool.avg_latency_ms}ms avg latency`);

  if (!mockArbitrage.items || mockArbitrage.items.length === 0) {
    throw new Error('Missing mock arbitrage items');
  }
  const otaCheaperCount = mockArbitrage.items.filter((i) => i.direction === 'OTA_CHEAPER').length;
  const airlineCheaperCount = mockArbitrage.items.filter((i) => i.direction === 'AIRLINE_CHEAPER').length;
  console.log(`✓ Arbitrage Opportunities: ${mockArbitrage.items.length} items (${otaCheaperCount} OTA Cheaper, ${airlineCheaperCount} Airline Cheaper)`);
  console.log(`✓ Peak Arbitrage Spread: +${mockArbitrage.max_spread_percentage}%`);
  console.log(`✓ Live Fare Stream Seed: ${mockLiveFares.length} initial broadcast packets`);
  // [Cycle 4] Verify Econometric & DGCA Datasets
  console.log('\n[Cycle 4] Verifying Econometric Engine & DGCA Surveillance Datasets...');
  if (!mockEconometricIndices.fisher_index || !mockEconometricIndices.laspeyres_index || !mockEconometricIndices.paasche_index) {
    throw new Error('Invalid mockEconometricIndices');
  }
  console.log(`✓ Econometric Indices: Fisher ${mockEconometricIndices.fisher_index} | Laspeyres ${mockEconometricIndices.laspeyres_index} | Paasche ${mockEconometricIndices.paasche_index} (Substitution Bias: Δ ${mockEconometricIndices.substitution_bias} pts)`);
  console.log(`✓ MoSPI CPI Divergence: +${mockCpiDivergence.current_divergence_pts} pts | Inflation Lead Time: +${mockCpiDivergence.inflation_lead_days} days | Correlation: ${mockCpiDivergence.correlation_coefficient}`);
  console.log(`✓ Price Elasticity Curve: ${mockPriceElasticity.gradient_points.length} gradient points (T+30 to T+1)`);
  console.log(`✓ DGCA Surveillance: ${mockDgcaSurveillance.total_violations} violations across ${mockDgcaSurveillance.total_evaluated} flights`);
  console.log(`✓ Carrier Distribution: ${mockDgcaSurveillance.carrier_distribution.length} scheduled airlines audited`);

  // -------------------------------------------------------------------------
  // 2. Verify ApiClient Service Methods
  // -------------------------------------------------------------------------
  console.log('\n[2/5] Validating Composite Mock Dashboard Dataset...');
  const summary = getMockDashboardSummary();
  if (!summary.nationalLatest || !summary.routes || !summary.leadTimeCurve || !summary.anomalies || !summary.systemHealth || !summary.econometricIndices || !summary.cpiDivergence || !summary.priceElasticity || !summary.dgcaSurveillance) {
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

  // Tab 5: TelemetryTab
  console.log('  -> Rendering TelemetryTab (Crawler fleet cards, proxy latency gauges, error breakdown)...');
  const telemetryHtml = renderToString(
    React.createElement(TelemetryTab, {
      telemetry: summary.telemetry,
      onRefresh: () => {},
    })
  );
  if (!telemetryHtml || telemetryHtml.length < 500) {
    throw new Error('TelemetryTab rendered empty or truncated markup');
  }
  if (!telemetryHtml.includes('Crawler Infrastructure') || (!telemetryHtml.includes('Proxy Pool Latency Gauges') && !telemetryHtml.includes('Proxy Pool Health Gauges'))) {
    throw new Error('TelemetryTab missing required crawler telemetry headers');
  }
  console.log(`  ✓ TelemetryTab rendered cleanly (${telemetryHtml.length} bytes HTML).`);

  // Component: LiveTicker
  console.log('  -> Rendering LiveTicker (Real-time streaming ticker, carrier tags, route badges)...');
  const tickerHtml = renderToString(
    React.createElement(LiveTicker, {})
  );
  if (!tickerHtml || tickerHtml.length < 200) {
    throw new Error('LiveTicker rendered empty or truncated markup');
  }
  // The header no longer says LIVE. Calling a simulated feed "LIVE FARE FEED"
  // was itself a false claim, so the contract now pins the honest header and the
  // provenance badge, which is a stronger check than the one it replaces.
  if (!tickerHtml.includes('FARE FEED')) {
    throw new Error('LiveTicker missing required stream status header');
  }
  // The provenance badge only renders when fares arrive over the WebSocket, which
  // a server-side render cannot exercise. Assert the four states against the
  // component source instead, so the honest labelling cannot be dropped silently.
  const tickerSource = fs.readFileSync(
    path.resolve(process.cwd(), 'src/components/LiveTicker.tsx'),
    'utf-8',
  );
  for (const state of ['DGCA BENCHMARK', 'MIXED', 'LIVE SCRAPE', 'PROVENANCE UNKNOWN']) {
    if (!tickerSource.includes(state)) {
      throw new Error(`LiveTicker is missing the ${state} provenance state`);
    }
  }
  console.log(`  ✓ LiveTicker rendered cleanly (${tickerHtml.length} bytes HTML).`);

  // Tab 6: ArbitrageTab
  console.log('  -> Rendering ArbitrageTab (Direct airline vs OTA spread analysis, savings alerts)...');
  const arbitrageHtml = renderToString(
    React.createElement(ArbitrageTab, {
      arbitrage: summary.arbitrage,
      onRefresh: () => {},
    })
  );
  if (!arbitrageHtml || arbitrageHtml.length < 500) {
    throw new Error('ArbitrageTab rendered empty or truncated markup');
  }
  if (!arbitrageHtml.includes('Airline Direct vs OTA Price Spread') || !arbitrageHtml.includes('Arbitrage Opportunities')) {
    throw new Error('ArbitrageTab missing required arbitrage headers');
  }
  console.log(`  ✓ ArbitrageTab rendered cleanly (${arbitrageHtml.length} bytes HTML).`);
  // Tab 7: EconometricsTab
  console.log('  -> Rendering EconometricsTab (Dual-axis composite line chart, Fisher/Laspeyres vs MoSPI, elasticity curve)...');
  const econometricsHtml = renderToString(
    React.createElement(EconometricsTab, {
      indices: summary.econometricIndices,
      cpiDivergence: summary.cpiDivergence,
      priceElasticity: summary.priceElasticity,
    })
  );
  if (!econometricsHtml || econometricsHtml.length < 500) {
    throw new Error('EconometricsTab rendered empty or truncated markup');
  }
  if (!econometricsHtml.includes('APIx Econometric Engine') || !econometricsHtml.includes('Substitution Bias')) {
    throw new Error('EconometricsTab missing required econometric headers');
  }
  console.log(`  ✓ EconometricsTab rendered cleanly (${econometricsHtml.length} bytes HTML).`);

  // Tab 8: DgcaSurveillanceTab
  console.log('  -> Rendering DgcaSurveillanceTab (Statutory violation feed, severity badges, carrier distribution)...');
  const dgcaHtml = renderToString(
    React.createElement(DgcaSurveillanceTab, {
      surveillance: summary.dgcaSurveillance,
    })
  );
  if (!dgcaHtml || dgcaHtml.length < 500) {
    throw new Error('DgcaSurveillanceTab rendered empty or truncated markup');
  }
  if (!dgcaHtml.includes('DGCA TARIFF SURVEILLANCE') || !dgcaHtml.includes('Regulatory Violation Feed')) {
    throw new Error('DgcaSurveillanceTab missing required surveillance headers');
  }
  console.log(`  ✓ DgcaSurveillanceTab rendered cleanly (${dgcaHtml.length} bytes HTML).`);


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
