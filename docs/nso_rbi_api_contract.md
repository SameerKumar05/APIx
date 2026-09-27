# APIx Data Consumption Contract for NSO and RBI

## 1. Executive Summary

This document specifies the machine-to-machine API contract for consuming APIx airfare index and econometric intelligence. The primary institutional consumers are:
1. The National Statistical Office (NSO) under the Ministry of Statistics and Programme Implementation (MoSPI), for augmenting the official monthly Consumer Price Index (CPI) Transportation sub-index.
2. The Reserve Bank of India (RBI) Monetary Policy Department, for tracking high-frequency airfare inflation early warnings and underlying dynamic pricing momentum.

All endpoints adhere strictly to OpenAPI 3.1 standards. The API operates over HTTPS and returns RFC 8259 compliant JSON payloads.

---

## 2. API Schema and Discovery Metadata

### 2.1 Specification URLs

- OpenAPI 3.1 JSON Schema: `/api/v1/openapi.json`
- Interactive Swagger UI: `/api/v1/docs`
- ReDoc Documentation: `/api/v1/redoc`

### 2.2 Versioning

The API version is declared in the path prefix `/api/v1`. Backward-incompatible modifications increment this major version component.

---

## 3. Security, Authentication, and Access Governance

### 3.1 Read Authentication

All public analytical and index endpoints are accessible without credentials. This eliminates polling friction for national accounting systems and central bank automated ingestion feeds. Institutional clients may optionally transmit an identification header:
- Header: `X-API-Key: <institutional-client-key>`
- Or Header: `Authorization: Bearer <institutional-client-key>`

### 3.2 Write and Ingestion Authentication

Endpoints that trigger scraper jobs or mutate data reject unauthorized requests with HTTP 401 Unauthorized.
- Header: `X-Ingestion-Key: <ingestion-secret-key>`

### 3.3 Rate Limiting

The API employs a deterministic fixed-window per-client rate limiter.
- Limit: 120 requests per 60 seconds per client IP address.
- Configurable environment keys: `API_RATE_LIMIT_REQUESTS=120`, `API_RATE_LIMIT_WINDOW_SECONDS=60`.

Every HTTP response includes rate limit telemetry headers:
- `X-RateLimit-Limit`: Maximum requests permitted in each window (120).
- `X-RateLimit-Remaining`: Remaining request quota in the active window.

When the quota is exceeded, the server returns HTTP 429 Too Many Requests:
```json
{
  "detail": "Rate limit exceeded. Retry after the window resets."
}
```
The HTTP 429 response includes the `Retry-After` header indicating seconds until quota reset.

### 3.4 Cross-Origin Resource Sharing (CORS)

CORS settings enforce strict origin validation:
- Permitted origins: Whitelisted origins configured in `BACKEND_CORS_ORIGINS` (default includes `http://localhost:3000`, `http://localhost:5173`, `http://127.0.0.1:3000`, `http://127.0.0.1:5173`).
- Wildcard origin (`*`) is strictly rejected by application startup validators.
- Allowed HTTP methods: `GET`, `POST`, `PATCH`, `OPTIONS`.
- Allowed HTTP headers: `Accept`, `Authorization`, `Content-Type`, `X-API-Key`, `X-Ingestion-Key`.
- Exposed HTTP headers: `X-Process-Time`.

---

## 4. Visualization and Data Feed Endpoints

### 4.1 Visual 1: Daily National Index and Historical Trends

#### GET `/api/v1/indices/national/latest`

Returns the most recent national composite airfare price index.

**Response Schema:**
```json
{
  "timestamp": "2026-09-28T04:00:00Z",
  "index_value": 118.65,
  "change_24h": 1.42,
  "change_7d": 3.78,
  "sample_size": 48290,
  "base_period": "2026-01=100",
  "confidence_interval_lower": 117.82,
  "confidence_interval_upper": 119.48,
  "status": "OFFICIAL",
  "weighted_median_fare_inr": 5480.0,
  "mospi_cpi": 107.4,
  "mospi_cpi_divergence": 11.25,
  "t1_index": 154.2,
  "t7_index": 128.6,
  "t15_index": 116.4,
  "t30_index": 100.0,
  "t45_index": 95.8
}
```

