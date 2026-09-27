/**
 * Project APIx - API Client Service
 * Live-only fetch wrapper. Every failure throws a typed ApiError.
 */

import {
  NationalIndexLatestResponse,
  NationalIndexHistoryResponse,
  RoutesOverviewResponse,
  RouteHistoryResponse,
  LeadTimeCurveResponse,
  HeatmapMatrixResponse,
  AnomalyAlertsResponse,
  DGCAValidationResponse,
  SystemHealthResponse,
  DashboardSummaryData,
  TelemetryResponse,
  ArbitrageResponse,
  CrawlerTriggerRequest,
  CrawlerTriggerResponse,
  LiveFareUpdate,
  EconometricIndicesResponse,
  CpiDivergenceResponse,
  PriceElasticityResponse,
  DgcaSurveillanceResponse,
} from '../types/api';

export type ApiError = {kind:"http";status:number;endpoint:string} | {kind:"network";endpoint:string} | {kind:"timeout";endpoint:string} | {kind:"parse";endpoint:string};

export interface ApiClientConfig {
  baseUrl: string;
  timeoutMs: number;
}

const resolveBaseUrl = (): string => {
  const metaEnv = (import.meta as unknown as { env?: Record<string, string> }).env;
  const envUrl = metaEnv?.VITE_API_BASE_URL;
  if (typeof envUrl === 'string' && envUrl.trim()) {
    const trimmed = envUrl.trim().replace(/\/+$/, '');
    if (!trimmed.endsWith('/api/v1')) {
      return `${trimmed}/api/v1`;
    }
    return trimmed;
  }
  return '/api/v1';
};

const DEFAULT_CONFIG: ApiClientConfig = {
  baseUrl: resolveBaseUrl(),
  timeoutMs: 5000,
};

const IATA_CITY_MAP: Record<string, string> = {
  DEL: 'Delhi',
  BOM: 'Mumbai',
  BLR: 'Bengaluru',
  CCU: 'Kolkata',
  HYD: 'Hyderabad',
  GOI: 'Goa',
  MAA: 'Chennai',
};

export class ApiClient {
  private config: ApiClientConfig;
  private lastFetchTime: Date | null = null;

