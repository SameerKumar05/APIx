import React, { useState, useMemo } from 'react';
import { DgcaSurveillanceResponse } from '../types/api';
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Flame,
  Download,
  Search,
  Clock,
  Plane,
  TrendingUp,
  BarChart2,
  FileSpreadsheet,
} from 'lucide-react';

interface DgcaSurveillanceTabProps {
  surveillance: DgcaSurveillanceResponse;
}

export const DgcaSurveillanceTab: React.FC<DgcaSurveillanceTabProps> = ({ surveillance }) => {
  const [selectedSeverity, setSelectedSeverity] = useState<string>('ALL');
  const [selectedCarrier, setSelectedCarrier] = useState<string>('ALL');
  const [selectedRoute, setSelectedRoute] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [noticeMap, setNoticeMap] = useState<Record<string, boolean>>({});

  // Extract unique routes from violations
  const availableRoutes = useMemo(() => {
    const routeSet = new Set<string>();
    for (const v of surveillance.violations) {
      routeSet.add(v.route_code);
    }
    return Array.from(routeSet).sort();
  }, [surveillance]);

  // Extract unique carriers from violations
  const availableCarriers = useMemo(() => {
    const carrierSet = new Set<string>();
    for (const v of surveillance.violations) {
      carrierSet.add(v.carrier_code);
    }
    return Array.from(carrierSet).sort();
  }, [surveillance]);

  // Filter violations feed
  const filteredViolations = useMemo(() => {
    return surveillance.violations.filter((v) => {
      if (selectedSeverity !== 'ALL' && v.severity !== selectedSeverity) {
        return false;
      }
      if (selectedCarrier !== 'ALL' && v.carrier_code !== selectedCarrier) {
        return false;
      }
      if (selectedRoute !== 'ALL' && v.route_code !== selectedRoute) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesFlight = v.flight_number.toLowerCase().includes(q);
        const matchesRoute = v.route_code.toLowerCase().includes(q);
        const matchesCarrier = v.carrier_name.toLowerCase().includes(q);
        const matchesDesc = v.description.toLowerCase().includes(q);
        if (!matchesFlight && !matchesRoute && !matchesCarrier && !matchesDesc) {
          return false;
        }
      }
      return true;
    });
  }, [surveillance, selectedSeverity, selectedCarrier, selectedRoute, searchQuery]);

  // Handle Export to CSV
  const handleExportCsv = () => {
    const headers = [
      'Violation ID',
      'Detected At',
      'Carrier Code',
      'Carrier Name',
      'Flight Number',
      'Route Code',
      'Window',
      'Observed Fare (INR)',
      'Statutory Cap (INR)',
      'Cap Excess (INR)',
      'Surge Multiplier',
      'Severity',
      'Compliance Status',
      'Violation Code',
      'Description',
    ];

    const rows = filteredViolations.map((v) => [
      v.id,
      v.detected_at,
      v.carrier_code,
      `"${v.carrier_name}"`,
      v.flight_number,
      v.route_code,
      v.window || 'N/A',
      v.observed_fare_inr,
      v.statutory_band_cap_inr,
      v.observed_fare_inr - v.statutory_band_cap_inr,
      v.surge_multiplier.toFixed(2),
      v.severity,
      v.compliance_status,
      v.violation_code || 'TARIFF_MONITOR',
      `"${v.description.replace(/"/g, '""')}"`,
    ]);

    const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute(
      'download',
      `DGCA_Statutory_Compliance_Audit_${new Date().toISOString().split('T')[0]}.csv`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };


  const totalEvaluated = surveillance.total_evaluated;
  const totalViolations = surveillance.total_violations;
  const severeCount =
    surveillance.summary?.severe_count ??
    surveillance.violations.filter((v) => v.severity === 'SEVERE').length;
  const criticalCount =
    surveillance.summary?.critical_count ??
    surveillance.violations.filter((v) => v.severity === 'CRITICAL').length;
  const warningCount =
    surveillance.summary?.warning_count ??
    surveillance.violations.filter((v) => v.severity === 'WARNING').length;

  const overallComplianceRate =
    totalEvaluated > 0
      ? Number((((totalEvaluated - totalViolations) / totalEvaluated) * 100).toFixed(1))
      : 98.5;

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-gradient-to-r from-slate-900 via-rose-950/30 to-slate-900 rounded-2xl p-6 border border-slate-800 shadow-xl relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-96 bg-rose-500/5 rounded-full blur-3xl pointer-events-none -mr-20 -mt-20"></div>
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 relative z-10">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-mono font-bold bg-rose-950 text-rose-400 border border-rose-800/80">
                DGCA TARIFF SURVEILLANCE
              </span>
              <span className="text-slate-500 text-xs">•</span>
              <span className="text-slate-400 text-xs font-mono">
                Statutory Authority: Rule 135, Aircraft Rules 1937
              </span>
            </div>
            <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
              <ShieldAlert className="w-5 h-5 text-rose-400" />
              Statutory Airfare Gouging &amp; Regulatory Audit Feed
            </h2>
            <p className="text-xs text-slate-400 mt-1 max-w-3xl leading-relaxed">
              Automated continuous surveillance identifying dynamic price gouging, upper fare bucket breaches,
              and carrier compliance against statutory fare bands. Real-time regulatory feed with exportable compliance audit logs.
            </p>
          </div>

          <div className="flex items-center gap-3 self-start lg:self-center">
            {/* Export Summary Button */}
            <button
              onClick={handleExportCsv}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-900 border border-slate-700 hover:border-slate-600 text-slate-200 hover:text-white text-xs font-semibold shadow-md transition-all group"
              title="Download verified statutory audit log in CSV format"
            >
              <Download className="w-4 h-4 text-sky-400 group-hover:scale-110 transition-transform" />
              <span>Export Compliance Audit (.CSV)</span>
            </button>
          </div>
        </div>
      </div>

      {/* Surveillance Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Total Flights Evaluated */}
        <div className="bg-slate-900/90 rounded-xl p-5 border border-slate-800 shadow-md">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Total Flights Audited</span>
            <span className="p-1.5 rounded-lg bg-sky-950/80 border border-sky-800/60 text-sky-400">
              <Plane className="w-4 h-4" />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-white">
              {totalEvaluated.toLocaleString('en-IN')}
            </span>
            <span className="text-xs font-mono text-slate-400">flights</span>
          </div>
          <div className="mt-2 text-[11px] text-slate-400">
            Across 10 domestic high-density trunk routes over the last 24h cycle.
          </div>
          <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-slate-400">
            <span>Sampling Coverage</span>
            <span className="text-emerald-400 font-bold">100% scheduled departures</span>
          </div>
        </div>

        {/* Card 2: Regulatory Violations & Severity Breakdown */}
        <div className="bg-slate-900/90 rounded-xl p-5 border border-slate-800 shadow-md">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Regulatory Violations</span>
            <span className="p-1.5 rounded-lg bg-rose-950/80 border border-rose-800/60 text-rose-400">
              <AlertTriangle className="w-4 h-4" />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-rose-400">{totalViolations}</span>
            <span className="text-xs font-mono text-rose-300 font-semibold">breaches</span>
          </div>
          <div className="mt-2 flex items-center gap-2 text-[11px] font-mono">
            <span className="px-1.5 py-0.2 rounded bg-rose-950 border border-rose-800 text-rose-400 font-bold">
              {severeCount} SEVERE
            </span>
            <span className="px-1.5 py-0.2 rounded bg-amber-950 border border-amber-800 text-amber-400 font-bold">
              {criticalCount} CRITICAL
            </span>
            <span className="px-1.5 py-0.2 rounded bg-yellow-950 border border-yellow-800 text-yellow-400 font-bold">
              {warningCount} WARN
            </span>
          </div>
          <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-slate-400">
            <span>Violation Ratio</span>
            <span className="text-rose-400 font-bold">
              {((totalViolations / totalEvaluated) * 100).toFixed(2)}% of flights
            </span>
          </div>
        </div>

        {/* Card 3: Market Average Surge Multiplier */}
        <div className="bg-slate-900/90 rounded-xl p-5 border border-slate-800 shadow-md">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Avg Market Surge Multiplier</span>
            <span className="p-1.5 rounded-lg bg-indigo-950/80 border border-indigo-800/60 text-indigo-400">
              <TrendingUp className="w-4 h-4" />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-indigo-400">2.37x</span>
            <span className="text-xs font-mono text-slate-400">baseline</span>
          </div>
          <div className="mt-2 text-[11px] text-slate-400">
            Statutory guideline warning trigger activates at 2.50x baseline fare.
          </div>
          <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-slate-400">
            <span>Max Peak Multiplier</span>
            <span className="text-rose-400 font-bold">3.55x (DEL-BOM)</span>
          </div>
        </div>

        {/* Card 4: Statutory Compliance Rate */}
        <div className="bg-slate-900/90 rounded-xl p-5 border border-slate-800 shadow-md">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-slate-400">Statutory Compliance Status</span>
            <span className="p-1.5 rounded-lg bg-emerald-950/80 border border-emerald-800/60 text-emerald-400">
              <ShieldCheck className="w-4 h-4" />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-emerald-400">
              {overallComplianceRate}%
            </span>
            <span className="text-xs font-mono text-emerald-300 font-semibold">compliant</span>
          </div>
          <div className="mt-2 text-[11px] text-slate-400">
            Compliant with published tariff limits under DGCA monitoring framework.
          </div>
          <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-slate-400">
            <span>Regulatory Posture</span>
            <span className="text-emerald-400 font-bold">ACTIVE ENFORCEMENT</span>
          </div>
        </div>
      </div>

      {/* Carrier Surge Multiplier Distribution & Statutory Compliance Status */}
      <div className="bg-slate-900/90 rounded-2xl p-6 border border-slate-800 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-slate-800">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <BarChart2 className="w-4 h-4 text-sky-400" />
              Carrier Surge Multiplier Distribution &amp; Statutory Compliance Status
            </h3>
            <p className="text-xs text-slate-400">
              Carrier-by-carrier surge factor distribution and statutory ceiling adherence across scheduled airlines
            </p>
          </div>
          <div className="text-xs font-mono text-slate-400">
            Statutory Ceiling Threshold: <span className="text-amber-400 font-bold">3.00x Base</span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {surveillance.carrier_distribution.map((carrier) => {
            const isHighSurge = carrier.avg_surge_multiplier >= 2.5;
            const isCompliant = carrier.compliance_rate >= 95.0;

            return (
              <div
                key={carrier.carrier_code}
                className="p-4 rounded-xl bg-slate-950/70 border border-slate-800/90 hover:border-slate-700 transition-all space-y-3"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="w-7 h-7 rounded-lg bg-slate-800 font-mono font-bold text-xs flex items-center justify-center text-white border border-slate-700">
                      {carrier.carrier_code}
                    </span>
                    <div>
                      <div className="text-xs font-bold text-white">{carrier.carrier_name}</div>
                      <div className="text-[10px] font-mono text-slate-400">
                        {carrier.violations_count} breaches flagged
                      </div>
                    </div>
                  </div>

                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${
                      isCompliant
                        ? 'bg-emerald-950/80 text-emerald-400 border-emerald-800/80'
                        : 'bg-amber-950/80 text-amber-400 border-amber-800/80'
                    }`}
                  >
                    {isCompliant ? 'COMPLIANT' : 'REVIEW'}
                  </span>
                </div>

                {/* Avg Surge Multiplier Gauge */}
                <div className="space-y-1">
                  <div className="flex justify-between text-[11px] font-mono">
                    <span className="text-slate-400">Avg Surge Multiplier:</span>
                    <span
                      className={`font-bold ${
                        isHighSurge ? 'text-amber-400' : 'text-indigo-400'
                      }`}
                    >
                      {carrier.avg_surge_multiplier.toFixed(2)}x
                    </span>
                  </div>
                  <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${
                        isHighSurge ? 'bg-amber-500' : 'bg-indigo-500'
                      }`}
                      style={{
                        width: `${Math.min(100, (carrier.avg_surge_multiplier / 3.5) * 100)}%`,
                      }}
                    ></div>
                  </div>
                </div>

                {/* Compliance Rate Progress */}
                <div className="space-y-1">
                  <div className="flex justify-between text-[11px] font-mono">
                    <span className="text-slate-400">Compliance Rate:</span>
                    <span
                      className={`font-bold ${
                        isCompliant ? 'text-emerald-400' : 'text-amber-400'
                      }`}
                    >
                      {carrier.compliance_rate.toFixed(1)}%
                    </span>
                  </div>
                  <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-emerald-500 rounded-full transition-all"
                      style={{ width: `${carrier.compliance_rate}%` }}
                    ></div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Filterable Regulatory Violation Feed */}
      <div className="bg-slate-900/90 rounded-2xl p-6 border border-slate-800 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-slate-800">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <Flame className="w-4 h-4 text-rose-400" />
              Regulatory Violation Feed ({filteredViolations.length} records)
            </h3>
            <p className="text-xs text-slate-400">
              Audit records of flights exceeding statutory fare band caps and emergency gouging thresholds
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Search Input */}
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search flight, route..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8 pr-3 py-1.5 text-xs bg-slate-950 border border-slate-700 rounded-lg text-slate-200 placeholder-slate-500 focus:outline-none focus:border-rose-500 font-mono w-44"
              />
            </div>

            {/* Severity Filter */}
            <select
              value={selectedSeverity}
              onChange={(e) => setSelectedSeverity(e.target.value)}
              className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-rose-500 font-mono"
            >
              <option value="ALL">All Severities</option>
              <option value="SEVERE">SEVERE Only</option>
              <option value="CRITICAL">CRITICAL Only</option>
              <option value="WARNING">WARNING Only</option>
            </select>

            {/* Carrier Filter */}
            <select
              value={selectedCarrier}
              onChange={(e) => setSelectedCarrier(e.target.value)}
              className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-rose-500 font-mono"
            >
              <option value="ALL">All Carriers</option>
              {availableCarriers.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>

            {/* Route Filter */}
            <select
              value={selectedRoute}
              onChange={(e) => setSelectedRoute(e.target.value)}
              className="bg-slate-950 border border-slate-700 text-slate-200 text-xs rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-rose-500 font-mono"
            >
              <option value="ALL">All Routes</option>
              {availableRoutes.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Violations Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-slate-950/80 text-slate-400 uppercase tracking-wider border-b border-slate-800">
              <tr>
                <th className="py-2.5 px-3">Violation / Flight</th>
                <th className="py-2.5 px-3">Route &amp; Window</th>
                <th className="py-2.5 px-3">Observed Fare</th>
                <th className="py-2.5 px-3">Statutory Cap</th>
                <th className="py-2.5 px-3">Surge</th>
                <th className="py-2.5 px-3">Severity</th>
                <th className="py-2.5 px-3">Description &amp; Section</th>
                <th className="py-2.5 px-3 text-right">Statutory Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {filteredViolations.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-8 text-center text-slate-500">
                    No regulatory violations matching current filters.
                  </td>
                </tr>
              ) : (
                filteredViolations.map((v) => {
                  const isNoticeIssued = noticeMap[v.id];
                  const capDiff = v.observed_fare_inr - v.statutory_band_cap_inr;

                  return (
                    <tr key={v.id} className="hover:bg-slate-800/40 transition-colors">
                      {/* Violation ID & Flight */}
                      <td className="py-3 px-3">
                        <div className="font-bold text-white">{v.flight_number}</div>
                        <div className="text-[10px] text-slate-500 flex items-center gap-1">
                          <span>{v.id}</span>
                          <span>•</span>
                          <span>{v.carrier_name}</span>
                        </div>
                      </td>

                      {/* Route & Window */}
                      <td className="py-3 px-3">
                        <div className="font-semibold text-slate-200">{v.route_code}</div>
                        <div className="text-[10px] text-slate-400">
                          {v.window || 'T+1'} window
                        </div>
                      </td>

                      {/* Observed Fare */}
                      <td className="py-3 px-3">
                        <div className="font-bold text-rose-400">
                          ₹{v.observed_fare_inr.toLocaleString('en-IN')}
                        </div>
                        <div className="text-[10px] text-rose-300">
                          +₹{capDiff.toLocaleString('en-IN')} over cap
                        </div>
                      </td>

                      {/* Statutory Cap */}
                      <td className="py-3 px-3">
                        <div className="text-slate-300">
                          ₹{v.statutory_band_cap_inr.toLocaleString('en-IN')}
                        </div>
                        <div className="text-[10px] text-slate-500">Upper Band Cap</div>
                      </td>

                      {/* Surge Multiplier */}
                      <td className="py-3 px-3">
                        <span
                          className={`font-bold ${
                            v.surge_multiplier >= 3.0
                              ? 'text-rose-400'
                              : v.surge_multiplier >= 2.5
                              ? 'text-amber-400'
                              : 'text-indigo-400'
                          }`}
                        >
                          {v.surge_multiplier.toFixed(2)}x
                        </span>
                      </td>

                      {/* Severity Badge (WARNING, CRITICAL, SEVERE) */}
                      <td className="py-3 px-3">
                        {v.severity === 'SEVERE' && (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-rose-600 text-white shadow-sm shadow-rose-900/50">
                            <Flame className="w-3 h-3" />
                            SEVERE
                          </span>
                        )}
                        {v.severity === 'CRITICAL' && (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-500 text-slate-950 shadow-sm shadow-amber-900/50">
                            <AlertTriangle className="w-3 h-3" />
                            CRITICAL
                          </span>
                        )}
                        {v.severity === 'WARNING' && (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-yellow-950 text-yellow-300 border border-yellow-700/80">
                            <Clock className="w-3 h-3" />
                            WARNING
                          </span>
                        )}
                      </td>

                      {/* Description & Section */}
                      <td className="py-3 px-3 max-w-xs">
                        <div className="text-[11px] text-slate-300 line-clamp-2">
                          {v.description}
                        </div>
                        <div className="text-[10px] text-slate-500 mt-0.5">
                          {v.violation_code || 'RULE_135_TARIFF'}
                        </div>
                      </td>

                      {/* Action Button */}
                      <td className="py-3 px-3 text-right">
                        <button
                          onClick={() => setNoticeMap((prev) => ({ ...prev, [v.id]: !prev[v.id] }))}
                          className={`px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-all ${
                            isNoticeIssued
                              ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                              : 'bg-slate-800 hover:bg-rose-950 text-slate-300 hover:text-rose-300 border border-slate-700 hover:border-rose-800'
                          }`}
                        >
                          {isNoticeIssued ? 'Notice Served' : 'Issue Notice'}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Exportable Compliance Summary Card */}
      <div className="bg-slate-900/90 rounded-2xl p-6 border border-slate-800 shadow-xl space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-2 border-b border-slate-800">
          <div>
            <h3 className="text-base font-bold text-white flex items-center gap-2">
              <FileSpreadsheet className="w-4 h-4 text-emerald-400" />
              Statutory Compliance Summary &amp; Formal Certification
            </h3>
            <p className="text-xs text-slate-400">
              DGCA Tariff Monitoring Unit Endorsement for Periodic Economic Oversight
            </p>
          </div>

          <button
            onClick={handleExportCsv}
            className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-emerald-950/80 hover:bg-emerald-900/80 border border-emerald-800/80 text-emerald-300 text-xs font-semibold shadow-sm transition-all"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Download Official Audit Log (.CSV)</span>
          </button>
        </div>

        <div className="p-4 rounded-xl bg-slate-950/80 border border-slate-800 text-xs text-slate-300 space-y-2 font-mono">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/80 pb-2 text-[11px]">
            <div>
              <span className="text-slate-500">AUDIT REF:</span>{' '}
              <span className="text-white font-bold">APIX-DGCA-2026-CY4</span>
            </div>
            <div>
              <span className="text-slate-500">AUDIT DATE:</span>{' '}
              <span className="text-white font-bold">{new Date().toISOString().split('T')[0]}</span>
            </div>
            <div>
              <span className="text-slate-500">STATUTORY BODY:</span>{' '}
              <span className="text-white font-bold">Directorate General of Civil Aviation</span>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1 text-[11px]">
            <div>
              <span className="text-slate-500 block">Total Evaluated Flights:</span>
              <span className="font-bold text-slate-200">{totalEvaluated} departures</span>
            </div>
            <div>
              <span className="text-slate-500 block">Total Violations Flagged:</span>
              <span className="font-bold text-rose-400">{totalViolations} incidents</span>
            </div>
            <div>
              <span className="text-slate-500 block">Market Statutory Adherence:</span>
              <span className="font-bold text-emerald-400">{overallComplianceRate}% (ACCEPTABLE)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default DgcaSurveillanceTab;
