import React, { useState, useEffect, useCallback } from 'react';
import {
  ActiveTab,
  DashboardSummaryData,
} from './types/api';
import apiClient, { ApiError } from './services/apiClient';
import { ApiErrorBoundary } from './components/ApiErrorBoundary';
import { OverviewTab } from './components/OverviewTab';
import { RoutesTab } from './components/RoutesTab';
import { ElasticityTab } from './components/ElasticityTab';
import { AnomaliesTab } from './components/AnomaliesTab';
import { TelemetryTab } from './components/TelemetryTab';
import { LiveTicker } from './components/LiveTicker';
import { ArbitrageTab } from './components/ArbitrageTab';
import { EconometricsTab } from './components/EconometricsTab';
import { DgcaSurveillanceTab } from './components/DgcaSurveillanceTab';
import {
  Plane,
  Activity,
  RefreshCw,
  Clock,
  ShieldCheck,
  ShieldAlert,
  Server,
  Scale,
  TrendingUp,
} from 'lucide-react';
type DashboardState = {kind:"loading"} | {kind:"live"; data:DashboardSummaryData; fetchedAt:Date} | {kind:"error"; error:ApiError; retry:()=>void};

function describeApiError(error: ApiError): string {
  switch (error.kind) {
    case "http":
      return `Live API request failed (HTTP ${error.status}) at ${error.endpoint}.`;
    case "network":
      return `Network error reaching ${error.endpoint}. Check backend connectivity.`;
    case "timeout":
      return `Live API request timed out at ${error.endpoint}.`;
    case "parse":
      return `Invalid response from ${error.endpoint}.`;
  }
}

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');
  const [state, setState] = useState<DashboardState>({kind:"loading"});
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [lastRefreshed, setLastRefreshed] = useState<Date>(new Date());

  const loadData = useCallback(async (isManualRefresh: boolean = false) => {
    if (isManualRefresh) {
      setRefreshing(true);
    } else {
      setState({kind:"loading"});
    }

    try {
      const summary = await apiClient.getDashboardSummary();
      setState({kind:"live", data: summary, fetchedAt: new Date()});
      setLastRefreshed(new Date());
    } catch (err) {
      const error = err as ApiError;
      setState({kind:"error", error, retry: () => { void loadData(true); }});
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();

    // Background refresh every 60 seconds
    const interval = setInterval(() => {
      loadData(false);
    }, 60000);

    return () => {
      clearInterval(interval);
    };
  }, [loadData]);

  const liveData = state.kind === "live" ? state.data : null;
  const healthStatus = liveData?.systemHealth.status ?? null;
  const statusLabel = state.kind === "loading" ? "LOADING" : state.kind === "error" ? "UNREACHABLE" : healthStatus;
  const statusDot =
    state.kind === "error" ? "bg-red-400" : healthStatus === "DEGRADED" ? "bg-amber-400" : liveData ? "bg-emerald-400" : "bg-neutral-500";
  const sourceLabel = state.kind === "error" ? "No live data" : state.kind === "loading" ? "Connecting" : "Live API";
  const criticalAlertsCount = liveData?.anomalies.filter((a) => a.severity === 'CRITICAL').length || 0;
  const dgcaViolationsCount = liveData?.dgcaSurveillance?.total_violations || 0;
  const arbitrageSpreadsCount = liveData?.arbitrage?.opportunities_count || 0;
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 flex flex-col font-sans selection:bg-neutral-800 selection:text-white">
      {/* Vercel Restrained Masthead */}
      <header className="sticky top-0 z-50 bg-neutral-950/95 backdrop-blur-md border-b border-neutral-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14 gap-4">
            {/* Sharp Monochrome Wordmark & Subtitle */}
            <div className="flex items-center gap-3 min-w-0">
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className="text-base font-bold tracking-tight text-white font-mono">
                  API<span className="text-neutral-400">x</span>
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-neutral-900 text-neutral-400 border border-neutral-800">
                  PS 26056
                </span>
              </div>
              <div className="hidden md:block h-3.5 w-px bg-neutral-800 flex-shrink-0" />
              <p className="text-xs text-neutral-400 truncate hidden md:block">
                Real-time Airfare Price Index for India
                <span className="text-neutral-600 mx-1.5">•</span>
                <span className="text-neutral-500">MoSPI CPI Augmentation &amp; DGCA Oversight</span>
              </p>
            </div>

            {/* Live Pipeline Telemetry & Quiet Controls */}
            <div className="flex items-center gap-2.5 flex-shrink-0">
              {/* Ingestion Run Status - Quiet Evidence */}
              <div
                className="hidden lg:flex items-center gap-2.5 px-2.5 py-1 rounded-md bg-neutral-900/60 border border-neutral-800 text-xs font-mono text-neutral-400"
                title="Ingestion Pipeline Run Status • Continuous Scraper Feeds"
              >
                <div className="flex items-center gap-1.5 text-neutral-300">
                  <span className={`inline-block h-1.5 w-1.5 rounded-full ${statusDot}`} />
                  <span className="text-[11px] font-medium tracking-wide">
                    {statusLabel}
                  </span>
                </div>

                <span className="text-neutral-700">/</span>

                <div className="flex items-center gap-1 text-[11px] text-neutral-400">
                  <span className="text-neutral-500">Scrapers:</span>
                  <span className="font-mono text-neutral-200 tabular-nums">
                      {liveData ? liveData.systemHealth.active_scrapers : "—"}
                  </span>
                </div>

                <span className="text-neutral-700">/</span>

                <div className="flex items-center gap-1 text-[11px] text-neutral-500">
                  <span>Sync:</span>
                  <span className="text-neutral-300 tabular-nums">
                    {liveData?.systemHealth.last_sync_timestamp
                      ? new Date(liveData.systemHealth.last_sync_timestamp).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                        })
                      : "—"}
                  </span>
                </div>
              </div>

              {/* Live Source Indicator */}
              <div
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-mono border border-neutral-800 bg-neutral-900/60 text-neutral-300"
                title={state.kind === "error" ? "Backend API unreachable" : "Live Backend API"}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${statusDot}`} />
                <span className="text-neutral-500 hidden sm:inline">Source:</span>
                <span className="font-medium">{sourceLabel}</span>
              </div>

              {/* Refresh Button */}
              <button
                onClick={() => loadData(true)}
                disabled={refreshing}
                className="p-1.5 rounded-md bg-neutral-900/60 border border-neutral-800 text-neutral-400 hover:text-white hover:bg-neutral-800 transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-neutral-950 disabled:opacity-50"
                title={`Last updated: ${lastRefreshed.toLocaleTimeString()}`}
              >
                <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'motion-safe:animate-spin text-neutral-200' : ''}`} />
              </button>
            </div>
          </div>

          {/* Crisp Segmented Tab Controls */}
          <div className="flex items-center space-x-1 border-t border-neutral-800 py-1.5 overflow-x-auto scrollbar-none">
            <button
              onClick={() => setActiveTab('overview')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950 ${
                activeTab === 'overview'
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-900/60'
              }`}
            >
              <Activity className="w-3.5 h-3.5" />
              <span>National Overview</span>
            </button>

            <button
              onClick={() => setActiveTab('econometrics')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950 ${
                activeTab === 'econometrics'
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-900/60'
              }`}
            >
              <TrendingUp className="w-3.5 h-3.5" />
              <span>Econometrics &amp; CPI Gap</span>
            </button>

            <button
              onClick={() => setActiveTab('dgca')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950 ${
                activeTab === 'dgca'
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-900/60'
              }`}
            >
              <ShieldAlert className="w-3.5 h-3.5" />
              <span>DGCA Surveillance</span>
              {dgcaViolationsCount > 0 && (
                <span className="ml-1 px-1.5 py-0.2 rounded text-[10px] font-mono tabular-nums font-semibold bg-rose-950/80 text-rose-300 border border-rose-800/80">
                  {dgcaViolationsCount}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('routes')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950 ${
                activeTab === 'routes'
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-900/60'
              }`}
            >
              <Plane className="w-3.5 h-3.5" />
              <span>Trunk Routes (10)</span>
            </button>

            <button
              onClick={() => setActiveTab('elasticity')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950 ${
                activeTab === 'elasticity'
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-900/60'
              }`}
            >
              <Clock className="w-3.5 h-3.5" />
              <span>Booking Elasticity</span>
            </button>

            <button
              onClick={() => setActiveTab('anomalies')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950 ${
                activeTab === 'anomalies'
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-900/60'
              }`}
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Anomaly Detector</span>
              {criticalAlertsCount > 0 && (
                <span className="ml-1 px-1.5 py-0.2 rounded text-[10px] font-mono tabular-nums font-semibold bg-amber-950/80 text-amber-300 border border-amber-800/80">
                  {criticalAlertsCount}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('telemetry')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950 ${
                activeTab === 'telemetry'
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-900/60'
              }`}
            >
              <Server className="w-3.5 h-3.5" />
              <span>Crawler Telemetry</span>
              {liveData?.telemetry && (
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 ml-0.5"></span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('arbitrage')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950 ${
                activeTab === 'arbitrage'
                  ? 'bg-neutral-800 text-white'
                  : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-900/60'
              }`}
            >
              <Scale className="w-3.5 h-3.5" />
              <span>Fare Arbitrage</span>
              {arbitrageSpreadsCount > 0 && (
                <span className="ml-1 px-1.5 py-0.2 rounded text-[10px] font-mono tabular-nums font-semibold bg-neutral-800 text-neutral-300 border border-neutral-700">
                  {arbitrageSpreadsCount}
                </span>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <ApiErrorBoundary onRetry={() => loadData(true)}>
        {state.kind === "loading" ? (
          <div className="flex flex-col items-center justify-center min-h-[400px] gap-3">
            <RefreshCw className="w-6 h-6 text-neutral-400 motion-safe:animate-spin" />
            <p className="text-xs text-neutral-500 font-mono">
              Aggregating live flight fares & calculating weighted median indices...
            </p>
          </div>
        ) : state.kind === "error" ? (
          <div className="text-center py-16 bg-neutral-950 rounded-lg border border-neutral-800">
            <p className="text-sm text-neutral-300">{describeApiError(state.error)}</p>
            <button
              onClick={state.retry}
              className="mt-4 px-3.5 py-1.5 bg-neutral-100 hover:bg-white text-neutral-950 text-xs font-medium rounded-md transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-neutral-950"
            >
              Retry Connection
            </button>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Real-time Streaming Fare Ticker */}
            <LiveTicker
              onSelectRoute={() => {
                setActiveTab('routes');
              }}
            />

            {/* Active Tab Views */}
            {activeTab === 'overview' && (
              <OverviewTab
                latest={state.data.nationalLatest}
                history={state.data.nationalHistory}
                routes={state.data.routes}
                anomalies={state.data.anomalies}
                onSelectTab={setActiveTab}
              />
            )}
            {activeTab === 'econometrics' && (
              <EconometricsTab
                indices={state.data.econometricIndices}
                cpiDivergence={state.data.cpiDivergence}
                priceElasticity={state.data.priceElasticity}
              />
            )}

            {activeTab === 'dgca' && (
              <DgcaSurveillanceTab
                surveillance={state.data.dgcaSurveillance}
              />
            )}


            {activeTab === 'routes' && (
              <RoutesTab
                routes={state.data.routes}
                nationalIndex={state.data.nationalLatest.index_value}
                anomalies={state.data.anomalies}
              />
            )}

            {activeTab === 'elasticity' && (
              <ElasticityTab
                leadTimeCurve={state.data.leadTimeCurve}
                heatmap={state.data.heatmap}
                sectorHeatmap={state.data.sectorHeatmap}
              />
            )}
            {activeTab === 'anomalies' && (
              <AnomaliesTab
                anomalies={state.data.anomalies}
                dgcaValidation={state.data.dgcaValidation}
              />
            )}

            {activeTab === 'telemetry' && (
              <TelemetryTab
                telemetry={state.data.telemetry}
                onRefresh={() => loadData(true)}
              />
            )}

            {activeTab === 'arbitrage' && (
              <ArbitrageTab
                arbitrage={state.data.arbitrage}
                onRefresh={() => loadData(true)}
              />
            )}
          </div>
        )}
        </ApiErrorBoundary>
      </main>

      {/* Footer - Restrained Vercel Editorial Style */}
      <footer className="bg-neutral-950 border-t border-neutral-800 py-6 text-xs text-neutral-500 font-mono">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-neutral-300">Team Woven tech</span>
            <span className="text-neutral-700">•</span>
            <span>Smart India Hackathon 2026 (PS 26056)</span>
            <span className="text-neutral-700">•</span>
            <span className="text-neutral-400">APIx Engine v0.1.0</span>
          </div>

          <div className="flex items-center gap-4 text-[11px] text-neutral-500">
            <span>Sources: IndiGo • Air India • SpiceJet • Akasa Air • MMT • EaseMyTrip</span>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default App;
