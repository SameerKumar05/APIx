import React, { useState } from 'react';
import { RouteOverviewItem } from '../types/api';
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
  SlidersHorizontal,
  TrendingUp,
  TrendingDown,
  Navigation,
} from 'lucide-react';

interface RoutesTabProps {
  routes: RouteOverviewItem[];
  nationalIndex: number;
}

type SortField = 'weight' | 'current_index' | 'median_fare_inr' | 'change_24h';

export const RoutesTab: React.FC<RoutesTabProps> = ({ routes, nationalIndex }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [sortField, setSortField] = useState<SortField>('weight');
  const [sortAsc, setSortAsc] = useState(false);
  const [selectedRouteCode, setSelectedRouteCode] = useState<string | null>(null);

  const filteredRoutes = routes.filter((r) => {
    const term = searchTerm.toLowerCase();
    return (
      r.route_code.toLowerCase().includes(term) ||
      r.origin_city.toLowerCase().includes(term) ||
      r.destination_city.toLowerCase().includes(term) ||
      r.origin.toLowerCase().includes(term) ||
      r.destination.toLowerCase().includes(term)
    );
  });

  filteredRoutes.sort((a, b) => {
    const factor = sortAsc ? 1 : -1;
    return (a[sortField] - b[sortField]) * factor;
  });

  const barChartData = [...routes]
    .sort((a, b) => b.weight - a.weight)
    .map((r) => ({
      route: r.route_code,
      index: r.current_index,
      diff: Number((r.current_index - nationalIndex).toFixed(1)),
      fare: r.median_fare_inr,
    }));

  const selectedRoute = routes.find((r) => r.route_code === selectedRouteCode);

  return (
    <div className="space-y-6">
      {/* Header and Controls */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Plane className="w-5 h-5 text-sky-400" />
              10 High-Density Domestic Trunk Corridors
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Prioritized by DGCA passenger traffic volume weighting.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Search Input */}
            <div className="relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search route or city..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-9 pr-3 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
            </div>

            {/* Sort Field */}
            <div className="flex items-center gap-2 text-xs text-slate-300">
              <SlidersHorizontal className="w-3.5 h-3.5 text-slate-400" />
              <select
                value={sortField}
                onChange={(e) => setSortField(e.target.value as SortField)}
                className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              >
                <option value="weight">Traffic Weight</option>
                <option value="current_index">Price Index</option>
                <option value="median_fare_inr">Median Fare</option>
                <option value="change_24h">24h Delta</option>
              </select>

              <button
                onClick={() => setSortAsc(!sortAsc)}
                className="p-1.5 bg-slate-950 border border-slate-800 rounded-lg text-slate-400 hover:text-white"
                title="Toggle sort direction"
              >
                <ArrowUpDown className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Comparison Chart: Route Index vs National Benchmark */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-md">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-white">Corridor Price Index vs National Benchmark</h3>
            <p className="text-xs text-slate-400">
              National weighted baseline reference at {nationalIndex.toFixed(1)}
            </p>
          </div>
          <div className="text-xs font-mono px-2 py-0.5 rounded bg-sky-950 border border-sky-800 text-sky-300">
            Base: 2026-01=100
          </div>
        </div>

        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={barChartData} margin={{ top: 10, right: 10, left: -20, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis
                dataKey="route"
                stroke="#64748b"
                tick={{ fontSize: 10 }}
                interval={0}
                angle={-25}
                textAnchor="end"
              />
              <YAxis domain={[90, 140]} stroke="#64748b" tick={{ fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: '#334155',
                  borderRadius: '0.5rem',
                  fontSize: '12px',
                }}
                formatter={(val: unknown) => [
                  typeof val === 'number' ? val.toFixed(1) : String(val),
                  'Index',
                ]}
              />
              <ReferenceLine
                y={nationalIndex}
                stroke="#ef4444"
                strokeDasharray="4 4"
                label={{
                  value: `National Avg (${nationalIndex.toFixed(1)})`,
                  fill: '#ef4444',
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

      {/* Routes Grid / Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredRoutes.map((route) => {
          const isSelected = route.route_code === selectedRouteCode;
          return (
            <div
              key={route.route_code}
              onClick={() =>
                setSelectedRouteCode(isSelected ? null : route.route_code)
              }
              className={`bg-slate-900/80 border rounded-xl p-5 cursor-pointer transition-all hover:border-slate-700 ${
                isSelected
                  ? 'border-sky-500 ring-1 ring-sky-500/50 bg-slate-900'
                  : 'border-slate-800'
              }`}
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-base font-extrabold text-white tracking-wide">
                      {route.origin}
                    </span>
                    <Navigation className="w-3.5 h-3.5 text-slate-500 rotate-90" />
                    <span className="text-base font-extrabold text-white tracking-wide">
                      {route.destination}
                    </span>
                  </div>
                  <span className="text-xs text-slate-400">
                    {route.origin_city} to {route.destination_city}
                  </span>
                </div>

                <div className="text-right">
                  <div className="text-xs font-mono font-bold text-sky-400">
                    Index: {route.current_index.toFixed(1)}
                  </div>
                  <div
                    className={`text-[11px] font-semibold flex items-center justify-end gap-0.5 ${
                      route.change_24h >= 0 ? 'text-rose-400' : 'text-emerald-400'
                    }`}
                  >
                    {route.change_24h >= 0 ? (
                      <TrendingUp className="w-3 h-3" />
                    ) : (
                      <TrendingDown className="w-3 h-3" />
                    )}
                    {route.change_24h >= 0 ? `+${route.change_24h}%` : `${route.change_24h}%`}
                  </div>
                </div>
              </div>

              {/* Stats */}
              <div className="mt-4 grid grid-cols-2 gap-2 text-xs border-t border-slate-800/80 pt-3">
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase">Median Fare</span>
                  <span className="font-mono font-bold text-white">
                    ₹{route.median_fare_inr.toLocaleString('en-IN')}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase">DGCA Weight</span>
                  <span className="font-mono font-bold text-slate-300">
                    {(route.weight * 100).toFixed(1)}% share
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase">Fare Range</span>
                  <span className="font-mono text-slate-400 text-[11px]">
                    ₹{(route.min_fare_inr || 0).toLocaleString('en-IN')} - ₹
                    {(route.max_fare_inr || 0).toLocaleString('en-IN')}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500 block text-[10px] uppercase">Sample Size</span>
                  <span className="font-mono text-slate-300 text-[11px]">
                    {route.sample_size.toLocaleString()} flights
                  </span>
                </div>
              </div>

              {/* Footer */}
              <div className="mt-3 flex items-center justify-between text-[11px] text-slate-500 pt-2 border-t border-slate-800/40">
                <span>{route.distance_km || 1000} km corridor</span>
                <span className="text-slate-400">{route.active_airlines_count || 4} airlines</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Selected Route Detail Drawer/Card */}
      {selectedRoute && (
        <div className="bg-sky-950/30 border border-sky-800/60 rounded-xl p-5 backdrop-blur-md">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <span>Selected Route Breakdown:</span>
                <span className="text-sky-300 font-mono">
                  {selectedRoute.route_code} ({selectedRoute.origin_city} ↔{' '}
                  {selectedRoute.destination_city})
                </span>
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                DGCA Air Traffic passenger weighting factor: {(selectedRoute.weight * 100).toFixed(2)}%
                of domestic index.
              </p>
            </div>
            <button
              onClick={() => setSelectedRouteCode(null)}
              className="px-3 py-1 text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition-colors"
            >
              Close Details
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
