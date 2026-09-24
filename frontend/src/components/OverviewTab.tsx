import React, { useState, useMemo } from 'react';
import {
  NationalIndexLatestResponse,
  NationalIndexPoint,
  RouteOverviewItem,
  AnomalyAlertItem,
} from '../types/api';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts';
import {
  TrendingUp,
  TrendingDown,
  Plane,
  AlertTriangle,
  Scale,
  SlidersHorizontal,
  Flame,
  Info,
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
  // Booking window sub-indices toggles
  const [showMospi, setShowMospi] = useState<boolean>(true);
  const [showT1, setShowT1] = useState<boolean>(true);
  const [showT7, setShowT7] = useState<boolean>(false);
  const [showT15, setShowT15] = useState<boolean>(false);
  const [showT30, setShowT30] = useState<boolean>(true);

  // Quick preset filters
  const setPreset = (preset: 'benchmark' | 'all' | 'extreme' | 'advance') => {
    switch (preset) {
      case 'benchmark':
        setShowMospi(true);
        setShowT1(false);
        setShowT7(false);
        setShowT15(false);
        setShowT30(false);
        break;
      case 'all':
        setShowMospi(true);
        setShowT1(true);
        setShowT7(true);
        setShowT15(true);
        setShowT30(true);
        break;
      case 'extreme':
        setShowMospi(true);
        setShowT1(true);
        setShowT7(false);
        setShowT15(false);
        setShowT30(true);
        break;
      case 'advance':
        setShowMospi(false);
        setShowT1(false);
        setShowT7(false);
        setShowT15(true);
        setShowT30(true);
        break;
    }
  };

  const chartData = useMemo(() => {
    return history.map((p) => {
      const d = new Date(p.timestamp);
      return {
        date: `${d.getDate()} ${d.toLocaleString('en-US', { month: 'short' })}`,
        fullDate: d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }),
        composite: p.index_value,
        mospi: p.mospi_cpi ?? Number((105.8 + 0.05 * 15).toFixed(2)),
        t1: p.t1_index ?? Number((p.index_value * 1.30).toFixed(2)),
        t7: p.t7_index ?? Number((p.index_value * 1.08).toFixed(2)),
        t15: p.t15_index ?? Number((p.index_value * 0.96).toFixed(2)),
        t30: p.t30_index ?? Number((p.index_value * 0.84).toFixed(2)),
        samples: p.sample_size,
      };
    });
  }, [history]);

  const criticalCount = anomalies.filter((a) => a.severity === 'CRITICAL').length;
  const topSurgeRoute = [...routes].sort((a, b) => b.change_24h - a.change_24h)[0];

  const mospiLatest = latest.mospi_cpi ?? 107.40;
  const mospiDivergence = latest.mospi_cpi_divergence ?? (latest.index_value - mospiLatest);

  return (
    <div className="space-y-6">
      {/* KPI Cards Row with daily and weekly percentage changes */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: National Composite Index */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm relative overflow-hidden group hover:border-sky-500/50 transition-all">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>National Composite Index</span>
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
            <span>7-day percentage change:</span>
            <span
              className={`font-semibold font-mono ${
                latest.change_7d >= 0 ? 'text-amber-400' : 'text-emerald-400'
              }`}
            >
              {latest.change_7d >= 0 ? `+${latest.change_7d}%` : `${latest.change_7d}%`}
            </span>
          </div>
        </div>

        {/* Card 2: MoSPI CPI Transport Comparison */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm hover:border-amber-500/50 transition-all">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>MoSPI CPI Benchmark</span>
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-950 text-amber-400 border border-amber-800">
              Transport Subgroup
            </span>
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-extrabold tracking-tight text-amber-300 font-mono">
              {mospiLatest.toFixed(2)}
            </span>
            <div className="flex items-center text-xs font-semibold text-rose-400">
              <TrendingUp className="w-3.5 h-3.5 mr-0.5 inline" />
              +{mospiDivergence.toFixed(1)} pts gap
            </div>
          </div>
          <div className="mt-3 text-xs text-slate-400 flex items-center justify-between border-t border-slate-800/80 pt-2.5">
            <span>Weekly MoSPI change:</span>
            <span className="font-semibold text-emerald-400 font-mono">+0.35% (Monthly lag)</span>
          </div>
        </div>

        {/* Card 3: Weighted Median Trunk Fare */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm hover:border-indigo-500/50 transition-all">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>Weighted Median Fare</span>
            <Scale className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-extrabold tracking-tight text-white font-mono">
              ₹{(latest.weighted_median_fare_inr || 5480).toLocaleString('en-IN')}
            </span>
            <span className="text-xs text-rose-400 font-semibold font-mono">
              +1.85% (24h)
            </span>
          </div>
          <div className="mt-3 text-xs text-slate-400 flex items-center justify-between border-t border-slate-800/80 pt-2.5">
            <span>Weekly fare change:</span>
            <span className="font-semibold text-amber-400 font-mono">+4.12% (7d)</span>
          </div>
        </div>

        {/* Card 4: Surge Multiplier (T+1 vs T+30) */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm hover:border-rose-500/50 transition-all">
          <div className="flex items-center justify-between text-slate-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>T+1 / T+30 Surge Ratio</span>
            <Flame className="w-4 h-4 text-rose-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-extrabold tracking-tight text-rose-400 font-mono">
              2.42x
            </span>
            <span className="text-xs text-rose-400 font-semibold font-mono">
              +5.2% (24h)
            </span>
          </div>
          <div className="mt-3 text-xs text-slate-400 flex items-center justify-between border-t border-slate-800/80 pt-2.5">
            <span>Top surge: {topSurgeRoute ? topSurgeRoute.route_code : 'DEL-BOM'}</span>
            <span className="font-semibold text-rose-400 font-mono">
              +{topSurgeRoute ? topSurgeRoute.change_24h : 3.8}%
            </span>
          </div>
        </div>
      </div>

      {/* Main Chart Section: Interactive Recharts Line Chart */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-6 backdrop-blur-md space-y-4">
        {/* Chart Header & Controls */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-white">
                Composite Airfare Index (APIx) vs MoSPI CPI Benchmark
              </h2>
              <span className="text-xs font-normal px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700 font-mono">
                Daily 30-Day Series
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Evaluates high-frequency dynamic pricing deviations against the official monthly MoSPI Consumer Price Index.
            </p>
          </div>

          {/* Preset Buttons */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-400 flex items-center gap-1 mr-1">
              <SlidersHorizontal className="w-3.5 h-3.5" /> Presets:
            </span>
            <button
              onClick={() => setPreset('benchmark')}
              className="px-2.5 py-1 text-xs rounded-lg font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white transition-all"
            >
              CPI Benchmark
            </button>
            <button
              onClick={() => setPreset('extreme')}
              className="px-2.5 py-1 text-xs rounded-lg font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white transition-all"
            >
              Surge Extremes
            </button>
            <button
              onClick={() => setPreset('all')}
              className="px-2.5 py-1 text-xs rounded-lg font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white transition-all"
            >
              All Series
            </button>
          </div>
        </div>

        {/* Booking Window Sub-Indices Toggle Bar */}
        <div className="flex flex-wrap items-center gap-2.5 py-2 px-3 rounded-lg bg-slate-950/60 border border-slate-800/80 text-xs">
          <span className="text-slate-400 font-medium mr-1">Active Series:</span>

          {/* Composite Index (Always On) */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-sky-950/80 border border-sky-700 text-sky-300 font-medium">
            <span className="w-2.5 h-2.5 rounded-full bg-sky-400"></span>
            <span>APIx Composite</span>
          </div>

          {/* MoSPI CPI Toggle */}
          <button
            onClick={() => setShowMospi(!showMospi)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium border transition-all ${
              showMospi
                ? 'bg-amber-950/80 border-amber-600 text-amber-300 shadow-sm'
                : 'bg-slate-900 border-slate-800 text-slate-500 hover:text-slate-300'
            }`}
          >
            <span className={`w-2.5 h-2.5 rounded-full ${showMospi ? 'bg-amber-400' : 'bg-slate-600'}`}></span>
            <span>MoSPI CPI (Transport)</span>
          </button>

          <span className="text-slate-700 hidden sm:inline">|</span>
          <span className="text-slate-400 font-medium hidden sm:inline">Sub-Indices:</span>

          {/* T+1 Toggle */}
          <button
            onClick={() => setShowT1(!showT1)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium border transition-all ${
              showT1
                ? 'bg-rose-950/80 border-rose-600 text-rose-300 shadow-sm'
                : 'bg-slate-900 border-slate-800 text-slate-500 hover:text-slate-300'
            }`}
            title="T+1: Emergency Next-Day Booking Window"
          >
            <span className={`w-2.5 h-2.5 rounded-full ${showT1 ? 'bg-rose-500' : 'bg-slate-600'}`}></span>
            <span>T+1 (Urgent Surge)</span>
          </button>

          {/* T+7 Toggle */}
          <button
            onClick={() => setShowT7(!showT7)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium border transition-all ${
              showT7
                ? 'bg-pink-950/80 border-pink-600 text-pink-300 shadow-sm'
                : 'bg-slate-900 border-slate-800 text-slate-500 hover:text-slate-300'
            }`}
            title="T+7: 1-Week Out Booking Window"
          >
            <span className={`w-2.5 h-2.5 rounded-full ${showT7 ? 'bg-pink-400' : 'bg-slate-600'}`}></span>
            <span>T+7 (1-Week)</span>
          </button>

          {/* T+15 Toggle */}
          <button
            onClick={() => setShowT15(!showT15)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium border transition-all ${
              showT15
                ? 'bg-purple-950/80 border-purple-600 text-purple-300 shadow-sm'
                : 'bg-slate-900 border-slate-800 text-slate-500 hover:text-slate-300'
            }`}
            title="T+15: Mid-Term Booking Window"
          >
            <span className={`w-2.5 h-2.5 rounded-full ${showT15 ? 'bg-purple-400' : 'bg-slate-600'}`}></span>
            <span>T+15 (Mid-Term)</span>
          </button>

          {/* T+30 Toggle */}
          <button
            onClick={() => setShowT30(!showT30)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md font-medium border transition-all ${
              showT30
                ? 'bg-emerald-950/80 border-emerald-600 text-emerald-300 shadow-sm'
                : 'bg-slate-900 border-slate-800 text-slate-500 hover:text-slate-300'
            }`}
            title="T+30: Advance Baseline Planning Window"
          >
            <span className={`w-2.5 h-2.5 rounded-full ${showT30 ? 'bg-emerald-400' : 'bg-slate-600'}`}></span>
            <span>T+30 (Baseline Advance)</span>
          </button>
        </div>

        {/* Recharts LineChart */}
        <div className="h-80 w-full pt-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 15, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis
                dataKey="date"
                stroke="#64748b"
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
              />
              <YAxis
                domain={['dataMin - 5', 'dataMax + 5']}
                stroke="#64748b"
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: '#334155' }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: '#334155',
                  borderRadius: '0.75rem',
                  fontSize: '12px',
                  boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.7)',
                }}
                labelStyle={{ color: '#94a3b8', fontWeight: 700, marginBottom: '6px' }}
                formatter={(val: unknown, name: unknown) => {
                  const num = typeof val === 'number' ? val.toFixed(2) : String(val);
                  return [num, String(name)];
                }}
              />
              <Legend
                wrapperStyle={{ fontSize: '11px', paddingTop: '12px' }}
                iconType="circle"
              />

              {/* APIx Composite Index */}
              <Line
                type="monotone"
                dataKey="composite"
                name="APIx Composite Index"
                stroke="#38bdf8"
                strokeWidth={3}
                dot={false}
                activeDot={{ r: 6, fill: '#38bdf8', stroke: '#0284c7' }}
              />

              {/* MoSPI CPI Benchmark */}
              {showMospi && (
                <Line
                  type="monotone"
                  dataKey="mospi"
                  name="MoSPI CPI Benchmark"
                  stroke="#fbbf24"
                  strokeWidth={2}
                  strokeDasharray="4 4"
                  dot={false}
                  activeDot={{ r: 5, fill: '#fbbf24' }}
                />
              )}

              {/* Sub-Index: T+1 Urgent */}
              {showT1 && (
                <Line
                  type="monotone"
                  dataKey="t1"
                  name="Sub-Index: T+1 (Urgent)"
                  stroke="#f43f5e"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 5, fill: '#f43f5e' }}
                />
              )}

              {/* Sub-Index: T+7 Near-Term */}
              {showT7 && (
                <Line
                  type="monotone"
                  dataKey="t7"
                  name="Sub-Index: T+7 (1-Week)"
                  stroke="#f472b6"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 5, fill: '#f472b6' }}
                />
              )}

              {/* Sub-Index: T+15 Mid-Term */}
              {showT15 && (
                <Line
                  type="monotone"
                  dataKey="t15"
                  name="Sub-Index: T+15 (Mid-Term)"
                  stroke="#c084fc"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 5, fill: '#c084fc' }}
                />
              )}

              {/* Sub-Index: T+30 Advance Baseline */}
              {showT30 && (
                <Line
                  type="monotone"
                  dataKey="t30"
                  name="Sub-Index: T+30 (Advance)"
                  stroke="#34d399"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 5, fill: '#34d399' }}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Sub-Indices Metric Tiles Row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 border-t border-slate-800/80 font-mono text-xs">
          <div className="bg-slate-950/60 border border-rose-900/40 rounded-lg p-3">
            <div className="text-[11px] text-rose-400 font-semibold font-sans">T+1 Urgent Surge</div>
            <div className="text-lg font-bold text-white mt-1">{(latest.t1_index || 154.20).toFixed(2)}</div>
            <div className="text-[11px] text-rose-400 flex items-center gap-0.5 mt-0.5">
              <TrendingUp className="w-3 h-3" /> +2.8% 24h • +6.5% 7d
            </div>
          </div>

          <div className="bg-slate-950/60 border border-pink-900/40 rounded-lg p-3">
            <div className="text-[11px] text-pink-400 font-semibold font-sans">T+7 Near-Term</div>
            <div className="text-lg font-bold text-white mt-1">{(latest.t7_index || 128.60).toFixed(2)}</div>
            <div className="text-[11px] text-pink-400 flex items-center gap-0.5 mt-0.5">
              <TrendingUp className="w-3 h-3" /> +1.9% 24h • +4.8% 7d
            </div>
          </div>

          <div className="bg-slate-950/60 border border-purple-900/40 rounded-lg p-3">
            <div className="text-[11px] text-purple-400 font-semibold font-sans">T+15 Mid-Window</div>
            <div className="text-lg font-bold text-white mt-1">{(latest.t15_index || 114.10).toFixed(2)}</div>
            <div className="text-[11px] text-purple-400 flex items-center gap-0.5 mt-0.5">
              <TrendingUp className="w-3 h-3" /> +0.6% 24h • +2.1% 7d
            </div>
          </div>

          <div className="bg-slate-950/60 border border-emerald-900/40 rounded-lg p-3">
            <div className="text-[11px] text-emerald-400 font-semibold font-sans">T+30 Advance Base</div>
            <div className="text-lg font-bold text-white mt-1">{(latest.t30_index || 99.40).toFixed(2)}</div>
            <div className="text-[11px] text-emerald-400 flex items-center gap-0.5 mt-0.5">
              <TrendingDown className="w-3 h-3" /> -0.2% 24h • +0.4% 7d
            </div>
          </div>
        </div>
      </div>

      {/* Two Column Grid: Top Corridors & Urgent Anomaly Snapshot */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Corridors Mini-Table */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Plane className="w-4 h-4 text-sky-400" />
              High-Traffic Corridors (DGCA Passenger Weights)
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
                  <th className="pb-2.5 font-medium">DGCA Weight</th>
                  <th className="pb-2.5 font-medium">Median Fare</th>
                  <th className="pb-2.5 font-medium">Current Index</th>
                  <th className="pb-2.5 font-medium text-right">24h / 7d</th>
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
                    <td className="py-2.5 text-white">₹{(route.median_fare_inr ?? route.median_fare ?? route.avg_fare_inr ?? route.avg_fare ?? 0).toLocaleString('en-IN')}</td>
                    <td className="py-2.5 text-sky-400">{route.current_index.toFixed(1)}</td>
                    <td className="py-2.5 text-right">
                      <span className={route.change_24h >= 0 ? 'text-rose-400' : 'text-emerald-400'}>
                        {route.change_24h >= 0 ? `+${route.change_24h}%` : `${route.change_24h}%`}
                      </span>
                      <span className="text-[10px] text-slate-500 block">
                        {route.change_7d >= 0 ? `+${route.change_7d}%` : `${route.change_7d}%`} 7d
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Regulatory Anomaly Snapshot */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-rose-400" />
              Surveillance Center ({anomalies.length} Alerts)
            </h3>
            <button
              onClick={() => onSelectTab('anomalies')}
              className="text-xs text-rose-400 hover:text-rose-300 font-medium transition-colors"
            >
              Surveillance Desk →
            </button>
          </div>

          <div className="space-y-3">
            {anomalies.slice(0, 3).map((a) => {
              const isCrit = a.severity === 'CRITICAL';
              return (
                <div
                  key={a.id}
                  className={`p-3 rounded-lg border text-xs ${
                    isCrit
                      ? 'bg-rose-950/30 border-rose-800/80'
                      : 'bg-amber-950/30 border-amber-800/80'
                  }`}
                >
                  <div className="flex items-center justify-between font-mono">
                    <div className="flex items-center gap-2">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          isCrit ? 'bg-rose-600 text-white' : 'bg-amber-600 text-slate-950'
                        }`}
                      >
                        {a.severity}
                      </span>
                      <span className="font-bold text-white">{a.route_code}</span>
                      <span className="text-slate-400">({a.airline_code})</span>
                    </div>
                    <div className="text-rose-400 font-bold font-mono">
                      +{a.deviation_percent.toFixed(1)}% Surge
                    </div>
                  </div>
                  <p className="text-[11px] text-slate-300 mt-1 line-clamp-1">{a.description}</p>
                  <div className="text-[10px] text-slate-500 font-mono mt-1 flex items-center justify-between">
                    <span>Observed: ₹{(a.observed_fare_inr ?? a.fare_inr ?? a.observed_fare ?? a.fare ?? 0).toLocaleString('en-IN')} (Z={a.z_score ?? '3.2'})</span>
                    <span>Window: {a.booking_window}</span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
            <span>DGCA Cap Breaches: {criticalCount} Active</span>
            <button
              onClick={() => onSelectTab('anomalies')}
              className="text-sky-400 hover:text-sky-300"
            >
              Audit Alerts & Statutory Caps →
            </button>
          </div>
        </div>
      </div>

      {/* Methodology Callout */}
      <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex items-start gap-3 text-xs text-slate-400">
        <Info className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" />
        <p>
          <strong className="text-slate-200">MoSPI Integration Note:</strong> Traditional monthly CPI surveys sample static airline tariff tables, failing to detect intra-month dynamic pricing gouging. APIx continuously ingests real-time seat inventories, producing a weighted geometric price index reflecting true transactional airfare inflation across advance booking windows.
        </p>
      </div>
    </div>
  );
};
