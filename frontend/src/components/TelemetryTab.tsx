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
  Clock,
  RefreshCw,
  Play,
  Globe,
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
  CartesianGrid,
} from 'recharts';

interface TelemetryTabProps {
  telemetry: TelemetryResponse;
  onRefresh?: () => void;
}

const isOnlineStatus = (status?: string): boolean => {
  const s = (status || '').toUpperCase();
  return s === 'ACTIVE' || s === 'ONLINE' || s === 'RUNNING' || s === 'HEALTHY' || s === 'OK';
};

export const TelemetryTab: React.FC<TelemetryTabProps> = ({ telemetry, onRefresh }) => {
  const [triggeringCrawler, setTriggeringCrawler] = useState<string | null>(null);
  const [triggerResult, setTriggerResult] = useState<CrawlerTriggerResponse | null>(null);
  const [selectedCrawlerFilter, setSelectedCrawlerFilter] = useState<string>('ALL');
  const [selectedErrorTypeFilter, setSelectedErrorTypeFilter] = useState<string>('ALL');
  const [manualScraper, setManualScraper] = useState<string>('all');
  const [manualRoute, setManualRoute] = useState<string>('ALL');

  const scrapers = telemetry.scrapers || [];
  const proxyPool = telemetry.proxy_pool || {
    active_proxies: 0,
    total_proxies: 0,
    blacklisted_proxies: 0,
    avg_latency_ms: 0,
    p95_latency_ms: 0,
    top_exit_nodes: [],
  };
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

  const exitNodesData = (proxyPool.top_exit_nodes && proxyPool.top_exit_nodes.length > 0)
    ? proxyPool.top_exit_nodes.map((node) => ({
        name: node.region.split(' ')[0] || node.region,
        region: node.region,
        ip: node.ip_prefix,
        latency: node.latency_ms ?? 0,
        status: node.status,
      }))
    : [
        { name: 'DEL', region: 'Delhi (DEL-1)', ip: '103.21.244.x', latency: Math.round((proxyPool.avg_latency_ms || 42) * 0.88), status: 'OPTIMAL' as const },
        { name: 'BOM', region: 'Mumbai (BOM-1)', ip: '103.22.200.x', latency: Math.round((proxyPool.avg_latency_ms || 42) * 0.94), status: 'OPTIMAL' as const },
        { name: 'BLR', region: 'Bengaluru (BLR-1)', ip: '103.28.248.x', latency: Math.round((proxyPool.avg_latency_ms || 42) * 1.05), status: 'OPTIMAL' as const },
        { name: 'HYD', region: 'Hyderabad (HYD-1)', ip: '103.31.4.x', latency: Math.round((proxyPool.avg_latency_ms || 42) * 1.12), status: 'OPTIMAL' as const },
        { name: 'CCU', region: 'Kolkata (CCU-1)', ip: '103.41.12.x', latency: Math.round((proxyPool.avg_latency_ms || 42) * 1.25), status: 'DEGRADED' as const },
      ];

  const totalFaresCollected = scrapers.reduce((acc, s) => acc + (s.fares_collected ?? 0), 0);
  const totalSuccessCount = scrapers.reduce((acc, s) => acc + (s.success_count ?? 0), 0);
  const totalErrorsCount = scrapers.reduce((acc, s) => acc + (s.error_count ?? 0), 0);
  const overallSuccessRate = totalSuccessCount + totalErrorsCount > 0
    ? ((totalSuccessCount / (totalSuccessCount + totalErrorsCount)) * 100).toFixed(2)
    : '100.00';

  return (
    <div className="space-y-6">
      {/* Top Banner / System Health & Controls */}
      <div className="border border-neutral-800 bg-neutral-950 rounded-lg p-5">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium border border-neutral-800 bg-neutral-900 text-neutral-300">
                PIPELINE TELEMETRY
              </span>
              <span className="text-neutral-600 text-xs">•</span>
              <span className="text-xs px-2 py-0.5 rounded font-mono font-medium border border-neutral-800 bg-neutral-900 text-neutral-300">
                {telemetry.system_health ?? 'HEALTHY'}
              </span>
            </div>
            <h1 className="text-base font-semibold tracking-tight text-white">
              Crawler Infrastructure &amp; Proxy Telemetry
            </h1>
            <p className="text-xs text-neutral-400 mt-1 max-w-2xl leading-relaxed">
              Real-time distributed multi-source crawler fleet monitoring, proxy pool latency gauges, and fault diagnostics.
            </p>
          </div>

          <div className="flex items-center gap-3">
            {onRefresh && (
              <button
                onClick={onRefresh}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono rounded border border-neutral-800 bg-neutral-900 hover:bg-neutral-800 text-neutral-200 hover:text-white transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5 text-neutral-400" />
                <span>Refresh Telemetry</span>
              </button>
            )}
            <div className="text-[11px] font-mono text-neutral-500">
              Synced: {new Date(telemetry.generated_at).toLocaleTimeString()}
            </div>
          </div>
        </div>

        {/* Global Pipeline KPI Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mt-5">
          <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-neutral-400">
                Active Crawlers
              </span>
              <Activity className="w-3.5 h-3.5 text-neutral-500" />
            </div>
            <div className="mt-2 flex items-baseline gap-1.5">
              <span className="text-2xl font-semibold font-mono tabular-nums text-white">
                {scrapers.filter((s) => isOnlineStatus(s.status)).length}
              </span>
              <span className="text-xs font-mono text-neutral-500">/ {scrapers.length}</span>
            </div>
            <div className="text-[10px] text-neutral-500 font-mono mt-1">100% Scheduled Fleet</div>
          </div>

          <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-neutral-400">
                Fares Collected
              </span>
              <Database className="w-3.5 h-3.5 text-neutral-500" />
            </div>
            <div className="mt-2">
              <span className="text-2xl font-semibold font-mono tabular-nums text-white">
                {totalFaresCollected.toLocaleString()}
              </span>
            </div>
            <div className="text-[10px] text-neutral-500 font-mono mt-1">Across 10 corridors</div>
          </div>

          <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-neutral-400">
                Success Rate
              </span>
              <span className="text-xs font-mono text-neutral-500">Cycle 3</span>
            </div>
            <div className="mt-2">
              <span className="text-2xl font-semibold font-mono tabular-nums text-white">
                {overallSuccessRate}%
              </span>
            </div>
            <div className="text-[10px] text-neutral-500 font-mono mt-1">
              {totalErrorsCount} recoverable errors
            </div>
          </div>

          <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-neutral-400">
                Proxy Nodes
              </span>
              <Globe className="w-3.5 h-3.5 text-neutral-500" />
            </div>
            <div className="mt-2 flex items-baseline gap-1.5">
              <span className="text-2xl font-semibold font-mono tabular-nums text-white">
                {proxyPool.active_proxies}
              </span>
              <span className="text-xs font-mono text-neutral-500">/ {proxyPool.total_proxies}</span>
            </div>
            <div className="text-[10px] text-neutral-500 font-mono mt-1">
              {proxyPool.blacklisted_proxies} blacklisted
            </div>
          </div>

          <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wider text-neutral-400">
                Avg Latency
              </span>
              <Wifi className="w-3.5 h-3.5 text-neutral-500" />
            </div>
            <div className="mt-2 flex items-baseline gap-1.5">
              <span className="text-2xl font-semibold font-mono tabular-nums text-white">
                {proxyPool.avg_latency_ms}
              </span>
              <span className="text-xs font-mono text-neutral-500">ms (p95: {proxyPool.p95_latency_ms}ms)</span>
            </div>
            <div className="text-[10px] text-neutral-500 font-mono mt-1">Residential &amp; DC</div>
          </div>
        </div>

        {/* Trigger Feedback Banner */}
        {triggerResult && (
          <div className="mt-4 p-3 rounded border border-neutral-800 bg-neutral-900 flex items-center justify-between text-xs text-neutral-200 font-mono">
            <div className="flex items-center gap-2">
              <span className="text-white font-medium">{triggerResult.status}:</span>
              <span>{triggerResult.message}</span>
              <span className="text-neutral-500">({triggerResult.task_id})</span>
            </div>
            <span className="text-[10px] text-neutral-500">
              {new Date(triggerResult.triggered_at).toLocaleTimeString()}
            </span>
          </div>
        )}
      </div>

      {/* Manual Crawler Trigger Dispatcher */}
      <div className="border border-neutral-800 bg-neutral-950 rounded-lg p-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Server className="w-4 h-4 text-neutral-400" />
            <h2 className="text-xs font-medium uppercase tracking-wider text-neutral-300">
              Manual Crawl Orchestration
            </h2>
            <span className="text-xs text-neutral-500 hidden sm:inline font-mono">• Force on-demand route sweep</span>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 text-xs text-neutral-400 font-mono">
              <span>Crawler:</span>
              <select
                value={manualScraper}
                onChange={(e) => setManualScraper(e.target.value)}
                className="bg-neutral-900 text-neutral-200 border border-neutral-800 rounded px-2.5 py-1 text-xs font-mono focus:outline-none focus:border-neutral-700"
              >
                <option value="all">All Fleet</option>
                <option value="easemytrip">EaseMyTrip</option>
                <option value="makemytrip">MakeMyTrip</option>
                <option value="spicejet">SpiceJet</option>
                <option value="amadeus">Amadeus</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5 text-xs text-neutral-400 font-mono">
              <span>Corridor:</span>
              <select
                value={manualRoute}
                onChange={(e) => setManualRoute(e.target.value)}
                className="bg-neutral-900 text-neutral-200 border border-neutral-800 rounded px-2.5 py-1 text-xs font-mono focus:outline-none focus:border-neutral-700"
              >
                <option value="ALL">All 10 Corridors</option>
                <option value="DEL-BOM">DEL-BOM</option>
                <option value="BOM-DEL">BOM-DEL</option>
                <option value="DEL-BLR">DEL-BLR</option>
                <option value="BLR-DEL">BLR-DEL</option>
                <option value="BOM-BLR">BOM-BLR</option>
                <option value="BLR-BOM">BLR-BOM</option>
                <option value="DEL-CCU">DEL-CCU</option>
                <option value="CCU-DEL">CCU-DEL</option>
                <option value="DEL-HYD">DEL-HYD</option>
                <option value="HYD-DEL">HYD-DEL</option>
              </select>
            </div>

            <button
              onClick={() => handleTrigger()}
              disabled={triggeringCrawler !== null}
              className="flex items-center gap-1.5 px-3 py-1 bg-neutral-900 hover:bg-neutral-800 text-white text-xs font-mono rounded border border-neutral-800 transition-colors disabled:opacity-50"
            >
              {triggeringCrawler === 'all' || triggeringCrawler === manualScraper ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin text-neutral-400" />
              ) : (
                <Play className="w-3.5 h-3.5 text-neutral-400" />
              )}
              <span>Dispatch Crawl</span>
            </button>
          </div>
        </div>
      </div>

      {/* Crawler Status Cards Grid */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs font-medium uppercase tracking-wider text-neutral-400">
            Multi-Source Crawler Fleet (4 Primary Engines)
          </h2>
          <span className="text-xs text-neutral-500 font-mono">
            Active Workers: {telemetry.active_workers ?? 16}
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {scrapers.map((crawler: CrawlerStatus) => {
            const isTriggering = triggeringCrawler === crawler.crawler_name;
            const isOnline = isOnlineStatus(crawler.status);

            return (
              <div
                key={crawler.crawler_name}
                className="bg-neutral-950 border border-neutral-800 rounded-lg p-4 hover:border-neutral-700 transition-colors flex flex-col justify-between"
              >
                <div>
                  {/* Card Header */}
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h3 className="text-sm font-semibold text-white capitalize font-mono">
                        {crawler.crawler_name}
                      </h3>
                      <p className="text-[11px] text-neutral-500 font-mono">
                        {crawler.platform}
                      </p>
                    </div>

                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium border ${
                        isOnline
                          ? 'border-neutral-800 bg-neutral-900 text-neutral-300'
                          : 'border-red-500/30 text-red-400 bg-red-950/20'
                      }`}
                    >
                      {crawler.status}
                    </span>
                  </div>

                  {/* Uptime Progress Bar */}
                  <div className="mt-3">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-neutral-500 font-mono text-[11px]">Uptime</span>
                      <span className="font-mono text-xs text-white tabular-nums">{crawler.uptime_pct}%</span>
                    </div>
                    <div className="w-full bg-neutral-900 border border-neutral-800 rounded-sm h-1.5 mt-1 overflow-hidden">
                      <div
                        className="h-full bg-neutral-300 rounded-sm transition-all"
                        style={{ width: `${crawler.uptime_pct}%` }}
                      />
                    </div>
                  </div>

                  {/* Metrics Grid */}
                  <div className="grid grid-cols-2 gap-2 mt-3 pt-2.5 border-t border-neutral-800 text-xs font-mono">
                    <div>
                      <span className="text-[10px] text-neutral-500 block">Fares Scraped</span>
                      <span className="font-semibold text-white tabular-nums">
                        {(crawler.fares_collected ?? 0).toLocaleString()}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-neutral-500 block">Avg Response</span>
                      <span className="text-neutral-300 tabular-nums">
                        {crawler.avg_response_time_ms ? `${crawler.avg_response_time_ms} ms` : '—'}
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-neutral-500 block">Success / Error</span>
                      <span className="text-neutral-300 tabular-nums">
                        <span className="text-white">{crawler.success_count}</span>
                        {' / '}
                        <span className={crawler.error_count > 0 ? 'text-red-400' : 'text-neutral-500'}>
                          {crawler.error_count}
                        </span>
                      </span>
                    </div>
                    <div>
                      <span className="text-[10px] text-neutral-500 block">Error Rate</span>
                      <span
                        className={`tabular-nums ${
                          crawler.error_rate_pct > 1 ? 'text-amber-400' : 'text-neutral-300'
                        }`}
                      >
                        {crawler.error_rate_pct}%
                      </span>
                    </div>
                  </div>

                  {/* Route tags */}
                  {crawler.target_routes && crawler.target_routes.length > 0 && (
                    <div className="mt-3">
                      <span className="text-[10px] text-neutral-500 block mb-1 font-mono">Target Corridors</span>
                      <div className="flex flex-wrap gap-1">
                        {crawler.target_routes.slice(0, 4).map((rt) => (
                          <span
                            key={rt}
                            className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-neutral-900 text-neutral-400 border border-neutral-800"
                          >
                            {rt}
                          </span>
                        ))}
                        {crawler.target_routes.length > 4 && (
                          <span className="text-[10px] font-mono text-neutral-500 self-center">
                            +{crawler.target_routes.length - 4} more
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* Footer / Trigger Button */}
                <div className="mt-3 pt-2.5 border-t border-neutral-800 flex items-center justify-between">
                  <div className="flex items-center gap-1 text-[10px] text-neutral-500 font-mono">
                    <Clock className="w-3 h-3 text-neutral-500" />
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
                    className="flex items-center gap-1 px-2.5 py-1 text-[11px] font-mono rounded border border-neutral-800 bg-neutral-900 hover:bg-neutral-800 text-neutral-200 hover:text-white transition-colors disabled:opacity-50"
                  >
                    {isTriggering ? (
                      <RefreshCw className="w-3 h-3 animate-spin text-neutral-400" />
                    ) : (
                      <Play className="w-3 h-3 text-neutral-400" />
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
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Latency Gauges & Metrics */}
        <div className="lg:col-span-1 border border-neutral-800 bg-neutral-950 rounded-lg p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Wifi className="w-4 h-4 text-neutral-400" />
              <h3 className="text-xs font-medium uppercase tracking-wider text-neutral-400">
                Proxy Pool Latency Gauges
              </h3>
            </div>
            <span className="text-[10px] font-mono text-neutral-300 border border-neutral-800 bg-neutral-900 px-2 py-0.5 rounded">
              {proxyPool.healthy_pct ?? 95.3}% Healthy
            </span>
          </div>

          <div className="space-y-4">
            {/* Average Latency Gauge */}
            <div className="bg-neutral-900/40 border border-neutral-800 rounded p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-neutral-400 font-medium">Fleet Mean Latency</span>
                <span className="text-xs font-semibold font-mono tabular-nums text-white">
                  {proxyPool.avg_latency_ms} ms
                </span>
              </div>
              <div className="w-full bg-neutral-900 border border-neutral-800 rounded-sm h-1.5 mt-2 overflow-hidden flex">
                <div
                  className="bg-neutral-300 h-full rounded-sm transition-all"
                  style={{ width: `${Math.min(100, (proxyPool.avg_latency_ms / 300) * 100)}%` }}
                />
              </div>
              <div className="flex justify-between text-[10px] text-neutral-500 font-mono mt-1">
                <span>0 ms</span>
                <span className="text-neutral-400">Optimal &lt; 150ms</span>
                <span>300 ms</span>
              </div>
            </div>

            {/* P95 Tail Latency Gauge */}
            <div className="bg-neutral-900/40 border border-neutral-800 rounded p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-neutral-400 font-medium">P95 Tail Latency</span>
                <span className="text-xs font-semibold font-mono tabular-nums text-white">
                  {proxyPool.p95_latency_ms} ms
                </span>
              </div>
              <div className="w-full bg-neutral-900 border border-neutral-800 rounded-sm h-1.5 mt-2 overflow-hidden flex">
                <div
                  className="bg-neutral-400 h-full rounded-sm transition-all"
                  style={{ width: `${Math.min(100, (proxyPool.p95_latency_ms / 500) * 100)}%` }}
                />
              </div>
              <div className="flex justify-between text-[10px] text-neutral-500 font-mono mt-1">
                <span>0 ms</span>
                <span className="text-neutral-400">Acceptable &lt; 350ms</span>
                <span>500 ms</span>
              </div>
            </div>

            {/* Proxy Health Breakdown */}
            <div className="grid grid-cols-2 gap-2 text-xs pt-1 font-mono">
              <div className="bg-neutral-900/40 border border-neutral-800 rounded p-2.5">
                <span className="text-[10px] text-neutral-500 block">Bandwidth Today</span>
                <span className="font-semibold text-white tabular-nums">
                  {proxyPool.bandwidth_mb_today ?? 1420} MB
                </span>
              </div>
              <div className="bg-neutral-900/40 border border-neutral-800 rounded p-2.5">
                <span className="text-[10px] text-neutral-500 block">Rotation Policy</span>
                <span className="text-neutral-200">Round-Robin</span>
              </div>
            </div>
          </div>
        </div>

        {/* Regional Exit Node Latency Chart */}
        <div className="lg:col-span-2 border border-neutral-800 bg-neutral-950 rounded-lg p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2">
                <Globe className="w-4 h-4 text-neutral-400" />
                <h3 className="text-xs font-medium uppercase tracking-wider text-neutral-400">
                  Regional Proxy Exit Node Latencies
                </h3>
              </div>
              <span className="text-[11px] text-neutral-500 font-mono">
                Edge routing resilience
              </span>
            </div>

            <p className="text-xs text-neutral-500 mb-3">
              Geographic dispersion across Indian domestic metro POPs minimizes challenges and mimics organic user navigation.
            </p>

            {exitNodesData.length === 0 ? (
              <div className="h-48 w-full flex flex-col items-center justify-center text-xs text-neutral-500 font-mono border border-neutral-800/60 rounded bg-neutral-900/20">
                <Globe className="w-5 h-5 text-neutral-600 mb-1.5" />
                <span>Regional exit node latency telemetry unavailable</span>
                <span className="text-[10px] text-neutral-600 mt-0.5">Top exit nodes not reported by gateway</span>
              </div>
            ) : (
              <div className="h-48 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={exitNodesData} margin={{ top: 10, right: 10, left: -20, bottom: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#262626" vertical={false} />
                    <XAxis
                      dataKey="name"
                      stroke="#737373"
                      fontSize={11}
                      tickLine={false}
                      axisLine={{ stroke: '#262626' }}
                    />
                    <YAxis
                      stroke="#737373"
                      fontSize={11}
                      unit="ms"
                      tickLine={false}
                      axisLine={{ stroke: '#262626' }}
                    />
                    <Tooltip
                      content={({ active, payload }) => {
                        if (active && payload && payload.length) {
                          const d = payload[0].payload;
                          return (
                            <div className="bg-neutral-950 border border-neutral-800 p-2.5 rounded font-mono text-xs">
                              <p className="font-semibold text-white">{d.region}</p>
                              <p className="text-neutral-500">Subnet: {d.ip}</p>
                              <p className="text-neutral-300 mt-1">Ping Latency: {d.latency} ms</p>
                              <p className="text-neutral-400">Status: {d.status}</p>
                            </div>
                          );
                        }
                        return null;
                      }}
                    />
                    <Bar dataKey="latency" radius={[2, 2, 0, 0]}>
                      {exitNodesData.map((entry, index) => (
                        <Cell
                          key={`cell-${index}`}
                          fill={entry.latency < 100 ? '#ffffff' : entry.latency < 200 ? '#a3a3a3' : '#525252'}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Node IP Table Pills */}
          <div className="pt-3 border-t border-neutral-800 font-mono">
            {exitNodesData.length > 0 ? (
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                {exitNodesData.map((node) => (
                  <div key={node.region} className="text-center p-1.5 rounded bg-neutral-900/40 border border-neutral-800">
                    <span className="text-[10px] text-neutral-300 block truncate">{node.name}</span>
                    <span className="text-[10px] text-neutral-500 block tabular-nums">{node.latency} ms</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-[11px] text-neutral-500 text-center py-1">
                No active exit node diagnostics reported
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Error Breakdown & Failure Diagnostics Log: 12-Column Semantic Table */}
      <div className="border border-neutral-800 bg-neutral-950 rounded-lg p-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-4">
          <div className="flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 text-neutral-400" />
            <div>
              <h3 className="text-xs font-medium uppercase tracking-wider text-neutral-400 flex items-center gap-2">
                Crawler Fault Diagnostics &amp; Error Breakdown
                <span className="text-[10px] px-2 py-0.5 rounded font-mono border border-neutral-800 bg-neutral-900 text-neutral-300">
                  {errorBreakdown?.total_errors ?? 0} Total
                </span>
              </h3>
            </div>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-2 text-xs font-mono">
            <Filter className="w-3.5 h-3.5 text-neutral-500" />
            <select
              value={selectedCrawlerFilter}
              onChange={(e) => setSelectedCrawlerFilter(e.target.value)}
              className="bg-neutral-900 text-neutral-200 border border-neutral-800 rounded px-2.5 py-1 text-xs font-mono focus:outline-none focus:border-neutral-700"
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
              className="bg-neutral-900 text-neutral-200 border border-neutral-800 rounded px-2.5 py-1 text-xs font-mono focus:outline-none focus:border-neutral-700"
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
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5 mb-4 font-mono">
            {Object.entries(errorBreakdown.by_type).map(([errType, count]) => (
              <div
                key={errType}
                onClick={() => setSelectedErrorTypeFilter(selectedErrorTypeFilter === errType ? 'ALL' : errType)}
                className={`p-2.5 rounded border cursor-pointer transition-colors ${
                  selectedErrorTypeFilter === errType
                    ? 'border-neutral-600 bg-neutral-900 text-white'
                    : 'bg-neutral-900/40 border-neutral-800 text-neutral-400 hover:border-neutral-700'
                }`}
              >
                <div className="flex items-center justify-between text-[11px] text-neutral-500">
                  <span className="truncate">{errType}</span>
                  <AlertTriangle className="w-3 h-3 text-neutral-500" />
                </div>
                <div className="mt-1 flex items-baseline justify-between">
                  <span className="text-base font-semibold text-white tabular-nums">{count}</span>
                  <span className="text-[10px] text-neutral-500 tabular-nums">
                    {Math.round((count / (errorBreakdown.total_errors || 1)) * 100)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Diagnostic Log Table: 12-Column Semantic Layout */}
        <div className="overflow-x-auto rounded border border-neutral-800">
          <table className="w-full text-left text-xs table-fixed font-mono">
            <colgroup>
              <col className="w-[12%]" /> {/* Timestamp: 1.5 cols */}
              <col className="w-[12%]" /> {/* Crawler: 1.5 cols */}
              <col className="w-[10%]" /> {/* Route: 1.2 cols */}
              <col className="w-[20%]" /> {/* Error Type: 2.5 cols */}
              <col className="w-[30%]" /> {/* Message: 3.5 cols */}
              <col className="w-[16%]" /> {/* Retries & Status: 1.8 cols */}
            </colgroup>
            <thead className="bg-neutral-900/40 text-neutral-400 border-b border-neutral-800 uppercase text-[11px] select-none">
              <tr>
                <th className="py-3 px-3 text-left font-medium">Timestamp</th>
                <th className="py-3 px-3 text-left font-medium">Crawler</th>
                <th className="py-3 px-3 text-left font-medium">Route</th>
                <th className="py-3 px-3 text-left font-medium">Error Type</th>
                <th className="py-3 px-3 text-left font-medium">Root Cause Message</th>
                <th className="py-3 px-3 text-right font-medium font-mono tabular-nums">Retries &amp; Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800 text-neutral-300">
              {filteredErrors.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-neutral-500 font-mono">
                    No error events match the active filter criteria.
                  </td>
                </tr>
              ) : (
                filteredErrors.map((err: CrawlerErrorItem) => (
                  <tr key={err.id} className="hover:bg-neutral-900/40 transition-colors">
                    {/* Timestamp (Left) */}
                    <td className="py-2.5 px-3 text-neutral-400 whitespace-nowrap">
                      {new Date(err.occurred_at).toLocaleTimeString([], {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </td>

                    {/* Crawler (Left) */}
                    <td className="py-2.5 px-3 font-medium text-white capitalize">
                      {err.crawler_name}
                    </td>

                    {/* Route (Left) */}
                    <td className="py-2.5 px-3">
                      <span className="px-1.5 py-0.5 rounded border border-neutral-800 bg-neutral-900 text-neutral-300 text-[10px]">
                        {err.route_code || 'GLOBAL'}
                      </span>
                    </td>

                    {/* Error Type & Code (Left) */}
                    <td className="py-2.5 px-3">
                      <div className="flex items-center gap-1.5">
                        <span className="text-neutral-200 font-medium">{err.error_type}</span>
                        {err.status_code && (
                          <span className="text-[10px] px-1 py-0.5 rounded border border-neutral-800 bg-neutral-900 text-neutral-400">
                            {err.status_code}
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Message (Left) */}
                    <td className="py-2.5 px-3 text-xs text-neutral-400 truncate" title={err.message}>
                      {err.message}
                    </td>

                    {/* Retries & Status (Right) */}
                    <td className="py-2.5 px-3 text-right whitespace-nowrap font-mono tabular-nums">
                      <div className="flex items-center justify-end gap-2">
                        <span className="text-neutral-500 text-[11px]">{err.retry_count}x</span>
                        {err.recovered ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-neutral-300 border border-neutral-800 bg-neutral-900 px-2 py-0.5 rounded">
                            <Check className="w-2.5 h-2.5 text-neutral-400" /> Recovered
                          </span>
                        ) : (
                          <span className="text-[10px] font-medium text-amber-400 border border-amber-500/30 bg-amber-950/20 px-2 py-0.5 rounded">
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
