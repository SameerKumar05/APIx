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
      ] = await Promise.all([
        this.getNationalIndexLatest(),
        this.getNationalIndexHistory(30),
        this.getRoutesOverview(),
        this.getLeadTimeCurve(),
        this.getHeatmap(),
        this.getAnomalies(),
        this.getDGCAValidation(),
        this.getSystemHealth(),
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
      };
    } catch {
      return getMockDashboardSummary();
    }
  }
}

// Singleton export
export const apiClient = new ApiClient();
export default apiClient;
