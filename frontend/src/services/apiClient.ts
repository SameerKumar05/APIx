/**
 * Project APIx - API Client Service
 * High-reliability fetch wrapper with automatic fallback to mock data provider.
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

import {
  mockNationalLatest,
  mockNationalHistory,
  mockRoutes,
  mockLeadTimeCurve,
  mockHeatmap,
  mockAnomalies,
  mockDGCAValidation,
  mockSystemHealth,
  mockTelemetry,
  mockArbitrage,
  mockEconometricIndices,
  mockCpiDivergence,
  mockPriceElasticity,
  mockDgcaSurveillance,
  getMockDashboardSummary,
  generateMockNationalHistory,
} from './mockData';

export interface ApiClientConfig {
  baseUrl: string;
  timeoutMs: number;
  preferMock: boolean;
}

const DEFAULT_CONFIG: ApiClientConfig = {
  baseUrl: typeof process !== 'undefined' && process.env?.VITE_API_BASE_URL 
    ? process.env.VITE_API_BASE_URL 
    : '/api/v1',
  timeoutMs: 5000,
  preferMock: false,
};

export class ApiClient {
  private config: ApiClientConfig;
  private isFallbackActive: boolean = false;
  private lastFetchTime: Date | null = null;
  private onSourceChangeListeners: Array<(usingMock: boolean) => void> = [];

  constructor(config: Partial<ApiClientConfig> = {}) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  public subscribeSourceChange(listener: (usingMock: boolean) => void): () => void {
    this.onSourceChangeListeners.push(listener);
    return () => {
      this.onSourceChangeListeners = this.onSourceChangeListeners.filter(l => l !== listener);
    };
  }

  private notifySourceChange(usingMock: boolean) {
    if (this.isFallbackActive !== usingMock) {
      this.isFallbackActive = usingMock;
      this.onSourceChangeListeners.forEach(listener => listener(usingMock));
    }
  }

  public isUsingMock(): boolean {
    return this.isFallbackActive || this.config.preferMock;
  }

  public getLastFetchTime(): Date | null {
    return this.lastFetchTime;
  }

  public setPreferMock(value: boolean) {
    this.config.preferMock = value;
    this.notifySourceChange(value);
  }

  /**
   * Generic request helper with timeout and fallback
   */
  private async request<T>(endpoint: string, mockFallback: () => T): Promise<T> {
    if (this.config.preferMock) {
      this.notifySourceChange(true);
      return mockFallback();
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.config.timeoutMs);
    const url = `${this.config.baseUrl}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
        },
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      this.notifySourceChange(false);
      this.lastFetchTime = new Date();
      return data as T;
    } catch {
      // Fallback gracefully to mock data
      clearTimeout(timeoutId);
      this.notifySourceChange(true);
      this.lastFetchTime = new Date();
      return mockFallback();
    }
  }

  /**
   * 1. National Index: Latest reading
   */
  public async getNationalIndexLatest(): Promise<NationalIndexLatestResponse> {
    return this.request<NationalIndexLatestResponse>(
      '/indices/national/latest',
      () => mockNationalLatest
    );
  }

  /**
   * 1. National Index: Historical series
   */
  public async getNationalIndexHistory(days: number = 30): Promise<NationalIndexHistoryResponse> {
    return this.request<NationalIndexHistoryResponse>(
      `/indices/national/history?days=${days}`,
      () => ({
        points: days === 30 ? mockNationalHistory : generateMockNationalHistory(days),
        total_points: days,
      })
    );
  }

  /**
   * 2. Routes: Overview list of 10 high-density corridors
   */
  public async getRoutesOverview(): Promise<RoutesOverviewResponse> {
    return this.request<RoutesOverviewResponse>(
      '/indices/routes',
      () => ({
        routes: mockRoutes,
        total_routes: mockRoutes.length,
      })
    );
  }

  /**
   * 2. Routes: Specific route historical index
   */
  public async getRouteHistory(routeCode: string, days: number = 30): Promise<RouteHistoryResponse> {
    const route = mockRoutes.find(r => r.route_code === routeCode) || mockRoutes[0];
    return this.request<RouteHistoryResponse>(
      `/indices/routes/${routeCode}/history?days=${days}`,
      () => ({
        route_code: routeCode,
        origin: route.origin,
        destination: route.destination,
        points: generateMockNationalHistory(days),
      })
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
      endpoint,
      () => ({
        ...mockLeadTimeCurve,
        route_code: routeCode || 'NATIONAL_WEIGHTED',
      })
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
      endpoint,
      () => mockHeatmap
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
      endpoint,
      () => {
        const filtered = severity 
          ? mockAnomalies.filter(a => a.severity.toUpperCase() === severity.toUpperCase())
          : mockAnomalies;
        return {
          alerts: filtered,
          total_alerts: filtered.length,
        };
      }
    );
  }

  /**
   * 5. DGCA Statutory Compliance Evaluation
   */
  public async getDGCAValidation(): Promise<DGCAValidationResponse> {
    return this.request<DGCAValidationResponse>(
      '/analytics/dgca-validation',
      () => mockDGCAValidation
    );
  }

  /**
   * 6. System Health & Scraping Pipeline Telemetry
   */
  public async getSystemHealth(): Promise<SystemHealthResponse> {
    return this.request<SystemHealthResponse>(
      '/health',
      () => mockSystemHealth
    );
  }

  /**
   * 7. Ingestion Pipeline & Crawler Telemetry
   */
  public async getTelemetry(): Promise<TelemetryResponse> {
    return this.request<TelemetryResponse>(
      '/ingestion/telemetry',
      () => mockTelemetry
    );
  }

  /**
   * 8. Direct Airline vs OTA Arbitrage Analysis
   */
  public async getArbitrage(): Promise<ArbitrageResponse> {
    return this.request<ArbitrageResponse>(
      '/analytics/arbitrage',
      () => mockArbitrage
    );
  }
  /**
   * 8a. Econometric Indices (Laspeyres, Paasche, Fisher, Substitution Bias)
   */
  public async getEconometricIndices(routeCode?: string): Promise<EconometricIndicesResponse> {
    const query = routeCode ? `?route_code=${encodeURIComponent(routeCode)}` : '';
    return this.request<EconometricIndicesResponse>(
      `/econometrics/indices${query}`,
      () => mockEconometricIndices
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
      `/econometrics/cpi-divergence${query}`,
      () => mockCpiDivergence
    );
  }

  /**
   * 8c. Price Elasticity Gradient Across Lead-Time Windows
   */
  public async getPriceElasticity(routeCode?: string): Promise<PriceElasticityResponse> {
    const query = routeCode ? `?route_code=${encodeURIComponent(routeCode)}` : '';
    return this.request<PriceElasticityResponse>(
      `/econometrics/elasticity${query}`,
      () => mockPriceElasticity
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
      `/econometrics/dgca-violations${query}`,
      () => mockDgcaSurveillance
    );
  }


  /**
   * 9. Trigger Manual Crawler Ingestion
   */
  public async triggerCrawler(req: CrawlerTriggerRequest = {}): Promise<CrawlerTriggerResponse> {
    if (this.config.preferMock) {
      return {
        task_id: `task-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
        status: 'QUEUED',
        message: `Crawler trigger accepted for ${req.crawler_name || 'all scrapers'}${req.route_code ? ` on route ${req.route_code}` : ''}`,
        triggered_at: new Date().toISOString(),
      };
    }

    try {
      const response = await fetch(`${this.config.baseUrl}/ingestion/trigger`, {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(req),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      return await response.json();
    } catch {
      return {
        task_id: `task-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
        status: 'QUEUED',
        message: `Crawler trigger fallback queued for ${req.crawler_name || 'all scrapers'}`,
        triggered_at: new Date().toISOString(),
      };
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
        const protocol = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = typeof window !== 'undefined' ? window.location.host : '127.0.0.1:8000';
        const wsUrl = `${protocol}//${host}/api/v1/stream/fares`;
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
    try {
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
    } catch {
      return getMockDashboardSummary();
    }
  }
}

// Singleton export
export const apiClient = new ApiClient();
export default apiClient;
