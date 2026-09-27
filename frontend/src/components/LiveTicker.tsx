import React, { useState, useEffect, useRef } from 'react';
import { LiveFareUpdate } from '../types/api';
import apiClient from '../services/apiClient';
import {
  Play,
  Pause,
  Clock,
  ChevronDown,
  ChevronUp,
  SlidersHorizontal,
} from 'lucide-react';

interface LiveTickerProps {
  onSelectRoute?: (routeCode: string) => void;
  className?: string;
}

const CARRIER_NAMES: Record<string, string> = {
  '6E': 'IndiGo',
  'AI': 'Air India',
  'IX': 'Air India Express',
  'SG': 'SpiceJet',
  'QP': 'Akasa Air',
  'UK': 'Vistara',
  'I5': 'AIX Connect',
};

const SOURCE_LABELS: Record<string, string> = {
  easemytrip: 'EaseMyTrip',
  makemytrip: 'MakeMyTrip',
  spicejet: 'SpiceJet Direct',
  indigo: 'IndiGo Direct',
  airindia: 'Air India Direct',
  airindiaexpress: 'AI Express',
  akasa: 'Akasa Air Direct',
  yatra: 'Yatra',
  cleartrip: 'Cleartrip',
  ixigo: 'Ixigo',
  goibibo: 'Goibibo',
  amadeus: 'Amadeus GDS',
  synthetic_dgca: 'DGCA Benchmark',
  synthetic: 'DGCA Benchmark',
};