#### GET `/api/v1/indices/national/history`

Returns the historical series for national composite airfare index with advance window sub-indices.

**Query Parameters:**
- `days` (integer, default 30): Historical duration in days.
- `frequency` (string, optional, default "daily"): Aggregation resolution ("daily", "weekly", "monthly").

**Response Schema:**
```json
{
  "points": [
    {
      "date": "2026-09-27",
      "index_value": 118.65,
      "t1_index": 154.2,
      "t7_index": 128.6,
      "t15_index": 116.4,
      "t30_index": 100.0,
      "t45_index": 95.8,
      "sample_size": 48290
    }
  ],
  "base_period": "2026-01=100",
  "total_points": 30
}
```

#### GET `/api/v1/indices/routes`

Returns all active domestic trunk corridors with DGCA passenger weights and latest index values.

**Response Schema:**
```json
{
  "total_routes": 10,
  "routes": [
    {
      "route_code": "DEL-BOM",
      "origin": "DEL",
      "destination": "BOM",
      "origin_city": "Delhi",
      "destination_city": "Mumbai",
      "weight": 0.2285,
      "current_index": 118.5,
      "change_24h": 1.2,
      "change_7d": 3.4,
      "median_fare_inr": 5480.0,
      "history_7d": [115.1, 115.8, 116.4, 117.0, 117.5, 118.1, 118.5],
      "active_flights_tracked": 84,
      "carrier_count": 4,
      "dominant_carrier": "6E",
      "anomaly_count": 0
    }
  ]
}
```

#### GET `/api/v1/indices/routes/{route_code}/history`

Returns route-level time-series index data.

**Path Parameters:**
- `route_code` (string, required): Standard IATA corridor code (e.g. `DEL-BOM`).

**Query Parameters:**
- `days` (integer, default 30): Lookback window in calendar days.
- `booking_window` (string, optional): Specific booking window filter (`COMPOSITE`, `T+1`, `T+7`, `T+15`, `T+30`, `T+45`).
- `frequency` (string, optional, default "daily"): Aggregation resolution ("daily", "weekly", "monthly").

---

### 4.2 Visual 2: Sector-Wise Heatmap Matrix

#### GET `/api/v1/analytics/sector-heatmap` (Alias: `/api/v1/indices/sector-heatmap`)

Returns the complete routes by advance booking windows matrix ($T+1, T+7, T+15, T+30, T+45$), surge multipliers, base fares, and urgent fares.

**Query Parameters:**
- `route_code` (string, optional): Filter by corridor code (e.g. `DEL-BOM`). When omitted, all evaluated corridors are returned.

**Response Schema:**
```json
{
  "generated_at": "2026-09-28T04:00:00Z",
  "windows": ["T+1", "T+7", "T+15", "T+30", "T+45"],
  "total_routes": 10,
  "data_available": true,
  "sectors": [
    {
      "route_code": "DEL-BOM",
      "origin": "DEL",
      "destination": "BOM",
      "windows": {
        "T+1": 8500.0,
        "T+7": 6200.0,
        "T+15": 5400.0,
        "T+30": 4800.0,
        "T+45": 4500.0
      },
      "surge_multiplier": 1.77,
      "base_fare_inr": 4800.0,
      "urgent_fare_inr": 8500.0,
      "composite_fare_inr": 5480.0,
      "sample_size": 125
    }
  ],
  "matrix": [
    {
      "route_code": "DEL-BOM",
      "origin": "DEL",
      "destination": "BOM",
      "booking_window": "T+1",
      "days_before_departure": 1,
      "avg_fare_inr": 8500.0,
      "median_fare_inr": 8400.0,
      "min_fare_inr": 7800.0,
      "max_fare_inr": 9500.0,
      "sample_size": 15,
      "fare_index": 177.08
    }
  ]
}
```

---

### 4.3 Visual 3: Lead-Time Elasticity Curves (Including T+45)

#### GET `/api/v1/analytics/lead-time-curve`

Returns dynamic pricing elasticity curve points across advance purchase horizons.

**Query Parameters:**
- `route_code` (string, optional, default "NATIONAL"): Corridor code or `NATIONAL`.

