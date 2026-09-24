import React, { useState, useEffect, useCallback } from 'react';
import {
  ActiveTab,
  DashboardSummaryData,
} from './types/api';
import apiClient from './services/apiClient';
import { OverviewTab } from './components/OverviewTab';
import { RoutesTab } from './components/RoutesTab';
import { ElasticityTab } from './components/ElasticityTab';
import { AnomaliesTab } from './components/AnomaliesTab';
import {
  Plane,
  Activity,
  RefreshCw,
  Clock,
  ShieldCheck,
  Database,
  Server,
} from 'lucide-react';
export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [data, setData] = useState<DashboardSummaryData | null>(null);
  const [isUsingMock, setIsUsingMock] = useState<boolean>(apiClient.isUsingMock());
  const [lastRefreshed, setLastRefreshed] = useState<Date>(new Date());

  const loadData = useCallback(async (isManualRefresh: boolean = false) => {
    if (isManualRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      const summary = await apiClient.getDashboardSummary();
      setData(summary);
      setIsUsingMock(apiClient.isUsingMock());
      setLastRefreshed(new Date());
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();

    const unsubscribe = apiClient.subscribeSourceChange((usingMock) => {
      setIsUsingMock(usingMock);
    });

    // Background refresh every 60 seconds
    const interval = setInterval(() => {
      loadData(false);
    }, 60000);

    return () => {
      unsubscribe();
      clearInterval(interval);
    };
  }, [loadData]);

  const toggleMockMode = () => {
    const nextMock = !isUsingMock;
    apiClient.setPreferMock(nextMock);
    setIsUsingMock(nextMock);
    loadData(true);
  };

  const criticalAlertsCount = data?.anomalies.filter((a) => a.severity === 'CRITICAL').length || 0;

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Top Header */}
      <header className="sticky top-0 z-50 bg-slate-950/80 backdrop-blur-md border-b border-slate-800/80">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16 gap-4">
            {/* Logo and Titles */}
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
                <Plane className="w-5 h-5 text-white" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xl font-extrabold tracking-tight text-white font-mono">
                    API<span className="text-sky-400">x</span>
                  </span>
                  <span className="hidden sm:inline-block text-[11px] font-semibold px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
                    PS 26056 • SIH 2026
                  </span>
                </div>
                <p className="text-[11px] text-slate-400 font-medium hidden sm:block">
                  Real-time Airfare Price Index for India • MoSPI CPI Augmentation & DGCA Oversight
                </p>
              </div>
            </div>

            {/* Live Pipeline Telemetry & Controls */}
            <div className="flex items-center gap-3">
              {/* Ingestion Run Status Indicator */}
              <div
                className="flex items-center gap-2.5 px-3 py-1.5 rounded-xl bg-slate-900/90 border border-slate-800 text-xs shadow-inner"
                title="Ingestion Pipeline Run Status • Continuous Scraper Feeds"
              >
                {/* Health Pill */}
                <div
                  className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-mono font-bold border shadow-sm ${
                    data?.systemHealth.status === 'HEALTHY'
                      ? 'bg-emerald-950/80 text-emerald-400 border-emerald-800/80'
                      : data?.systemHealth.status === 'DEGRADED'
                      ? 'bg-amber-950/80 text-amber-400 border-amber-800/80'
                      : 'bg-sky-950/80 text-sky-400 border-sky-800/80'
                  }`}
                >
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                  </span>
                  <span>{data?.systemHealth.status || 'HEALTHY'}</span>
                </div>

                {/* Active Scrapers Count */}
                <div className="flex items-center gap-1 text-slate-300 font-medium">
                  <Server className="w-3.5 h-3.5 text-sky-400" />
                  <span className="font-mono text-sky-400 font-semibold">
                    {data?.systemHealth.active_scrapers ?? 8}
                  </span>
                  <span className="text-slate-400 hidden sm:inline">Active Scrapers</span>
                </div>

                <span className="text-slate-700 hidden md:inline">|</span>

                {/* Last Scrape Timestamp */}
                <div className="flex items-center gap-1 text-slate-400 font-mono text-[11px]">
                  <Clock className="w-3 h-3 text-slate-400" />
                  <span className="text-slate-500 hidden md:inline">Last Scrape:</span>
                  <span className="text-slate-200 font-semibold">
                    {data?.systemHealth.last_sync_timestamp
                      ? new Date(data.systemHealth.last_sync_timestamp).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                        })
                      : 'Just now'}
                  </span>
                </div>
              </div>
              {/* Data Source Badge with Toggle */}
              <button
                onClick={toggleMockMode}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-mono font-medium border transition-all ${
                  isUsingMock
                    ? 'bg-amber-950/40 text-amber-300 border-amber-800 hover:bg-amber-900/40'
                    : 'bg-emerald-950/40 text-emerald-300 border-emerald-800 hover:bg-emerald-900/40'
                }`}
                title="Click to toggle between Mock Fallback and Live Backend API"
              >
                <Database className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Source:</span>
                <span>{isUsingMock ? 'Mock Fallback' : 'Live API'}</span>
              </button>

              {/* Refresh Button */}
              <button
                onClick={() => loadData(true)}
                disabled={refreshing}
                className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:border-slate-700 transition-colors disabled:opacity-50"
                title={`Last updated: ${lastRefreshed.toLocaleTimeString()}`}
              >
                <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-sky-400' : ''}`} />
              </button>
            </div>
          </div>

          {/* Navigation Tabs */}
          <div className="flex space-x-1 border-t border-slate-800/80 overflow-x-auto py-1">
            <button
              onClick={() => setActiveTab('overview')}
              className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold rounded-lg transition-all ${
                activeTab === 'overview'
                  ? 'bg-slate-800 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60'
              }`}
            >
              <Activity className="w-3.5 h-3.5 text-sky-400" />
              <span>National Overview</span>
            </button>

            <button
              onClick={() => setActiveTab('routes')}
              className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold rounded-lg transition-all ${
                activeTab === 'routes'
                  ? 'bg-slate-800 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60'
              }`}
            >
              <Plane className="w-3.5 h-3.5 text-sky-400" />
              <span>Trunk Routes (10)</span>
            </button>

            <button
              onClick={() => setActiveTab('elasticity')}
              className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold rounded-lg transition-all ${
                activeTab === 'elasticity'
                  ? 'bg-slate-800 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60'
              }`}
            >
              <Clock className="w-3.5 h-3.5 text-indigo-400" />
              <span>Booking Elasticity (T-Days)</span>
            </button>

            <button
              onClick={() => setActiveTab('anomalies')}
              className={`flex items-center gap-2 px-4 py-2.5 text-xs font-semibold rounded-lg transition-all relative ${
                activeTab === 'anomalies'
                  ? 'bg-slate-800 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900/60'
              }`}
            >
              <ShieldCheck className="w-3.5 h-3.5 text-rose-400" />
              <span>DGCA Surveillance</span>
              {criticalAlertsCount > 0 && (
                <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold bg-rose-600 text-white">
                  {criticalAlertsCount}
                </span>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {loading ? (
          <div className="flex flex-col items-center justify-center min-h-[400px] gap-3">
            <RefreshCw className="w-8 h-8 text-sky-500 animate-spin" />
            <p className="text-xs text-slate-400 font-mono">
              Aggregating live flight fares & calculating weighted median indices...
            </p>
          </div>
        ) : !data ? (
          <div className="text-center py-16 bg-slate-900/40 rounded-xl border border-slate-800">
            <p className="text-sm text-slate-300">Unable to load dashboard summary.</p>
            <button
              onClick={() => loadData(true)}
              className="mt-4 px-4 py-2 bg-sky-600 text-white text-xs font-medium rounded-lg"
            >
              Retry Connection
            </button>
          </div>
        ) : (
          <div>
            {activeTab === 'overview' && (
              <OverviewTab
                latest={data.nationalLatest}
                history={data.nationalHistory}
                routes={data.routes}
                anomalies={data.anomalies}
                onSelectTab={setActiveTab}
              />
            )}

            {activeTab === 'routes' && (
              <RoutesTab
                routes={data.routes}
                nationalIndex={data.nationalLatest.index_value}
                anomalies={data.anomalies}
              />
            )}

            {activeTab === 'elasticity' && (
              <ElasticityTab
                leadTimeCurve={data.leadTimeCurve}
                heatmap={data.heatmap}
              />
            )}

            {activeTab === 'anomalies' && (
              <AnomaliesTab
                anomalies={data.anomalies}
                dgcaValidation={data.dgcaValidation}
              />
            )}
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="bg-slate-950 border-t border-slate-800/80 py-6 text-xs text-slate-500">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-400">Team Woven tech</span>
            <span>•</span>
            <span>Smart India Hackathon 2026 (PS 26056)</span>
            <span>•</span>
            <span className="font-mono text-sky-400">APIx Engine v0.1.0-cycle1</span>
          </div>

          <div className="flex items-center gap-4 text-[11px] font-mono">
            <span>Sources: IndiGo • Air India • SpiceJet • Akasa Air • MMT • EaseMyTrip</span>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default App;