  constructor(config: Partial<ApiClientConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  public getLastFetchTime(): Date | null {
    return this.lastFetchTime;
  }

  /**
   * Generic request helper with timeout. Throws typed ApiError on any failure.
   */
  private async request<T>(endpoint: string): Promise<T> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.config.timeoutMs);
    const url = `${this.config.baseUrl}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

    let response: Response;
    try {
      response = await fetch(url, {
        signal: controller.signal,
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
        },
      });
    } catch (err) {
      clearTimeout(timeoutId);
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw { kind: 'timeout', endpoint } as ApiError;
      }
      throw { kind: 'network', endpoint } as ApiError;
    }

    clearTimeout(timeoutId);

    if (!response.ok) {
      throw { kind: 'http', status: response.status, endpoint } as ApiError;
    }

    let data: unknown;
    try {
      data = await response.json();
    } catch {
      throw { kind: 'parse', endpoint } as ApiError;
    }
    if (data === null || data === undefined) {
      throw { kind: 'parse', endpoint } as ApiError;
    }
    this.lastFetchTime = new Date();
    return data as T;
  }

  /**
   * 1. National Index: Latest reading
   */
  public async getNationalIndexLatest(): Promise<NationalIndexLatestResponse> {
    return this.request<NationalIndexLatestResponse>(
      '/indices/national/latest'
    );
  }

  /**
   * 1. National Index: Historical series
   */
  public async getNationalIndexHistory(days: number = 30): Promise<NationalIndexHistoryResponse> {
    return this.request<NationalIndexHistoryResponse>(
      `/indices/national/history?days=${days}`
    );
  }

  /**
   * 2. Routes: Overview list of 10 high-density corridors
   */
  public async getRoutesOverview(): Promise<RoutesOverviewResponse> {
    const res = await this.request<RoutesOverviewResponse>(
      '/indices/routes'
    );
    const rawRoutes = res.routes || [];
    const enrichedRoutes = rawRoutes.map((r) => {
      return {
        ...r,
        origin_city: r.origin_city || IATA_CITY_MAP[r.origin] || r.origin || '',
        destination_city: r.destination_city || IATA_CITY_MAP[r.destination] || r.destination || '',
      };
    });
    return {
      routes: enrichedRoutes,
      total_routes: res.total_routes ?? enrichedRoutes.length,
    };
  }

  /**
   * 2. Routes: Specific route historical index
   */
  public async getRouteHistory(routeCode: string, days: number = 30): Promise<RouteHistoryResponse> {
    return this.request<RouteHistoryResponse>(
      `/indices/routes/${routeCode}/history?days=${days}`
    );
  }

  /**
   * 3. Analytics: Booking window / lead-time elasticity curve
   */
  public async getLeadTimeCurve(routeCode?: string): Promise<LeadTimeCurveResponse> {
    const endpoint = routeCode 
      ? `/analytics/lead-time-curve?route_code=${encodeURIComponent(routeCode)}`
      : '/analytics/lead-time-curve';

    return this.request<LeadTimeCurveResponse>(
      endpoint
    );
  }

  /**
   * 3. Analytics: Heatmap matrix of fare indices
   */
  public async getHeatmap(routeCode?: string): Promise<HeatmapMatrixResponse> {
    const endpoint = routeCode 
      ? `/analytics/heatmap?route_code=${encodeURIComponent(routeCode)}`
      : '/analytics/heatmap';

    return this.request<HeatmapMatrixResponse>(
      endpoint
    );
  }

  /**
   * 4. Analytics: Anomaly alerts
   */
  public async getAnomalies(severity?: string): Promise<AnomalyAlertsResponse> {
    const endpoint = severity 
      ? `/analytics/anomalies?severity=${encodeURIComponent(severity)}`
      : '/analytics/anomalies';

    return this.request<AnomalyAlertsResponse>(
      endpoint
    );
  }

  /**
   * 5. DGCA Statutory Compliance Evaluation
   */
  public async getDGCAValidation(): Promise<DGCAValidationResponse> {
    return this.request<DGCAValidationResponse>(
      '/analytics/dgca-validation'
    );
  }

  /**
   * 6. System Health & Scraping Pipeline Telemetry
   */
  public async getSystemHealth(): Promise<SystemHealthResponse> {
    return this.request<SystemHealthResponse>(
      '/health'
    );
  }

  /**
   * 7. Ingestion Pipeline & Crawler Telemetry
   */
  public async getTelemetry(): Promise<TelemetryResponse> {
    return this.request<TelemetryResponse>(
      '/ingestion/telemetry'
    );
  }

  /**
   * 8. Direct Airline vs OTA Arbitrage Analysis
   */
  public async getArbitrage(): Promise<ArbitrageResponse> {
    const res = await this.request<any>(
      '/analytics/arbitrage'
    );
    const rawItems = res.items || res.opportunities || [];
    const normalizedItems = rawItems.map((item: any) => {
      const directFare = item.direct_fare ?? item.airline_direct_fare;
      const otaFare = item.ota_fare;
      const otaName = item.ota_platform || item.ota_name || 'OTA';
      const spreadInr = item.spread_inr ?? item.spread_amount ?? (
        directFare !== undefined && otaFare !== undefined ? Math.abs(directFare - otaFare) : undefined
      );
      const spreadPct = item.spread_percentage ?? (
        directFare && spreadInr !== undefined ? (spreadInr / directFare) * 100 : undefined
      );
      const direction = item.direction || (
        directFare !== undefined && otaFare !== undefined
          ? (otaFare < directFare ? 'OTA_CHEAPER' : 'AIRLINE_CHEAPER')
          : 'OTA_CHEAPER'
      );
      return {
        ...item,
        direct_fare: directFare,
        airline_direct_fare: directFare,
        ota_platform: otaName,
        ota_name: otaName,
        spread_inr: spreadInr,
        spread_amount: spreadInr,
        spread_percentage: spreadPct !== undefined ? Number(Number(spreadPct).toFixed(2)) : undefined,
        direction,
        actionable: item.actionable ?? true,
      };
    });
    return {
      generated_at: res.generated_at || new Date().toISOString(),
      routes_evaluated: res.routes_evaluated ?? 0,
      opportunities_count: res.opportunities_count ?? normalizedItems.length,
      items: normalizedItems,
      total_potential_savings_inr: res.total_potential_savings_inr ?? res.total_savings_potential_inr,
      total_savings_potential_inr: res.total_potential_savings_inr ?? res.total_savings_potential_inr,
      avg_spread_percentage: res.avg_spread_percentage ?? res.max_spread_percentage,
      max_spread_percentage: res.max_spread_percentage ?? res.avg_spread_percentage,
    };
  }
  /**
   * 8a. Econometric Indices (Laspeyres, Paasche, Fisher, Substitution Bias)
   */
  public async getEconometricIndices(routeCode?: string): Promise<EconometricIndicesResponse> {
    const query = routeCode ? `?route_code=${encodeURIComponent(routeCode)}` : '';
    return this.request<EconometricIndicesResponse>(
      `/econometrics/indices${query}`
    );
  }

  /**
   * 8b. MoSPI CPI Divergence & Lead-Lag Tracking
   */
  public async getCpiDivergence(startMonth?: string, endMonth?: string): Promise<CpiDivergenceResponse> {
    const params = new URLSearchParams();
    if (startMonth) params.append('start_month', startMonth);
    if (endMonth) params.append('end_month', endMonth);
    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request<CpiDivergenceResponse>(
      `/econometrics/cpi-divergence${query}`
    );
  }

  /**
   * 8c. Price Elasticity Gradient Across Lead-Time Windows
   */
  public async getPriceElasticity(routeCode?: string): Promise<PriceElasticityResponse> {
    const query = routeCode ? `?route_code=${encodeURIComponent(routeCode)}` : '';
    return this.request<PriceElasticityResponse>(
      `/econometrics/elasticity${query}`
    );
  }

  /**
   * 8d. DGCA Statutory Violation Feed & Carrier Distribution
   */
  public async getDgcaSurveillance(params?: {
    severity?: string;
    route_code?: string;
    airline_code?: string;
    limit?: number;
  }): Promise<DgcaSurveillanceResponse> {
    const queryParams = new URLSearchParams();
    if (params?.severity) queryParams.append('severity', params.severity);
    if (params?.route_code) queryParams.append('route_code', params.route_code);
    if (params?.airline_code) queryParams.append('airline_code', params.airline_code);
    if (params?.limit) queryParams.append('limit', String(params.limit));
    const query = queryParams.toString() ? `?${queryParams.toString()}` : '';
    return this.request<DgcaSurveillanceResponse>(
      `/econometrics/dgca-violations${query}`
    );
  }


  /**
   * 9. Trigger Manual Crawler Ingestion
   */
  public async triggerCrawler(req: CrawlerTriggerRequest = {}): Promise<CrawlerTriggerResponse> {
    const endpoint = '/ingestion/trigger';
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.config.timeoutMs);

    let response: Response;
    try {
      response = await fetch(`${this.config.baseUrl}${endpoint}`, {
        method: 'POST',
        signal: controller.signal,
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(req),
      });
    } catch (err) {
      clearTimeout(timeoutId);
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw { kind: 'timeout', endpoint } as ApiError;
      }
      throw { kind: 'network', endpoint } as ApiError;
    }

    clearTimeout(timeoutId);

    if (!response.ok) {
      throw { kind: 'http', status: response.status, endpoint } as ApiError;
    }

    try {
      const data = await response.json();
      if (data === null || data === undefined) {
        throw { kind: 'parse', endpoint } as ApiError;
      }
      return data as CrawlerTriggerResponse;
    } catch (err) {
      if (err instanceof SyntaxError) {
        throw { kind: 'parse', endpoint } as ApiError;
      }
      throw err;
    }
  }

  /**
   * 10. Real-time Fare Stream (Production WebSocket Gateway)
   */
  public connectFareStream(
    onUpdate: (fare: LiveFareUpdate) => void,
    onStatusChange?: (status: 'connected' | 'connecting' | 'disconnected' | 'reconnecting') => void
  ): () => void {
    let ws: WebSocket | null = null;
    let isCleanedUp = false;
    let reconnectTimeout: NodeJS.Timeout | number | undefined = undefined;
    let pingInterval: NodeJS.Timeout | number | undefined = undefined;

    // Pre-seed buffer immediately from backend live recent fares endpoint
    if (typeof fetch !== 'undefined') {
      fetch(`${this.config.baseUrl}/stream/recent?limit=25`)
        .then((res) => (res.ok ? res.json() : null))
        .then((recentFares) => {
          if (!isCleanedUp && Array.isArray(recentFares) && recentFares.length > 0) {
            recentFares.forEach((fare: LiveFareUpdate) => onUpdate(fare));
          }
        })
        .catch(() => {});
    }

    const connect = () => {
      if (isCleanedUp) return;
      onStatusChange?.('connecting');

      try {
        let wsUrl: string;
        if (this.config.baseUrl.startsWith('http://') || this.config.baseUrl.startsWith('https://')) {
          const parsed = new URL(this.config.baseUrl);
          const wsProtocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:';
          wsUrl = `${wsProtocol}//${parsed.host}/api/v1/stream/fares`;
        } else {
          const protocol = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:';
          const host = typeof window !== 'undefined' ? window.location.host : '127.0.0.1:8000';
          wsUrl = `${protocol}//${host}/api/v1/stream/fares`;
        }
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          if (isCleanedUp) {
            ws?.close();
            return;
          }
          onStatusChange?.('connected');

          // Send subscription handshake
          try {
            if (ws && ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: 'subscribe', route: 'ALL' }));
            }
          } catch {
            // Non-blocking
          }

          // Heartbeat ping every 25 seconds to keep connection alive
          pingInterval = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
              try {
                ws.send(JSON.stringify({ type: 'ping' }));
              } catch {
                // Ignore ping send failures
              }
            }
          }, 25000);
        };

        ws.onmessage = (event) => {
          if (isCleanedUp) return;
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'initial_buffer' && Array.isArray(data.fares)) {
              data.fares.forEach((item: LiveFareUpdate) => onUpdate(item));
            } else if (data.type === 'fare_update' && (data.fare_inr || data.fare)) {
              onUpdate(data as LiveFareUpdate);
            } else if (Array.isArray(data.fares)) {
              data.fares.forEach((item: LiveFareUpdate) => onUpdate(item));
            } else if (Array.isArray(data)) {
              data.forEach((item) => {
                if (item.type === 'fare_update' || item.fare_inr) onUpdate(item);
              });
            } else if (data.data) {
              if (Array.isArray(data.data)) {
                data.data.forEach((item: LiveFareUpdate) => onUpdate(item));
              } else if (data.data.type === 'fare_update' || data.data.fare_inr) {
                onUpdate(data.data);
              }
            }
          } catch {
            // Non-json or heartbeat frames
          }
        };

        ws.onerror = () => {
          clearInterval(pingInterval);
        };

        ws.onclose = () => {
          clearInterval(pingInterval);
          if (isCleanedUp) return;
          onStatusChange?.('reconnecting');
          reconnectTimeout = setTimeout(connect, 3000);
        };
      } catch {
        onStatusChange?.('reconnecting');
        reconnectTimeout = setTimeout(connect, 3000);
      }
    };

    connect();

    return () => {
      isCleanedUp = true;
      clearInterval(pingInterval);
      clearTimeout(reconnectTimeout);
      if (ws) {
        ws.onclose = null;
        ws.onerror = null;
        ws.close();
      }
    };
  }

  /**
   * Composite Dashboard Summary
   */
  public async getDashboardSummary(): Promise<DashboardSummaryData> {
    const [
      nationalLatest,
      nationalHistoryRes,
      routesRes,
      leadTimeCurve,
      heatmap,
      anomaliesRes,
      dgcaValidation,
      systemHealth,
      telemetry,
      arbitrage,
      econometricIndices,
      cpiDivergence,
      priceElasticity,
      dgcaSurveillance,
    ] = await Promise.all([
      this.getNationalIndexLatest(),
      this.getNationalIndexHistory(30),
      this.getRoutesOverview(),
      this.getLeadTimeCurve(),
      this.getHeatmap(),
      this.getAnomalies(),
      this.getDGCAValidation(),
      this.getSystemHealth(),
      this.getTelemetry(),
      this.getArbitrage(),
      this.getEconometricIndices(),
      this.getCpiDivergence(),
      this.getPriceElasticity(),
      this.getDgcaSurveillance(),
    ]);

    return {
      nationalLatest,
      nationalHistory: nationalHistoryRes.points,
      routes: routesRes.routes,
      leadTimeCurve,
      heatmap,
      anomalies: anomaliesRes.alerts,
      dgcaValidation,
      systemHealth,
      telemetry,
      arbitrage,
      econometricIndices,
      cpiDivergence,
      priceElasticity,
      dgcaSurveillance,
    };
  }
}

// Singleton export
export const apiClient = new ApiClient();
export default apiClient;
