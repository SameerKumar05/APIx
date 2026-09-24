import React, { useState } from 'react';
import {
  TelemetryResponse,
  CrawlerStatus,
  CrawlerErrorItem,
  CrawlerTriggerResponse,
} from '../types/api';
import apiClient from '../services/apiClient';
import {
  Server,
  Activity,
  Wifi,
  AlertTriangle,
  CheckCircle2,
  Clock,
  RefreshCw,
  Play,
  Globe,
  Zap,
  ShieldAlert,
  Filter,
  Check,
  Database,
} from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
} from 'recharts';

interface TelemetryTabProps {
  telemetry: TelemetryResponse;
  onRefresh?: () => void;
}

export const TelemetryTab: React.FC<TelemetryTabProps> = ({ telemetry, onRefresh }) => {
  const [triggeringCrawler, setTriggeringCrawler] = useState<string | null>(null);
  const [triggerResult, setTriggerResult] = useState<CrawlerTriggerResponse | null>(null);
  const [selectedCrawlerFilter, setSelectedCrawlerFilter] = useState<string>('ALL');
  const [selectedErrorTypeFilter, setSelectedErrorTypeFilter] = useState<string>('ALL');
  const [manualScraper, setManualScraper] = useState<string>('all');
  const [manualRoute, setManualRoute] = useState<string>('ALL');

  const scrapers = telemetry.scrapers;
  const proxyPool = telemetry.proxy_pool;
  const errorBreakdown = telemetry.error_breakdown;

  // Execute manual crawler trigger
  const handleTrigger = async (crawlerName?: string, routeCode?: string) => {
    const target = crawlerName || manualScraper;
    const targetRoute = routeCode || (manualRoute === 'ALL' ? undefined : manualRoute);
    setTriggeringCrawler(target);

    try {
      const res = await apiClient.triggerCrawler({
        crawler_name: target === 'all' ? undefined : target,
        route_code: targetRoute,
      });
      setTriggerResult(res);
      setTimeout(() => {
        setTriggerResult(null);
      }, 7000);
    } finally {
      setTriggeringCrawler(null);
    }
  };

  // Filter recent error events
  const filteredErrors = (errorBreakdown?.recent_errors || []).filter((err: CrawlerErrorItem) => {
    if (selectedCrawlerFilter !== 'ALL' && err.crawler_name.toLowerCase() !== selectedCrawlerFilter.toLowerCase()) {
      return false;
    }
    if (selectedErrorTypeFilter !== 'ALL' && err.error_type !== selectedErrorTypeFilter) {
      return false;
    }
    return true;
  });

  // Latency chart data for exit nodes
  const exitNodesData = (proxyPool.top_exit_nodes || []).map((node) => ({
    name: node.region.split(' ')[0] || node.region,
    region: node.region,
    ip: node.ip_prefix,
    latency: node.latency_ms,
    status: node.status,
  }));

  const totalFaresCollected = scrapers.reduce((acc, s) => acc + s.fares_collected, 0);
  const totalSuccessCount = scrapers.reduce((acc, s) => acc + s.success_count, 0);
  const totalErrorsCount = scrapers.reduce((acc, s) => acc + s.error_count, 0);
  const overallSuccessRate = totalSuccessCount + totalErrorsCount > 0
    ? ((totalSuccessCount / (totalSuccessCount + totalErrorsCount)) * 100).toFixed(2)
    : '100.00';

  return (
    <div className="space-y-6">
      {/* Top Banner / System Health & Controls */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 backdrop-blur-sm">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-sky-500/10 border border-sky-500/20 text-sky-400">
                <Server className="w-5 h-5" />
              </div>
              <div>
                <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                  Crawler Infrastructure & Proxy Telemetry
                  <span className="text-xs px-2.5 py-0.5 rounded-full font-mono font-semibold bg-emerald-950/80 text-emerald-400 border border-emerald-800/80">
                    {telemetry.system_health}
                  </span>
                </h1>
                <p className="text-xs text-slate-400 mt-0.5">
                  Real-time distributed multi-source crawler fleet monitoring, proxy pool latency gauges, and fault diagnostics
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {onRefresh && (
              <button
                onClick={onRefresh}
                className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-all"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Refresh Telemetry</span>
              </button>
            )}
            <div className="text-[11px] font-mono text-slate-500">
              Synced: {new Date(telemetry.generated_at).toLocaleTimeString()}
            </div>
          </div>
        </div>

        {/* Global Pipeline KPI Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mt-6">
          <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-slate-400">Active Crawlers</span>
              <Activity className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="mt-2 flex items-baseline gap-1.5">
              <span className="text-xl font-bold font-mono text-white">
                {scrapers.filter((s) => s.status === 'ONLINE' || s.status === 'RUNNING').length}
              </span>
              <span className="text-xs font-mono text-slate-500">/ {scrapers.length}</span>
            </div>
            <div className="text-[10px] text-emerald-400/90 font-medium mt-1">100% Scheduled Fleet</div>
          </div>

          <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-slate-400">Fares Collected</span>
              <Database className="w-4 h-4 text-sky-400" />
            </div>
            <div className="mt-2">
              <span className="text-xl font-bold font-mono text-white">
                {totalFaresCollected.toLocaleString()}
              </span>
            </div>
            <div className="text-[10px] text-slate-400 font-medium mt-1">Today across 10 corridors</div>
          </div>

          <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-slate-400">Success Rate</span>
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="mt-2">
              <span className="text-xl font-bold font-mono text-emerald-400">
                {overallSuccessRate}%
              </span>
            </div>
            <div className="text-[10px] text-slate-400 font-medium mt-1">
              {totalErrorsCount} recoverable errors
            </div>
          </div>

          <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-slate-400">Proxy Nodes</span>
              <Globe className="w-4 h-4 text-indigo-400" />
            </div>
            <div className="mt-2 flex items-baseline gap-1.5">
              <span className="text-xl font-bold font-mono text-white">
                {proxyPool.active_proxies}
              </span>
              <span className="text-xs font-mono text-slate-500">/ {proxyPool.total_proxies}</span>
            </div>
            <div className="text-[10px] text-indigo-400 font-medium mt-1">
              {proxyPool.blacklisted_proxies} blacklisted (isolated)
            </div>
          </div>

          <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-slate-400">Avg Proxy Latency</span>
              <Wifi className="w-4 h-4 text-amber-400" />
            </div>
            <div className="mt-2 flex items-baseline gap-1.5">
              <span className="text-xl font-bold font-mono text-amber-300">
                {proxyPool.avg_latency_ms}
              </span>
              <span className="text-xs font-mono text-slate-500">ms (p95: {proxyPool.p95_latency_ms}ms)</span>
            </div>
            <div className="text-[10px] text-emerald-400 font-medium mt-1">Residential & Datacenter</div>
          </div>
        </div>

        {/* Trigger Toast / Feedback banner */}
        {triggerResult && (
          <div className="mt-4 p-3 rounded-xl bg-sky-950/70 border border-sky-800/70 flex items-center justify-between text-xs text-sky-200 animate-fadeIn">
            <div className="flex items-center gap-2">
              <Zap className="w-4 h-4 text-sky-400 animate-pulse" />
              <span>
                <strong>{triggerResult.status}:</strong> {triggerResult.message}
              </span>
              <span className="font-mono text-[10px] text-sky-400/80">({triggerResult.task_id})</span>
            </div>
            <span className="text-[10px] text-slate-400 font-mono">
              {new Date(triggerResult.triggered_at).toLocaleTimeString()}
            </span>
          </div>
        )}
      </div>

      {/* Manual Crawler Trigger Dispatcher */}
      <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-amber-400" />
            <h2 className="text-sm font-bold text-white">Manual Crawl Orchestration</h2>
            <span className="text-[11px] text-slate-400 hidden sm:inline">• Force on-demand route sweep</span>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <div className="flex items-center gap-1.5 text-xs text-slate-400 font-medium">
              <span>Crawler:</span>
              <select
                value={manualScraper}
                onChange={(e) => setManualScraper(e.target.value)}
                className="bg-slate-800 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-sky-500"
              >
                <option value="all">All Crawlers (Fleet)</option>
                <option value="easemytrip">EaseMyTrip</option>
                <option value="makemytrip">MakeMyTrip</option>
                <option value="spicejet">SpiceJet</option>
                <option value="amadeus">Amadeus</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5 text-xs text-slate-400 font-medium">
              <span>Corridor:</span>
              <select
                value={manualRoute}
                onChange={(e) => setManualRoute(e.target.value)}
                className="bg-slate-800 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-sky-500"
              >
                <option value="ALL">All 10 Trunk Routes</option>
                <option value="DEL-BOM">DEL-BOM (Delhi-Mumbai)</option>
                <option value="BLR-DEL">BLR-DEL (Bengaluru-Delhi)</option>
                <option value="BOM-GOI">BOM-GOI (Mumbai-Goa)</option>
                <option value="DEL-CCU">DEL-CCU (Delhi-Kolkata)</option>
                <option value="HYD-DEL">HYD-DEL (Hyderabad-Delhi)</option>
                <option value="BOM-BLR">BOM-BLR (Mumbai-Bengaluru)</option>
              </select>
            </div>

            <button
              onClick={() => handleTrigger()}
              disabled={triggeringCrawler !== null}
              className="flex items-center gap-1.5 px-3.5 py-1.5 bg-gradient-to-r from-sky-600 to-indigo-600 hover:from-sky-500 hover:to-indigo-500 text-white text-xs font-semibold rounded-lg shadow-sm transition-all disabled:opacity-50"
            >
              {triggeringCrawler === 'all' || triggeringCrawler === manualScraper ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Play className="w-3.5 h-3.5" />
              )}
              <span>Dispatch Crawl</span>
            </button>
          </div>
        </div>
      </div>

      {/* Crawler Status Cards Grid */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-bold text-white uppercase tracking-wider text-slate-300">
            Multi-Source Crawler Fleet (4 Primary Engines)
          </h2>
          <span className="text-xs text-slate-400 font-mono">
            Cycle 3 Distributed Workers: {telemetry.active_workers ?? 16}
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {scrapers.map((crawler: CrawlerStatus) => {
            const isTriggering = triggeringCrawler === crawler.crawler_name;
            const isOnline = crawler.status === 'ONLINE' || crawler.status === 'RUNNING';

            return (
              <div
                key={crawler.crawler_name}
                className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 hover:border-slate-700 transition-all flex flex-col justify-between"
              >
                <div>
                  {/* Card Header */}
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h3 className="text-base font-bold text-white capitalize">
                        {crawler.crawler_name}
                      </h3>
                      <p className="text-[11px] text-slate-400 font-medium">
                        {crawler.platform}
                      </p>
                    </div>

                    <div
                      className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-bold border ${
                        isOnline
                          ? 'bg-emerald-950/80 text-emerald-400 border-emerald-800/80'
                          : 'bg-rose-950/80 text-rose-400 border-rose-800/80'
                      }`}
                    >
                      <span className="relative flex h-2 w-2">
                        {isOnline && (
                          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                        )}
                        <span
                          className={`relative inline-flex rounded-full h-2 w-2 ${
                            isOnline ? 'bg-emerald-500' : 'bg-rose-500'
                          }`}
                        ></span>
                      </span>
                      <span>{crawler.status}</span>
                    </div>
                  </div>

                  {/* Uptime Progress Bar */}
                  <div className="mt-4">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-slate-400">Uptime</span>
                      <span className="font-mono font-bold text-white">{crawler.uptime_pct}%</span>
                    </div>
                    <div className="w-full bg-slate-800 rounded-full h-1.5 mt-1.5 overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          crawler.uptime_pct >= 99
                            ? 'bg-emerald-500'
                            : crawler.uptime_pct >= 97
                            ? 'bg-sky-500'
                            : 'bg-amber-500'
                        }`}
                        style={{ width: `${crawler.uptime_pct}%` }}
                      ></div>
                    </div>
                  </div>

                  {/* Metrics Grid */}
                  <div className="grid grid-cols-2 gap-2 mt-4 pt-3 border-t border-slate-800/60 text-xs">
                    <div>
                      <span className="text-[10px] text-slate-500 block">Fares Scraped</span>
                      <span className="font-mono font-semibold text-white">
                        {crawler.fares_collected.toLocaleString()}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 block">Avg Response</span>
                      <span className="font-mono font-semibold text-slate-300">
                        {crawler.avg_response_time_ms ? `${crawler.avg_response_time_ms} ms` : '—'}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 block">Success / Error</span>
                      <span className="font-mono font-semibold text-slate-300">
                        <span className="text-emerald-400">{crawler.success_count}</span>
                        {' / '}
                        <span className={crawler.error_count > 0 ? 'text-rose-400' : 'text-slate-500'}>
                          {crawler.error_count}
                        </span>
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-500 block">Error Rate</span>
                      <span
                        className={`font-mono font-semibold ${
                          crawler.error_rate_pct > 1 ? 'text-amber-400' : 'text-emerald-400'
                        }`}
                      >
                        {crawler.error_rate_pct}%
                      </span>
                    </div>
                  </div>

                  {/* Route tags */}
                  {crawler.target_routes && crawler.target_routes.length > 0 && (
                    <div className="mt-3">
                      <span className="text-[10px] text-slate-500 block mb-1">Target Corridors</span>
                      <div className="flex flex-wrap gap-1">
                        {crawler.target_routes.slice(0, 4).map((rt) => (
                          <span
                            key={rt}
                            className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800/80 text-slate-300 border border-slate-700/60"
                          >
                            {rt}
                          </span>
                        ))}
                        {crawler.target_routes.length > 4 && (
                          <span className="text-[10px] font-mono text-slate-500 self-center">
                            +{crawler.target_routes.length - 4} more
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Footer / Trigger Button */}
                <div className="mt-4 pt-3 border-t border-slate-800/60 flex items-center justify-between">
                  <div className="flex items-center gap-1 text-[10px] text-slate-400 font-mono">
                    <Clock className="w-3 h-3 text-slate-500" />
                    <span>
                      {new Date(crawler.last_run_at).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </span>
                  </div>

                  <button
                    onClick={() => handleTrigger(crawler.crawler_name)}
                    disabled={isTriggering}
                    className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-slate-800 hover:bg-slate-700 text-sky-400 hover:text-sky-300 border border-slate-700 transition-colors disabled:opacity-50"
                  >
                    {isTriggering ? (
                      <RefreshCw className="w-3 h-3 animate-spin" />
                    ) : (
                      <Play className="w-3 h-3" />
                    )}
                    <span>Trigger</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Proxy Pool Latency Gauges & Regional Health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Latency Gauges & Metrics */}
        <div className="lg:col-span-1 bg-slate-900/60 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Wifi className="w-4 h-4 text-sky-400" />
              <h3 className="text-sm font-bold text-white">Proxy Pool Health Gauges</h3>
            </div>
            <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-800/60 px-2 py-0.5 rounded-full">
              {proxyPool.healthy_pct ?? 95.3}% Healthy
            </span>
          </div>

          <div className="space-y-4">
            {/* Average Latency Gauge */}
            <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3.5">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400 font-medium">Fleet Mean Latency</span>
                <span className="text-sm font-bold font-mono text-emerald-400">
                  {proxyPool.avg_latency_ms} ms
                </span>
              </div>
              <div className="w-full bg-slate-800 rounded-full h-2 mt-2 overflow-hidden flex">
                <div
                  className="bg-emerald-500 h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(100, (proxyPool.avg_latency_ms / 300) * 100)}%` }}
                ></div>
              </div>
              <div className="flex justify-between text-[10px] text-slate-500 font-mono mt-1">
                <span>0 ms</span>
                <span className="text-emerald-500 font-semibold">Optimal &lt; 150ms</span>
                <span>300 ms</span>
              </div>
            </div>

            {/* P95 Tail Latency Gauge */}
            <div className="bg-slate-950/60 border border-slate-800/80 rounded-xl p-3.5">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400 font-medium">P95 Tail Latency</span>
                <span className="text-sm font-bold font-mono text-amber-400">
                  {proxyPool.p95_latency_ms} ms
                </span>
              </div>
              <div className="w-full bg-slate-800 rounded-full h-2 mt-2 overflow-hidden flex">
                <div
                  className="bg-amber-500 h-full rounded-full transition-all duration-500"
                  style={{ width: `${Math.min(100, (proxyPool.p95_latency_ms / 500) * 100)}%` }}
                ></div>
              </div>
              <div className="flex justify-between text-[10px] text-slate-500 font-mono mt-1">
                <span>0 ms</span>
                <span className="text-amber-500 font-semibold">Acceptable &lt; 350ms</span>
                <span>500 ms</span>
              </div>
            </div>

            {/* Proxy Health Breakdown */}
            <div className="grid grid-cols-2 gap-2 text-xs pt-2">
              <div className="bg-slate-950/40 border border-slate-800/60 rounded-lg p-2.5">
                <span className="text-[10px] text-slate-500 block">Bandwidth Today</span>
                <span className="font-mono font-bold text-slate-200">
                  {proxyPool.bandwidth_mb_today ?? 1420} MB
                </span>
              </div>
              <div className="bg-slate-950/40 border border-slate-800/60 rounded-lg p-2.5">
                <span className="text-[10px] text-slate-500 block">Rotation Policy</span>
                <span className="font-mono font-bold text-sky-400">Round-Robin</span>
              </div>
            </div>
          </div>
        </div>

        {/* Regional Exit Node Latency Chart */}
        <div className="lg:col-span-2 bg-slate-900/60 border border-slate-800 rounded-2xl p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Globe className="w-4 h-4 text-indigo-400" />
                <h3 className="text-sm font-bold text-white">Regional Proxy Exit Node Latencies</h3>
              </div>
              <span className="text-[11px] text-slate-400 font-mono">
                Edge routing for anti-bot resilience
              </span>
            </div>

            <p className="text-xs text-slate-400 mb-4">
              Geographic dispersion across Indian domestic metro POPs minimizes CAPTCHA challenges and mimics organic user navigation.
            </p>

            <div className="h-52 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={exitNodesData} margin={{ top: 10, right: 10, left: -20, bottom: 20 }}>
                  <XAxis
                    dataKey="name"
                    stroke="#64748b"
                    fontSize={11}
                    tickLine={false}
                  />
                  <YAxis
                    stroke="#64748b"
                    fontSize={11}
                    unit="ms"
                    tickLine={false}
                  />
                  <Tooltip
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        const d = payload[0].payload;
                        return (
                          <div className="bg-slate-900 border border-slate-700 p-2.5 rounded-lg shadow-xl text-xs font-mono">
                            <p className="font-bold text-white">{d.region}</p>
                            <p className="text-slate-400">Subnet: {d.ip}</p>
                            <p className="text-sky-400 mt-1">Ping Latency: {d.latency} ms</p>
                            <p className="text-emerald-400">Status: {d.status}</p>
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Bar dataKey="latency" radius={[6, 6, 0, 0]}>
                    {exitNodesData.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={
                          entry.latency < 100
                            ? '#10b981'
                            : entry.latency < 200
                            ? '#38bdf8'
                            : '#f59e0b'
                        }
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Node IP Table Pill */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 pt-3 border-t border-slate-800/80">
            {exitNodesData.map((node) => (
              <div key={node.region} className="text-center p-1.5 rounded-lg bg-slate-950/40 border border-slate-800/60">
                <span className="text-[10px] font-semibold text-slate-300 block truncate">{node.name}</span>
                <span className="text-[10px] font-mono text-sky-400 block">{node.latency} ms</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Error Breakdown & Failure Diagnostics Log */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-5">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-rose-400" />
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                Crawler Fault Diagnostics & Error Breakdown
                <span className="text-xs px-2 py-0.5 rounded-full font-mono bg-rose-950/80 text-rose-300 border border-rose-800/80">
                  {errorBreakdown?.total_errors ?? 0} Total
                </span>
              </h3>
              <p className="text-xs text-slate-400">
                Categorized crawler interception, timeout incidents, and automated proxy recovery logs
              </p>
            </div>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-2 text-xs">
            <Filter className="w-3.5 h-3.5 text-slate-500" />
            <select
              value={selectedCrawlerFilter}
              onChange={(e) => setSelectedCrawlerFilter(e.target.value)}
              className="bg-slate-800 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1 text-xs font-mono focus:outline-none"
            >
              <option value="ALL">All Crawlers</option>
              <option value="easemytrip">EaseMyTrip</option>
              <option value="makemytrip">MakeMyTrip</option>
              <option value="spicejet">SpiceJet</option>
              <option value="amadeus">Amadeus</option>
            </select>

            <select
              value={selectedErrorTypeFilter}
              onChange={(e) => setSelectedErrorTypeFilter(e.target.value)}
              className="bg-slate-800 text-slate-200 border border-slate-700 rounded-lg px-2.5 py-1 text-xs font-mono focus:outline-none"
            >
              <option value="ALL">All Error Codes</option>
              <option value="HTTP_TIMEOUT">HTTP_TIMEOUT</option>
              <option value="CAPTCHA_CHALLENGE">CAPTCHA_CHALLENGE</option>
              <option value="RATE_LIMIT_EXCEEDED">RATE_LIMIT_EXCEEDED</option>
              <option value="DOM_PARSE_ERROR">DOM_PARSE_ERROR</option>
              <option value="PROXY_RESET">PROXY_RESET</option>
            </select>
          </div>
        </div>

        {/* Error Category Summary Badges */}
        {errorBreakdown?.by_type && (
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-5">
            {Object.entries(errorBreakdown.by_type).map(([errType, count]) => (
              <div
                key={errType}
                onClick={() => setSelectedErrorTypeFilter(selectedErrorTypeFilter === errType ? 'ALL' : errType)}
                className={`p-3 rounded-xl border cursor-pointer transition-all ${
                  selectedErrorTypeFilter === errType
                    ? 'bg-rose-950/60 border-rose-600 text-white shadow-sm'
                    : 'bg-slate-950/50 border-slate-800 text-slate-300 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono">
                  <span className="truncate">{errType}</span>
                  <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
                </div>
                <div className="mt-1 flex items-baseline justify-between">
                  <span className="text-lg font-bold font-mono text-white">{count}</span>
                  <span className="text-[10px] text-slate-500">
                    {Math.round((count / errorBreakdown.total_errors) * 100)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Diagnostic Log Table */}
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950 text-slate-400 border-b border-slate-800 uppercase font-mono text-[10px]">
              <tr>
                <th className="py-2.5 px-3">Timestamp</th>
                <th className="py-2.5 px-3">Crawler</th>
                <th className="py-2.5 px-3">Route</th>
                <th className="py-2.5 px-3">Error Type & Status</th>
                <th className="py-2.5 px-3">Message / Root Cause</th>
                <th className="py-2.5 px-3 text-right">Retries & Recovery</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono text-slate-300">
              {filteredErrors.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-slate-500">
                    No error events match the active filter criteria.
                  </td>
                </tr>
              ) : (
                filteredErrors.map((err: CrawlerErrorItem) => (
                  <tr key={err.id} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-2.5 px-3 text-slate-400 whitespace-nowrap">
                      {new Date(err.occurred_at).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </td>
                    <td className="py-2.5 px-3 font-semibold text-white capitalize">
                      {err.crawler_name}
                    </td>
                    <td className="py-2.5 px-3">
                      <span className="px-1.5 py-0.5 rounded bg-slate-800 text-sky-300 border border-slate-700">
                        {err.route_code || 'GLOBAL'}
                      </span>
                    </td>
                    <td className="py-2.5 px-3">
                      <div className="flex items-center gap-1.5">
                        <span className="text-rose-400 font-bold">{err.error_type}</span>
                        {err.status_code && (
                          <span className="text-[10px] px-1 py-0.2 rounded bg-slate-800 text-slate-400 border border-slate-700">
                            {err.status_code}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-2.5 px-3 font-sans text-xs text-slate-400 max-w-md truncate" title={err.message}>
                      {err.message}
                    </td>
                    <td className="py-2.5 px-3 text-right whitespace-nowrap">
                      <div className="flex items-center justify-end gap-2">
                        <span className="text-slate-500 text-[11px]">{err.retry_count}x</span>
                        {err.recovered ? (
                          <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-950/70 border border-emerald-800/70 px-2 py-0.5 rounded-full">
                            <Check className="w-2.5 h-2.5" /> Recovered
                          </span>
                        ) : (
                          <span className="text-[10px] font-bold text-amber-400 bg-amber-950/70 border border-amber-800/70 px-2 py-0.5 rounded-full">
                            Retrying
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
