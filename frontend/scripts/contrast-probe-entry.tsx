/**
 * Verification-only probe page for the tooltip contrast gate.
 *
 * Renders every chart-bearing dashboard tab with mock data on one page so
 * `verify-contrast.ts` can activate each Recharts tooltip in headless
 * Chromium WITHOUT a backend (the real App needs /api/*, which does not
 * exist in CI). Each section carries `data-tab="<key>"` matching the tab
 * keys used by the checker. This file is never part of the production
 * build (vite only bundles `index.html`).
 */
import React, { useEffect } from 'react';
import ReactDOM from 'react-dom/client';
import { OverviewTab } from '../src/components/OverviewTab';
import { RoutesTab } from '../src/components/RoutesTab';
import { EconometricsTab } from '../src/components/EconometricsTab';
import { ElasticityTab } from '../src/components/ElasticityTab';
import { ArbitrageTab } from '../src/components/ArbitrageTab';
import { TelemetryTab } from '../src/components/TelemetryTab';
import { getMockDashboardSummary } from '../src/services/mockData';
import '../src/index.css';

const summary = getMockDashboardSummary();
const noop = (): void => {};

function Section(props: { tab: string; title: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <section
      data-tab={props.tab}
      style={{ borderBottom: '1px solid #262626', padding: '24px', maxWidth: 1100 }}
    >
      <h2 style={{ color: '#fff', fontFamily: 'monospace', fontSize: 14, marginBottom: 16 }}>
        TAB: {props.title}
      </h2>
      {props.children}
    </section>
  );
}

function Probe(): React.JSX.Element {
  useEffect(() => {
    // Signal to the checker that React has mounted. The checker additionally
    // waits for `.recharts-wrapper` nodes, so this is belt-and-braces.
    (window as unknown as { __contrastProbeReady?: boolean }).__contrastProbeReady = true;
  }, []);
  return (
    <div style={{ background: '#0a0a0a', color: '#f5f5f5', fontFamily: 'monospace' }}>
      <Section tab="overview" title="National Overview">
        <OverviewTab
          latest={summary.nationalLatest}
          history={summary.nationalHistory}
          routes={summary.routes}
          anomalies={summary.anomalies}
          onSelectTab={noop}
        />
      </Section>
      <Section tab="routes" title="Trunk Routes (10)">
        <RoutesTab
          routes={summary.routes}
          nationalIndex={summary.nationalLatest.index_value}
          anomalies={summary.anomalies}
        />
      </Section>
      <Section tab="econometrics" title="Econometrics & CPI Gap">
        <EconometricsTab
          indices={summary.econometricIndices}
          cpiDivergence={summary.cpiDivergence}
          priceElasticity={summary.priceElasticity}
        />
      </Section>
      <Section tab="elasticity" title="Booking Elasticity">
        <ElasticityTab leadTimeCurve={summary.leadTimeCurve} heatmap={summary.heatmap} />
      </Section>
      <Section tab="arbitrage" title="Fare Arbitrage">
        <ArbitrageTab arbitrage={summary.arbitrage} onRefresh={noop} />
      </Section>
      <Section tab="telemetry" title="Crawler Telemetry">
        <TelemetryTab telemetry={summary.telemetry} onRefresh={noop} />
      </Section>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Probe />
  </React.StrictMode>
);
