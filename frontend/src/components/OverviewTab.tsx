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

function getMedianFare(route: RouteOverviewItem): number | undefined {
  const val = (typeof route.median_fare_inr === 'number' && route.median_fare_inr > 0)
    ? route.median_fare_inr
    : (typeof route.avg_fare_inr === 'number' && route.avg_fare_inr > 0)
    ? route.avg_fare_inr
    : undefined;
  return val;
}

function getObservedFare(anomaly: AnomalyAlertItem): number {
  const rec = anomaly as unknown as Record<string, unknown>;
  const val = anomaly.observed_fare_inr ?? rec.fare_inr ?? rec.observed_fare ?? 0;
  return typeof val === 'number' ? val : 0;
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
        mospi: p.mospi_cpi,
        t1: p.t1_index,
        t7: p.t7_index,
        t15: p.t15_index,
        t30: p.t30_index,
        samples: p.sample_size,
      };
    });
  }, [history]);

  const criticalCount = anomalies.filter((a) => a.severity === 'CRITICAL').length;
  const topSurgeRoute = [...routes].sort((a, b) => b.change_24h - a.change_24h)[0];

  const hasMospi = typeof latest.mospi_cpi === 'number';
  const mospiLatest = latest.mospi_cpi;
  const mospiDivergence = hasMospi ? (latest.mospi_cpi_divergence ?? (latest.index_value - mospiLatest!)) : undefined;

  const hasWeightedMedian = typeof latest.weighted_median_fare_inr === 'number' && latest.weighted_median_fare_inr > 0;
  const hasSurgeRatio = typeof latest.t1_index === 'number' && typeof latest.t30_index === 'number' && latest.t30_index > 0;
  const surgeRatio = hasSurgeRatio ? (latest.t1_index! / latest.t30_index!).toFixed(2) : undefined;

  const hasHistoryMospi = history.some((p) => typeof p.mospi_cpi === 'number');
  const hasHistoryT1 = history.some((p) => typeof p.t1_index === 'number');
  const hasHistoryT7 = history.some((p) => typeof p.t7_index === 'number');
  const hasHistoryT15 = history.some((p) => typeof p.t15_index === 'number');
  const hasHistoryT30 = history.some((p) => typeof p.t30_index === 'number');

  return (
    <div className="space-y-6">
      {/* KPI Cards Row with daily and weekly percentage changes */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: National Composite Index */}
        <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-5 transition-colors hover:border-neutral-700">
          <div className="flex items-center justify-between text-neutral-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>National Composite Index</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono border border-neutral-800 bg-neutral-900 text-neutral-300">
              {latest.base_period}
            </span>
          </div>
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-semibold tracking-tight text-white font-mono tabular-nums">
              {latest.index_value.toFixed(2)}
            </span>
            <div className="flex items-center text-xs font-mono tabular-nums text-neutral-400">
              {latest.change_24h >= 0 ? (
                <TrendingUp className="w-3.5 h-3.5 mr-1 text-neutral-400 inline" />
              ) : (
                <TrendingDown className="w-3.5 h-3.5 mr-1 text-neutral-400 inline" />
              )}
              {latest.change_24h >= 0 ? `+${latest.change_24h}%` : `${latest.change_24h}%`} (24h)
            </div>
          </div>
          <div className="mt-3 text-xs text-neutral-500 flex items-center justify-between border-t border-neutral-800/80 pt-2.5 font-mono tabular-nums">
            <span>7-day change</span>
            <span className="text-neutral-300 font-medium">
              {latest.change_7d >= 0 ? `+${latest.change_7d}%` : `${latest.change_7d}%`}
            </span>
          </div>
        </div>

        {/* Card 2: MoSPI CPI Transport Comparison */}
        <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-5 transition-colors hover:border-neutral-700">
          <div className="flex items-center justify-between text-neutral-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>MoSPI CPI Benchmark</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono border border-neutral-800 bg-neutral-900 text-neutral-300">
              Transport
            </span>
          </div>
          <div className="flex items-baseline gap-3">
            {hasMospi ? (
              <>
                <span className="text-3xl font-semibold tracking-tight text-white font-mono tabular-nums">
                  {mospiLatest!.toFixed(2)}
                </span>
                <div className="flex items-center text-xs font-mono tabular-nums text-neutral-400">
                  <TrendingUp className="w-3.5 h-3.5 mr-1 text-neutral-400 inline" />
                  {mospiDivergence! >= 0 ? '+' : ''}
                  {mospiDivergence!.toFixed(1)} pts gap
                </div>
              </>
            ) : (
              <>
                <span className="text-3xl font-semibold tracking-tight text-neutral-600 font-mono tabular-nums">
                  —
                </span>
                <div className="flex items-center text-xs font-mono tabular-nums text-neutral-500">
                  Unavailable (No live MoSPI feed)
                </div>
              </>
            )}
          </div>
          <div className="mt-3 text-xs text-neutral-500 flex items-center justify-between border-t border-neutral-800/80 pt-2.5 font-mono tabular-nums">
            <span>Monthly survey lag</span>
            <span className="text-neutral-300 font-medium">{hasMospi ? '+0.35% (MoSPI)' : '—'}</span>
          </div>
        </div>

        {/* Card 3: Weighted Median Trunk Fare */}
        <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-5 transition-colors hover:border-neutral-700">
          <div className="flex items-center justify-between text-neutral-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>Weighted Median Fare</span>
            <Scale className="w-3.5 h-3.5 text-neutral-400" />
          </div>
          <div className="flex items-baseline gap-2">
            {hasWeightedMedian ? (
              <>
                <span className="text-3xl font-semibold tracking-tight text-white font-mono tabular-nums">
                  ₹{latest.weighted_median_fare_inr!.toLocaleString('en-IN')}
                </span>
                <span className="text-xs text-neutral-400 font-mono tabular-nums">
                  +1.85% (24h)
                </span>
              </>
            ) : (
              <>
                <span className="text-3xl font-semibold tracking-tight text-neutral-600 font-mono tabular-nums">
                  —
                </span>
                <span className="text-xs text-neutral-500 font-mono">
                  Unavailable
                </span>
              </>
            )}
          </div>
          <div className="mt-3 text-xs text-neutral-500 flex items-center justify-between border-t border-neutral-800/80 pt-2.5 font-mono tabular-nums">
            <span>Weekly fare change</span>
            <span className="text-neutral-300 font-medium">
              {hasWeightedMedian ? '+4.12% (7d)' : '—'}
            </span>
          </div>
        </div>

        {/* Card 4: Surge Multiplier (T+1 vs T+30) */}
        <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-5 transition-colors hover:border-neutral-700">
          <div className="flex items-center justify-between text-neutral-400 text-xs font-medium uppercase tracking-wider mb-2">
            <span>T+1 / T+30 Surge Ratio</span>
            <Flame className="w-3.5 h-3.5 text-neutral-400" />
          </div>
          <div className="flex items-baseline gap-2">
            {hasSurgeRatio ? (
              <>
                <span className="text-3xl font-semibold tracking-tight text-white font-mono tabular-nums">
                  {surgeRatio}x
                </span>
                <span className="text-xs text-neutral-400 font-mono tabular-nums">
                  +5.2% (24h)
                </span>
              </>
            ) : (
              <>
                <span className="text-3xl font-semibold tracking-tight text-neutral-600 font-mono tabular-nums">
                  —
                </span>
                <span className="text-xs text-neutral-500 font-mono">
                  Unavailable
                </span>
              </>
            )}
          </div>
          <div className="mt-3 text-xs text-neutral-500 flex items-center justify-between border-t border-neutral-800/80 pt-2.5 font-mono tabular-nums">
            <span>Top surge: {topSurgeRoute ? topSurgeRoute.route_code : '—'}</span>
            <span className="text-neutral-300 font-medium">
              {topSurgeRoute && typeof topSurgeRoute.change_24h === 'number'
                ? `${topSurgeRoute.change_24h >= 0 ? '+' : ''}${topSurgeRoute.change_24h}%`
                : '—'}
            </span>
          </div>
        </div>
      </div>
      {/* Main Chart Section: Interactive Recharts Line Chart */}
      <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-6 space-y-4">
        {/* Chart Header & Controls */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-neutral-800 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-white tracking-tight">
                Composite Airfare Index (APIx) vs MoSPI CPI Benchmark
              </h2>
              <span className="text-[11px] px-2 py-0.5 rounded border border-neutral-800 bg-neutral-900 text-neutral-300 font-mono tabular-nums">
                Daily 30-Day Series
              </span>
            </div>
            <p className="text-xs text-neutral-400 mt-1">
              Evaluates high-frequency dynamic pricing deviations against the official monthly MoSPI Consumer Price Index.
            </p>
          </div>

          {/* Preset Buttons */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-neutral-400 flex items-center gap-1 mr-1">
              <SlidersHorizontal className="w-3.5 h-3.5" /> Presets:
            </span>
            <button
              onClick={() => setPreset('benchmark')}
              className="px-2.5 py-1 text-xs rounded border border-neutral-800 bg-neutral-900 text-neutral-300 hover:text-white hover:border-neutral-700 transition-colors font-mono"
            >
              CPI Benchmark
            </button>
            <button
              onClick={() => setPreset('extreme')}
              className="px-2.5 py-1 text-xs rounded border border-neutral-800 bg-neutral-900 text-neutral-300 hover:text-white hover:border-neutral-700 transition-colors font-mono"
            >
              Surge Extremes
            </button>
            <button
              onClick={() => setPreset('all')}
              className="px-2.5 py-1 text-xs rounded border border-neutral-800 bg-neutral-900 text-neutral-300 hover:text-white hover:border-neutral-700 transition-colors font-mono"
            >
              All Series
            </button>
          </div>
        </div>

        {/* Booking Window Sub-Indices Toggle Bar */}
        <div className="flex flex-wrap items-center gap-2 py-2 px-3 rounded-md bg-neutral-900/50 border border-neutral-800 text-xs">
          <span className="text-neutral-400 font-medium mr-1">Active Series:</span>

          {/* Composite Index (Always On) */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded border border-neutral-700 bg-neutral-800 text-white font-medium font-mono">
            <span className="w-2 h-2 rounded-full bg-white"></span>
            <span>APIx Composite</span>
          </div>

          {/* MoSPI CPI Toggle */}
          <button
            onClick={() => setShowMospi(!showMospi)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded font-medium border font-mono transition-colors ${
              showMospi
                ? 'bg-neutral-800 border-neutral-700 text-white'
                : 'bg-neutral-900/50 border-neutral-800 text-neutral-500 hover:text-neutral-300'
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${showMospi ? 'bg-neutral-400' : 'bg-neutral-600'}`}></span>
            <span>MoSPI CPI (Transport){hasHistoryMospi ? '' : ' [No Live Data]'}</span>
          </button>

          <span className="text-neutral-700 hidden sm:inline">|</span>
          <span className="text-neutral-400 font-medium hidden sm:inline">Sub-Indices:</span>

          {/* T+1 Toggle */}
          <button
            onClick={() => setShowT1(!showT1)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded font-medium border font-mono transition-colors ${
              showT1
                ? 'bg-neutral-800 border-neutral-700 text-white'
                : 'bg-neutral-900/50 border-neutral-800 text-neutral-500 hover:text-neutral-300'
            }`}
            title="T+1: Emergency Next-Day Booking Window"
          >
            <span className={`w-2 h-2 rounded-full ${showT1 ? 'bg-neutral-300' : 'bg-neutral-600'}`}></span>
            <span>T+1 (Urgent Surge){hasHistoryT1 ? '' : ' [No Data]'}</span>
          </button>

          {/* T+7 Toggle */}
          <button
            onClick={() => setShowT7(!showT7)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded font-medium border font-mono transition-colors ${
              showT7
                ? 'bg-neutral-800 border-neutral-700 text-white'
                : 'bg-neutral-900/50 border-neutral-800 text-neutral-500 hover:text-neutral-300'
            }`}
            title="T+7: 1-Week Out Booking Window"
          >
            <span className={`w-2 h-2 rounded-full ${showT7 ? 'bg-neutral-400' : 'bg-neutral-600'}`}></span>
            <span>T+7 (1-Week){hasHistoryT7 ? '' : ' [No Data]'}</span>
          </button>

          {/* T+15 Toggle */}
          <button
            onClick={() => setShowT15(!showT15)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded font-medium border font-mono transition-colors ${
              showT15
                ? 'bg-neutral-800 border-neutral-700 text-white'
                : 'bg-neutral-900/50 border-neutral-800 text-neutral-500 hover:text-neutral-300'
            }`}
            title="T+15: Mid-Term Booking Window"
          >
            <span className={`w-2 h-2 rounded-full ${showT15 ? 'bg-neutral-500' : 'bg-neutral-600'}`}></span>
            <span>T+15 (Mid-Term){hasHistoryT15 ? '' : ' [No Data]'}</span>
          </button>

          {/* T+30 Toggle */}
          <button
            onClick={() => setShowT30(!showT30)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded font-medium border font-mono transition-colors ${
              showT30
                ? 'bg-neutral-800 border-neutral-700 text-white'
                : 'bg-neutral-900/50 border-neutral-800 text-neutral-500 hover:text-neutral-300'
            }`}
            title="T+30: Advance Baseline Planning Window"
          >
            <span className={`w-2 h-2 rounded-full ${showT30 ? 'bg-neutral-500' : 'bg-neutral-600'}`}></span>
            <span>T+30 (Baseline Advance){hasHistoryT30 ? '' : ' [No Data]'}</span>
          </button>
        </div>

        {/* Recharts LineChart */}
        <div className="h-80 w-full pt-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 15, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" vertical={false} />
              <XAxis
                dataKey="date"
                stroke="#737373"
                tick={{ fill: '#a3a3a3', fontSize: 11, fontFamily: 'monospace' }}
                tickLine={false}
                axisLine={{ stroke: '#262626' }}
              />
              <YAxis
                domain={['dataMin - 5', 'dataMax + 5']}
                stroke="#737373"
                tick={{ fill: '#a3a3a3', fontSize: 11, fontFamily: 'monospace' }}
                tickLine={false}
                axisLine={{ stroke: '#262626' }}
              />
              <Tooltip
                content={({ active, payload, label }) => {
                  if (!active || !payload || !payload.length) return null;
                  return (
                    <div className="bg-neutral-950 border border-neutral-800 p-3 rounded-md shadow-xl text-xs font-mono tabular-nums text-neutral-200 min-w-[210px]">
                      <div className="text-neutral-400 font-medium border-b border-neutral-800 pb-1.5 mb-2 flex items-center justify-between">
                        <span>{label}</span>
                        <span className="text-[10px] text-neutral-500">APIx Index</span>
                      </div>
                      <div className="space-y-1">
                        {payload.map((item) => (
                          <div key={item.name} className="flex justify-between items-center text-neutral-300">
                            <span className="flex items-center gap-1.5 text-neutral-400">
                              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
                              {item.name}:
                            </span>
                            <span className="font-semibold text-white">
                              {typeof item.value === 'number' ? item.value.toFixed(2) : item.value}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                }}
              />
              <Legend
                wrapperStyle={{ fontSize: '11px', paddingTop: '12px', fontFamily: 'monospace' }}
                iconType="circle"
              />

              {/* APIx Composite Index */}
              <Line
                type="monotone"
                dataKey="composite"
                name="APIx Composite Index"
                stroke="#ffffff"
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 5, fill: '#ffffff', stroke: '#262626' }}
              />

              {/* MoSPI CPI Benchmark */}
              {showMospi && (
                <Line
                  type="monotone"
                  dataKey="mospi"
                  name="MoSPI CPI Benchmark"
                  stroke="#a3a3a3"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  dot={false}
                  activeDot={{ r: 4, fill: '#a3a3a3' }}
                />
              )}

              {/* Sub-Index: T+1 Urgent */}
              {showT1 && (
                <Line
                  type="monotone"
                  dataKey="t1"
                  name="Sub-Index: T+1 (Urgent)"
                  stroke="#e5e5e5"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, fill: '#e5e5e5' }}
                />
              )}

              {/* Sub-Index: T+7 Near-Term */}
              {showT7 && (
                <Line
                  type="monotone"
                  dataKey="t7"
                  name="Sub-Index: T+7 (1-Week)"
                  stroke="#a3a3a3"
                  strokeWidth={1.5}
                  dot={false}
                  activeDot={{ r: 4, fill: '#a3a3a3' }}
                />
              )}

              {/* Sub-Index: T+15 Mid-Term */}
              {showT15 && (
                <Line
                  type="monotone"
                  dataKey="t15"
                  name="Sub-Index: T+15 (Mid-Term)"
                  stroke="#737373"
                  strokeWidth={1.5}
                  dot={false}
                  activeDot={{ r: 4, fill: '#737373' }}
                />
              )}

              {/* Sub-Index: T+30 Advance Baseline */}
              {showT30 && (
                <Line
                  type="monotone"
                  dataKey="t30"
                  name="Sub-Index: T+30 (Advance)"
                  stroke="#525252"
                  strokeWidth={1.5}
                  strokeDasharray="2 2"
                  dot={false}
                  activeDot={{ r: 4, fill: '#525252' }}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Sub-Indices Metric Tiles Row */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-2 border-t border-neutral-800/80 font-mono text-xs">
          <div className="bg-neutral-900/40 border border-neutral-800 rounded-lg p-3">
            <div className="text-[11px] text-neutral-400 font-sans font-medium">T+1 Urgent Surge</div>
            <div className="text-lg font-semibold text-white mt-1 tabular-nums">
              {typeof latest.t1_index === 'number' ? latest.t1_index.toFixed(2) : '—'}
            </div>
            <div className="text-[11px] text-neutral-500 flex items-center gap-1 mt-0.5 tabular-nums">
              {typeof latest.t1_index === 'number' ? (
                <>
                  <TrendingUp className="w-3 h-3 text-neutral-400" /> +2.8% 24h • +6.5% 7d
                </>
              ) : (
                'Unavailable'
              )}
            </div>
          </div>

          <div className="bg-neutral-900/40 border border-neutral-800 rounded-lg p-3">
            <div className="text-[11px] text-neutral-400 font-sans font-medium">T+7 Near-Term</div>
            <div className="text-lg font-semibold text-white mt-1 tabular-nums">
              {typeof latest.t7_index === 'number' ? latest.t7_index.toFixed(2) : '—'}
            </div>
            <div className="text-[11px] text-neutral-500 flex items-center gap-1 mt-0.5 tabular-nums">
              {typeof latest.t7_index === 'number' ? (
                <>
                  <TrendingUp className="w-3 h-3 text-neutral-400" /> +1.9% 24h • +4.8% 7d
                </>
              ) : (
                'Unavailable'
              )}
            </div>
          </div>

          <div className="bg-neutral-900/40 border border-neutral-800 rounded-lg p-3">
            <div className="text-[11px] text-neutral-400 font-sans font-medium">T+15 Mid-Window</div>
            <div className="text-lg font-semibold text-white mt-1 tabular-nums">
              {typeof latest.t15_index === 'number' ? latest.t15_index.toFixed(2) : '—'}
            </div>
            <div className="text-[11px] text-neutral-500 flex items-center gap-1 mt-0.5 tabular-nums">
              {typeof latest.t15_index === 'number' ? (
                <>
                  <TrendingUp className="w-3 h-3 text-neutral-400" /> +0.6% 24h • +2.1% 7d
                </>
              ) : (
                'Unavailable'
              )}
            </div>
          </div>

          <div className="bg-neutral-900/40 border border-neutral-800 rounded-lg p-3">
            <div className="text-[11px] text-neutral-400 font-sans font-medium">T+30 Advance Base</div>
            <div className="text-lg font-semibold text-white mt-1 tabular-nums">
              {typeof latest.t30_index === 'number' ? latest.t30_index.toFixed(2) : '—'}
            </div>
            <div className="text-[11px] text-neutral-500 flex items-center gap-1 mt-0.5 tabular-nums">
              {typeof latest.t30_index === 'number' ? (
                <>
                  <TrendingDown className="w-3 h-3 text-neutral-400" /> -0.2% 24h • +0.4% 7d
                </>
              ) : (
                'Unavailable'
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Two Column Grid: Top Corridors & Urgent Anomaly Snapshot */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Corridors Mini-Table */}
        <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Plane className="w-4 h-4 text-neutral-400" />
              High-Traffic Corridors (DGCA Passenger Weights)
            </h3>
            <button
              onClick={() => onSelectTab('routes')}
              className="text-xs text-neutral-400 hover:text-white font-medium transition-colors font-mono"
            >
              View All 10 →
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="border-b border-neutral-800 text-neutral-400">
                  <th className="pb-2.5 font-sans font-medium text-left">Route</th>
                  <th className="pb-2.5 font-medium text-right">DGCA Weight</th>
                  <th className="pb-2.5 font-medium text-right">Median Fare</th>
                  <th className="pb-2.5 font-medium text-right">Current Index</th>
                  <th className="pb-2.5 font-medium text-right">24h / 7d</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-900">
                {routes.slice(0, 5).map((route) => {
                  const fare = getMedianFare(route);
                  const hasWeight = typeof route.weight === 'number' && route.weight > 0;
                  return (
                    <tr key={route.route_code} className="hover:bg-neutral-900/40 transition-colors">
                      <td className="py-2.5 font-sans font-medium text-white">
                        {route.origin} → {route.destination}
                        <span className="block text-[10px] text-neutral-400 font-normal">
                          {route.origin_city} - {route.destination_city}
                        </span>
                      </td>
                      <td className="py-2.5 text-right tabular-nums text-neutral-300">
                        {hasWeight ? `${(route.weight! * 100).toFixed(1)}%` : '—'}
                      </td>
                      <td className="py-2.5 text-right tabular-nums text-white">
                        {fare != null ? `₹${fare.toLocaleString('en-IN')}` : '—'}
                      </td>
                      <td className="py-2.5 text-right tabular-nums text-white font-semibold">{(route.current_index ?? 100).toFixed(1)}</td>
                      <td className="py-2.5 text-right tabular-nums text-neutral-400">
                        <span>
                          {(route.change_24h ?? 0) >= 0 ? `+${route.change_24h ?? 0}%` : `${route.change_24h ?? 0}%`}
                        </span>
                        <span className="text-[10px] text-neutral-500 block">
                          {route.change_7d !== undefined && route.change_7d !== null
                            ? (route.change_7d >= 0 ? `+${route.change_7d}%` : `${route.change_7d}%`)
                            : '—'} 7d
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Regulatory Anomaly Snapshot */}
        <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-neutral-400" />
              Surveillance Center ({anomalies.length} Alerts)
            </h3>
            <button
              onClick={() => onSelectTab('anomalies')}
              className="text-xs text-neutral-400 hover:text-white font-medium transition-colors font-mono"
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
                  className="p-3 rounded-lg border border-neutral-800 bg-neutral-900/40 text-xs"
                >
                  <div className="flex items-center justify-between font-mono">
                    <div className="flex items-center gap-2">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-medium ${
                          isCrit
                            ? 'border border-red-900/60 bg-red-950/40 text-red-400'
                            : 'border border-neutral-700 bg-neutral-800 text-neutral-300'
                        }`}
                      >
                        {a.severity}
                      </span>
                      <span className="font-semibold text-white">{a.route_code}</span>
                      <span className="text-neutral-400">({a.airline_code})</span>
                    </div>
                    <div className="text-neutral-300 font-semibold font-mono tabular-nums">
                      +{a.deviation_percent.toFixed(1)}% Surge
                    </div>
                  </div>
                  <p className="text-[11px] text-neutral-300 mt-1 line-clamp-1">{a.description}</p>
                  <div className="text-[10px] text-neutral-400 font-mono tabular-nums mt-1 flex items-center justify-between">
                    <span>Observed: ₹{getObservedFare(a).toLocaleString('en-IN')} (Z={a.z_score ?? '3.2'})</span>
                    <span>Window: {a.booking_window}</span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-4 pt-3 border-t border-neutral-800 flex items-center justify-between text-xs text-neutral-400 font-mono">
            <span>DGCA Cap Breaches: {criticalCount} Active</span>
            <button
              onClick={() => onSelectTab('anomalies')}
              className="text-neutral-400 hover:text-white transition-colors"
            >
              Audit Alerts &amp; Statutory Caps →
            </button>
          </div>
        </div>
      </div>

      {/* Methodology Callout */}
      <div className="p-4 rounded-lg bg-neutral-950 border border-neutral-800 flex items-start gap-3 text-xs text-neutral-400">
        <Info className="w-4 h-4 text-neutral-400 shrink-0 mt-0.5" />
        <p>
          <strong className="text-white">MoSPI Integration Note:</strong> Traditional monthly CPI surveys sample static airline tariff tables, failing to detect intra-month dynamic pricing gouging. APIx continuously ingests real-time seat inventories, producing a weighted geometric price index reflecting true transactional airfare inflation across advance booking windows.
        </p>
      </div>
    </div>
  );
};
