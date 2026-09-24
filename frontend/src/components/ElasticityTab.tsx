import React, { useState, useMemo } from 'react';
import { LeadTimeCurveResponse, HeatmapMatrixResponse } from '../types/api';
import {
  ResponsiveContainer,
  ComposedChart,
  Area,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from 'recharts';
import {
  Clock,
  Calendar,
  TrendingUp,
  Info,
  Flame,
  Grid3X3,
  BarChart3,
  Layers,
} from 'lucide-react';

interface ElasticityTabProps {
  leadTimeCurve: LeadTimeCurveResponse;
  heatmap: HeatmapMatrixResponse;
}

type ChartViewMode = 'composed' | 'envelope' | 'multipliers';
type MatrixViewMode = 'routes_leadtime' | 'day_hour';

// Pre-calculated route lead-time matrix for the 10 trunk corridors
interface RouteLeadTimeRow {
  route_code: string;
  corridor: string;
  t30_fare: number;
  t21_fare: number;
  t14_fare: number;
  t7_fare: number;
  t3_fare: number;
  t1_fare: number;
  surge_ratio: number;
}

const ROUTE_LEADTIME_DATA: RouteLeadTimeRow[] = [
  { route_code: 'DEL-BOM', corridor: 'Delhi - Mumbai', t30_fare: 4500, t21_fare: 4800, t14_fare: 5300, t7_fare: 6500, t3_fare: 8500, t1_fare: 10900, surge_ratio: 2.42 },
  { route_code: 'DEL-BLR', corridor: 'Delhi - Bengaluru', t30_fare: 5200, t21_fare: 5600, t14_fare: 6200, t7_fare: 7800, t3_fare: 10400, t1_fare: 13400, surge_ratio: 2.58 },
  { route_code: 'BOM-BLR', corridor: 'Mumbai - Bengaluru', t30_fare: 3600, t21_fare: 3850, t14_fare: 4200, t7_fare: 5100, t3_fare: 6700, t1_fare: 8200, surge_ratio: 2.28 },
  { route_code: 'DEL-CCU', corridor: 'Delhi - Kolkata', t30_fare: 4400, t21_fare: 4700, t14_fare: 5150, t7_fare: 6300, t3_fare: 8200, t1_fare: 10600, surge_ratio: 2.41 },
  { route_code: 'DEL-HYD', corridor: 'Delhi - Hyderabad', t30_fare: 4200, t21_fare: 4450, t14_fare: 4900, t7_fare: 5950, t3_fare: 7600, t1_fare: 9800, surge_ratio: 2.33 },
  { route_code: 'DEL-MAA', corridor: 'Delhi - Chennai', t30_fare: 5100, t21_fare: 5500, t14_fare: 6100, t7_fare: 7650, t3_fare: 10100, t1_fare: 12800, surge_ratio: 2.51 },
  { route_code: 'MAA-BOM', corridor: 'Chennai - Mumbai', t30_fare: 3800, t21_fare: 4050, t14_fare: 4450, t7_fare: 5400, t3_fare: 7000, t1_fare: 8900, surge_ratio: 2.34 },
  { route_code: 'BOM-CCU', corridor: 'Mumbai - Kolkata', t30_fare: 5300, t21_fare: 5700, t14_fare: 6300, t7_fare: 7800, t3_fare: 10200, t1_fare: 12900, surge_ratio: 2.43 },
  { route_code: 'BLR-HYD', corridor: 'Bengaluru - Hyderabad', t30_fare: 2600, t21_fare: 2750, t14_fare: 3000, t7_fare: 3650, t3_fare: 4600, t1_fare: 5800, surge_ratio: 2.23 },
  { route_code: 'BOM-GOI', corridor: 'Mumbai - Goa', t30_fare: 2800, t21_fare: 3100, t14_fare: 3600, t7_fare: 4900, t3_fare: 6800, t1_fare: 8600, surge_ratio: 3.07 },
];

export const ElasticityTab: React.FC<ElasticityTabProps> = ({ leadTimeCurve, heatmap }) => {
  const [selectedRoute, setSelectedRoute] = useState<string>('DEL-BOM');
  const [chartView, setChartView] = useState<ChartViewMode>('composed');
  const [matrixView, setMatrixView] = useState<MatrixViewMode>('routes_leadtime');

  // Lead-time points ordered from advance booking (T+60, T+30) down to departure (T+1)
  const chartData = useMemo(() => {
    return [...leadTimeCurve.curve_points]
      .sort((a, b) => b.days_before_departure - a.days_before_departure)
      .map((p) => ({
        window: p.booking_window_label || `T+${p.days_before_departure}`,
        days: p.days_before_departure,
        avgFare: p.avg_fare_inr,
        medianFare: p.median_fare_inr,
        p10Fare: p.p10_fare_inr,
        p90Fare: p.p90_fare_inr,
        elasticity: Number(p.elasticity_factor.toFixed(2)),
        samples: p.sample_count,
        spread: p.p90_fare_inr - p.p10_fare_inr,
      }));
  }, [leadTimeCurve]);

  const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const hours = [6, 9, 12, 15, 18, 21];

  // Cell color helper for Route x Booking Window matrix
  const getFareCellClass = (fare: number, baseline: number) => {
    const ratio = fare / baseline;
    if (ratio >= 2.5) return 'bg-rose-950/90 text-rose-300 border border-rose-700/80 font-bold';
    if (ratio >= 2.0) return 'bg-rose-950/70 text-rose-300 border border-rose-800/60 font-semibold';
    if (ratio >= 1.5) return 'bg-amber-950/70 text-amber-300 border border-amber-800/60';
    if (ratio >= 1.2) return 'bg-sky-950/70 text-sky-300 border border-sky-800/60';
    return 'bg-emerald-950/60 text-emerald-300 border border-emerald-800/50';
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <Clock className="w-5 h-5 text-indigo-400" />
                Advance Booking Window & Lead-Time Price Elasticity
              </h2>
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-indigo-950 text-indigo-300 border border-indigo-800 font-mono">
                T+30 to T+1 Surge Model
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Empirical modeling of algorithmic dynamic pricing multipliers as departure approaches across domestic airline booking windows.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-400">Target Corridor:</span>
            <select
              value={selectedRoute}
              onChange={(e) => setSelectedRoute(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
            >
              <option value="DEL-BOM">DEL-BOM (Delhi - Mumbai)</option>
              <option value="DEL-BLR">DEL-BLR (Delhi - Bengaluru)</option>
              <option value="BOM-BLR">BOM-BLR (Mumbai - Bengaluru)</option>
              <option value="DEL-CCU">DEL-CCU (Delhi - Kolkata)</option>
              <option value="BOM-GOI">BOM-GOI (Mumbai - Goa)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Booking Window Multipliers Grid (T+1 to T+60) */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3 font-mono">
        {leadTimeCurve.curve_points.map((pt) => {
          const isExtreme = pt.days_before_departure === 1;
          const isUrgent = pt.days_before_departure === 3 || pt.days_before_departure === 7;
          const isBase = pt.days_before_departure === 30;

          return (
            <div
              key={pt.days_before_departure}
              className={`p-3.5 rounded-xl border text-center transition-all ${
                isExtreme
                  ? 'bg-rose-950/40 border-rose-700/80 shadow-md shadow-rose-950/30'
                  : isUrgent
                  ? 'bg-amber-950/30 border-amber-800/60'
                  : isBase
                  ? 'bg-sky-950/30 border-sky-800/60'
                  : 'bg-slate-900/80 border-slate-800'
              }`}
            >
              <div className="flex items-center justify-center gap-1 text-[11px] text-slate-400">
                {isExtreme && <Flame className="w-3 h-3 text-rose-400" />}
                <span>{pt.booking_window_label || `T+${pt.days_before_departure}`}</span>
              </div>
              <div className="text-[10px] text-slate-500 font-sans mt-0.5">
                {pt.days_before_departure}d out
              </div>
              <div
                className={`mt-1.5 text-lg font-extrabold ${
                  isExtreme ? 'text-rose-400' : isUrgent ? 'text-amber-400' : 'text-white'
                }`}
              >
                {pt.elasticity_factor.toFixed(2)}x
              </div>
              <div className="text-[11px] text-slate-300 mt-1">
                ₹{pt.median_fare_inr.toLocaleString('en-IN')}
              </div>
            </div>
          );
        })}
      </div>

      {/* Main Dynamic Pricing Lead-Time Elasticity Bar/Area Chart */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-6 backdrop-blur-md space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-sky-400" />
                Dynamic Pricing Surge Curve (T+30 Baseline down to T+1 Emergency)
              </h3>
              <span className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                {selectedRoute}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Visualizes the hyperbolic price acceleration from promotional advance fares (T+30) to steep surge tariffs (T+1).
            </p>
          </div>

          {/* Chart View Toggles */}
          <div className="flex items-center rounded-lg bg-slate-950 border border-slate-800 p-0.5 text-xs font-mono">
            <button
              onClick={() => setChartView('composed')}
              className={`px-2.5 py-1 rounded-md transition-all flex items-center gap-1.5 ${
                chartView === 'composed'
                  ? 'bg-slate-800 text-white font-semibold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Layers className="w-3.5 h-3.5 text-sky-400" />
              Fare & Multipliers
            </button>
            <button
              onClick={() => setChartView('envelope')}
              className={`px-2.5 py-1 rounded-md transition-all flex items-center gap-1.5 ${
                chartView === 'envelope'
                  ? 'bg-slate-800 text-white font-semibold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
              P10-P90 Envelope
            </button>
            <button
              onClick={() => setChartView('multipliers')}
              className={`px-2.5 py-1 rounded-md transition-all flex items-center gap-1.5 ${
                chartView === 'multipliers'
                  ? 'bg-slate-800 text-white font-semibold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <BarChart3 className="w-3.5 h-3.5 text-indigo-400" />
              Surge Bars
            </button>
          </div>
        </div>

        {/* Recharts Chart Area */}
        <div className="h-80 w-full pt-2">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="window" stroke="#64748b" tick={{ fontSize: 11 }} />

              {/* Primary Y-Axis: Fares in INR */}
              <YAxis
                yAxisId="fare"
                stroke="#64748b"
                tick={{ fontSize: 11 }}
                domain={['dataMin - 1000', 'dataMax + 1000']}
                tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`}
              />

              {/* Secondary Y-Axis: Elasticity Factor Multiplier */}
              <YAxis
                yAxisId="multiplier"
                orientation="right"
                stroke="#818cf8"
                tick={{ fontSize: 11 }}
                domain={[0.8, 2.8]}
                tickFormatter={(v) => `${v.toFixed(1)}x`}
              />

              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: '#334155',
                  borderRadius: '0.75rem',
                  fontSize: '12px',
                  boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.7)',
                }}
                formatter={(val: unknown, name: unknown) => {
                  if (typeof val === 'number') {
                    if (String(name).includes('Surge Multiplier')) {
                      return [`${val.toFixed(2)}x`, String(name)];
                    }
                    return [`₹${val.toLocaleString('en-IN')}`, String(name)];
                  }
                  return [String(val), String(name)];
                }}
              />
              <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />

              {/* Composed Mode: Area for Median, Bar for Multiplier, Lines for P90/P10 */}
              {chartView === 'composed' && (
                <>
                  <Bar
                    yAxisId="multiplier"
                    dataKey="elasticity"
                    name="Surge Multiplier (x Baseline)"
                    fill="#6366f1"
                    opacity={0.35}
                    radius={[4, 4, 0, 0]}
                  />
                  <Area
                    yAxisId="fare"
                    type="monotone"
                    dataKey="medianFare"
                    name="Median Fare (INR)"
                    stroke="#38bdf8"
                    strokeWidth={2.5}
                    fill="#38bdf8"
                    fillOpacity={0.15}
                  />
                  <Line
                    yAxisId="fare"
                    type="monotone"
                    dataKey="p90Fare"
                    name="P90 (Surge Ceiling)"
                    stroke="#f43f5e"
                    strokeWidth={2}
                    strokeDasharray="4 4"
                    dot={{ r: 3 }}
                  />
                  <Line
                    yAxisId="fare"
                    type="monotone"
                    dataKey="p10Fare"
                    name="P10 (Promo Floor)"
                    stroke="#10b981"
                    strokeWidth={2}
                    strokeDasharray="4 4"
                    dot={{ r: 3 }}
                  />
                </>
              )}

              {/* Envelope Mode: P10, Average, Median, P90 */}
              {chartView === 'envelope' && (
                <>
                  <Area
                    yAxisId="fare"
                    type="monotone"
                    dataKey="p90Fare"
                    name="P90 (Upper Bound)"
                    stroke="#f43f5e"
                    strokeWidth={2}
                    fill="#f43f5e"
                    fillOpacity={0.1}
                  />
                  <Line
                    yAxisId="fare"
                    type="monotone"
                    dataKey="avgFare"
                    name="Average Fare"
                    stroke="#a855f7"
                    strokeWidth={1.75}
                    dot={{ r: 3 }}
                  />
                  <Line
                    yAxisId="fare"
                    type="monotone"
                    dataKey="medianFare"
                    name="Median Fare"
                    stroke="#38bdf8"
                    strokeWidth={2.5}
                    dot={{ r: 4 }}
                  />
                  <Line
                    yAxisId="fare"
                    type="monotone"
                    dataKey="p10Fare"
                    name="P10 (Lower Bound)"
                    stroke="#10b981"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                  />
                </>
              )}

              {/* Multipliers Mode: Bar chart of elasticity multipliers */}
              {chartView === 'multipliers' && (
                <>
                  <Bar
                    yAxisId="multiplier"
                    dataKey="elasticity"
                    name="Surge Multiplier (x Baseline)"
                    fill="#f43f5e"
                    radius={[6, 6, 0, 0]}
                  />
                  <Line
                    yAxisId="fare"
                    type="monotone"
                    dataKey="medianFare"
                    name="Median Fare (INR)"
                    stroke="#38bdf8"
                    strokeWidth={2.5}
                    dot={{ r: 4 }}
                  />
                </>
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Route Price Heatmap Matrix Section */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 backdrop-blur-md space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Grid3X3 className="w-4 h-4 text-indigo-400" />
                Route Price Heatmap Matrix
              </h3>
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
                {matrixView === 'routes_leadtime' ? '10 Trunk Corridors × Booking Windows' : 'Departure Day × Hour Slots'}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Cross-sectional price matrix illuminating surge hot-spots across advance purchase windows and departure slots.
            </p>
          </div>

          {/* Matrix View Toggle Buttons */}
          <div className="flex items-center rounded-lg bg-slate-950 border border-slate-800 p-0.5 text-xs font-mono">
            <button
              onClick={() => setMatrixView('routes_leadtime')}
              className={`px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5 ${
                matrixView === 'routes_leadtime'
                  ? 'bg-indigo-600 text-white font-semibold shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Grid3X3 className="w-3.5 h-3.5" />
              Routes × Booking Windows (10 Corridors)
            </button>
            <button
              onClick={() => setMatrixView('day_hour')}
              className={`px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5 ${
                matrixView === 'day_hour'
                  ? 'bg-indigo-600 text-white font-semibold shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Calendar className="w-3.5 h-3.5" />
              Day of Week × Departure Slot
            </button>
          </div>
        </div>

        {/* Matrix View 1: 10 Trunk Routes x Lead-Time Windows Matrix */}
        {matrixView === 'routes_leadtime' && (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span className="font-mono">Fare Heatmap Matrix (INR) across Booking Horizons:</span>
              <div className="flex items-center gap-3 text-[11px] font-mono">
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded bg-emerald-950 border border-emerald-700"></span> 1.0x Base
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded bg-sky-950 border border-sky-700"></span> 1.2x - 1.5x
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded bg-amber-950 border border-amber-700"></span> 1.5x - 2.0x
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2.5 h-2.5 rounded bg-rose-950 border border-rose-700"></span> &gt; 2.0x Surge
                </span>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr className="border-b border-slate-800 text-slate-400 bg-slate-950/60">
                    <th className="py-2.5 px-3 font-sans font-medium">Corridor</th>
                    <th className="py-2.5 px-3 text-center">T+30 (Base)</th>
                    <th className="py-2.5 px-3 text-center">T+21</th>
                    <th className="py-2.5 px-3 text-center">T+14</th>
                    <th className="py-2.5 px-3 text-center">T+7</th>
                    <th className="py-2.5 px-3 text-center">T+3</th>
                    <th className="py-2.5 px-3 text-center font-sans font-bold text-rose-400">T+1 (Urgent)</th>
                    <th className="py-2.5 px-3 text-right">Surge Multiplier</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {ROUTE_LEADTIME_DATA.map((row) => (
                    <tr key={row.route_code} className="hover:bg-slate-800/30 transition-colors">
                      <td className="py-3 px-3 font-sans">
                        <div className="font-extrabold text-white font-mono">{row.route_code}</div>
                        <div className="text-[10px] text-slate-400">{row.corridor}</div>
                      </td>

                      {/* T+30 */}
                      <td className="py-3 px-3 text-center">
                        <span className={`px-2.5 py-1 rounded-md text-xs inline-block ${getFareCellClass(row.t30_fare, row.t30_fare)}`}>
                          ₹{row.t30_fare.toLocaleString()}
                        </span>
                      </td>

                      {/* T+21 */}
                      <td className="py-3 px-3 text-center">
                        <span className={`px-2.5 py-1 rounded-md text-xs inline-block ${getFareCellClass(row.t21_fare, row.t30_fare)}`}>
                          ₹{row.t21_fare.toLocaleString()}
                        </span>
                      </td>

                      {/* T+14 */}
                      <td className="py-3 px-3 text-center">
                        <span className={`px-2.5 py-1 rounded-md text-xs inline-block ${getFareCellClass(row.t14_fare, row.t30_fare)}`}>
                          ₹{row.t14_fare.toLocaleString()}
                        </span>
                      </td>

                      {/* T+7 */}
                      <td className="py-3 px-3 text-center">
                        <span className={`px-2.5 py-1 rounded-md text-xs inline-block ${getFareCellClass(row.t7_fare, row.t30_fare)}`}>
                          ₹{row.t7_fare.toLocaleString()}
                        </span>
                      </td>

                      {/* T+3 */}
                      <td className="py-3 px-3 text-center">
                        <span className={`px-2.5 py-1 rounded-md text-xs inline-block ${getFareCellClass(row.t3_fare, row.t30_fare)}`}>
                          ₹{row.t3_fare.toLocaleString()}
                        </span>
                      </td>

                      {/* T+1 */}
                      <td className="py-3 px-3 text-center">
                        <span className={`px-2.5 py-1 rounded-md text-xs inline-block ${getFareCellClass(row.t1_fare, row.t30_fare)}`}>
                          ₹{row.t1_fare.toLocaleString()}
                        </span>
                      </td>

                      {/* Surge Ratio */}
                      <td className="py-3 px-3 text-right">
                        <span
                          className={`font-bold px-2 py-0.5 rounded text-xs ${
                            row.surge_ratio >= 2.5
                              ? 'bg-rose-950 text-rose-300 border border-rose-800'
                              : 'bg-slate-800 text-slate-200'
                          }`}
                        >
                          {row.surge_ratio.toFixed(2)}x
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Matrix View 2: Day of Week x Departure Hour Slot Matrix */}
        {matrixView === 'day_hour' && (
          <div className="space-y-3">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{selectedRoute} Departure Slot Intensity Matrix:</span>
              <div className="flex items-center gap-2 text-[10px]">
                <span className="px-2 py-0.5 rounded bg-emerald-950 text-emerald-300">&lt; 100 Base</span>
                <span className="px-2 py-0.5 rounded bg-sky-950 text-sky-300">100-120 Moderate</span>
                <span className="px-2 py-0.5 rounded bg-amber-950 text-amber-300">120-135 Elevated</span>
                <span className="px-2 py-0.5 rounded bg-rose-950 text-rose-300">&gt; 135 Peak Surge</span>
              </div>
            </div>

            <div className="overflow-x-auto">
              <div className="min-w-[540px]">
                {/* Hour Header */}
                <div className="grid grid-cols-7 gap-2 text-center text-xs text-slate-400 font-mono mb-2">
                  <div className="text-left font-sans text-slate-500 font-medium">Day \ Hour</div>
                  {hours.map((h) => (
                    <div key={h} className="bg-slate-950/60 py-1 rounded">
                      {h.toString().padStart(2, '0')}:00
                    </div>
                  ))}
                </div>

                {/* Rows for each day of week */}
                <div className="space-y-2">
                  {dayNames.map((dayName, dow) => (
                    <div key={dayName} className="grid grid-cols-7 gap-2 items-center">
                      <div className="text-xs font-semibold text-slate-300 font-mono">{dayName}</div>
                      {hours.map((hr) => {
                        const cell = heatmap.matrix.find(
                          (m) => m.day_of_week === dow && m.hour_of_day === hr
                        );
                        const index = cell ? cell.fare_index : 100;
                        const fare = cell ? cell.avg_fare_inr : 4500;

                        let bgClass = 'bg-slate-800 text-slate-200';
                        if (index >= 135) {
                          bgClass = 'bg-rose-950/90 text-rose-300 border border-rose-800/80';
                        } else if (index >= 120) {
                          bgClass = 'bg-amber-950/80 text-amber-300 border border-amber-800/60';
                        } else if (index >= 100) {
                          bgClass = 'bg-sky-950/80 text-sky-300 border border-sky-800/60';
                        } else {
                          bgClass = 'bg-emerald-950/80 text-emerald-300 border border-emerald-800/60';
                        }

                        return (
                          <div
                            key={hr}
                            className={`py-2 px-1 rounded-lg text-center font-mono transition-transform hover:scale-105 cursor-default ${bgClass}`}
                            title={`${dayName} ${hr}:00 - Index: ${index}, Fare: ₹${fare}`}
                          >
                            <div className="text-xs font-bold">{index}</div>
                            <div className="text-[10px] opacity-75">₹{(fare / 1000).toFixed(1)}k</div>
                          </div>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* CPI Augmentation Methodology Info Box */}
      <div className="bg-indigo-950/20 border border-indigo-800/50 rounded-xl p-5 backdrop-blur-md">
        <div className="flex items-start gap-3">
          <Info className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
          <div className="text-xs text-slate-300 space-y-1">
            <h4 className="font-bold text-white text-sm">
              Methodological Significance for Consumer Price Index (CPI):
            </h4>
            <p>
              Traditional CPI airfare collection only samples a single monthly quote per state, capturing less than 10% of true transactional pricing. APIx captures the full hyperbolic surge curve across purchase windows (T+1 to T+60), allowing economists at MoSPI and DGCA to construct a passenger-weighted geometric mean that reflects true household travel expenditures.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
