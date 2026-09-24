import React, { useState, useEffect, useRef } from 'react';
import { LiveFareUpdate } from '../types/api';
import apiClient from '../services/apiClient';
import {
  Radio,
  Play,
  Pause,
  Clock,
  Sparkles,
  Plane,
  ChevronDown,
  ChevronUp,
  SlidersHorizontal,
} from 'lucide-react';

interface LiveTickerProps {
  onSelectRoute?: (routeCode: string) => void;
  className?: string;
}

// Carrier branding style mapping
const CARRIER_CONFIG: Record<
  string,
  { name: string; bg: string; text: string; border: string; dot: string }
> = {
  '6E': {
    name: 'IndiGo',
    bg: 'bg-sky-950/80',
    text: 'text-sky-300',
    border: 'border-sky-700/80',
    dot: 'bg-sky-400',
  },
  'AI': {
    name: 'Air India',
    bg: 'bg-rose-950/80',
    text: 'text-rose-300',
    border: 'border-rose-700/80',
    dot: 'bg-rose-400',
  },
  'SG': {
    name: 'SpiceJet',
    bg: 'bg-amber-950/80',
    text: 'text-amber-300',
    border: 'border-amber-700/80',
    dot: 'bg-amber-400',
  },
  'QP': {
    name: 'Akasa Air',
    bg: 'bg-orange-950/80',
    text: 'text-orange-300',
    border: 'border-orange-700/80',
    dot: 'bg-orange-400',
  },
  'UK': {
    name: 'Vistara',
    bg: 'bg-purple-950/80',
    text: 'text-purple-300',
    border: 'border-purple-700/80',
    dot: 'bg-purple-400',
  },
};

// Source tag styling
const SOURCE_CONFIG: Record<string, { label: string; text: string; bg: string }> = {
  easemytrip: { label: 'EaseMyTrip', text: 'text-emerald-300', bg: 'bg-emerald-950/60' },
  makemytrip: { label: 'MakeMyTrip', text: 'text-red-300', bg: 'bg-red-950/60' },
  spicejet: { label: 'SpiceJet Direct', text: 'text-amber-300', bg: 'bg-amber-950/60' },
  amadeus: { label: 'Amadeus GDS', text: 'text-blue-300', bg: 'bg-blue-950/60' },
};

