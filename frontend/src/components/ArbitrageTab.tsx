import React, { useState, useMemo } from 'react';
import { ArbitrageResponse, ArbitrageOpportunity } from '../types/api';
import {
  Scale,
  AlertTriangle,
  Filter,
  CheckCircle2,
  Plane,
  Percent,
  Search,
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
        const spreadPct = item.spread_percentage ?? 0;
        if (spreadPct < minSpreadPct) return false;
        if (actionableOnly && !item.actionable) return false;
        if (searchQuery.trim()) {
          const q = searchQuery.toLowerCase().trim();
          const matchesRoute = (item.route_code || '').toLowerCase().includes(q);
          const otaName = item.ota_platform || item.ota_name || '';
          const matchesOta = otaName.toLowerCase().includes(q);
          const matchesAirline = (item.airline_name || item.airline_code || '').toLowerCase().includes(q);
          const matchesFlight = (item.flight_number || '').toLowerCase().includes(q);
          if (!matchesRoute && !matchesOta && !matchesAirline && !matchesFlight) return false;
        }
        return true;
      })
      .sort((a, b) => {
        const spreadA = a.spread_percentage ?? 0;
        const spreadB = b.spread_percentage ?? 0;
        const inrA = a.spread_inr ?? a.spread_amount ?? 0;
        const inrB = b.spread_inr ?? b.spread_amount ?? 0;
        if (sortBy === 'spread_pct') {
          return spreadB - spreadA;
        }
        return inrB - inrA;
      });
  }, [items, selectedRoute, selectedAirline, selectedDirection, minSpreadPct, actionableOnly, searchQuery, sortBy]);

  // Unique lists for dropdowns
  const uniqueRoutes = useMemo(() => {
    return Array.from(new Set(items.map((i) => i.route_code).filter(Boolean))).sort();
  }, [items]);

  const uniqueAirlines = useMemo(() => {
    return Array.from(new Set(items.map((i) => i.airline_code).filter(Boolean))).sort();
  }, [items]);

  // Chart data
  const chartData = useMemo(() => {
    return items.slice(0, 8).map((item) => {
      const otaName = item.ota_platform || item.ota_name || 'OTA';
      const airlineFare = item.direct_fare ?? item.airline_direct_fare ?? 0;
      const otaFare = item.ota_fare ?? 0;
      const spreadInr = item.spread_inr ?? item.spread_amount ?? (airlineFare > otaFare ? airlineFare - otaFare : otaFare - airlineFare);
      const spreadPct = item.spread_percentage ?? (airlineFare > 0 ? (spreadInr / airlineFare) * 100 : 0);
      return {
        name: `${item.route_code || ''} (${item.airline_code || ''})`,
        route: item.route_code || '',
        carrier: item.airline_code || '',
        airlineFare,
        otaFare,
        spreadInr,
        spreadPct: Number(spreadPct.toFixed(2)),
        direction: item.direction || (otaFare < airlineFare ? 'OTA_CHEAPER' : 'AIRLINE_CHEAPER'),
        otaName,
      };
    });
  }, [items]);

  const maxSpreadObserved = items.reduce((max, i) => Math.max(max, i.spread_percentage ?? 0), 0);
  const totalPotentialSavings = items.reduce((sum, i) => sum + (i.spread_inr ?? 0), 0);
  const highSpreadAlertsCount = items.filter((i) => (i.spread_percentage ?? 0) >= 8.0).length;

  return (
    <div className="space-y-6">
      {/* Top Banner & Summary Cards */}
      <div className="border border-neutral-800 bg-neutral-950 rounded-lg p-5">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium border border-neutral-800 bg-neutral-900 text-neutral-300">
                PRICE DISPERSION AUDIT
              </span>
              <span className="text-neutral-600 text-xs">•</span>
              <span className="text-xs px-2 py-0.5 rounded font-mono font-medium border border-neutral-800 bg-neutral-900 text-neutral-300">
                {arbitrage.opportunities_count ?? 0} Active Spreads
              </span>
            </div>
            <h1 className="text-base font-semibold tracking-tight text-white">
              Airline Direct vs OTA Price Spread &amp; Arbitrage
            </h1>
            <p className="text-xs text-neutral-400 mt-1 max-w-2xl leading-relaxed">
              Surveillance of pricing disparities between airline direct booking engines and Online Travel Agencies (OTAs).
            </p>
          </div>

          <div className="flex items-center gap-3">
            {onRefresh && (
              <button
                onClick={onRefresh}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono rounded border border-neutral-800 bg-neutral-900 hover:bg-neutral-800 text-neutral-200 hover:text-white transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5 text-neutral-400" />
                <span>Refresh Spreads</span>
              </button>
            )}
            <div className="text-[11px] font-mono text-neutral-500">
              Evaluated: {new Date(arbitrage.generated_at).toLocaleTimeString()}
            </div>
          </div>
        </div>

        {/* High Spread Alert Banner */}
        {highSpreadAlertsCount > 0 && (
          <div className="mt-4 p-3.5 rounded border border-amber-500/30 bg-amber-950/10 flex items-start gap-2.5 text-xs text-amber-200 font-mono">
            <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
            <div>
              <span className="font-semibold text-amber-300">
                Arbitrage Alert ({highSpreadAlertsCount} Corridors &ge; 8.0% Spread):
              </span>{' '}
              Substantial price divergence detected between direct airline inventory and OTA aggregator portals.
              Suggests targeted OTA discounting, commission subsidization, or delayed inventory synchronization.
            </div>
          </div>
        )}

        {/* Global Summary KPI Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
          <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-3.5">
            <div className="flex items-center justify-between text-xs font-medium uppercase tracking-wider text-neutral-400">
              <span>Routes Evaluated</span>
              <Plane className="w-3.5 h-3.5 text-neutral-500" />
            </div>
            <div className="mt-2">
              <span className="text-2xl font-semibold font-mono tabular-nums text-white">
                {arbitrage.routes_evaluated}
              </span>
            </div>
            <div className="text-[10px] text-neutral-500 font-mono mt-1">High-density trunk corridors</div>
          </div>

          <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-3.5">
            <div className="flex items-center justify-between text-xs font-medium uppercase tracking-wider text-neutral-400">
              <span>Arbitrage Opportunities</span>
              <Scale className="w-3.5 h-3.5 text-neutral-500" />
            </div>
            <div className="mt-2 flex items-baseline gap-1.5">
              <span className="text-2xl font-semibold font-mono tabular-nums text-white">
                {arbitrage.opportunities_count}
              </span>
              <span className="text-xs font-mono text-neutral-500">actionable</span>
            </div>
            <div className="text-[10px] text-neutral-500 font-mono mt-1">Direct consumer savings</div>
          </div>

          <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-3.5">
            <div className="flex items-center justify-between text-xs font-medium uppercase tracking-wider text-neutral-400">
              <span>Peak Price Spread</span>
              <Percent className="w-3.5 h-3.5 text-neutral-500" />
            </div>
            <div className="mt-2">
              <span className="text-2xl font-semibold font-mono tabular-nums text-white">
                +{maxSpreadObserved.toFixed(2)}%
              </span>
            </div>
            <div className="text-[10px] text-neutral-500 font-mono mt-1">Max divergence recorded</div>
          </div>

          <div className="bg-neutral-950 border border-neutral-800 rounded-lg p-3.5">
            <div className="flex items-center justify-between text-xs font-medium uppercase tracking-wider text-neutral-400">
              <span>Total Potential Savings</span>
              <span className="text-xs font-mono text-neutral-500">Per ticket</span>
            </div>
            <div className="mt-2">
              <span className="text-2xl font-semibold font-mono tabular-nums text-white">
                ₹{totalPotentialSavings.toLocaleString('en-IN')}
              </span>
            </div>
            <div className="text-[10px] text-neutral-500 font-mono mt-1">Aggregated across corridors</div>
          </div>
        </div>
      </div>

      {/* Recharts Spread Visualizer */}
      <div className="border border-neutral-800 bg-neutral-950 rounded-lg p-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-4">
          <div>
            <h3 className="text-xs font-medium uppercase tracking-wider text-neutral-400">
              Direct Airline vs OTA Spread Comparison Across Key Corridors
            </h3>
            <p className="text-xs text-neutral-500 mt-0.5">
              Monochrome bars denote net INR savings when booking through the cheaper channel
            </p>
          </div>
          <div className="flex items-center gap-4 text-xs font-mono">
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 bg-white rounded-sm"></span>
              <span className="text-neutral-300">Spread &ge; 8% (High)</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 bg-neutral-600 rounded-sm"></span>
              <span className="text-neutral-400">Spread &lt; 8% (Moderate)</span>
            </div>
          </div>
        </div>

        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 25 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" vertical={false} />
              <XAxis
                dataKey="name"
                stroke="#737373"
                tick={{ fill: '#a3a3a3', fontSize: 11, fontFamily: 'monospace' }}
                tickLine={false}
                interval={0}
                angle={-15}
                textAnchor="end"
                axisLine={{ stroke: '#262626' }}
              />
              <YAxis
                stroke="#737373"
                tick={{ fill: '#a3a3a3', fontSize: 11, fontFamily: 'monospace' }}
                tickLine={false}
                unit="₹"
                axisLine={{ stroke: '#262626' }}
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (active && payload && payload.length) {
                    const d = payload[0].payload;
                    return (
                      <div className="bg-neutral-950 border border-neutral-800 p-3 rounded font-mono text-xs">
                        <p className="font-semibold text-white">{d.route} • {d.carrier}</p>
                        <div className="mt-2 space-y-1">
                          <p className="text-neutral-400">
                            Airline Direct: <strong className="text-white">₹{d.airlineFare.toLocaleString('en-IN')}</strong>
                          </p>
                          <p className="text-neutral-400">
                            OTA ({d.otaName}): <strong className="text-white">₹{d.otaFare.toLocaleString('en-IN')}</strong>
                          </p>
                          <p className="text-white font-medium mt-1">
                            Net Spread: ₹{d.spreadInr.toLocaleString('en-IN')} (+{d.spreadPct}%)
                          </p>
                          <p className="text-neutral-300">
                            Cheaper: {d.direction === 'OTA_CHEAPER' ? `OTA (${d.otaName})` : 'Airline Direct'}
                          </p>
                        </div>
                      </div>
                    );
                  }
                  return null;
                }}
              />
              <Bar dataKey="spreadInr" radius={[2, 2, 0, 0]}>
                {chartData.map((entry, index) => (
                  <Cell
                    key={`bar-cell-${index}`}
                    fill={entry.spreadPct >= 8.0 ? '#ffffff' : '#525252'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Interactive Filter Toolbar */}
      <div className="border border-neutral-800 bg-neutral-950 rounded-lg p-4">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2.5">
            {/* Search Box */}
            <div className="relative min-w-[200px]">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 transform -translate-y-1/2 text-neutral-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search route, airline, OTA..."
                className="w-full bg-neutral-900 border border-neutral-800 rounded pl-8 pr-3 py-1.5 text-xs text-neutral-200 placeholder-neutral-500 focus:outline-none focus:border-neutral-700 font-mono"
              />
            </div>

            {/* Route Filter */}
            <div className="flex items-center gap-1.5 text-xs text-neutral-400 font-mono">
              <Filter className="w-3.5 h-3.5 text-neutral-500" />
              <span>Route:</span>
              <select
                value={selectedRoute}
                onChange={(e) => setSelectedRoute(e.target.value)}
                className="bg-neutral-900 text-neutral-200 border border-neutral-800 rounded px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-neutral-700"
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
            <div className="flex items-center gap-1.5 text-xs text-neutral-400 font-mono">
              <span>Carrier:</span>
              <select
                value={selectedAirline}
                onChange={(e) => setSelectedAirline(e.target.value)}
                className="bg-neutral-900 text-neutral-200 border border-neutral-800 rounded px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-neutral-700"
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
            <div className="flex items-center gap-1.5 text-xs text-neutral-400 font-mono">
              <span>Winner:</span>
              <select
                value={selectedDirection}
                onChange={(e) => setSelectedDirection(e.target.value)}
                className="bg-neutral-900 text-neutral-200 border border-neutral-800 rounded px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-neutral-700"
              >
                <option value="ALL">All Directions</option>
                <option value="OTA_CHEAPER">OTA Cheaper</option>
                <option value="AIRLINE_CHEAPER">Airline Direct Cheaper</option>
              </select>
            </div>

            {/* Min Spread Threshold */}
            <div className="flex items-center gap-1.5 text-xs text-neutral-400 font-mono">
              <span>Min Spread:</span>
              <select
                value={minSpreadPct}
                onChange={(e) => setMinSpreadPct(Number(e.target.value))}
                className="bg-neutral-900 text-neutral-200 border border-neutral-800 rounded px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-neutral-700"
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
            <label className="flex items-center gap-2 cursor-pointer text-xs text-neutral-300 font-mono">
              <input
                type="checkbox"
                checked={actionableOnly}
                onChange={(e) => setActionableOnly(e.target.checked)}
                className="rounded border-neutral-700 bg-neutral-900 text-white focus:ring-0"
              />
              <span>Actionable Only</span>
            </label>

            <span className="text-neutral-800">|</span>

            <div className="flex items-center gap-1 text-xs text-neutral-400 font-mono">
              <span>Sort:</span>
              <button
                onClick={() => setSortBy('spread_pct')}
                className={`px-2 py-1 rounded text-xs font-mono transition-colors ${
                  sortBy === 'spread_pct'
                    ? 'bg-neutral-800 text-white font-medium border border-neutral-700'
                    : 'bg-neutral-900 text-neutral-400 hover:text-white border border-neutral-800'
                }`}
              >
                % Spread
              </button>
              <button
                onClick={() => setSortBy('spread_inr')}
                className={`px-2 py-1 rounded text-xs font-mono transition-colors ${
                  sortBy === 'spread_inr'
                    ? 'bg-neutral-800 text-white font-medium border border-neutral-700'
                    : 'bg-neutral-900 text-neutral-400 hover:text-white border border-neutral-800'
                }`}
              >
                ₹ Spread
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Arbitrage Opportunity Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {filteredItems.map((item: ArbitrageOpportunity, idx: number) => {
          const isOtaCheaper = item.direction === 'OTA_CHEAPER';
          const isHighSpread = (item.spread_percentage ?? 0) >= 8.0;

          const airlineFare = item.direct_fare ?? item.airline_direct_fare ?? 0;
          const otaFare = item.ota_fare ?? 0;
          const spreadInr = item.spread_inr ?? item.spread_amount ?? (airlineFare > otaFare ? airlineFare - otaFare : otaFare - airlineFare);
          const otaName = item.ota_platform || item.ota_name || 'OTA';

          return (
            <div
              key={`${item.route_code}-${item.airline_code}-${idx}`}
              className="bg-neutral-950 border border-neutral-800 rounded-lg p-4 hover:border-neutral-700 transition-colors flex flex-col justify-between"
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
                        <span className="text-xs font-mono text-neutral-400 bg-neutral-900 border border-neutral-800 px-1.5 py-0.5 rounded">
                          {item.flight_number}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-neutral-400 mt-0.5">
                      {item.airline_name || item.airline_code}
                    </p>
                  </div>

                  <div className="flex flex-col items-end gap-1">
                    <span
                      className={`px-2 py-0.5 rounded font-mono text-[10px] font-medium border ${
                        isHighSpread
                          ? 'border-amber-500/30 text-amber-400 bg-amber-950/20'
                          : 'border-neutral-800 bg-neutral-900 text-neutral-300'
                      }`}
                    >
                      +{(item.spread_percentage ?? 0).toFixed(2)}% SPREAD
                    </span>

                    {item.actionable && (
                      <span className="flex items-center gap-1 text-[10px] font-mono text-neutral-400">
                        <CheckCircle2 className="w-2.5 h-2.5 text-neutral-300" /> Actionable
                      </span>
                    )}
                  </div>
                </div>

                {/* Price Comparison Box */}
                <div className="mt-3 p-3 rounded border border-neutral-800 bg-neutral-900/40">
                  <div className="grid grid-cols-2 gap-2 text-center">
                    {/* Airline Direct */}
                    <div className="p-2 rounded border border-neutral-800 bg-neutral-900/60">
                      <span className="text-[10px] text-neutral-400 uppercase font-mono block">
                        Airline Direct
                      </span>
                      <span className="text-sm font-semibold font-mono tabular-nums text-white mt-0.5 block">
                        {airlineFare > 0 ? `₹${airlineFare.toLocaleString('en-IN')}` : '—'}
                      </span>
                      <span className="text-[10px] text-neutral-500 font-mono">Official Site</span>
                    </div>

                    {/* OTA */}
                    <div className="p-2 rounded border border-neutral-800 bg-neutral-900/60">
                      <span className="text-[10px] text-neutral-400 uppercase font-mono block truncate">
                        OTA ({otaName})
                      </span>
                      <span className="text-sm font-semibold font-mono tabular-nums text-white mt-0.5 block">
                        {otaFare > 0 ? `₹${otaFare.toLocaleString('en-IN')}` : '—'}
                      </span>
                      <span className="text-[10px] text-neutral-500 font-mono capitalize">
                        Aggregator
                      </span>
                    </div>
                  </div>

                  {/* Net Delta Footer */}
                  <div className="mt-2.5 pt-2 border-t border-neutral-800 flex items-center justify-between text-xs font-mono">
                    <span className="text-neutral-400">Price Disparity:</span>
                    <span className="font-medium text-white tabular-nums">
                      {spreadInr > 0 ? `Save ₹${spreadInr.toLocaleString('en-IN')}` : '—'}
                    </span>
                  </div>
                </div>

                {/* Recommendation */}
                <div className="mt-2.5 flex items-center justify-between text-[11px] p-2 rounded border border-neutral-800 bg-neutral-900/30">
                  <span className="text-neutral-400">Recommendation:</span>
                  <span className="text-neutral-200 font-mono">
                    {isOtaCheaper ? (
                      <>Book via <span className="text-white capitalize">{otaName}</span></>
                    ) : (
                      <>Book <span className="text-white">Direct Airline</span></>
                    )}
                  </span>
                </div>
              </div>

              {/* Timestamp footer */}
              {item.departure_datetime && (
                <div className="mt-3 pt-2 border-t border-neutral-800 flex items-center justify-between text-[10px] text-neutral-500 font-mono">
                  <span>
                    Dep:{' '}
                    {new Date(item.departure_datetime).toLocaleDateString([], {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })}
                  </span>
                  <span className="text-neutral-400">Verified Cycle 3</span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {filteredItems.length === 0 && (
        <div className="py-12 text-center bg-neutral-950 border border-neutral-800 rounded-lg">
          <Info className="w-6 h-6 text-neutral-500 mx-auto mb-2" />
          <p className="text-sm text-neutral-300 font-medium">No arbitrage opportunities match filters.</p>
          <p className="text-xs text-neutral-500 mt-1">Try relaxing minimum spread % or clearing the search query.</p>
        </div>
      )}

      {/* Comprehensive Arbitrage Ledger: 12-Column Semantic Table */}
      <div className="border border-neutral-800 bg-neutral-950 rounded-lg overflow-hidden">
        <div className="p-4 border-b border-neutral-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-xs font-medium uppercase tracking-wider text-neutral-400">
              Direct vs OTA Price Arbitrage Ledger ({filteredItems.length} records)
            </h3>
          </div>
          <span className="text-[11px] text-neutral-500 font-mono">
            DGCA Fair Competition Oversight
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs table-fixed font-mono">
            <colgroup>
              <col className="w-[12%]" /> {/* Corridor: 1.5 cols */}
              <col className="w-[8%]" />  {/* Airline: 1 col */}
              <col className="w-[8%]" />  {/* Flight: 1 col */}
              <col className="w-[15%]" /> {/* Airline Direct: 1.8 cols */}
              <col className="w-[12%]" /> {/* OTA Channel: 1.5 cols */}
              <col className="w-[15%]" /> {/* OTA Fare: 1.8 cols */}
              <col className="w-[12%]" /> {/* Net Spread: 1.4 cols */}
              <col className="w-[8%]" />  {/* Spread %: 1 col */}
              <col className="w-[10%]" /> {/* Optimal: 1 col */}
            </colgroup>
            <thead className="bg-neutral-900/40 text-neutral-400 text-[11px] uppercase border-b border-neutral-800 select-none">
              <tr>
                <th className="py-3 px-3 text-left font-medium">Corridor</th>
                <th className="py-3 px-3 text-left font-medium">Airline</th>
                <th className="py-3 px-3 text-left font-medium">Flight</th>
                <th className="py-3 px-3 text-right font-medium font-mono tabular-nums">Airline Direct</th>
                <th className="py-3 px-3 text-left font-medium">OTA Channel</th>
                <th className="py-3 px-3 text-right font-medium font-mono tabular-nums">OTA Fare</th>
                <th className="py-3 px-3 text-right font-medium font-mono tabular-nums">Net Spread</th>
                <th className="py-3 px-3 text-right font-medium font-mono tabular-nums">Spread (%)</th>
                <th className="py-3 px-3 text-right font-medium">Channel</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800 text-neutral-300">
              {filteredItems.map((item: ArbitrageOpportunity, idx: number) => {
                const isOtaCheaper = item.direction === 'OTA_CHEAPER';
                const airlineFare = item.direct_fare ?? item.airline_direct_fare ?? 0;
                const otaFare = item.ota_fare ?? 0;
                const spreadInr = item.spread_inr ?? item.spread_amount ?? (airlineFare > otaFare ? airlineFare - otaFare : otaFare - airlineFare);
                const otaName = item.ota_platform || item.ota_name || 'OTA';

                return (
                  <tr key={`ledger-${item.route_code}-${idx}`} className="hover:bg-neutral-900/40 transition-colors">
                    {/* Corridor (Left) */}
                    <td className="py-3 px-3 font-semibold text-white">
                      {item.route_code}
                    </td>

                    {/* Airline (Left) */}
                    <td className="py-3 px-3">
                      <span className="px-1.5 py-0.5 rounded border border-neutral-800 bg-neutral-900 text-neutral-300 text-[10px]">
                        {item.airline_code}
                      </span>
                    </td>

                    {/* Flight (Left) */}
                    <td className="py-3 px-3 text-neutral-400">
                      {item.flight_number || '—'}
                    </td>

                    {/* Airline Direct (Right) */}
                    <td className="py-3 px-3 text-right text-white font-medium font-mono tabular-nums">
                      {airlineFare > 0 ? `₹${airlineFare.toLocaleString('en-IN')}` : '—'}
                    </td>

                    {/* OTA Channel (Left) */}
                    <td className="py-3 px-3 capitalize text-neutral-300">
                      {otaName}
                    </td>

                    {/* OTA Fare (Right) */}
                    <td className="py-3 px-3 text-right text-white font-medium font-mono tabular-nums">
                      {otaFare > 0 ? `₹${otaFare.toLocaleString('en-IN')}` : '—'}
                    </td>

                    {/* Net Spread (Right) */}
                    <td className="py-3 px-3 text-right text-white font-medium font-mono tabular-nums">
                      {spreadInr > 0 ? `₹${spreadInr.toLocaleString('en-IN')}` : '—'}
                    </td>

                    {/* Spread (%) (Right) */}
                    <td className="py-3 px-3 text-right font-mono tabular-nums">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${
                          (item.spread_percentage ?? 0) >= 8.0
                            ? 'border-amber-500/30 text-amber-400 bg-amber-950/20'
                            : 'border-neutral-800 bg-neutral-900 text-neutral-300'
                        }`}
                      >
                        +{(item.spread_percentage ?? 0).toFixed(2)}%
                      </span>
                    </td>

                    {/* Optimal Channel (Right) */}
                    <td className="py-3 px-3 text-right">
                      <span className="text-[11px] text-neutral-400 capitalize">
                        {isOtaCheaper ? otaName : 'Direct'}
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

export default ArbitrageTab;