export const LiveTicker: React.FC<LiveTickerProps> = ({ onSelectRoute, className = '' }) => {
  const [fares, setFares] = useState<LiveFareUpdate[]>([]);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [isExpanded, setIsExpanded] = useState<boolean>(false);
  const [streamStatus, setStreamStatus] = useState<
    'connected' | 'connecting' | 'disconnected' | 'reconnecting'
  >('connecting');
  const [selectedCarrierFilter, setSelectedCarrierFilter] = useState<string>('ALL');

  // Stats
  const totalStreamedCountRef = useRef<number>(0);
  const minFareRef = useRef<number>(Infinity);
  const maxFareRef = useRef<number>(0);

  const isPausedRef = useRef<boolean>(false);
  isPausedRef.current = isPaused;

  useEffect(() => {
    const cleanup = apiClient.connectFareStream(
      (fare: LiveFareUpdate) => {
        if (isPausedRef.current) return;

        totalStreamedCountRef.current += 1;
        const rawFare = 'fare' in fare && typeof fare.fare === 'number' ? fare.fare : undefined;
        const fareValue = fare.fare_inr ?? rawFare ?? 0;
        if (fareValue > 0) {
          if (fareValue < minFareRef.current) minFareRef.current = fareValue;
          if (fareValue > maxFareRef.current) maxFareRef.current = fareValue;
        }

        setFares((prev) => {
          const updated = [fare, ...prev];
          // Keep buffer capped at 50 most recent records
          return updated.slice(0, 50);
        });
      },
      (status) => {
        setStreamStatus(status);
      }
    );

    return () => {
      cleanup();
    };
  }, []);

  const filteredFares = fares.filter((fare) => {
    if (selectedCarrierFilter !== 'ALL' && fare.airline_code !== selectedCarrierFilter) {
      return false;
    }
    return true;
  });

  const labelled = filteredFares.filter((fare) => typeof fare.is_synthetic === 'boolean');
  const allSimulated = labelled.length > 0 && labelled.every((fare) => fare.is_synthetic === true);
  const anySimulated = labelled.some((fare) => fare.is_synthetic === true);
  const provenance: 'simulated' | 'mixed' | 'live' | 'unverified' =
    labelled.length !== filteredFares.length
      ? 'unverified'
      : allSimulated
      ? 'simulated'
      : anySimulated
      ? 'mixed'
      : 'live';

  const minFare = minFareRef.current !== Infinity ? minFareRef.current : 0;
  const maxFare = maxFareRef.current > 0 ? maxFareRef.current : 0;

  const statusLabel =
    streamStatus === 'connected'
      ? 'WEBSOCKET LIVE'
      : streamStatus === 'connecting'
      ? 'CONNECTING PIPELINE'
      : streamStatus === 'reconnecting'
      ? 'RECONNECTING'
      : 'OFFLINE';

  return (
    <div
      className={`bg-neutral-950 border border-neutral-800 rounded-lg overflow-hidden ${className}`}
    >
      {/* Ticker Control Bar */}
      <div className="px-4 py-2 bg-neutral-950 border-b border-neutral-800 flex flex-wrap items-center justify-between gap-3 text-xs">
        {/* Left: Stream Status & Live Indicator */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                streamStatus === 'connected'
                  ? 'bg-emerald-400 animate-pulse'
                  : streamStatus === 'connecting'
                  ? 'bg-amber-400 animate-pulse'
                  : 'bg-neutral-500'
              }`}
            />
            <span className="font-mono text-[11px] font-semibold tracking-wider text-neutral-200">
              FARE FEED
            </span>
            <span
              className={`px-1.5 py-0.5 rounded font-mono text-[10px] font-medium border ${
                streamStatus === 'connected'
                  ? 'bg-emerald-950/60 border-emerald-800 text-emerald-400'
                  : streamStatus === 'connecting'
                  ? 'bg-amber-950/60 border-amber-800 text-amber-300'
                  : 'bg-neutral-900 border-neutral-800 text-neutral-400'
              }`}
            >
              {statusLabel}
            </span>
            {filteredFares.length > 0 && (
              <span
                className={`px-1.5 py-0.5 rounded font-mono text-[10px] font-medium border ${
                  provenance === 'simulated'
                    ? 'bg-cyan-950/60 border-cyan-800 text-cyan-300'
                    : provenance === 'mixed'
                    ? 'bg-amber-950/60 border-amber-800 text-amber-300'
                    : provenance === 'live'
                    ? 'bg-emerald-950/60 border-emerald-800 text-emerald-300'
                    : 'bg-neutral-900 border-neutral-700 text-neutral-400'
                }`}
              >
                {provenance === 'simulated'
                  ? 'DGCA BENCHMARK'
                  : provenance === 'mixed'
                  ? 'MIXED (HYBRID)'
                  : provenance === 'live'
                  ? 'LIVE SCRAPE'
                  : 'PROVENANCE UNKNOWN'}
              </span>
            )}
          </div>

          <span className="text-neutral-700 hidden md:inline">/</span>

          {/* Quick Metrics */}
          <div className="hidden sm:flex items-center gap-3 text-[11px] font-mono text-neutral-400">
            <span>
              Ingested:{' '}
              <span className="text-neutral-200 tabular-nums font-medium">
                {totalStreamedCountRef.current}
              </span>
            </span>
            {minFare > 0 && (
              <span>
                Low:{' '}
                <span className="text-neutral-200 tabular-nums font-medium">
                  ₹{minFare.toLocaleString('en-IN')}
                </span>
              </span>
            )}
            {maxFare > 0 && (
              <span>
                Peak:{' '}
                <span className="text-neutral-200 tabular-nums font-medium">
                  ₹{maxFare.toLocaleString('en-IN')}
                </span>
              </span>
            )}
          </div>
        </div>

        {/* Right: Controls & Filters */}
        <div className="flex items-center gap-2">
          {/* Carrier Filter */}
          <div className="flex items-center gap-1.5">
            <SlidersHorizontal className="w-3 h-3 text-neutral-500" />
            <select
              value={selectedCarrierFilter}
              onChange={(e) => setSelectedCarrierFilter(e.target.value)}
              className="bg-neutral-900 text-neutral-300 border border-neutral-800 rounded px-2 py-1 text-[11px] font-mono focus:border-neutral-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950"
            >
              <option value="ALL">All Airlines</option>
              <option value="6E">6E (IndiGo)</option>
              <option value="AI">AI (Air India)</option>
              <option value="SG">SG (SpiceJet)</option>
              <option value="QP">QP (Akasa)</option>
            </select>
          </div>

          {/* Pause / Resume Button */}
          <button
            onClick={() => setIsPaused(!isPaused)}
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-neutral-900 hover:bg-neutral-800 text-neutral-300 border border-neutral-800 text-[11px] font-mono transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950"
            title={isPaused ? 'Resume streaming feed' : 'Pause streaming feed'}
          >
            {isPaused ? <Play className="w-3 h-3 text-neutral-300" /> : <Pause className="w-3 h-3 text-neutral-400" />}
            <span>{isPaused ? 'Resume' : 'Pause'}</span>
          </button>

          {/* Expand / Collapse Ledger Button */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-1 px-2.5 py-1 rounded bg-neutral-900 hover:bg-neutral-800 text-neutral-300 border border-neutral-800 text-[11px] font-mono transition-colors motion-reduce:transition-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950"
          >
            <span>{isExpanded ? 'Hide Ledger' : 'View Ledger'}</span>
            {isExpanded ? <ChevronUp className="w-3 h-3 text-neutral-400" /> : <ChevronDown className="w-3 h-3 text-neutral-400" />}
          </button>
        </div>
      </div>

      {/* Horizontal Carousel / Ticker Stream */}
      <div
        className="p-3 overflow-x-auto scrollbar-thin flex gap-2.5 items-center live-ticker-stream motion-reduce:scroll-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-1 focus-visible:ring-offset-neutral-950"
        data-ticker-stream="true"
        aria-label="Live fare ticker"
      >
        {filteredFares.length === 0 ? (
          <div className="py-3 px-4 text-xs text-neutral-500 font-mono flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 text-neutral-500" />
            <span>Connecting to live fare pipeline and waiting for crawler packets...</span>
          </div>
        ) : (
          filteredFares.slice(0, 15).map((fare, idx) => {
            const rawFare = 'fare' in fare && typeof fare.fare === 'number' ? fare.fare : undefined;
            const fareValue = fare.fare_inr ?? rawFare ?? 0;
            const sourceLabel = SOURCE_LABELS[fare.source?.toLowerCase()] || fare.source;

            return (
              <div
                key={`${fare.flight_number}-${fare.timestamp}-${idx}`}
                onClick={() => onSelectRoute?.(`${fare.origin}-${fare.destination}`)}
                className="flex-shrink-0 cursor-pointer rounded-md p-3 border border-neutral-800 bg-neutral-950 hover:border-neutral-700 hover:bg-neutral-900/40 transition-colors motion-reduce:transition-none min-w-[210px]"
              >
                {/* Header: Carrier Tag + Route */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-neutral-900 border border-neutral-800 text-neutral-300"
                      title={CARRIER_NAMES[fare.airline_code] ?? fare.airline_name ?? fare.airline_code}
                    >
                      {fare.airline_code}
                    </span>
                    <span className="text-xs font-mono text-neutral-300 font-medium">
                      {fare.flight_number}
                    </span>
                  </div>

                  <div className="flex items-center gap-1 text-xs font-mono font-medium text-neutral-400">
                    <span>{fare.origin}</span>
                    <span className="text-neutral-600">→</span>
                    <span>{fare.destination}</span>
                  </div>
                </div>

                {/* Fare & Source Row */}
                <div className="mt-2.5 flex items-baseline justify-between">
                  <div className="flex items-baseline gap-1">
                    <span className="text-base font-semibold font-mono tabular-nums text-white tracking-tight">
                      ₹{fareValue.toLocaleString('en-IN')}
                    </span>
                    <span className="text-[10px] text-neutral-500 font-mono uppercase">INR</span>
                  </div>

                  <span className="text-[10px] font-mono text-neutral-500">
                    {sourceLabel}
                  </span>
                </div>

                {/* Footer: Date & Timestamp */}
                <div className="mt-2 pt-2 border-t border-neutral-900 flex items-center justify-between text-[10px] text-neutral-500 font-mono">
                  <span>
                    Dep:{' '}
                    {fare.departure_datetime
                      ? new Date(fare.departure_datetime).toLocaleDateString([], {
                          month: 'short',
                          day: 'numeric',
                        })
                      : '—'}
                  </span>
                  <span className="flex items-center gap-1 text-neutral-500">
                    <Clock className="w-2.5 h-2.5" />
                    {fare.timestamp
                      ? new Date(fare.timestamp).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                          second: '2-digit',
                        })
                      : '—'}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Expandable Full Stream Ledger Table */}
      {isExpanded && (
        <div className="border-t border-neutral-800 bg-neutral-950 p-4 max-h-72 overflow-y-auto">
          <div className="flex items-center justify-between mb-2.5">
            <span className="text-xs font-medium text-white font-mono">
              Stream Ledger ({filteredFares.length} Packets)
            </span>
            <span className="text-[11px] text-neutral-500 font-mono">
              FIFO ring buffer
            </span>
          </div>

          <table className="w-full text-left text-xs">
            <thead className="bg-neutral-900/60 text-neutral-400 font-mono text-[10px] uppercase tracking-wider border-b border-neutral-800">
              <tr>
                <th className="py-2 px-3 font-medium">Arrival</th>
                <th className="py-2 px-3 font-medium">Carrier</th>
                <th className="py-2 px-3 font-medium">Flight</th>
                <th className="py-2 px-3 font-medium">Corridor</th>
                <th className="py-2 px-3 font-medium text-right">Fare (INR)</th>
                <th className="py-2 px-3 font-medium">Source</th>
                <th className="py-2 px-3 font-medium">Departure Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-800/60 font-mono text-neutral-300">
              {filteredFares.map((fare, idx) => {
                const rawFare = 'fare' in fare && typeof fare.fare === 'number' ? fare.fare : undefined;
                const fareValue = fare.fare_inr ?? rawFare ?? 0;
                const sourceLabel = SOURCE_LABELS[fare.source?.toLowerCase()] || fare.source;
                return (
                  <tr key={`tbl-${fare.flight_number}-${idx}`} className="hover:bg-neutral-900/40 transition-colors motion-reduce:transition-none">
                    <td className="py-1.5 px-3 text-neutral-500 text-[11px] tabular-nums">
                      {fare.timestamp
                        ? new Date(fare.timestamp).toLocaleTimeString([], {
                            hour: '2-digit',
                            minute: '2-digit',
                            second: '2-digit',
                          })
                        : '—'}
                    </td>
                    <td className="py-1.5 px-3">
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-neutral-900 border border-neutral-800 text-neutral-300"
                        title={CARRIER_NAMES[fare.airline_code] ?? fare.airline_name ?? fare.airline_code}
                      >
                        {fare.airline_code}
                      </span>
                    </td>
                    <td className="py-1.5 px-3 font-medium text-white">{fare.flight_number}</td>
                    <td className="py-1.5 px-3 text-neutral-300">
                      {fare.origin} <span className="text-neutral-600">→</span> {fare.destination}
                    </td>
                    <td className="py-1.5 px-3 text-right font-medium text-white tabular-nums">
                      ₹{fareValue.toLocaleString('en-IN')}
                    </td>
                    <td className="py-1.5 px-3 text-neutral-400 text-[11px] capitalize">
                      {sourceLabel}
                    </td>
                    <td className="py-1.5 px-3 text-neutral-400 text-[11px]">
                      {fare.departure_datetime
                        ? new Date(fare.departure_datetime).toLocaleDateString([], {
                            month: 'short',
                            day: 'numeric',
                            year: 'numeric',
                          })
                        : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
