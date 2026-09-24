import React, { useState } from 'react';
import {
  AnomalyAlertItem,
  DGCAValidationResponse,
  SeverityLevel,
} from '../types/api';
import {
  AlertTriangle,
  ShieldAlert,
  ShieldCheck,
  CheckCircle,
  TrendingUp,
  FileText,
  Filter,
} from 'lucide-react';

interface AnomaliesTabProps {
  anomalies: AnomalyAlertItem[];
  dgcaValidation: DGCAValidationResponse;
}

export const AnomaliesTab: React.FC<AnomaliesTabProps> = ({ anomalies, dgcaValidation }) => {
  const [selectedSeverity, setSelectedSeverity] = useState<string>('ALL');
  const [acknowledgedIds, setAcknowledgedIds] = useState<Set<string>>(new Set());

  const toggleAcknowledge = (id: string) => {
    setAcknowledgedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const filteredAlerts = anomalies.filter((a) => {
    if (selectedSeverity === 'ALL') return true;
    return a.severity.toUpperCase() === selectedSeverity.toUpperCase();
  });

  const getSeverityBadgeClass = (severity: SeverityLevel | string) => {
    switch (severity.toUpperCase()) {
      case 'CRITICAL':
        return 'bg-rose-950 text-rose-300 border-rose-800';
      case 'HIGH':
        return 'bg-amber-950 text-amber-300 border-amber-800';
      case 'MEDIUM':
        return 'bg-indigo-950 text-indigo-300 border-indigo-800';
      case 'LOW':
        return 'bg-emerald-950 text-emerald-300 border-emerald-800';
      default:
        return 'bg-slate-900 text-slate-300 border-slate-700';
    }
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <ShieldAlert className="w-5 h-5 text-rose-400" />
              DGCA Regulatory Surveillance & Price Anomaly Center
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Automated detection of dynamic pricing gouging, algorithmic spikes, and statutory band violations.
            </p>
          </div>

          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-400 flex items-center gap-1">
              <Filter className="w-3.5 h-3.5" /> Severity:
            </span>
            {['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((sev) => (
              <button
                key={sev}
                onClick={() => setSelectedSeverity(sev)}
                className={`px-2.5 py-1 rounded-lg font-mono text-[11px] font-semibold transition-all ${
                  selectedSeverity === sev
                    ? 'bg-rose-600 text-white shadow-lg shadow-rose-900/40'
                    : 'bg-slate-950 text-slate-400 border border-slate-800 hover:text-white'
                }`}
              >
                {sev}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* DGCA Statutory Band Cap Compliance Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
          <div className="text-xs text-slate-400 font-medium uppercase tracking-wider mb-1">
            Evaluated Routes
          </div>
          <div className="text-3xl font-extrabold text-white font-mono">
            {dgcaValidation.total_routes_evaluated}
          </div>
          <div className="mt-2 text-xs text-slate-400 flex items-center gap-1.5">
            <ShieldCheck className="w-4 h-4 text-emerald-400" />
            100% DGCA domestic network coverage
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
          <div className="text-xs text-slate-400 font-medium uppercase tracking-wider mb-1">
            Statutory Cap Breaches
          </div>
          <div className="text-3xl font-extrabold text-rose-400 font-mono">
            {dgcaValidation.total_violations}
          </div>
          <div className="mt-2 text-xs text-rose-400 flex items-center gap-1.5">
            <AlertTriangle className="w-4 h-4" />
            Formal enquiry notices triggered
          </div>
        </div>

        <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5">
          <div className="text-xs text-slate-400 font-medium uppercase tracking-wider mb-1">
            Surveillance Status
          </div>
          <div className="text-2xl font-extrabold text-emerald-400 flex items-center gap-2">
            <CheckCircle className="w-6 h-6" /> ACTIVE
          </div>
          <div className="mt-2 text-xs text-slate-400">
            Automated scrape sampling rate: 5-minute intervals
          </div>
        </div>
      </div>

      {/* Statutory Band Evaluation Summary Table */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 backdrop-blur-md">
        <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
          <FileText className="w-4 h-4 text-sky-400" />
          Statutory Route Fare Band Compliance Summary
        </h3>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-slate-800 text-slate-400">
                <th className="pb-2.5 font-sans font-medium">Corridor</th>
                <th className="pb-2.5 font-medium">Statutory Cap</th>
                <th className="pb-2.5 font-medium">Observed Max Fare</th>
                <th className="pb-2.5 font-medium">Violations Count</th>
                <th className="pb-2.5 font-medium text-right">Compliance Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {dgcaValidation.violations.map((v) => {
                const isBreach = v.compliance_status === 'BREACH';
                const isWarning = v.compliance_status === 'WARNING';

                return (
                  <tr key={v.route_code} className="hover:bg-slate-800/40 transition-colors">
                    <td className="py-2.5 font-sans font-bold text-white">{v.route_code}</td>
                    <td className="py-2.5 text-slate-300">
                      ₹{v.statutory_band_cap_inr.toLocaleString('en-IN')}
                    </td>
                    <td
                      className={`py-2.5 font-bold ${
                        isBreach ? 'text-rose-400' : isWarning ? 'text-amber-400' : 'text-slate-200'
                      }`}
                    >
                      ₹{v.observed_max_fare_inr.toLocaleString('en-IN')}
                    </td>
                    <td className="py-2.5 text-slate-300">{v.violations_count} detected</td>
                    <td className="py-2.5 text-right">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold border uppercase tracking-wider ${
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

      {/* Anomaly Alerts Stream */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            Detected Surge & Gouging Incidents ({filteredAlerts.length})
          </h3>
          <span className="text-xs text-slate-500">
            {acknowledgedIds.size} acknowledged in session
          </span>
        </div>

        {filteredAlerts.map((alert) => {
          const isAck = acknowledgedIds.has(alert.id);
          return (
            <div
              key={alert.id}
              className={`p-5 rounded-xl border backdrop-blur-md transition-all ${
                isAck
                  ? 'bg-slate-900/40 border-slate-800/60 opacity-60'
                  : 'bg-slate-900/80 border-slate-800 hover:border-slate-700'
              }`}
            >
              <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`px-2.5 py-0.5 rounded text-[11px] font-bold font-mono border uppercase tracking-wider ${getSeverityBadgeClass(
                        alert.severity
                      )}`}
                    >
                      {alert.severity}
                    </span>
                    <span className="text-xs font-mono font-bold text-sky-400 px-2 py-0.5 bg-slate-950 rounded border border-slate-800">
                      {alert.route_code}
                    </span>
                    <span className="text-xs font-semibold text-slate-300">
                      Airline: {alert.airline_code} {alert.flight_number ? `(${alert.flight_number})` : ''}
                    </span>
                    <span className="text-xs text-slate-500 font-mono">
                      {new Date(alert.detected_at).toLocaleTimeString()}
                    </span>
                  </div>

                  <p className="text-xs text-slate-200 leading-relaxed font-sans">
                    {alert.description}
                  </p>

                  <div className="flex flex-wrap items-center gap-4 text-xs font-mono text-slate-400 pt-1">
                    <div>
                      Observed:{' '}
                      <span className="text-rose-400 font-bold">
                        ₹{alert.observed_fare_inr.toLocaleString('en-IN')}
                      </span>
                    </div>
                    <div>
                      Expected:{' '}
                      <span className="text-slate-300 font-bold">
                        ₹{alert.expected_fare_inr.toLocaleString('en-IN')}
                      </span>
                    </div>
                    <div className="text-rose-400 font-bold flex items-center gap-0.5">
                      <TrendingUp className="w-3.5 h-3.5 inline" />
                      +{alert.deviation_percent.toFixed(1)}% Surge
                    </div>
                    {alert.booking_window && (
                      <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                        Window: {alert.booking_window}
                      </span>
                    )}
                  </div>

                  {alert.recommended_action && (
                    <div className="mt-2 text-xs bg-slate-950/80 border border-slate-800 rounded-lg p-2.5 text-slate-300">
                      <span className="font-semibold text-sky-400 mr-1.5 font-sans">
                        Regulatory Recommendation:
                      </span>
                      {alert.recommended_action}
                    </div>
                  )}
                </div>

                <div className="flex md:flex-col items-center gap-2 shrink-0">
                  <button
                    onClick={() => toggleAcknowledge(alert.id)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                      isAck
                        ? 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                        : 'bg-sky-600 hover:bg-sky-500 text-white shadow-md shadow-sky-900/30'
                    }`}
                  >
                    {isAck ? 'Acknowledged' : 'Acknowledge'}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
