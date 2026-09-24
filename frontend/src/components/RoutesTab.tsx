import React, { useState, useMemo } from 'react';
import { RouteOverviewItem, AnomalyAlertItem } from '../types/api';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ReferenceLine,
  Cell,
} from 'recharts';
import {
  ArrowUpDown,
  Search,
  AlertTriangle,
  CheckCircle2,
  ShieldAlert,
} from 'lucide-react';

interface RoutesTabProps {
  routes: RouteOverviewItem[];
  nationalIndex: number;
  anomalies?: AnomalyAlertItem[];
}

type SortField =
  | 'weight'
  | 'current_index'
  | 'median_fare_inr'
  | 'change_24h'
  | 'change_7d'
  | 'route_code'
  | 'anomaly_count';

// Inline SVG 7-Day Sparkline component - Minimalist Monochrome
const Sparkline: React.FC<{ data?: number[]; isSurge?: boolean }> = ({ data, isSurge }) => {
  if (!data || data.length < 2) {
    return <span className="text-neutral-600 font-mono text-[11px]">—</span>;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const width = 84;
  const height = 22;
  const points = data
    .map((val, idx) => {
      const x = (idx / (data.length - 1)) * (width - 8) + 4;
      const y = height - 4 - ((val - min) / range) * (height - 8);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  const strokeColor = isSurge ? '#f87171' : '#ffffff';
  const lastX = width - 4;
  const lastY = height - 4 - ((data[data.length - 1] - min) / range) * (height - 8);

  return (
    <div
      className="inline-flex items-center"
      title={`7-day trend: ₹${min.toLocaleString('en-IN')} to ₹${max.toLocaleString('en-IN')}`}
    >
      <svg width={width} height={height} className="overflow-visible">
        <polyline
          fill="none"
          stroke={strokeColor}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          points={points}
        />
        <circle cx={lastX} cy={lastY} r="2" fill={strokeColor} />
      </svg>
    </div>
  );
};

export const RoutesTab: React.FC<RoutesTabProps> = ({
  routes,
  nationalIndex,
  anomalies = [],
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [sortField, setSortField] = useState<SortField>('weight');
  const [sortAsc, setSortAsc] = useState(false);
  const [selectedRouteCode, setSelectedRouteCode] = useState<string | null>(null);
  const [filterSeverity, setFilterSeverity] = useState<'ALL' | 'ALERTS_ONLY'>('ALL');

  // Compute anomaly record per route
  const routeAnomalyMap = useMemo(() => {
    const record: Record<string, AnomalyAlertItem[]> = {};
    for (const a of anomalies) {
      if (!record[a.route_code]) {
        record[a.route_code] = [];
      }
      record[a.route_code].push(a);
    }
    return record;
  }, [anomalies]);

  // Filter and sort routes
  const processedRoutes = useMemo(() => {
    let list = routes.filter((r) => {
      const term = searchTerm.toLowerCase().trim();
      const matchesSearch =
        !term ||
        r.route_code?.toLowerCase().includes(term) ||
        (r.origin_city && r.origin_city.toLowerCase().includes(term)) ||
        (r.destination_city && r.destination_city.toLowerCase().includes(term)) ||
        r.origin?.toLowerCase().includes(term) ||
        r.destination?.toLowerCase().includes(term);
      if (!matchesSearch) return false;

      if (filterSeverity === 'ALERTS_ONLY') {
        const routeAlerts = routeAnomalyMap[r.route_code] || [];
        return routeAlerts.length > 0 || ((r.anomaly_count ?? 0) > 0);
      }
      return true;
    });

    list.sort((a, b) => {
      const factor = sortAsc ? 1 : -1;
      if (sortField === 'route_code') {
        return a.route_code.localeCompare(b.route_code) * factor;
      }
      if (sortField === 'anomaly_count') {
        const countA = (routeAnomalyMap[a.route_code] || []).length || a.anomaly_count || 0;
        const countB = (routeAnomalyMap[b.route_code] || []).length || b.anomaly_count || 0;
        return (countA - countB) * factor;
      }
      return ((a[sortField] as number) - (b[sortField] as number)) * factor;
    });

    return list;
  }, [routes, searchTerm, sortField, sortAsc, filterSeverity, routeAnomalyMap]);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(false);
    }
  };

  const selectedRoute = routes.find((r) => r.route_code === selectedRouteCode);
  const selectedRouteAlerts = selectedRoute
    ? routeAnomalyMap[selectedRoute.route_code] || []
    : [];

  const barChartData = useMemo(() => {
    return [...routes]
      .sort((a, b) => (b.weight ?? 0.1) - (a.weight ?? 0.1))
      .map((r) => {
        const rAny = r as unknown as Record<string, number | undefined>;
        const currentIdx = r.current_index ?? 100.0;
        const natl = nationalIndex ?? 100.0;
        const w = r.weight ?? 0.1;
        return {
          route: r.route_code,
          index: currentIdx,
          diff: Number((currentIdx - natl).toFixed(1)),
          weight: (w * 100).toFixed(1),
          fare: r.median_fare_inr ?? rAny.median_fare ?? 0,
        };
      });
  }, [routes, nationalIndex]);

  const totalMonitoredWeight = routes.reduce((acc, r) => acc + (r.weight ?? 0.1), 0);

  return (
    <div className="space-y-6">
      {/* Top Banner and Search/Filter Controls */}
      <div className="border border-neutral-800 bg-neutral-950 rounded-lg p-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5">
              <h2 className="text-base font-semibold text-white tracking-tight">
                DGCA High-Density Domestic Trunk Corridors
              </h2>
              <span className="text-xs px-2.5 py-0.5 rounded border border-neutral-800 bg-neutral-900 text-neutral-300 font-mono tabular-nums">
                10 Corridors • {(totalMonitoredWeight * 100).toFixed(1)}% Traffic Share
              </span>
            </div>
            <p className="text-xs text-neutral-400 mt-1 max-w-2xl leading-relaxed">
              Statutory surveillance and pricing index weighted according to Directorate General of Civil Aviation passenger traffic returns.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {/* Search Input */}
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
              <input
                type="text"
                placeholder="Search corridor or city..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-8 pr-3 py-1.5 text-xs bg-neutral-900 border border-neutral-800 rounded text-neutral-200 placeholder-neutral-500 focus:outline-none focus:border-neutral-700 w-48 sm:w-56 font-mono"
              />
            </div>

            {/* Filter Toggle */}
            <div className="flex items-center rounded border border-neutral-800 bg-neutral-900 p-0.5 text-xs font-mono">
              <button
                onClick={() => setFilterSeverity('ALL')}
                className={`px-2.5 py-1 rounded transition-colors ${
                  filterSeverity === 'ALL'
                    ? 'bg-neutral-800 text-white font-medium'
                    : 'text-neutral-400 hover:text-neutral-200'
                }`}
              >
                All (10)
              </button>
              <button
                onClick={() => setFilterSeverity('ALERTS_ONLY')}
                className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1 ${
                  filterSeverity === 'ALERTS_ONLY'
                    ? 'border border-red-500/30 text-red-400 bg-red-950/20 font-medium'
                    : 'text-neutral-400 hover:text-red-400'
                }`}
              >
                <AlertTriangle className="w-3 h-3 text-red-400" />
                Alerts Active
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Corridor Benchmark Comparison Chart */}
      <div className="border border-neutral-800 bg-neutral-950 rounded-lg p-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
          <div>
            <h3 className="text-xs font-medium uppercase tracking-wider text-neutral-400">
              Corridor Price Index vs National Benchmark
            </h3>
            <p className="text-xs text-neutral-500 mt-0.5">
              National baseline indexed at{' '}
              <span className="font-mono text-white font-medium">{nationalIndex.toFixed(2)}</span>
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs font-mono">
            <span className="flex items-center gap-1.5 text-neutral-300">
              <span className="w-2 h-2 bg-white rounded-sm inline-block"></span> &ge; Benchmark
            </span>
            <span className="flex items-center gap-1.5 text-neutral-400">
              <span className="w-2 h-2 bg-neutral-600 rounded-sm inline-block"></span> &lt; Benchmark
            </span>
          </div>
        </div>

        <div className="h-52 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={barChartData} margin={{ top: 10, right: 10, left: -20, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" vertical={false} />
              <XAxis
                dataKey="route"
                stroke="#737373"
                tick={{ fontSize: 11, fill: '#a3a3a3' }}
                interval={0}
                angle={-20}
                textAnchor="end"
                axisLine={{ stroke: '#262626' }}
                tickLine={false}
              />
              <YAxis
                domain={[95, 140]}
                stroke="#737373"
                tick={{ fontSize: 11, fill: '#a3a3a3' }}
                axisLine={{ stroke: '#262626' }}
                tickLine={false}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0a0a0a',
                  borderColor: '#262626',
                  borderRadius: '0.375rem',
                  fontSize: '12px',
                  fontFamily: 'monospace',
                  color: '#e5e5e5',
                }}
                formatter={(val: unknown) => [
                  typeof val === 'number' ? val.toFixed(1) : String(val),
                  'Index Value',
                ]}
              />
              <ReferenceLine
                y={nationalIndex}
                stroke="#737373"
                strokeDasharray="4 4"
                label={{
                  value: `Benchmark (${nationalIndex.toFixed(1)})`,
                  fill: '#a3a3a3',
                  fontSize: 10,
                  position: 'insideTopRight',
                }}
              />
              <Bar dataKey="index" radius={[2, 2, 0, 0]}>
                {barChartData.map((entry) => (
                  <Cell
                    key={`cell-${entry.route}`}
                    fill={entry.index >= nationalIndex ? '#ffffff' : '#525252'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Main Corridor Table: 12-Column Semantic Layout */}
      <div className="border border-neutral-800 bg-neutral-950 rounded-lg overflow-hidden">
        <div className="p-4 border-b border-neutral-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-medium uppercase tracking-wider text-neutral-400">
              Domestic Trunk Route Directory
            </h3>
            <span className="text-xs text-neutral-500 font-mono tabular-nums">
              ({processedRoutes.length} corridors)
            </span>
          </div>
          <span className="text-[11px] text-neutral-500 font-mono">
            Click row for corridor breakdown
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs table-fixed">
            <colgroup>
              <col className="w-[28%]" /> {/* Corridor: 3.5 cols */}
              <col className="w-[14%]" /> {/* DGCA Weight: 1.7 cols */}
              <col className="w-[17%]" /> {/* Median Fare: 2 cols */}
              <col className="w-[13%]" /> {/* Price Index: 1.5 cols */}
              <col className="w-[12%]" /> {/* 24h / 7d Delta: 1.4 cols */}
              <col className="w-[8%]" />  {/* Sparkline: 1 col */}
              <col className="w-[8%]" />  {/* Surveillance Status: 1 col */}
            </colgroup>
            <thead>
              <tr className="border-b border-neutral-800 bg-neutral-900/40 text-neutral-400 text-xs font-medium uppercase tracking-wider select-none">
                {/* Corridor (Left) */}
                <th
                  onClick={() => handleSort('route_code')}
                  className="py-3 px-4 font-medium text-left cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Corridor</span>
                    <ArrowUpDown className="w-3 h-3 text-neutral-500" />
                  </div>
                </th>

                {/* DGCA Passenger Weight (Right) */}
                <th
                  onClick={() => handleSort('weight')}
                  className="py-3 px-4 font-medium text-right font-mono tabular-nums cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center justify-end gap-1.5">
                    <span>DGCA Weight</span>
                    <ArrowUpDown className="w-3 h-3 text-neutral-500" />
                  </div>
                </th>

                {/* Median Fare (Right) */}
                <th
                  onClick={() => handleSort('median_fare_inr')}
                  className="py-3 px-4 font-medium text-right font-mono tabular-nums cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center justify-end gap-1.5">
                    <span>Median Fare</span>
                    <ArrowUpDown className="w-3 h-3 text-neutral-500" />
                  </div>
                </th>

                {/* Current Index (Right) */}
                <th
                  onClick={() => handleSort('current_index')}
                  className="py-3 px-4 font-medium text-right font-mono tabular-nums cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center justify-end gap-1.5">
                    <span>Price Index</span>
                    <ArrowUpDown className="w-3 h-3 text-neutral-500" />
                  </div>
                </th>

                {/* 24h & 7d Change (Right) */}
                <th
                  onClick={() => handleSort('change_24h')}
                  className="py-3 px-4 font-medium text-right font-mono tabular-nums cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center justify-end gap-1.5">
                    <span>24h / 7d Delta</span>
                    <ArrowUpDown className="w-3 h-3 text-neutral-500" />
                  </div>
                </th>

                {/* 7-Day Sparkline (Right) */}
                <th className="py-3 px-4 font-medium text-right font-mono text-neutral-400">
                  <span>7d Trend</span>
                </th>

                {/* Surveillance Status (Right) */}
                <th
                  onClick={() => handleSort('anomaly_count')}
                  className="py-3 px-4 font-medium text-right cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center justify-end gap-1.5">
                    <span>Status</span>
                    <ArrowUpDown className="w-3 h-3 text-neutral-500" />
                  </div>
                </th>
              </tr>
            </thead>

            <tbody className="divide-y divide-neutral-800">
              {processedRoutes.map((route) => {
                const isSelected = route.route_code === selectedRouteCode;
                const routeAlerts = routeAnomalyMap[route.route_code] || [];
                const critAlerts = routeAlerts.filter((a) => a.severity === 'CRITICAL');
                const highAlerts = routeAlerts.filter((a) => a.severity === 'HIGH');
                const hasAnomalies = routeAlerts.length > 0 || ((route.anomaly_count ?? 0) > 0);
                const isSurge = route.change_24h > 1.0;

                const rAny = route as unknown as Record<string, number | undefined>;
                const medianFare = route.median_fare_inr ?? rAny.median_fare ?? rAny.avg_fare_inr ?? 0;
                const minFare = route.min_fare_inr ?? rAny.min_fare ?? 0;
                const maxFare = route.max_fare_inr ?? rAny.max_fare ?? 0;

                return (
                  <tr
                    key={route.route_code}
                    onClick={() => setSelectedRouteCode(isSelected ? null : route.route_code)}
                    className={`cursor-pointer transition-colors ${
                      isSelected
                        ? 'bg-neutral-900 text-white'
                        : 'hover:bg-neutral-900/40 text-neutral-300'
                    }`}
                  >
                    {/* Corridor (Left) */}
                    <td className="py-3 px-4">
                      <div className="flex items-baseline gap-2">
                        <span className="font-bold text-white font-mono text-sm tracking-tight">
                          {route.route_code}
                        </span>
                        <span className="text-xs text-neutral-400 truncate">
                          {route.origin_city || route.origin} → {route.destination_city || route.destination}
                        </span>
                      </div>
                      <div className="text-[11px] text-neutral-500 font-mono mt-0.5">
                        {route.origin}–{route.destination} • {route.distance_km ?? 1150} km • {route.active_airlines_count || 4} airlines
                      </div>
                    </td>

                    {/* DGCA Weight (Right) */}
                    <td className="py-3 px-4 text-right font-mono tabular-nums">
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-14 bg-neutral-900 border border-neutral-800 rounded-sm h-1 overflow-hidden hidden sm:block">
                          <div
                            className="bg-neutral-400 h-full rounded-sm"
                            style={{ width: `${Math.min(100, (((route.weight ?? 0.1)) / 0.16) * 100)}%` }}
                          />
                        </div>
                        <span className="font-medium text-neutral-200">
                          {((route.weight ?? 0.1) * 100).toFixed(1)}%
                        </span>
                      </div>
                    </td>

                    {/* Median Fare (Right) */}
                    <td className="py-3 px-4 text-right font-mono tabular-nums">
                      <div className="font-semibold text-white">
                        ₹{medianFare.toLocaleString('en-IN')}
                      </div>
                      <div className="text-[10px] text-neutral-500 mt-0.5">
                        ₹{minFare.toLocaleString('en-IN')} – ₹{maxFare.toLocaleString('en-IN')}
                      </div>
                    </td>

                    {/* Current Index (Right) */}
                    <td className="py-3 px-4 text-right font-mono tabular-nums">
                      <span className="font-semibold text-white">
                        {(route.current_index ?? 100).toFixed(1)}
                      </span>
                      <span className="text-[10px] text-neutral-500 block mt-0.5">
                        {((route.current_index ?? 100) - (nationalIndex ?? 100)) >= 0 ? '+' : ''}
                        {((route.current_index ?? 100) - (nationalIndex ?? 100)).toFixed(1)} vs natl
                      </span>
                    </td>

                    {/* 24h & 7d Changes (Right) */}
                    <td className="py-3 px-4 text-right font-mono tabular-nums">
                      <div className="font-medium text-neutral-200">
                        {(route.change_24h ?? 0) >= 0 ? `+${(route.change_24h ?? 0).toFixed(1)}%` : `${(route.change_24h ?? 0).toFixed(1)}%`}
                      </div>
                      <div className="text-[10px] text-neutral-500 mt-0.5">
                        {route.change_7d !== undefined && route.change_7d !== null
                          ? (route.change_7d >= 0 ? `+${Number(route.change_7d).toFixed(1)}%` : `${Number(route.change_7d).toFixed(1)}%`)
                          : '—'} 7d
                      </div>
                    </td>
                    {/* 7-Day Sparkline (Right) */}
                    <td className="py-3 px-4 text-right">
                      <Sparkline
                        data={route.sparkline_7d || [medianFare * 0.96, medianFare]}
                        isSurge={isSurge}
                      />
                    </td>

                    {/* Surveillance Status (Right) */}
                    <td className="py-3 px-4 text-right">
                      <div className="flex justify-end">
                        {critAlerts.length > 0 || route.max_severity === 'CRITICAL' ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-medium border border-red-500/30 text-red-400 bg-red-950/20">
                            <span>CRITICAL ({critAlerts.length || route.anomaly_count || 1})</span>
                          </span>
                        ) : highAlerts.length > 0 || route.max_severity === 'HIGH' ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-medium border border-amber-500/30 text-amber-400 bg-amber-950/20">
                            <span>WARNING ({highAlerts.length || route.anomaly_count || 1})</span>
                          </span>
                        ) : hasAnomalies ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-medium border border-neutral-700 text-neutral-300 bg-neutral-900">
                            <span>ALERT ({routeAlerts.length || route.anomaly_count || 1})</span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-medium border border-neutral-800 text-neutral-400 bg-neutral-900/40">
                            <span>COMPLIANT</span>
                          </span>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Selected Route Inspection Detail Drawer */}
      {selectedRoute && (
        <div className="border border-neutral-700 bg-neutral-950 rounded-lg p-6 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-neutral-800 pb-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-white font-mono">
                  {selectedRoute.route_code}
                </span>
                <span className="text-sm text-neutral-300">
                  {selectedRoute.origin_city} ({selectedRoute.origin}) ⇄ {selectedRoute.destination_city} ({selectedRoute.destination})
                </span>
              </div>
              {(() => {
                const selAny = selectedRoute as unknown as Record<string, number | undefined>;
                const selSampleSize = selectedRoute.sample_size ?? selAny.active_flights_tracked ?? 0;
                return (
                  <p className="text-xs text-neutral-500 font-mono mt-0.5">
                    Detailed corridor telemetry • Sample size:{' '}
                    {selSampleSize.toLocaleString()} observations
                  </p>
                );
              })()}
            </div>

            <button
              onClick={() => setSelectedRouteCode(null)}
              className="text-xs text-neutral-400 hover:text-white px-2.5 py-1 rounded border border-neutral-800 bg-neutral-900 transition-colors w-fit"
            >
              Close Detail
            </button>
          </div>

          {(() => {
            const selAny = selectedRoute as unknown as Record<string, number | undefined>;
            const selMedianFare = selectedRoute.median_fare_inr ?? selAny.median_fare ?? 0;
            const selMinFare = selectedRoute.min_fare_inr ?? selAny.min_fare ?? 0;
            const selMaxFare = selectedRoute.max_fare_inr ?? selAny.max_fare ?? 0;

            return (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div className="bg-neutral-900/40 p-3.5 rounded border border-neutral-800">
                  <span className="text-[11px] text-neutral-400 uppercase font-mono">DGCA Passenger Share</span>
                  <div className="text-base font-semibold text-white font-mono tabular-nums mt-1">
                    {((selectedRoute.weight ?? 0.1) * 100).toFixed(2)}%
                  </div>
                  <span className="text-[10px] text-neutral-500">Trunk Corridor Priority</span>
                </div>

                <div className="bg-neutral-900/40 p-3.5 rounded border border-neutral-800">
                  <span className="text-[11px] text-neutral-400 uppercase font-mono">Representative Fare Band</span>
                  <div className="text-base font-semibold text-white font-mono tabular-nums mt-1">
                    ₹{selMedianFare.toLocaleString('en-IN')}
                  </div>
                  <span className="text-[10px] text-neutral-500">
                    Floor ₹{selMinFare.toLocaleString('en-IN')} • Ceiling ₹{selMaxFare.toLocaleString('en-IN')}
                  </span>
                </div>

                <div className="bg-neutral-900/40 p-3.5 rounded border border-neutral-800">
                  <span className="text-[11px] text-neutral-400 uppercase font-mono">7-Day Trajectory</span>
                  <div className="text-base font-semibold font-mono tabular-nums mt-1 text-white">
                    {selectedRoute.change_7d !== undefined && selectedRoute.change_7d !== null
                      ? (selectedRoute.change_7d >= 0 ? `+${Number(selectedRoute.change_7d).toFixed(1)}%` : `${Number(selectedRoute.change_7d).toFixed(1)}%`)
                      : '—'}
                  </div>
                  <span className="text-[10px] text-neutral-500">
                    24-hour delta: {selectedRoute.change_24h !== undefined ? `${selectedRoute.change_24h}%` : '0%'}
                  </span>
                </div>

                <div className="bg-neutral-900/40 p-3.5 rounded border border-neutral-800">
                  <span className="text-[11px] text-neutral-400 uppercase font-mono">Regulatory Oversight</span>
                  <div className="text-base font-semibold font-mono tabular-nums mt-1 text-neutral-200">
                    {selectedRouteAlerts.length} Active Alerts
                  </div>
                  <span className="text-[10px] text-neutral-500">Automated 3-sigma audit</span>
                </div>
              </div>
            );
          })()}

          {/* Active alerts for this route */}
          {selectedRouteAlerts.length > 0 ? (
            <div className="mt-3 p-4 rounded border border-neutral-800 bg-neutral-900/50 space-y-2">
              <div className="text-xs font-semibold text-neutral-200 flex items-center gap-1.5 font-mono">
                <ShieldAlert className="w-3.5 h-3.5 text-red-400" />
                Active Anomaly Incidents for {selectedRoute.route_code}:
              </div>
              {selectedRouteAlerts.map((alt) => {
                const aAny = alt as unknown as Record<string, number | undefined>;
                const altObserved = alt.observed_fare_inr ?? aAny.fare_inr ?? aAny.observed_fare ?? 0;
                return (
                  <div
                    key={alt.id}
                    className="text-xs text-neutral-300 flex items-center justify-between font-mono bg-neutral-950 border border-neutral-800 p-2.5 rounded"
                  >
                    <span>
                      {alt.airline_code} {alt.flight_number} • {alt.anomaly_type} • Observed ₹{altObserved.toLocaleString('en-IN')} (Z={alt.z_score ?? 3.2})
                    </span>
                    <span className="text-red-400 font-semibold tabular-nums">+{alt.deviation_percent}%</span>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="p-3 rounded border border-neutral-800 bg-neutral-900/30 text-xs text-neutral-400 flex items-center gap-2 font-mono">
              <CheckCircle2 className="w-3.5 h-3.5 text-neutral-400" />
              <span>No algorithmic price gouging or statutory band breaches currently flagged on this corridor.</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