export const LiveTicker: React.FC<LiveTickerProps> = ({ onSelectRoute, className = '' }) => {
  const [fares, setFares] = useState<LiveFareUpdate[]>([]);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [isExpanded, setIsExpanded] = useState<boolean>(false);
  const [streamStatus, setStreamStatus] = useState<
    'connected' | 'connecting' | 'disconnected' | 'reconnecting'
  >('connecting');
  const [selectedCarrierFilter, setSelectedCarrierFilter] = useState<string>('ALL');
  const [newlyAddedId, setNewlyAddedId] = useState<string | null>(null);

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
        if (fare.fare_inr < minFareRef.current) minFareRef.current = fare.fare_inr;
        if (fare.fare_inr > maxFareRef.current) maxFareRef.current = fare.fare_inr;

        const uniqueKey = `${fare.flight_number}-${fare.source}-${Date.now()}`;
        setNewlyAddedId(uniqueKey);
        setTimeout(() => setNewlyAddedId(null), 1200);

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

  return (
    <div
      className={`bg-slate-900/90 border border-slate-800 rounded-2xl shadow-xl overflow-hidden backdrop-blur-md ${className}`}
    >
      {/* Ticker Control Bar */}
      <div className="px-4 py-2.5 bg-slate-950/70 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs">
        {/* Left: Stream Status & Live Indicator */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="relative flex h-2.5 w-2.5">
              <span
                className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                  streamStatus === 'connected'
                    ? 'bg-emerald-400'
                    : streamStatus === 'connecting'
                    ? 'bg-sky-400'
                    : 'bg-rose-400'
                }`}
              ></span>
              <span
                className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
                  streamStatus === 'connected'
                    ? 'bg-emerald-500'
                    : streamStatus === 'connecting'
                    ? 'bg-sky-500'
                    : 'bg-rose-500'
                }`}
              ></span>
            </span>

            <span className="font-mono font-bold tracking-wider text-[11px] text-white flex items-center gap-1.5">
              <Radio className="w-3.5 h-3.5 text-sky-400 animate-pulse" />
              <span>LIVE FARE FEED</span>
            </span>
          </div>

          <span
            className={`px-2 py-0.5 rounded-full font-mono text-[10px] font-semibold border ${
              streamStatus === 'connected'
                ? 'bg-emerald-950/80 text-emerald-300 border-emerald-800'
                : streamStatus === 'connecting'
                ? 'bg-sky-950/80 text-sky-300 border-sky-800'
                : streamStatus === 'reconnecting'
                ? 'bg-amber-950/80 text-amber-300 border-amber-800'
                : 'bg-rose-950/80 text-rose-300 border-rose-800'
            }`}
          >
            {streamStatus === 'connected'
              ? 'WEBSOCKET LIVE'
              : streamStatus === 'connecting'
              ? 'CONNECTING PIPELINE'
              : streamStatus === 'reconnecting'
              ? 'RECONNECTING'
              : 'OFFLINE'}
          </span>
          <span className="text-slate-600 hidden md:inline">|</span>

          {/* Quick Metrics */}
          <div className="hidden sm:flex items-center gap-3 text-[11px] font-mono text-slate-400">
            <span>
              Ingested: <strong className="text-white">{totalStreamedCountRef.current}</strong>
            </span>
            {minFareRef.current !== Infinity && (
              <span>
                Low: <strong className="text-emerald-400">₹{minFareRef.current.toLocaleString()}</strong>
              </span>
            )}
            {maxFareRef.current > 0 && (
              <span>
                Peak: <strong className="text-rose-400">₹{maxFareRef.current.toLocaleString()}</strong>
              </span>
            )}
          </div>
        </div>

        {/* Right: Controls & Filters */}
        <div className="flex items-center gap-2">
          {/* Carrier Filter */}
          <div className="flex items-center gap-1">
            <SlidersHorizontal className="w-3 h-3 text-slate-500" />
            <select
              value={selectedCarrierFilter}
              onChange={(e) => setSelectedCarrierFilter(e.target.value)}
              className="bg-slate-900 text-slate-300 border border-slate-700/80 rounded-lg px-2 py-1 text-[11px] font-mono focus:outline-none"
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
            className={`flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-colors ${
              isPaused
                ? 'bg-amber-950/60 text-amber-300 border-amber-800 hover:bg-amber-900/60'
                : 'bg-slate-900 text-slate-300 border-slate-700 hover:bg-slate-800'
            }`}
            title={isPaused ? 'Resume streaming feed' : 'Pause streaming feed'}
          >
            {isPaused ? <Play className="w-3 h-3 text-amber-400" /> : <Pause className="w-3 h-3 text-slate-400" />}
            <span>{isPaused ? 'Resume' : 'Pause'}</span>
          </button>

          {/* Expand / Collapse Ledger Button */}
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-900 text-slate-300 border border-slate-700 hover:bg-slate-800 text-[11px] font-medium transition-colors"
          >
            <span>{isExpanded ? 'Hide Ledger' : 'View Ledger'}</span>
            {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
        </div>
      </div>

      {/* Horizontal Carousel / Ticker Stream */}
      <div className="p-3 overflow-x-auto scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-slate-950 flex gap-3 items-center">
        {filteredFares.length === 0 ? (
          <div className="py-4 px-6 text-xs text-slate-500 font-mono flex items-center gap-2">
            <Clock className="w-4 h-4 animate-spin text-slate-600" />
            <span>Connecting to live fare pipeline and waiting for crawler packets...</span>
          </div>
        ) : (
          filteredFares.slice(0, 15).map((fare, idx) => {
            const carrier = CARRIER_CONFIG[fare.airline_code] || {
              name: fare.airline_name || fare.airline_code,
              bg: 'bg-slate-900',
              text: 'text-slate-300',
              border: 'border-slate-700',
              dot: 'bg-slate-400',
            };
            const source = SOURCE_CONFIG[fare.source.toLowerCase()] || {
              label: fare.source,
              text: 'text-slate-300',
              bg: 'bg-slate-800',
            };
            const isFresh = idx === 0 && newlyAddedId !== null;

            return (
              <div
                key={`${fare.flight_number}-${fare.timestamp}-${idx}`}
                onClick={() => onSelectRoute?.(`${fare.origin}-${fare.destination}`)}
                className={`flex-shrink-0 cursor-pointer rounded-xl p-3 border transition-all duration-300 min-w-[240px] ${
                  isFresh
                    ? 'bg-sky-950/60 border-sky-500 shadow-md shadow-sky-500/20 scale-[1.02]'
                    : 'bg-slate-950/60 border-slate-800/80 hover:border-slate-700 hover:bg-slate-950'
                }`}
              >
                {/* Header: Carrier Tag + Route Badge */}
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold border ${carrier.bg} ${carrier.text} ${carrier.border}`}
                    >
                      {fare.airline_code}
                    </span>
                    <span className="text-[11px] font-mono text-slate-300 font-semibold">
                      {fare.flight_number}
                    </span>
                  </div>

                  <div className="flex items-center gap-1 text-[11px] font-mono font-bold text-sky-400 bg-sky-950/60 border border-sky-800/60 px-2 py-0.5 rounded">
                    <span>{fare.origin}</span>
                    <Plane className="w-2.5 h-2.5 text-sky-400 transform rotate-90" />
                    <span>{fare.destination}</span>
                  </div>
                </div>

                {/* Fare & Source Row */}
                <div className="mt-2.5 flex items-baseline justify-between">
                  <div className="flex items-baseline gap-1">
                    <span className="text-lg font-bold font-mono text-white tracking-tight">
                      ₹{fare.fare_inr.toLocaleString()}
                    </span>
                    <span className="text-[10px] text-slate-500 font-sans uppercase">INR</span>
                  </div>

                  <span
                    className={`text-[10px] font-mono px-1.5 py-0.2 rounded border border-slate-700/60 ${source.bg} ${source.text}`}
                  >
                    {source.label}
                  </span>
                </div>

                {/* Footer: Relative Time & Departure Window */}
                <div className="mt-2 pt-2 border-t border-slate-900 flex items-center justify-between text-[10px] text-slate-500 font-mono">
                  <span>
                    Dep:{' '}
                    {new Date(fare.departure_datetime).toLocaleDateString([], {
                      month: 'short',
                      day: 'numeric',
                    })}
                  </span>
                  <span className="flex items-center gap-1 text-slate-400">
                    <Clock className="w-2.5 h-2.5" />
                    {new Date(fare.timestamp).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                    })}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Expandable Full Stream Ledger Table */}
      {isExpanded && (
        <div className="border-t border-slate-800 bg-slate-950/80 p-4 max-h-72 overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-bold text-white font-mono flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-sky-400" />
              <span>Real-Time Stream Buffer ({filteredFares.length} Packets)</span>
            </span>
            <span className="text-[11px] text-slate-400 font-mono">
              Auto-pruned FIFO ring buffer
            </span>
          </div>

          <table className="w-full text-left text-xs">
            <thead className="bg-slate-900 text-slate-400 font-mono text-[10px] uppercase border-b border-slate-800">
              <tr>
                <th className="py-2 px-3">Arrival</th>
                <th className="py-2 px-3">Carrier</th>
                <th className="py-2 px-3">Flight</th>
                <th className="py-2 px-3">Corridor</th>
                <th className="py-2 px-3">Fare (INR)</th>
                <th className="py-2 px-3">Source Engine</th>
                <th className="py-2 px-3">Departure Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-mono text-slate-300">
              {filteredFares.map((fare, idx) => (
                <tr key={`tbl-${fare.flight_number}-${idx}`} className="hover:bg-slate-800/40">
                  <td className="py-1.5 px-3 text-slate-500 text-[11px]">
                    {new Date(fare.timestamp).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                    })}
                  </td>
                  <td className="py-1.5 px-3">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-slate-800 border border-slate-700 text-white">
                      {fare.airline_code}
                    </span>
                  </td>
                  <td className="py-1.5 px-3 font-semibold text-white">{fare.flight_number}</td>
                  <td className="py-1.5 px-3 text-sky-400 font-bold">
                    {fare.origin} → {fare.destination}
                  </td>
                  <td className="py-1.5 px-3 text-white font-bold">
                    ₹{fare.fare_inr.toLocaleString()}
                  </td>
                  <td className="py-1.5 px-3 text-slate-400 text-[11px] capitalize">
                    {fare.source}
                  </td>
                  <td className="py-1.5 px-3 text-slate-400 text-[11px]">
                    {new Date(fare.departure_datetime).toLocaleDateString([], {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
