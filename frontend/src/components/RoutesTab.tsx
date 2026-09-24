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
  Plane,
  ArrowUpDown,
  Search,
  TrendingUp,
  TrendingDown,
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

// Inline SVG 7-Day Sparkline component
const Sparkline: React.FC<{ data?: number[]; isSurge?: boolean }> = ({ data, isSurge }) => {
  if (!data || data.length < 2) {
    return <span className="text-slate-600 font-mono text-[11px]">—</span>;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const width = 84;
  const height = 24;
  const points = data
    .map((val, idx) => {
      const x = (idx / (data.length - 1)) * (width - 8) + 4;
      const y = height - 4 - ((val - min) / range) * (height - 8);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  const strokeColor = isSurge ? '#f43f5e' : '#10b981';
  const lastX = width - 4;
  const lastY = height - 4 - ((data[data.length - 1] - min) / range) * (height - 8);

  return (
    <div className="flex items-center gap-1.5" title={`7-day trend: ₹${min.toLocaleString()} to ₹${max.toLocaleString()}`}>
      <svg width={width} height={height} className="overflow-visible">
        <polyline
          fill="none"
          stroke={strokeColor}
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
          points={points}
        />
        <circle cx={lastX} cy={lastY} r="2.5" fill={strokeColor} />
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
        r.route_code.toLowerCase().includes(term) ||
        r.origin_city.toLowerCase().includes(term) ||
        r.destination_city.toLowerCase().includes(term) ||
        r.origin.toLowerCase().includes(term) ||
        r.destination.toLowerCase().includes(term);

      if (!matchesSearch) return false;

      if (filterSeverity === 'ALERTS_ONLY') {
        const routeAlerts = routeAnomalyMap[r.route_code] || [];
        return routeAlerts.length > 0 || (r.anomaly_count && r.anomaly_count > 0);
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
      .sort((a, b) => b.weight - a.weight)
      .map((r) => ({
        route: r.route_code,
        index: r.current_index,
        diff: Number((r.current_index - nationalIndex).toFixed(1)),
        weight: (r.weight * 100).toFixed(1),
        fare: r.median_fare_inr,
      }));
  }, [routes, nationalIndex]);

  const totalMonitoredWeight = routes.reduce((acc, r) => acc + r.weight, 0);

  return (
    <div className="space-y-6">
      {/* Top Banner and Search/Filter Controls */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <Plane className="w-5 h-5 text-sky-400" />
                DGCA High-Density Domestic Trunk Corridors
              </h2>
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-sky-950 text-sky-300 border border-sky-800 font-mono">
                10 Routes • {(totalMonitoredWeight * 100).toFixed(1)}% Traffic Share
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Statutory surveillance and pricing index weighted according to Directorate General of Civil Aviation passenger traffic returns.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Search Input */}
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search corridor or city..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-9 pr-3 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500 w-48 sm:w-60"
              />
            </div>

            {/* Filter Toggle */}
            <div className="flex items-center rounded-lg bg-slate-950 border border-slate-800 p-0.5 text-xs font-mono">
              <button
                onClick={() => setFilterSeverity('ALL')}
                className={`px-2.5 py-1 rounded-md transition-all ${
                  filterSeverity === 'ALL'
                    ? 'bg-slate-800 text-white font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                All (10)
              </button>
              <button
                onClick={() => setFilterSeverity('ALERTS_ONLY')}
                className={`px-2.5 py-1 rounded-md transition-all flex items-center gap-1 ${
                  filterSeverity === 'ALERTS_ONLY'
                    ? 'bg-rose-900/60 text-rose-300 font-semibold border border-rose-800/60'
                    : 'text-slate-400 hover:text-rose-300'
                }`}
              >
                <AlertTriangle className="w-3 h-3 text-rose-400" />
                Alerts Active
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Corridor Benchmark Comparison Chart */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-md">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
          <div>
            <h3 className="text-sm font-bold text-white">Corridor Price Index vs National Benchmark</h3>
            <p className="text-xs text-slate-400">
              National Laspeyres baseline is indexed at{' '}
              <span className="font-mono text-rose-400 font-bold">{nationalIndex.toFixed(2)}</span>
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <span className="flex items-center gap-1 text-sky-400">
              <span className="w-2.5 h-2.5 bg-sky-400 rounded-sm inline-block"></span> Above National
            </span>
            <span className="flex items-center gap-1 text-indigo-400">
              <span className="w-2.5 h-2.5 bg-indigo-400 rounded-sm inline-block"></span> Below National
            </span>
          </div>
        </div>

        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={barChartData} margin={{ top: 10, right: 10, left: -20, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis
                dataKey="route"
                stroke="#64748b"
                tick={{ fontSize: 11 }}
                interval={0}
                angle={-20}
                textAnchor="end"
              />
              <YAxis domain={[95, 140]} stroke="#64748b" tick={{ fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: '#334155',
                  borderRadius: '0.5rem',
                  fontSize: '12px',
                }}
                formatter={(val: unknown) => [
                  typeof val === 'number' ? val.toFixed(1) : String(val),
                  'Index Value',
                ]}
              />
              <ReferenceLine
                y={nationalIndex}
                stroke="#f43f5e"
                strokeDasharray="4 4"
                label={{
                  value: `National Avg (${nationalIndex.toFixed(1)})`,
                  fill: '#f43f5e',
                  fontSize: 10,
                  position: 'insideTopRight',
                }}
              />
              <Bar dataKey="index" radius={[4, 4, 0, 0]}>
                {barChartData.map((entry) => (
                  <Cell
                    key={`cell-${entry.route}`}
                    fill={entry.index >= nationalIndex ? '#38bdf8' : '#818cf8'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Main Corridor Table: Searchable, Sortable, DGCA Weights, Median Fares, Sparklines, Badges */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl overflow-hidden backdrop-blur-md shadow-lg">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <span>Domestic Trunk Route Directory</span>
            <span className="text-xs text-slate-500 font-mono">({processedRoutes.length} matching)</span>
          </h3>
          <span className="text-xs text-slate-400">Click any row to inspect airline inventory breakdown</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/60 text-slate-400 select-none">
                {/* Route */}
                <th
                  onClick={() => handleSort('route_code')}
                  className="py-3 px-4 font-medium cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Corridor</span>
                    <ArrowUpDown className="w-3 h-3 text-slate-500" />
                  </div>
                </th>

                {/* DGCA Passenger Weight */}
                <th
                  onClick={() => handleSort('weight')}
                  className="py-3 px-4 font-medium cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>DGCA Weight</span>
                    <ArrowUpDown className="w-3 h-3 text-slate-500" />
                  </div>
                </th>

                {/* Median Fare */}
                <th
                  onClick={() => handleSort('median_fare_inr')}
                  className="py-3 px-4 font-medium cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Median Fare</span>
                    <ArrowUpDown className="w-3 h-3 text-slate-500" />
                  </div>
                </th>

                {/* Current Index */}
                <th
                  onClick={() => handleSort('current_index')}
                  className="py-3 px-4 font-medium cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>Price Index</span>
                    <ArrowUpDown className="w-3 h-3 text-slate-500" />
                  </div>
                </th>

                {/* 24h & 7d Change */}
                <th
                  onClick={() => handleSort('change_24h')}
                  className="py-3 px-4 font-medium cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center gap-1.5">
                    <span>24h / 7d Delta</span>
                    <ArrowUpDown className="w-3 h-3 text-slate-500" />
                  </div>
                </th>

                {/* 7-Day Sparkline */}
                <th className="py-3 px-4 font-medium text-center">
                  <span>7-Day Sparkline</span>
                </th>

                {/* Anomaly Alert Badge */}
                <th
                  onClick={() => handleSort('anomaly_count')}
                  className="py-3 px-4 font-medium text-right cursor-pointer hover:text-white transition-colors"
                >
                  <div className="flex items-center justify-end gap-1.5">
                    <span>Surveillance Status</span>
                    <ArrowUpDown className="w-3 h-3 text-slate-500" />
                  </div>
                </th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-800/60 font-mono">
              {processedRoutes.map((route) => {
                const isSelected = route.route_code === selectedRouteCode;
                const routeAlerts = routeAnomalyMap[route.route_code] || [];
                const critAlerts = routeAlerts.filter((a) => a.severity === 'CRITICAL');
                const highAlerts = routeAlerts.filter((a) => a.severity === 'HIGH');
                const hasAnomalies = routeAlerts.length > 0 || (route.anomaly_count && route.anomaly_count > 0);
                const isSurge = route.change_24h > 1.0;

                return (
                  <tr
                    key={route.route_code}
                    onClick={() => setSelectedRouteCode(isSelected ? null : route.route_code)}
                    className={`cursor-pointer transition-colors ${
                      isSelected
                        ? 'bg-sky-950/40 hover:bg-sky-950/50'
                        : 'hover:bg-slate-800/40'
                    }`}
                  >
                    {/* Route Corridor */}
                    <td className="py-3.5 px-4 font-sans">
                      <div className="flex items-center gap-2">
                        <span className="font-extrabold text-sm text-white font-mono">
                          {route.route_code} • {route.origin} → {route.destination}
                        </span>
                        <span className="text-[11px] text-slate-400 font-normal">
                          ({route.origin_city} - {route.destination_city})
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                        {route.distance_km} km • {route.active_airlines_count || 4} airlines operating
                      </div>
                    </td>

                    {/* DGCA Weight */}
                    <td className="py-3.5 px-4 text-slate-200">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white w-12">
                          {(route.weight * 100).toFixed(1)}%
                        </span>
                        <div className="w-20 bg-slate-800 rounded-full h-1.5 overflow-hidden">
                          <div
                            className="bg-sky-400 h-1.5 rounded-full"
                            style={{ width: `${Math.min(100, (route.weight / 0.16) * 100)}%` }}
                          ></div>
                        </div>
                      </div>
                    </td>

                    {/* Median Fare */}
                    <td className="py-3.5 px-4">
                      <div className="font-bold text-white text-sm">
                        ₹{route.median_fare_inr.toLocaleString('en-IN')}
                      </div>
                      <div className="text-[10px] text-slate-500">
                        ₹{route.min_fare_inr?.toLocaleString('en-IN')} – ₹{route.max_fare_inr?.toLocaleString('en-IN')}
                      </div>
                    </td>

                    {/* Current Index */}
                    <td className="py-3.5 px-4">
                      <span
                        className={`font-extrabold text-sm ${
                          route.current_index >= nationalIndex ? 'text-sky-400' : 'text-indigo-400'
                        }`}
                      >
                        {route.current_index.toFixed(1)}
                      </span>
                      <span className="text-[10px] text-slate-500 block">
                        {route.current_index >= nationalIndex ? '+' : ''}
                        {(route.current_index - nationalIndex).toFixed(1)} vs natl
                      </span>
                    </td>

                    {/* 24h & 7d Changes */}
                    <td className="py-3.5 px-4">
                      <div
                        className={`flex items-center gap-1 font-semibold ${
                          route.change_24h >= 0 ? 'text-rose-400' : 'text-emerald-400'
                        }`}
                      >
                        {route.change_24h >= 0 ? (
                          <TrendingUp className="w-3.5 h-3.5" />
                        ) : (
                          <TrendingDown className="w-3.5 h-3.5" />
                        )}
                        <span>{route.change_24h >= 0 ? `+${route.change_24h}%` : `${route.change_24h}%`}</span>
                      </div>
                      <div
                        className={`text-[10px] ${
                          route.change_7d >= 0 ? 'text-amber-400' : 'text-emerald-400'
                        }`}
                      >
                        {route.change_7d >= 0 ? `+${route.change_7d}%` : `${route.change_7d}%`} 7d
                      </div>
                    </td>

                    {/* 7-Day Sparkline */}
                    <td className="py-3.5 px-4 text-center">
                      <div className="flex justify-center">
                        <Sparkline
                          data={route.sparkline_7d || [route.median_fare_inr * 0.96, route.median_fare_inr]}
                          isSurge={isSurge}
                        />
                      </div>
                    </td>

                    {/* Anomaly Alert Badge */}
                    <td className="py-3.5 px-4 text-right">
                      {critAlerts.length > 0 || route.max_severity === 'CRITICAL' ? (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold bg-rose-950 text-rose-300 border border-rose-800 shadow-sm animate-pulse">
                          <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
                          <span>CRITICAL ({critAlerts.length || route.anomaly_count})</span>
                        </span>
                      ) : highAlerts.length > 0 || route.max_severity === 'HIGH' ? (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-950 text-amber-300 border border-amber-800 shadow-sm">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span>
                          <span>WARNING ({highAlerts.length || route.anomaly_count})</span>
                        </span>
                      ) : hasAnomalies ? (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold bg-indigo-950 text-indigo-300 border border-indigo-800">
                          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400"></span>
                          <span>ALERT ({routeAlerts.length || route.anomaly_count})</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-semibold bg-emerald-950/80 text-emerald-300 border border-emerald-800/80">
                          <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                          <span>COMPLIANT</span>
                        </span>
                      )}
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
        <div className="bg-slate-900 border border-sky-500/50 rounded-xl p-6 shadow-xl backdrop-blur-md space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xl font-extrabold text-white font-mono">
                  {selectedRoute.route_code}
                </span>
                <span className="text-sm text-slate-300">
                  {selectedRoute.origin_city} ({selectedRoute.origin}) ⇄ {selectedRoute.destination_city} ({selectedRoute.destination})
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Detailed corridor telemetry • Sample size: {selectedRoute.sample_size.toLocaleString()} observations
              </p>
            </div>

            <button
              onClick={() => setSelectedRouteCode(null)}
              className="text-xs text-slate-400 hover:text-white px-2.5 py-1 rounded bg-slate-800 w-fit"
            >
              Close Detail
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-slate-950/60 p-3.5 rounded-lg border border-slate-800">
              <span className="text-[11px] text-slate-400">DGCA Passenger Share</span>
              <div className="text-lg font-bold text-white font-mono mt-1">
                {(selectedRoute.weight * 100).toFixed(2)}%
              </div>
              <span className="text-[10px] text-slate-500">Ranking: Trunk Corridor Priority</span>
            </div>

            <div className="bg-slate-950/60 p-3.5 rounded-lg border border-slate-800">
              <span className="text-[11px] text-slate-400">Representative Fare Band</span>
              <div className="text-lg font-bold text-white font-mono mt-1">
                ₹{selectedRoute.median_fare_inr.toLocaleString('en-IN')}
              </div>
              <span className="text-[10px] text-slate-500">
                Floor ₹{selectedRoute.min_fare_inr?.toLocaleString('en-IN')} • Ceiling ₹{selectedRoute.max_fare_inr?.toLocaleString('en-IN')}
              </span>
            </div>

            <div className="bg-slate-950/60 p-3.5 rounded-lg border border-slate-800">
              <span className="text-[11px] text-slate-400">7-Day Trajectory</span>
              <div className="text-lg font-bold font-mono mt-1 flex items-center gap-1 text-amber-400">
                {selectedRoute.change_7d >= 0 ? '+' : ''}{selectedRoute.change_7d}%
              </div>
              <span className="text-[10px] text-slate-500">24-hour delta: {selectedRoute.change_24h}%</span>
            </div>

            <div className="bg-slate-950/60 p-3.5 rounded-lg border border-slate-800">
              <span className="text-[11px] text-slate-400">Regulatory Oversight</span>
              <div className="text-lg font-bold font-mono mt-1 text-rose-400">
                {selectedRouteAlerts.length} Surveillance Alerts
              </div>
              <span className="text-[10px] text-slate-500">Automated 3-sigma audit</span>
            </div>
          </div>

          {/* Active alerts for this route */}
          {selectedRouteAlerts.length > 0 ? (
            <div className="mt-3 p-4 rounded-lg bg-rose-950/20 border border-rose-800/50 space-y-2">
              <div className="text-xs font-bold text-rose-300 flex items-center gap-1.5">
                <ShieldAlert className="w-4 h-4 text-rose-400" />
                Active Anomaly Incidents for {selectedRoute.route_code}:
              </div>
              {selectedRouteAlerts.map((alt) => (
                <div key={alt.id} className="text-xs text-slate-300 flex items-center justify-between font-mono bg-slate-950/80 p-2 rounded">
                  <span>
                    {alt.airline_code} {alt.flight_number} • {alt.anomaly_type} • Observed ₹{alt.observed_fare_inr.toLocaleString('en-IN')} (Z={alt.z_score ?? 3.2})
                  </span>
                  <span className="text-rose-400 font-bold">+{alt.deviation_percent}%</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-3 rounded-lg bg-emerald-950/20 border border-emerald-800/40 text-xs text-emerald-300 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span>No algorithmic price gouging or statutory band breaches currently flagged on this corridor.</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
