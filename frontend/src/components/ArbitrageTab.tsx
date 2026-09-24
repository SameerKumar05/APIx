import React, { useState, useMemo } from 'react';
import { ArbitrageResponse, ArbitrageOpportunity } from '../types/api';
import {
  Scale,
  TrendingDown,
  AlertTriangle,
  Filter,
  CheckCircle2,
  Plane,
  Percent,
  Search,
  Sparkles,
  RefreshCw,
  Info,
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

interface ArbitrageTabProps {
  arbitrage: ArbitrageResponse;
  onRefresh?: () => void;
}

export const ArbitrageTab: React.FC<ArbitrageTabProps> = ({ arbitrage, onRefresh }) => {
  const [selectedRoute, setSelectedRoute] = useState<string>('ALL');
  const [selectedAirline, setSelectedAirline] = useState<string>('ALL');
  const [selectedDirection, setSelectedDirection] = useState<string>('ALL');
  const [minSpreadPct, setMinSpreadPct] = useState<number>(0);
  const [actionableOnly, setActionableOnly] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [sortBy, setSortBy] = useState<'spread_pct' | 'spread_inr'>('spread_pct');

  const items = arbitrage.items || [];

  // Filter and sort items
  const filteredItems = useMemo(() => {
    return items
      .filter((item: ArbitrageOpportunity) => {
        if (selectedRoute !== 'ALL' && item.route_code !== selectedRoute) return false;
        if (selectedAirline !== 'ALL' && item.airline_code !== selectedAirline) return false;
        if (selectedDirection !== 'ALL' && item.direction !== selectedDirection) return false;
        if (item.spread_percentage < minSpreadPct) return false;
        if (actionableOnly && !item.actionable) return false;
        if (searchQuery.trim()) {
          const q = searchQuery.toLowerCase();
          const matchesRoute = item.route_code.toLowerCase().includes(q);
          const matchesOta = item.ota_name.toLowerCase().includes(q);
          const matchesAirline = (item.airline_name || item.airline_code).toLowerCase().includes(q);
          const matchesFlight = (item.flight_number || '').toLowerCase().includes(q);
          if (!matchesRoute && !matchesOta && !matchesAirline && !matchesFlight) return false;
        }
        return true;
      })
      .sort((a, b) => {
        if (sortBy === 'spread_pct') {
          return b.spread_percentage - a.spread_percentage;
        }
        return b.spread_inr - a.spread_inr;
      });
  }, [items, selectedRoute, selectedAirline, selectedDirection, minSpreadPct, actionableOnly, searchQuery, sortBy]);

  // Unique lists for dropdowns
  const uniqueRoutes = useMemo(() => {
    return Array.from(new Set(items.map((i) => i.route_code))).sort();
  }, [items]);

  const uniqueAirlines = useMemo(() => {
    return Array.from(new Set(items.map((i) => i.airline_code))).sort();
  }, [items]);

  // Chart data
  const chartData = useMemo(() => {
    return items.slice(0, 8).map((item) => ({
      name: `${item.route_code} (${item.airline_code})`,
      route: item.route_code,
      carrier: item.airline_code,
      airlineFare: item.airline_direct_fare,
      otaFare: item.ota_fare,
      spreadInr: item.spread_inr,
      spreadPct: item.spread_percentage,
      direction: item.direction,
      otaName: item.ota_name,
    }));
  }, [items]);

  const maxSpreadObserved = items.reduce((max, i) => Math.max(max, i.spread_percentage), 0);
  const totalPotentialSavings = items.reduce((sum, i) => sum + i.spread_inr, 0);
  const highSpreadAlertsCount = items.filter((i) => i.spread_percentage >= 8.0).length;

  return (
    <div className="space-y-6">
      {/* Top Banner & Summary Cards */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 backdrop-blur-sm">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <Scale className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Airline Direct vs OTA Price Spread & Arbitrage
                <span className="text-xs px-2.5 py-0.5 rounded-full font-mono font-semibold bg-indigo-950/80 text-indigo-300 border border-indigo-800/80">
                  {arbitrage.opportunities_count} Active Spreads
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Surveillance of pricing disparities between airline direct booking engines and Online Travel Agencies (OTAs)
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {onRefresh && (
              <button
                onClick={onRefresh}
                className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-all"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Refresh Spreads</span>
              </button>
            )}
            <div className="text-[11px] font-mono text-slate-500">
              Evaluated: {new Date(arbitrage.generated_at).toLocaleTimeString()}
            </div>
          </div>
        </div>

        {/* High Spread Alert Banner */}
        {highSpreadAlertsCount > 0 && (
          <div className="mt-5 p-4 rounded-xl bg-amber-950/60 border border-amber-800/80 flex items-start gap-3 text-xs text-amber-200">
            <AlertTriangle className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
            <div>
              <span className="font-bold text-amber-300">
                Significant Arbitrage Alert ({highSpreadAlertsCount} Corridors &ge; 8.0% Spread):
              </span>{' '}
              Substantial price divergence detected between direct airline inventory and OTA aggregator portals.
              Such spreads suggest targeted OTA discounting, commission subsidization, or delayed inventory synchronization.
            </div>
          </div>
        )}

        {/* Global Summary KPI Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6">
          <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-3.5">
            <div className="flex items-center justify-between text-[11px] font-medium text-slate-400">
              <span>Routes Evaluated</span>
              <Plane className="w-4 h-4 text-sky-400" />
            </div>
            <div className="mt-2">
              <span className="text-2xl font-bold font-mono text-white">
                {arbitrage.routes_evaluated}
              </span>
            </div>
            <div className="text-[10px] text-slate-500 mt-1">High-density trunk corridors</div>
          </div>

          <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-3.5">
            <div className="flex items-center justify-between text-[11px] font-medium text-slate-400">
              <span>Arbitrage Opportunities</span>
              <Scale className="w-4 h-4 text-indigo-400" />
            </div>
            <div className="mt-2 flex items-baseline gap-1.5">
              <span className="text-2xl font-bold font-mono text-indigo-400">
                {arbitrage.opportunities_count}
              </span>
              <span className="text-xs font-mono text-slate-500">actionable</span>
            </div>
            <div className="text-[10px] text-emerald-400 mt-1">Direct consumer savings</div>
          </div>

          <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-3.5">
            <div className="flex items-center justify-between text-[11px] font-medium text-slate-400">
              <span>Peak Price Spread</span>
              <Percent className="w-4 h-4 text-rose-400" />
            </div>
            <div className="mt-2">
              <span className="text-2xl font-bold font-mono text-rose-400">
                +{maxSpreadObserved.toFixed(2)}%
              </span>
            </div>
            <div className="text-[10px] text-slate-500 mt-1">Max divergence recorded</div>
          </div>

          <div className="bg-slate-950/50 border border-slate-800/80 rounded-xl p-3.5">
            <div className="flex items-center justify-between text-[11px] font-medium text-slate-400">
              <span>Total Potential Savings</span>
              <TrendingDown className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="mt-2">
              <span className="text-2xl font-bold font-mono text-emerald-400">
                ₹{totalPotentialSavings.toLocaleString()}
              </span>
            </div>
            <div className="text-[10px] text-slate-500 mt-1">Per ticket across corridors</div>
          </div>
        </div>
      </div>

      {/* Recharts Spread Visualizer */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-sky-400" />
              Direct Airline vs OTA Spread Comparison Across Key Corridors
            </h3>
            <p className="text-xs text-slate-400">
              Green bars denote net INR savings when booking through the cheaper channel
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs font-mono">
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded bg-emerald-500"></span>
              <span className="text-slate-300">Spread &ge; 8% (High)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded bg-sky-500"></span>
              <span className="text-slate-300">Spread &lt; 8% (Moderate)</span>
            </div>
          </div>
        </div>

        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 25 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} />
              <XAxis
                dataKey="name"
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                interval={0}
                angle={-15}
                textAnchor="end"
              />
              <YAxis
                stroke="#64748b"
                fontSize={11}
                tickLine={false}
                unit="₹"
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (active && payload && payload.length) {
                    const d = payload[0].payload;
                    return (
                      <div className="bg-slate-900 border border-slate-700 p-3 rounded-xl shadow-xl text-xs font-mono">
                        <p className="font-bold text-white text-sm">{d.route} • {d.carrier}</p>
                        <div className="mt-2 space-y-1">
                          <p className="text-slate-300">
                            Airline Direct: <strong className="text-white">₹{d.airlineFare.toLocaleString()}</strong>
                          </p>
                          <p className="text-slate-300">
                            OTA ({d.otaName}): <strong className="text-white">₹{d.otaFare.toLocaleString()}</strong>
                          </p>
                          <p className="text-emerald-400 font-bold mt-1">
                            Net Spread: ₹{d.spreadInr.toLocaleString()} (+{d.spreadPct}%)
                          </p>
                          <p className="text-sky-300 font-semibold">
                            Winner: {d.direction === 'OTA_CHEAPER' ? `OTA (${d.otaName})` : 'Airline Direct'}
                          </p>
                        </div>
                      </div>
                    );
                  }
                  return null;
                }}
              />
              <Bar dataKey="spreadInr" radius={[6, 6, 0, 0]}>
                {chartData.map((entry, index) => (
                  <Cell
                    key={`bar-cell-${index}`}
                    fill={entry.spreadPct >= 8.0 ? '#10b981' : '#38bdf8'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Interactive Filter Toolbar */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
            {/* Search Box */}
            <div className="relative min-w-[200px]">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 transform -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search route, airline, OTA..."
                className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
            </div>

            {/* Route Filter */}
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <Filter className="w-3.5 h-3.5 text-slate-500" />
              <span>Route:</span>
              <select
                value={selectedRoute}
                onChange={(e) => setSelectedRoute(e.target.value)}
                className="bg-slate-950 text-slate-200 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none"
              >
                <option value="ALL">All Routes</option>
                {uniqueRoutes.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>

            {/* Airline Filter */}
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <span>Carrier:</span>
              <select
                value={selectedAirline}
                onChange={(e) => setSelectedAirline(e.target.value)}
                className="bg-slate-950 text-slate-200 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none"
              >
                <option value="ALL">All Airlines</option>
                {uniqueAirlines.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>

            {/* Direction Filter */}
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <span>Winner:</span>
              <select
                value={selectedDirection}
                onChange={(e) => setSelectedDirection(e.target.value)}
                className="bg-slate-950 text-slate-200 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none"
              >
                <option value="ALL">All Directions</option>
                <option value="OTA_CHEAPER">OTA Cheaper</option>
                <option value="AIRLINE_CHEAPER">Airline Direct Cheaper</option>
              </select>
            </div>

            {/* Min Spread Threshold */}
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <span>Min Spread:</span>
              <select
                value={minSpreadPct}
                onChange={(e) => setMinSpreadPct(Number(e.target.value))}
                className="bg-slate-950 text-slate-200 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none"
              >
                <option value={0}>All (&ge; 0%)</option>
                <option value={5}>&ge; 5% Spread</option>
                <option value={7}>&ge; 7% Spread</option>
                <option value={8}>&ge; 8% High Spread</option>
              </select>
            </div>
          </div>

          {/* Actionable Toggle & Sort By */}
          <div className="flex items-center gap-3 self-end lg:self-auto">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300">
              <input
                type="checkbox"
                checked={actionableOnly}
                onChange={(e) => setActionableOnly(e.target.checked)}
                className="rounded border-slate-700 bg-slate-950 text-sky-500 focus:ring-0"
              />
              <span>Actionable Only</span>
            </label>

            <span className="text-slate-700">|</span>

            <div className="flex items-center gap-1 text-xs text-slate-400">
              <span>Sort:</span>
              <button
                onClick={() => setSortBy('spread_pct')}
                className={`px-2 py-1 rounded text-xs font-mono font-semibold ${
                  sortBy === 'spread_pct' ? 'bg-sky-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-white'
                }`}
              >
                % Spread
              </button>
              <button
                onClick={() => setSortBy('spread_inr')}
                className={`px-2 py-1 rounded text-xs font-mono font-semibold ${
                  sortBy === 'spread_inr' ? 'bg-sky-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-white'
                }`}
              >
                ₹ Spread
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Arbitrage Opportunity Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredItems.map((item: ArbitrageOpportunity, idx: number) => {
          const isOtaCheaper = item.direction === 'OTA_CHEAPER';
          const isHighSpread = item.spread_percentage >= 8.0;

          return (
            <div
              key={`${item.route_code}-${item.airline_code}-${idx}`}
              className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 hover:border-slate-700 transition-all flex flex-col justify-between"
            >
              <div>
                {/* Header: Route, Flight & Badges */}
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-base font-bold font-mono text-white">
                        {item.route_code}
                      </span>
                      {item.flight_number && (
                        <span className="text-xs font-mono text-slate-400 bg-slate-800 px-1.5 py-0.2 rounded">
                          {item.flight_number}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-400 font-medium">
                      {item.airline_name || item.airline_code}
                    </p>
                  </div>

                  <div className="flex flex-col items-end gap-1">
                    <span
                      className={`px-2 py-0.5 rounded-full font-mono text-[10px] font-bold border ${
                        isHighSpread
                          ? 'bg-rose-950/80 text-rose-300 border-rose-800'
                          : 'bg-emerald-950/80 text-emerald-300 border-emerald-800'
                      }`}
                    >
                      +{item.spread_percentage.toFixed(2)}% SPREAD
                    </span>

                    {item.actionable && (
                      <span className="flex items-center gap-1 text-[10px] font-mono text-emerald-400">
                        <CheckCircle2 className="w-2.5 h-2.5" /> Actionable
                      </span>
                    )}
                  </div>
                </div>

                {/* Price Comparison Box */}
                <div className="mt-4 p-3 rounded-xl bg-slate-950/70 border border-slate-800/80">
                  <div className="grid grid-cols-2 gap-3 text-center">
                    {/* Airline Direct */}
                    <div className="p-2 rounded-lg bg-slate-900/60 border border-slate-800">
                      <span className="text-[10px] text-slate-400 uppercase font-mono block">
                        Airline Direct
                      </span>
                      <span className="text-base font-bold font-mono text-white mt-1 block">
                        ₹{item.airline_direct_fare.toLocaleString()}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono">Official Site</span>
                    </div>

                    {/* OTA */}
                    <div className="p-2 rounded-lg bg-slate-900/60 border border-slate-800">
                      <span className="text-[10px] text-slate-400 uppercase font-mono block truncate">
                        OTA ({item.ota_name})
                      </span>
                      <span className="text-base font-bold font-mono text-white mt-1 block">
                        ₹{item.ota_fare.toLocaleString()}
                      </span>
                      <span className="text-[10px] text-slate-500 font-mono capitalize">
                        Aggregator
                      </span>
                    </div>
                  </div>

                  {/* Net Delta Footer */}
                  <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex items-center justify-between text-xs font-mono">
                    <span className="text-slate-400">Price Disparity:</span>
                    <span className="font-bold text-emerald-400 flex items-center gap-1">
                      <TrendingDown className="w-3.5 h-3.5" />
                      Save ₹{item.spread_inr.toLocaleString()}
                    </span>
                  </div>
                </div>

                {/* Recommendation Pill */}
                <div className="mt-3 flex items-center justify-between text-[11px] p-2 rounded-lg bg-slate-800/40 border border-slate-700/40">
                  <span className="text-slate-400">Recommendation:</span>
                  <span className="font-semibold text-white flex items-center gap-1">
                    {isOtaCheaper ? (
                      <>
                        Book via <strong className="text-sky-400 capitalize">{item.ota_name}</strong>
                      </>
                    ) : (
                      <>
                        Book <strong className="text-amber-400">Direct Airline</strong>
                      </>
                    )}
                  </span>
                </div>
              </div>

              {/* Timestamp footer */}
              {item.departure_datetime && (
                <div className="mt-4 pt-2 border-t border-slate-800/60 flex items-center justify-between text-[10px] text-slate-500 font-mono">
                  <span>
                    Dep:{' '}
                    {new Date(item.departure_datetime).toLocaleDateString([], {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })}
                  </span>
                  <span className="text-slate-400">Verified Cycle 3</span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {filteredItems.length === 0 && (
        <div className="py-12 text-center bg-slate-900/40 border border-slate-800 rounded-2xl">
          <Info className="w-8 h-8 text-slate-500 mx-auto mb-2" />
          <p className="text-sm text-slate-300 font-medium">No arbitrage opportunities match filters.</p>
          <p className="text-xs text-slate-500 mt-1">Try relaxing minimum spread % or clearing the search query.</p>
        </div>
      )}

      {/* Comprehensive Arbitrage Ledger Table */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Scale className="w-4 h-4 text-indigo-400" />
            <h3 className="text-sm font-bold text-white">
              Direct vs OTA Price Arbitrage Ledger ({filteredItems.length} Records)
            </h3>
          </div>
          <span className="text-[11px] text-slate-400 font-mono">
            DGCA Fair Competition & Price Gouging Monitoring
          </span>
        </div>

        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950 text-slate-400 font-mono text-[10px] uppercase border-b border-slate-800">
              <tr>
                <th className="py-2.5 px-3">Corridor</th>
                <th className="py-2.5 px-3">Airline</th>
                <th className="py-2.5 px-3">Flight</th>
                <th className="py-2.5 px-3 text-right">Airline Direct (₹)</th>
                <th className="py-2.5 px-3">OTA Channel</th>
                <th className="py-2.5 px-3 text-right">OTA Fare (₹)</th>
                <th className="py-2.5 px-3 text-right">Net Spread (₹)</th>
                <th className="py-2.5 px-3 text-right">Spread (%)</th>
                <th className="py-2.5 px-3">Optimal Channel</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono text-slate-300">
              {filteredItems.map((item: ArbitrageOpportunity, idx: number) => {
                const isOtaCheaper = item.direction === 'OTA_CHEAPER';
                return (
                  <tr key={`ledger-${item.route_code}-${idx}`} className="hover:bg-slate-800/40">
                    <td className="py-2.5 px-3 font-bold text-sky-400">
                      {item.route_code}
                    </td>
                    <td className="py-2.5 px-3">
                      <span className="px-1.5 py-0.5 rounded bg-slate-800 text-white font-semibold border border-slate-700">
                        {item.airline_code}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-slate-400">
                      {item.flight_number || '—'}
                    </td>
                    <td className="py-2.5 px-3 text-right text-white font-semibold">
                      ₹{item.airline_direct_fare.toLocaleString()}
                    </td>
                    <td className="py-2.5 px-3 capitalize text-slate-300">
                      {item.ota_name}
                    </td>
                    <td className="py-2.5 px-3 text-right text-white font-semibold">
                      ₹{item.ota_fare.toLocaleString()}
                    </td>
                    <td className="py-2.5 px-3 text-right text-emerald-400 font-bold">
                      ₹{item.spread_inr.toLocaleString()}
                    </td>
                    <td className="py-2.5 px-3 text-right font-bold">
                      <span
                        className={`px-1.5 py-0.5 rounded ${
                          item.spread_percentage >= 8.0
                            ? 'bg-rose-950/80 text-rose-300 border border-rose-800/80'
                            : 'bg-emerald-950/80 text-emerald-300 border border-emerald-800/80'
                        }`}
                      >
                        +{item.spread_percentage.toFixed(2)}%
                      </span>
                    </td>
                    <td className="py-2.5 px-3">
                      <span className="flex items-center gap-1 font-sans text-xs">
                        {isOtaCheaper ? (
                          <span className="text-sky-300 font-medium capitalize">
                            OTA ({item.ota_name})
                          </span>
                        ) : (
                          <span className="text-amber-300 font-medium">
                            Airline Direct
                          </span>
                        )}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