**Response Schema:**
```json
{
  "route_code": "NATIONAL",
  "data_available": true,
  "generated_at": "2026-09-28T04:00:00Z",
  "curve_points": [
    {
      "days_before_departure": 45,
      "booking_window_label": "T+45",
      "avg_fare_inr": 4500.0,
      "median_fare_inr": 4450.0,
      "p10_fare_inr": 4100.0,
      "p90_fare_inr": 5100.0,
      "elasticity_factor": 1.0,
      "sample_count": 820
    },
    {
      "days_before_departure": 30,
      "booking_window_label": "T+30",
      "avg_fare_inr": 4800.0,
      "median_fare_inr": 4750.0,
      "p10_fare_inr": 4300.0,
      "p90_fare_inr": 5500.0,
      "elasticity_factor": 1.07,
      "sample_count": 940
    },
    {
      "days_before_departure": 15,
      "booking_window_label": "T+15",
      "avg_fare_inr": 5400.0,
      "median_fare_inr": 5350.0,
      "p10_fare_inr": 4900.0,
      "p90_fare_inr": 6000.0,
      "elasticity_factor": 1.20,
      "sample_count": 1100
    },
    {
      "days_before_departure": 7,
      "booking_window_label": "T+7",
      "avg_fare_inr": 6200.0,
      "median_fare_inr": 6100.0,
      "p10_fare_inr": 5600.0,
      "p90_fare_inr": 7000.0,
      "elasticity_factor": 1.37,
      "sample_count": 1280
    },
    {
      "days_before_departure": 1,
      "booking_window_label": "T+1",
      "avg_fare_inr": 8500.0,
      "median_fare_inr": 8400.0,
      "p10_fare_inr": 7800.0,
      "p90_fare_inr": 9500.0,
      "elasticity_factor": 1.89,
      "sample_count": 1450
    }
  ]
}
```

---

### 4.4 Visual 4: Econometric Comparisons & CPI Divergence

#### GET `/api/v1/econometrics/indices`

Computes dual-index formula decomposition: True Laspeyres ($P_L$), Paasche ($P_P$), and Fisher Ideal ($P_F = \sqrt{P_L \cdot P_P}$), alongside commodity substitution bias.

**Query Parameters:**
- `route_code` (string, optional, default "NATIONAL"): Route corridor or national aggregate.

**Response Schema:**
```json
{
  "date": "2026-09-28",
  "route_code": "NATIONAL",
  "fisher_index": 118.65,
  "laspeyres_index": 122.40,
  "paasche_index": 115.01,
  "substitution_bias": 7.39,
  "confidence_interval_lower": 117.82,
  "confidence_interval_upper": 119.48,
  "base_period": "2026-01=100",
  "summary": {
    "current_fisher": 118.65,
    "current_laspeyres": 122.40,
    "current_paasche": 115.01,
    "avg_substitution_bias": 7.39
  }
}
```

#### GET `/api/v1/econometrics/cpi-divergence`

Computes high-frequency divergence between the APIx Fisher index and the official MoSPI Consumer Price Index (Transport component), reporting empirical inflation lead days and Pearson cross-correlation.

**Query Parameters:**
- `start_month` (string, optional, e.g. "2024-01"): Filter start boundary in YYYY-MM format.
- `end_month` (string, optional, e.g. "2026-09"): Filter end boundary in YYYY-MM format.

**Response Schema:**
```json
{
  "current_divergence_pts": 11.25,
  "inflation_lead_days": 38,
  "correlation_coefficient": 0.89,
  "divergence_series": [
    {
      "date": "2026-08",
      "apix_index": 118.65,
      "mospi_cpi": 107.40,
      "divergence_pts": 11.25,
      "lead_status": "LEADING",
      "lead_window_days": 38
    }
  ]
}
```

---

## 5. Automated Verification Protocol

NSO and RBI IT teams can verify endpoint availability using the provided verification suite:
```bash
/home/adix/Work/woventech/APIx/.venv/bin/pytest tests/test_visual_and_api_contract.py
```
This automated suite verifies schema conformity, status codes, rate limit headers, and the presence of all four mandatory visualization structures.
