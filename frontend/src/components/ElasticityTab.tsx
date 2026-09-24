import React, { useState } from 'react';
import { LeadTimeCurveResponse, HeatmapMatrixResponse } from '../types/api';
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
  Clock,
  Calendar,
  TrendingUp,
  Info,
} from 'lucide-react';
interface ElasticityTabProps {
  leadTimeCurve: LeadTimeCurveResponse;
  heatmap: HeatmapMatrixResponse;
}

export const ElasticityTab: React.FC<ElasticityTabProps> = ({ leadTimeCurve, heatmap }) => {
  const [selectedRoute, setSelectedRoute] = useState<string>('DEL-BOM');

  const chartData = [...leadTimeCurve.curve_points]
    .sort((a, b) => b.days_before_departure - a.days_before_departure)
    .map((p) => ({
      window: p.booking_window_label || `T+${p.days_before_departure}`,
      days: p.days_before_departure,
      avgFare: p.avg_fare_inr,
      medianFare: p.median_fare_inr,
      p10Fare: p.p10_fare_inr,
      p90Fare: p.p90_fare_inr,
      elasticity: p.elasticity_factor,
      samples: p.sample_count,
    }));

  const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const hours = [6, 9, 12, 15, 18, 21];

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Clock className="w-5 h-5 text-sky-400" />
              Advance Booking Window & Price Elasticity
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Analysis of dynamic pricing multipliers from T+60 days down to T+1 emergency booking.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-400">Target Corridor:</span>
            <select
              value={selectedRoute}
              onChange={(e) => setSelectedRoute(e.target.value)}
              className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono"
            >
              <option value="DEL-BOM">DEL-BOM (Delhi - Mumbai)</option>
              <option value="DEL-BLR">DEL-BLR (Delhi - Bengaluru)</option>
              <option value="BOM-BLR">BOM-BLR (Mumbai - Bengaluru)</option>
              <option value="DEL-CCU">DEL-CCU (Delhi - Kolkata)</option>
            </select>
          </div>
        </div>
      </div>

      {/* Elasticity Multipliers Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        {leadTimeCurve.curve_points.map((pt) => {
          const isUrgent = pt.days_before_departure <= 3;
          const isBase = pt.days_before_departure === 30;

          return (
            <div
              key={pt.days_before_departure}
              className={`p-3 rounded-xl border text-center transition-all ${
                isUrgent
                  ? 'bg-rose-950/20 border-rose-800/60'
                  : isBase
                  ? 'bg-sky-950/20 border-sky-800/60'
                  : 'bg-slate-900/80 border-slate-800'
              }`}
            >
              <div className="text-[11px] font-mono text-slate-400">
                {pt.booking_window_label || `T+${pt.days_before_departure}`}
              </div>
              <div className="text-xs text-slate-500 font-sans mt-0.5">
                {pt.days_before_departure}d out
              </div>
              <div className="mt-2 text-base font-extrabold text-white font-mono">
                {pt.elasticity_factor.toFixed(2)}x
              </div>
              <div className="text-[10px] text-slate-400 mt-1 font-mono">
                ₹{pt.median_fare_inr.toLocaleString('en-IN')}
              </div>
            </div>
          );
        })}
      </div>

      {/* Main Elasticity Curve Chart */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 backdrop-blur-md">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-sky-400" />
              Fare Distribution by Booking Window (T-Days to Departure)
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Notice the hyperbolic surge starting at T-7 and peaking at T-1 (urgent business travel).
            </p>
          </div>

          <div className="flex items-center gap-4 text-xs font-mono">
            <span className="flex items-center gap-1.5 text-rose-400">
              <span className="w-2.5 h-0.5 bg-rose-400 inline-block"></span> P90 Upper Ceiling
            </span>
            <span className="flex items-center gap-1.5 text-sky-400">
              <span className="w-2.5 h-0.5 bg-sky-400 inline-block"></span> Median Fare
            </span>
            <span className="flex items-center gap-1.5 text-emerald-400">
              <span className="w-2.5 h-0.5 bg-emerald-400 inline-block"></span> P10 Lower Floor
            </span>
          </div>
        </div>

        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="window" stroke="#64748b" tick={{ fontSize: 11 }} />
              <YAxis
                stroke="#64748b"
                tick={{ fontSize: 11 }}
                domain={['dataMin - 1000', 'dataMax + 1000']}
                tickFormatter={(v) => `₹${(v / 1000).toFixed(0)}k`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: '#334155',
                  borderRadius: '0.5rem',
                  fontSize: '12px',
                }}
                formatter={(val: unknown) => [
                  typeof val === 'number' ? `₹${val.toLocaleString('en-IN')}` : String(val),
                  '',
                ]}
              />
              <Legend wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
              <Line
                type="monotone"
                dataKey="p90Fare"
                name="P90 (Surge Ceiling)"
                stroke="#f43f5e"
                strokeWidth={2}
                strokeDasharray="4 4"
                dot={{ r: 3 }}
              />
              <Line
                type="monotone"
                dataKey="avgFare"
                name="Average Fare"
                stroke="#a855f7"
                strokeWidth={1.5}
                dot={{ r: 3 }}
              />
              <Line
                type="monotone"
                dataKey="medianFare"
                name="Median Fare"
                stroke="#38bdf8"
                strokeWidth={2.5}
                dot={{ r: 4 }}
              />
              <Line
                type="monotone"
                dataKey="p10Fare"
                name="P10 (Promo Floor)"
                stroke="#10b981"
                strokeWidth={2}
                strokeDasharray="4 4"
                dot={{ r: 3 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Day of Week & Hour of Day Heatmap */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 backdrop-blur-md">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Calendar className="w-4 h-4 text-indigo-400" />
              Departure Timing Heatmap ({selectedRoute})
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Fare index variations by day of week and departure time slot.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-400">Scale:</span>
            <span className="px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 text-[10px]">
              &lt; 100 Base
            </span>
            <span className="px-2 py-0.5 rounded bg-sky-950 text-sky-300 text-[10px]">
              100-120 Moderate
            </span>
            <span className="px-2 py-0.5 rounded bg-rose-950 text-rose-300 text-[10px]">
              &gt; 130 Peak
            </span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <div className="min-w-[500px]">
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
                    } else if (index >= 115) {
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
