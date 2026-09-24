import React from 'react';
import {
  NationalIndexLatestResponse,
  NationalIndexPoint,
  RouteOverviewItem,
  AnomalyAlertItem,
} from '../types/api';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';
import {
  TrendingUp,
  TrendingDown,
  Plane,
  AlertTriangle,
  Scale,
  CheckCircle2,
} from 'lucide-react';

interface OverviewTabProps {
  latest: NationalIndexLatestResponse;
  history: NationalIndexPoint[];
  routes: RouteOverviewItem[];
  anomalies: AnomalyAlertItem[];
  onSelectTab: (tab: 'overview' | 'routes' | 'elasticity' | 'anomalies') => void;
}

export const OverviewTab: React.FC<OverviewTabProps> = ({
  latest,
  history,
  routes,
  anomalies,
  onSelectTab,
}) => {
  const chartData = history.map((p) => {
    const d = new Date(p.timestamp);
    return {
      date: `${d.getDate()} ${d.toLocaleString('en-US', { month: 'short' })}`,
      index: p.index_value,
      movingAvg: p.moving_avg_7d || p.index_value,
      ciLower: p.confidence_interval_lower,
      ciUpper: p.confidence_interval_upper,
      samples: p.sample_size,
    };
  });

  const criticalCount = anomalies.filter((a) => a.severity === 'CRITICAL').length;
  const topSurgeRoute = [...routes].sort((a, b) => b.change_24h - a.change_24h)[0];

  return (
    <div className="space-y-6">
      {/* KPI Cards Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: National Index */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm relative overflow-hidden group hover:border-sky-500/50 transition-all">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>National Airfare Index</span>
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-950 text-sky-400 border border-sky-800">
              {latest.base_period}
            </span>
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-extrabold tracking-tight text-white font-mono">
              {latest.index_value.toFixed(2)}
            </span>
            <div
              className={`flex items-center text-xs font-semibold ${
                latest.change_24h >= 0 ? 'text-rose-400' : 'text-emerald-400'
              }`}
            >
              {latest.change_24h >= 0 ? (
                <TrendingUp className="w-3.5 h-3.5 mr-0.5 inline" />
              ) : (
                <TrendingDown className="w-3.5 h-3.5 mr-0.5 inline" />
              )}
              {latest.change_24h >= 0 ? `+${latest.change_24h}%` : `${latest.change_24h}%`} (24h)
            </div>
          </div>
          <div className="mt-3 text-xs text-slate-400 flex items-center justify-between border-t border-slate-800/80 pt-2.5">
            <span>7-day inflation:</span>
            <span
              className={`font-semibold ${
                latest.change_7d >= 0 ? 'text-amber-400' : 'text-emerald-400'
              }`}
            >
              {latest.change_7d >= 0 ? `+${latest.change_7d}%` : `${latest.change_7d}%`}
            </span>
          </div>
        </div>

        {/* Card 2: Weighted Median Fare */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm hover:border-indigo-500/50 transition-all">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>Weighted Median Fare</span>
            <Scale className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-extrabold tracking-tight text-white font-mono">
              ₹{(latest.weighted_median_fare_inr || 5480).toLocaleString('en-IN')}
            </span>
            <span className="text-xs text-slate-400 font-medium">/ pax</span>
          </div>
          <div className="mt-3 text-xs text-slate-400 flex items-center justify-between border-t border-slate-800/80 pt-2.5">
            <span>Confidence Band (95%):</span>
            <span className="font-mono text-slate-300">
              {latest.confidence_interval_lower?.toFixed(1)} – {latest.confidence_interval_upper?.toFixed(1)}
            </span>
          </div>
        </div>

        {/* Card 3: Monitored Corridors & Sample Size */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm hover:border-emerald-500/50 transition-all">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>Active Observations</span>
            <Plane className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-extrabold tracking-tight text-white font-mono">
              {latest.sample_size.toLocaleString()}
            </span>
            <span className="text-xs text-emerald-400 font-medium flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" /> Live
            </span>
          </div>
          <div className="mt-3 text-xs text-slate-400 flex items-center justify-between border-t border-slate-800/80 pt-2.5">
            <span>High-Density Routes:</span>
            <span className="font-semibold text-slate-200">{routes.length} Corridors</span>
          </div>
        </div>

        {/* Card 4: Regulatory Alert Status */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm hover:border-rose-500/50 transition-all">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>DGCA Anomaly Flags</span>
            <AlertTriangle className="w-4 h-4 text-rose-400" />
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-extrabold tracking-tight text-white font-mono">
              {anomalies.length}
            </span>
            <span className="text-xs font-semibold px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800">
              {criticalCount} Critical
            </span>
          </div>
          <div className="mt-3 text-xs text-slate-400 flex items-center justify-between border-t border-slate-800/80 pt-2.5">
            <span>Top Surge Corridor:</span>
            <span className="font-semibold text-rose-400">
              {topSurgeRoute ? `${topSurgeRoute.route_code} (+${topSurgeRoute.change_24h}%)` : 'None'}
            </span>
          </div>
        </div>
      </div>

      {/* Main Chart Section: 30-Day Index Time Series */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-6 backdrop-blur-md">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <span>National Composite Airfare Index (APIx)</span>
              <span className="text-xs font-normal px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
                Daily Aggregation (T-30 Days)
              </span>
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Weighted geometric Laspeyres-type aggregation across 10 DGCA domestic trunk routes.
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs">
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-full bg-sky-500 inline-block"></span>
              <span className="text-slate-300">Composite Index</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-full bg-emerald-500 inline-block"></span>
              <span className="text-slate-400">7-Day Moving Avg</span>
            </div>
          </div>
        </div>

        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="indexGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#0284c7" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#0284c7" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis
                dataKey="date"
                stroke="#64748b"
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
              />
              <YAxis
                domain={['auto', 'auto']}
                stroke="#64748b"
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: '#334155',
                  borderRadius: '0.5rem',
                  fontSize: '12px',
                  boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.5)',
                }}
                labelStyle={{ color: '#94a3b8', fontWeight: 600, marginBottom: '4px' }}
                formatter={(val: unknown) => [
                  typeof val === 'number' ? val.toFixed(2) : String(val),
                  'Index Value',
                ]}
              />
              <Area
                type="monotone"
                dataKey="index"
                stroke="#38bdf8"
                strokeWidth={2.5}
                fillOpacity={1}
                fill="url(#indexGradient)"
              />
              <Area
                type="monotone"
                dataKey="movingAvg"
                stroke="#10b981"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                fill="none"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Two Column Grid: Top Corridors & Urgent Anomaly Snapshot */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Corridors Mini-Table */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Plane className="w-4 h-4 text-sky-400" />
              High-Traffic Corridors (DGCA Weight)
            </h3>
            <button
              onClick={() => onSelectTab('routes')}
              className="text-xs text-sky-400 hover:text-sky-300 font-medium transition-colors"
            >
              View All 10 →
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th className="pb-2.5 font-medium">Route</th>
                  <th className="pb-2.5 font-medium">Weight</th>
                  <th className="pb-2.5 font-medium">Median Fare</th>
                  <th className="pb-2.5 font-medium">Current Index</th>
                  <th className="pb-2.5 font-medium text-right">24h</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {routes.slice(0, 5).map((route) => (
                  <tr key={route.route_code} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-2.5 font-sans font-semibold text-white">
                      {route.origin} → {route.destination}
                      <span className="block text-[10px] text-slate-400 font-normal">
                        {route.origin_city} - {route.destination_city}
                      </span>
                    </td>
                    <td className="py-2.5 text-slate-300">{(route.weight * 100).toFixed(1)}%</td>
                    <td className="py-2.5 text-white">₹{route.median_fare_inr.toLocaleString('en-IN')}</td>
                    <td className="py-2.5 text-sky-400">{route.current_index.toFixed(1)}</td>
                    <td
                      className={`py-2.5 text-right font-semibold ${
                        route.change_24h >= 0 ? 'text-rose-400' : 'text-emerald-400'
                      }`}
                    >
                      {route.change_24h >= 0 ? `+${route.change_24h}%` : `${route.change_24h}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Urgent Anomaly Warnings Mini-List */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-rose-400" />
              Active DGCA Surveillance Alerts
            </h3>
            <button
              onClick={() => onSelectTab('anomalies')}
              className="text-xs text-rose-400 hover:text-rose-300 font-medium transition-colors"
            >
              Surveillance Center →
            </button>
          </div>
          <div className="space-y-3">
            {anomalies.slice(0, 3).map((alert) => (
              <div
                key={alert.id}
                className="p-3 rounded-lg bg-slate-950/60 border border-slate-800/80 hover:border-slate-700 transition-all flex items-start gap-3"
              >
                <div
                  className={`px-2 py-1 rounded text-[10px] font-bold font-mono uppercase tracking-wider shrink-0 mt-0.5 ${
                    alert.severity === 'CRITICAL'
                      ? 'bg-rose-950 text-rose-300 border border-rose-800'
                      : alert.severity === 'HIGH'
                      ? 'bg-amber-950 text-amber-300 border border-amber-800'
                      : 'bg-blue-950 text-blue-300 border border-blue-800'
                  }`}
                >
                  {alert.severity}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-white">
                      {alert.route_code} • {alert.airline_code} {alert.flight_number || ''}
                    </span>
                    <span className="text-[10px] font-mono text-rose-400 font-bold">
                      +{alert.deviation_percent.toFixed(1)}% Surge
                    </span>
                  </div>
                  <p className="text-xs text-slate-300 mt-1 line-clamp-2">{alert.description}</p>
                  <div className="mt-1.5 flex items-center gap-3 text-[10px] text-slate-400 font-mono">
                    <span>Observed: ₹{alert.observed_fare_inr.toLocaleString('en-IN')}</span>
                    <span>Expected: ₹{alert.expected_fare_inr.toLocaleString('en-IN')}</span>
                    <span className="text-slate-400">{alert.booking_window}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
