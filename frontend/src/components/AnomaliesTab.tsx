import React, { useState, useMemo } from 'react';
import {
  AnomalyAlertItem,
  DGCAValidationResponse,
} from '../types/api';
import {
  AlertTriangle,
  ShieldAlert,
  ShieldCheck,
  CheckCircle,
  TrendingUp,
  FileText,
  Filter,
  Search,
  Scale,
  Flame,
  Send,
  Check,
} from 'lucide-react';

interface AnomaliesTabProps {
  anomalies: AnomalyAlertItem[];
  dgcaValidation: DGCAValidationResponse;
}

export const AnomaliesTab: React.FC<AnomaliesTabProps> = ({ anomalies, dgcaValidation }) => {
  const [selectedRoute, setSelectedRoute] = useState<string>('ALL');
  const [selectedSeverity, setSelectedSeverity] = useState<string>('ALL');
  const [selectedType, setSelectedType] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [acknowledgedMap, setAcknowledgedMap] = useState<Record<string, boolean>>({});
  const [enquiryNotices, setEnquiryNotices] = useState<Record<string, boolean>>({});

  // Extract all unique routes present in anomalies
  const availableRoutes = useMemo(() => {
    const routeSet = new Set<string>();
    for (const a of anomalies) {
      routeSet.add(a.route_code);
    }
    return Array.from(routeSet).sort();
  }, [anomalies]);

  const availableTypes = useMemo(() => {
    const typeSet = new Set<string>();
    for (const a of anomalies) {
      if (a.anomaly_type) typeSet.add(a.anomaly_type);
    }
    ['SURGE_PRICING', 'SURGE', 'DGCA_CAP_EXCEEDED', 'PRICE_CRASH', 'FLASH_SALE'].forEach((t) => typeSet.add(t));
    return Array.from(typeSet);
  }, [anomalies]);

  const formatAnomalyType = (type: string) => {
    switch (type) {
      case 'SURGE_PRICING':
        return 'Surge Pricing';
      case 'SURGE':
        return 'Surge Alert';
      case 'DGCA_CAP_EXCEEDED':
        return 'DGCA Cap Exceeded';
      case 'PRICE_CRASH':
        return 'Price Crash';
      case 'FLASH_SALE':
        return 'Flash Sale';
      case 'PRICE_GOUGING':
        return 'Price Gouging';
      case 'DISPERSION_SPIKE':
        return 'Dispersion Spike';
      case 'FLASH_DROP':
        return 'Flash Drop';
      default:
        return type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
    }
  };

  // Filter alerts by route, severity, type, and search query
  const filteredAlerts = useMemo(() => {
    return anomalies.filter((a) => {
      // Filter by Route
      if (selectedRoute !== 'ALL' && a.route_code !== selectedRoute) {
        return false;
      }

      // Filter by Severity / Z-score tier
      if (selectedSeverity !== 'ALL') {
        const z = a.z_score ?? (a.deviation_percent / 25);
        if (selectedSeverity === 'CRITICAL' && (z < 3.0 && a.severity !== 'CRITICAL')) {
          return false;
        }
        if (selectedSeverity === 'WARNING' && ((z < 2.0 || z >= 3.0) && a.severity !== 'HIGH' && a.severity !== 'WARNING')) {
          return false;
        }
        if (selectedSeverity === 'MODERATE' && (z >= 2.0 && a.severity !== 'MEDIUM' && a.severity !== 'LOW')) {
          return false;
        }
      }

      // Filter by Anomaly Type
      if (selectedType !== 'ALL') {
        const typeMatches =
          a.anomaly_type === selectedType ||
          (selectedType === 'SURGE' && a.anomaly_type === 'SURGE_PRICING') ||
          (selectedType === 'SURGE_PRICING' && a.anomaly_type === 'SURGE');
        if (!typeMatches) return false;
      }

      // Search Query
      if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase().trim();
        const matchesFlight = (a.flight_number || '').toLowerCase().includes(query);
        const matchesAirline = (a.airline_code || '').toLowerCase().includes(query);
        const matchesRoute = (a.route_code || '').toLowerCase().includes(query);
        const matchesDesc = (a.description || '').toLowerCase().includes(query);
        if (!matchesFlight && !matchesAirline && !matchesRoute && !matchesDesc) {
          return false;
        }
      }

      return true;
    });
  }, [anomalies, selectedRoute, selectedSeverity, selectedType, searchQuery]);

  // Compute surveillance KPIs
  const criticalCount = useMemo(() => {
    return anomalies.filter((a) => {
      const z = a.z_score ?? (a.deviation_percent / 25);
      return z >= 3.0 || a.severity === 'CRITICAL';
    }).length;
  }, [anomalies]);

  const warningCount = useMemo(() => {
    return anomalies.filter((a) => {
      const z = a.z_score ?? (a.deviation_percent / 25);
      return a.severity === 'WARNING' || a.severity === 'HIGH' || (z >= 2.0 && z < 3.0 && a.severity !== 'CRITICAL');
    }).length;
  }, [anomalies]);

  const peakAnomaly = useMemo(() => {
    let peak: AnomalyAlertItem | null = null;
    let max = 0;
    for (const a of anomalies) {
      const z = a.z_score ?? (a.deviation_percent / 25);
      if (z > max) {
        max = z;
        peak = a;
      }
    }
    return { zScore: max, peak };
  }, [anomalies]);
  const maxZScore = peakAnomaly.zScore;
  const peakRouteLabel = peakAnomaly.peak
    ? [peakAnomaly.peak.route_code, peakAnomaly.peak.booking_window].filter(Boolean).join(' ') || 'Live feed'
    : 'No live alerts';

  const toggleAcknowledge = (id: string) => {
    setAcknowledgedMap((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
  };

  const triggerEnquiry = (id: string) => {
    setEnquiryNotices((prev) => ({
      ...prev,
      [id]: true,
    }));
  };

  const acknowledgedCount = Object.values(acknowledgedMap).filter(Boolean).length;

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <ShieldAlert className="w-5 h-5 text-rose-400" />
                DGCA Regulatory Surveillance & Price Anomaly Center
              </h2>
              <span className="text-xs px-2.5 py-0.5 rounded-full bg-rose-950 text-rose-300 border border-rose-800 font-mono">
                Real-Time 3-Sigma Surge Audit
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Automated algorithmic surveillance detecting dynamic pricing gouging, sudden volatility surges, and statutory route fare band breaches.
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs font-mono">
            <span className="text-slate-400">Surveillance Engine:</span>
            <span className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-emerald-950 text-emerald-300 border border-emerald-800 font-bold">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
              ACTIVE (5m sampling)
            </span>
          </div>
        </div>
      </div>

      {/* Surveillance Summary KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 font-mono">
        {/* Card 1: Active Surge Alerts */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between text-slate-400 text-xs font-sans font-medium uppercase tracking-wider mb-2">
            <span>Surveillance Alerts</span>
            <AlertTriangle className="w-4 h-4 text-rose-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-white">{anomalies.length}</span>
            <span className="text-xs text-rose-400 font-sans font-bold">({criticalCount} Critical)</span>
          </div>
          <div className="mt-3 text-xs text-slate-400 flex items-center justify-between border-t border-slate-800/80 pt-2 font-sans">
            <span>Warning (Z ≥ 2.0):</span>
            <span className="font-semibold text-amber-400 font-mono">{warningCount} active</span>
          </div>
        </div>

        {/* Card 2: Maximum Z-Score Surge */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between text-slate-400 text-xs font-sans font-medium uppercase tracking-wider mb-2">
            <span>Max Z-Score Detected</span>
            <Flame className="w-4 h-4 text-rose-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-rose-400">
              +{maxZScore.toFixed(2)}σ
            </span>
            <span className="text-xs text-slate-400 font-sans">{peakRouteLabel}</span>
          </div>
          <div className="mt-3 text-xs text-slate-400 flex items-center justify-between border-t border-slate-800/80 pt-2 font-sans">
            <span>Surge Threshold:</span>
            <span className="font-semibold text-rose-400 font-mono">Critical Z ≥ 3.0</span>
          </div>
        </div>

        {/* Card 3: Statutory Cap Breaches */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between text-slate-400 text-xs font-sans font-medium uppercase tracking-wider mb-2">
            <span>Statutory Cap Breaches</span>
            <Scale className="w-4 h-4 text-amber-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-amber-400">{dgcaValidation.total_violations}</span>
            <span className="text-xs text-slate-400 font-sans">Corridors flagged</span>
          </div>
          <div className="mt-3 text-xs text-slate-400 flex items-center justify-between border-t border-slate-800/80 pt-2 font-sans">
            <span>Routes Evaluated:</span>
            <span className="font-semibold text-slate-200 font-mono">
              {dgcaValidation.total_routes_evaluated} Trunk Corridors
            </span>
          </div>
        </div>

        {/* Card 4: Session Audit Status */}
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-sm">
          <div className="flex items-center justify-between text-slate-400 text-xs font-sans font-medium uppercase tracking-wider mb-2">
            <span>Audit Progress</span>
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-emerald-400">
              {acknowledgedCount} / {anomalies.length}
            </span>
            <span className="text-xs text-slate-400 font-sans">Acknowledged</span>
          </div>
          <div className="mt-3 text-xs text-slate-400 flex items-center justify-between border-t border-slate-800/80 pt-2 font-sans">
            <span>Formal Enquiries:</span>
            <span className="font-semibold text-sky-400 font-mono">
              {Object.values(enquiryNotices).filter(Boolean).length} Triggered
            </span>
          </div>
        </div>
      </div>

      {/* Filter and Surveillance Control Bar */}
      <div className="bg-slate-900/90 border border-slate-800 rounded-xl p-4 backdrop-blur-md space-y-3">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          {/* Left: Route and Severity Filters */}
          <div className="flex flex-wrap items-center gap-3">
            {/* Filter by Route Dropdown */}
            <div className="flex items-center gap-1.5 text-xs">
              <span className="text-slate-400 flex items-center gap-1 font-medium">
                <Filter className="w-3.5 h-3.5 text-sky-400" /> Filter Corridor:
              </span>
              <select
                value={selectedRoute}
                onChange={(e) => setSelectedRoute(e.target.value)}
                className="bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono"
              >
                <option value="ALL">All Trunk Corridors (10)</option>
                {availableRoutes.map((routeCode) => (
                  <option key={routeCode} value={routeCode}>
                    {routeCode} Corridor
                  </option>
                ))}
              </select>
            </div>

            {/* Filter by Type Dropdown */}
            <div className="flex items-center gap-1.5 text-xs">
              <span className="text-slate-400 font-medium">Type:</span>
              <select
                value={selectedType}
                onChange={(e) => setSelectedType(e.target.value)}
                className="bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500 font-mono"
              >
                <option value="ALL">All Types</option>
                {availableTypes.map((type) => (
                  <option key={type} value={type}>
                    {formatAnomalyType(type)}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-wrap items-center rounded-lg bg-slate-950 border border-slate-800 p-0.5 text-xs font-mono">
              <button
                onClick={() => setSelectedSeverity('ALL')}
                className={`px-2.5 py-1 rounded-md transition-all ${
                  selectedSeverity === 'ALL'
                    ? 'bg-slate-800 text-white font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                All Severities
              </button>
              <button
                onClick={() => setSelectedSeverity('CRITICAL')}
                className={`px-2.5 py-1 rounded-md transition-all flex items-center gap-1 ${
                  selectedSeverity === 'CRITICAL'
                    ? 'bg-rose-950 text-rose-300 font-bold border border-rose-800'
                    : 'text-slate-400 hover:text-rose-300'
                }`}
              >
                <span className="w-2 h-2 rounded-full bg-rose-500"></span>
                CRITICAL (Z ≥ 3.0)
              </button>
              <button
                onClick={() => setSelectedSeverity('WARNING')}
                className={`px-2.5 py-1 rounded-md transition-all flex items-center gap-1 ${
                  selectedSeverity === 'WARNING'
                    ? 'bg-amber-950 text-amber-300 font-bold border border-amber-800'
                    : 'text-slate-400 hover:text-amber-300'
                }`}
              >
                <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                WARNING (Z ≥ 2.0)
              </button>
              <button
                onClick={() => setSelectedSeverity('MODERATE')}
                className={`px-2.5 py-1 rounded-md transition-all ${
                  selectedSeverity === 'MODERATE'
                    ? 'bg-indigo-950 text-indigo-300 font-bold border border-indigo-800'
                    : 'text-slate-400 hover:text-indigo-300'
                }`}
              >
                Moderate (Z &lt; 2.0)
              </button>
            </div>
          </div>

          {/* Right: Search Input */}
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search flight, airline, or route..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-3 py-1.5 text-xs bg-slate-950 border border-slate-800 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500 w-full sm:w-64"
            />
          </div>
        </div>

        {/* Quick Corridor Selection Pills for Faster Toggling */}
        <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-800/80 text-[11px] font-mono">
          <span className="text-slate-500 mr-1">Corridors:</span>
          <button
            onClick={() => setSelectedRoute('ALL')}
            className={`px-2 py-0.5 rounded transition-all ${
              selectedRoute === 'ALL'
                ? 'bg-sky-600 text-white font-bold'
                : 'bg-slate-950 text-slate-400 hover:text-white border border-slate-800'
            }`}
          >
            ALL
          </button>
          {availableRoutes.map((r) => {
            const count = anomalies.filter((a) => a.route_code === r).length;
            const hasCrit = anomalies.some(
              (a) => a.route_code === r && (a.severity === 'CRITICAL' || (a.z_score ?? 0) >= 3.0)
            );
            return (
              <button
                key={r}
                onClick={() => setSelectedRoute(r)}
                className={`px-2 py-0.5 rounded transition-all flex items-center gap-1 ${
                  selectedRoute === r
                    ? 'bg-sky-600 text-white font-bold'
                    : hasCrit
                    ? 'bg-rose-950/60 text-rose-300 border border-rose-800/60 hover:bg-rose-900/40'
                    : 'bg-slate-950 text-slate-400 hover:text-white border border-slate-800'
                }`}
              >
                <span>{r}</span>
                <span className="text-[10px] opacity-75">({count})</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Statutory Route Fare Band Compliance Summary Table */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-md">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <FileText className="w-4 h-4 text-sky-400" />
            Statutory Route Fare Band Compliance Summary
          </h3>
          <span className="text-xs text-slate-400 font-mono">DGCA Gazette Tariff Ceiling Orders</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400 bg-slate-950/60">
                <th className="py-2.5 px-3 font-sans font-medium">Corridor</th>
                <th className="py-2.5 px-3 font-medium">Statutory Cap</th>
                <th className="py-2.5 px-3 font-medium">Observed Max Fare</th>
                <th className="py-2.5 px-3 font-medium">Cap Utilization</th>
                <th className="py-2.5 px-3 font-medium">Violations</th>
                <th className="py-2.5 px-3 font-medium text-right font-sans">Compliance Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {dgcaValidation.violations.map((v) => {
                const isBreach = v.compliance_status === 'BREACH';
                const isWarning = v.compliance_status === 'WARNING';
                const utilization = (v.observed_max_fare_inr / v.statutory_band_cap_inr) * 100;

                return (
                  <tr key={v.route_code} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-3 px-3 font-sans font-bold text-white">{v.route_code}</td>
                    <td className="py-3 px-3 text-slate-300">
                      ₹{v.statutory_band_cap_inr.toLocaleString('en-IN')}
                    </td>
                    <td
                      className={`py-3 px-3 font-bold ${
                        isBreach ? 'text-rose-400' : isWarning ? 'text-amber-400' : 'text-slate-200'
                      }`}
                    >
                      ₹{v.observed_max_fare_inr.toLocaleString('en-IN')}
                    </td>
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-2">
                        <span className={`w-12 font-bold ${isBreach ? 'text-rose-400' : 'text-slate-300'}`}>
                          {utilization.toFixed(1)}%
                        </span>
                        <div className="w-20 bg-slate-800 rounded-full h-1.5 overflow-hidden">
                          <div
                            className={`h-1.5 rounded-full ${
                              isBreach ? 'bg-rose-500' : isWarning ? 'bg-amber-400' : 'bg-emerald-400'
                            }`}
                            style={{ width: `${Math.min(100, utilization)}%` }}
                          ></div>
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-3 text-slate-300">{v.violations_count} detected</td>
                    <td className="py-3 px-3 text-right">
                      <span
                        className={`px-2.5 py-0.5 rounded text-[10px] font-bold border uppercase tracking-wider ${
                          isBreach
                            ? 'bg-rose-950 text-rose-300 border-rose-800'
                            : isWarning
                            ? 'bg-amber-950 text-amber-300 border-amber-800'
                            : 'bg-emerald-950 text-emerald-300 border-emerald-800'
                        }`}
                      >
                        {v.compliance_status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Active Surge Alerts Stream with Z-score Badges & Baseline Fare Comparisons */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            Detected Surge & Algorithmic Gouging Incidents ({filteredAlerts.length})
          </h3>
          <span className="text-xs text-slate-500 font-mono">
            Filtered from {anomalies.length} total surveillance observations
          </span>
        </div>

        {filteredAlerts.length === 0 ? (
          <div className="p-8 text-center rounded-xl bg-slate-900/40 border border-slate-800 text-slate-400 text-xs">
            No anomaly alerts match the current filter criteria ({selectedRoute}, {selectedSeverity}).
          </div>
        ) : (
          filteredAlerts.map((alert) => {
            const isAck = acknowledgedMap[alert.id] ?? false;
            const hasEnquiry = enquiryNotices[alert.id] ?? false;
            const zScore = alert.z_score ?? Number((alert.deviation_percent / 25).toFixed(2));
            const isCriticalZ = zScore >= 3.0 || alert.severity === 'CRITICAL';
            const isWarningZ = alert.severity === 'WARNING' || alert.severity === 'HIGH' || (zScore >= 2.0 && zScore < 3.0);
            const baseline = alert.baseline_fare_inr || alert.expected_fare_inr;
            const variance = alert.observed_fare_inr - baseline;

            return (
              <div
                key={alert.id}
                className={`p-5 rounded-xl border backdrop-blur-md transition-all ${
                  isAck
                    ? 'bg-slate-900/40 border-slate-800/60 opacity-65'
                    : isCriticalZ
                    ? 'bg-rose-950/20 border-rose-800/80 hover:border-rose-700'
                    : isWarningZ
                    ? 'bg-amber-950/20 border-amber-800/80 hover:border-amber-700'
                    : 'bg-slate-900/80 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-5">
                  <div className="space-y-3 flex-1">
                    {/* Header Badges Row with prominent Z-Score Badge */}
                    <div className="flex flex-wrap items-center gap-2.5">
                      {/* Z-Score Badge */}
                      {isCriticalZ ? (
                        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono font-extrabold bg-rose-950 text-rose-300 border border-rose-700 shadow-md shadow-rose-950/50">
                          <span className="w-2 h-2 rounded-full bg-rose-500 animate-ping"></span>
                          <span>CRITICAL • Z = +{zScore.toFixed(2)}σ</span>
                        </span>
                      ) : isWarningZ ? (
                        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-mono font-extrabold bg-amber-950 text-amber-300 border border-amber-700 shadow-md shadow-amber-950/50">
                          <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                          <span>WARNING • Z = +{zScore.toFixed(2)}σ</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-mono font-bold bg-indigo-950 text-indigo-300 border border-indigo-700">
                          <span>MODERATE • Z = +{zScore.toFixed(2)}σ</span>
                        </span>
                      )}

                      {/* Route Code */}
                      <span className="text-xs font-mono font-extrabold text-sky-400 px-2.5 py-0.5 bg-slate-950 rounded-lg border border-slate-800">
                        {alert.route_code}
                      </span>

                      {/* Airline & Flight */}
                      <span className="text-xs font-semibold text-slate-200">
                        Airline: <span className="font-mono text-white">{alert.airline_code}</span> {alert.flight_number ? `(${alert.flight_number})` : ''}
                      </span>

                      {/* Booking Window */}
                      {alert.booking_window && (
                        <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[11px] font-mono">
                          Window: {alert.booking_window}
                        </span>
                      )}

                      {/* Detection Timestamp */}
                      <span className="text-xs text-slate-500 font-mono ml-auto">
                        Detected: {new Date(alert.detected_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>

                    {/* Alert Description */}
                    <p className="text-xs text-slate-200 leading-relaxed font-sans">
                      {alert.description}
                    </p>

                    {/* Baseline Fare Comparison Block */}
                    <div className="p-3 rounded-lg bg-slate-950/80 border border-slate-800/80 space-y-2 font-mono text-xs">
                      <div className="text-[11px] text-slate-400 font-sans font-semibold flex items-center gap-1">
                        <Scale className="w-3.5 h-3.5 text-sky-400" />
                        <span>Baseline Fare Comparison & Gouging Spread:</span>
                      </div>

                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center sm:text-left">
                        <div>
                          <span className="text-[10px] text-slate-500 block">Baseline Expected</span>
                          <span className="font-bold text-slate-300 text-sm">
                            ₹{baseline.toLocaleString('en-IN')}
                          </span>
                        </div>

                        <div>
                          <span className="text-[10px] text-slate-500 block">Observed Surge</span>
                          <span className="font-bold text-rose-400 text-sm">
                            ₹{alert.observed_fare_inr.toLocaleString('en-IN')}
                          </span>
                        </div>

                        <div>
                          <span className="text-[10px] text-slate-500 block">Spread Above Base</span>
                          <span className="font-bold text-rose-400 text-sm">
                            {variance >= 0 ? `+₹${variance.toLocaleString('en-IN')}` : `-₹${Math.abs(variance).toLocaleString('en-IN')}`}
                          </span>
                        </div>

                        <div>
                          <span className="text-[10px] text-slate-500 block">Surge Deviation</span>
                          <span className="font-extrabold text-rose-400 text-sm flex items-center gap-0.5">
                            <TrendingUp className="w-3.5 h-3.5 inline" />
                            +{alert.deviation_percent.toFixed(1)}%
                          </span>
                        </div>
                      </div>

                      {/* Visual Comparison Progress Bar */}
                      <div className="pt-1">
                        <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden flex">
                          <div
                            className="bg-sky-500 h-2"
                            style={{ width: `${Math.min(100, (baseline / alert.observed_fare_inr) * 100)}%` }}
                            title={`Baseline Fare: ₹${baseline.toLocaleString()}`}
                          ></div>
                          <div
                            className="bg-rose-500 h-2"
                            style={{ width: `${Math.max(0, 100 - (baseline / alert.observed_fare_inr) * 100)}%` }}
                            title={`Surge Markup: +₹${variance.toLocaleString()}`}
                          ></div>
                        </div>
                        <div className="flex justify-between text-[10px] text-slate-500 mt-1">
                          <span>Normal Expected Band</span>
                          <span className="text-rose-400 font-semibold">Algorithmic Surge Margin</span>
                        </div>
                      </div>
                    </div>

                    {/* Regulatory Recommendation Callout */}
                    {alert.recommended_action && (
                      <div className="text-xs bg-slate-950/60 border border-slate-800 rounded-lg p-2.5 text-slate-300 flex items-start gap-2">
                        <ShieldCheck className="w-4 h-4 text-sky-400 shrink-0 mt-0.5" />
                        <div>
                          <span className="font-semibold text-sky-400 mr-1.5 font-sans">
                            DGCA Recommended Action:
                          </span>
                          <span>{alert.recommended_action}</span>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Right Actions Column */}
                  <div className="flex lg:flex-col items-center lg:items-stretch gap-2 shrink-0">
                    <button
                      onClick={() => toggleAcknowledge(alert.id)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center justify-center gap-1.5 ${
                        isAck
                          ? 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                          : 'bg-sky-600 hover:bg-sky-500 text-white shadow-md shadow-sky-900/30'
                      }`}
                    >
                      {isAck ? (
                        <>
                          <Check className="w-3.5 h-3.5" /> Acknowledged
                        </>
                      ) : (
                        'Acknowledge'
                      )}
                    </button>

                    <button
                      onClick={() => triggerEnquiry(alert.id)}
                      disabled={hasEnquiry}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center justify-center gap-1.5 ${
                        hasEnquiry
                          ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-800/80 cursor-default'
                          : 'bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700'
                      }`}
                      title="Issue formal algorithmic price gouging enquiry notice to airline"
                    >
                      {hasEnquiry ? (
                        <>
                          <CheckCircle className="w-3.5 h-3.5 text-emerald-400" /> Notice Triggered
                        </>
                      ) : (
                        <>
                          <Send className="w-3.5 h-3.5 text-slate-400" /> Trigger Notice
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
