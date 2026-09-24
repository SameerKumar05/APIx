# APIx Production Deployment Guide
**SIH 2026 Problem Statement 26056: Real-time Airfare Price Index for India**  
*Augmenting the Official Consumer Price Index (CPI) Transportation Sub-Index*

---

## Table of Contents
1. [Architecture & Deployment Topology](#1-architecture--deployment-topology)
2. [FastAPI Backend Deployment on Render](#2-fastapi-backend-deployment-on-render)
3. [React Dashboard Deployment on Vercel](#3-react-dashboard-deployment-on-vercel)
4. [Distributed Scraper Automation on GitHub Actions](#4-distributed-scraper-automation-on-github-actions)
5. [Environment Variables & Secrets Reference](#5-environment-variables--secrets-reference)
6. [Secret Rotation & Security Protocol](#6-secret-rotation--security-protocol)
7. [Cold-Start Mitigation & Performance Tuning](#7-cold-start-mitigation--performance-tuning)
8. [Monitoring, Observability & Incident Response](#8-monitoring-observability--incident-response)
9. [Local Containerized Deployment (Docker Compose)](#9-local-containerized-deployment-docker-compose)

---

## 1. Architecture & Deployment Topology

The APIx platform is designed as a cloud-native, decoupled system distributed across resilient managed providers to achieve high availability, cost efficiency, and zero maintenance overhead:

```
  +-----------------------------------------------------------------------------------+
  |                               GitHub Actions Runner                               |
  |  - Scheduled Cron (02:00 UTC / 07:30 IST)                                         |
  |  - Playwright Chromium Headless Scrapers (EaseMyTrip, MakeMyTrip)                 |
  |  - Amadeus GDS Flight Offers API Client                                           |
  |  - Ingestion Orchestrator (ingestion.orchestrator)                                |
  +-----------------------------------------+-----------------------------------------+
                                            |
                         HTTPS POST /api/v1/ingestion/batch
                         (Header: X-Ingestion-Key)
                                            |
                                            v
  +-----------------------------------------------------------------------------------+
  |                                Render Web Service                                 |
  |  - FastAPI ASGI Backend (Uvicorn 4 Workers)                                       |
  |  - Quant Statistical Engine (Fisher, Laspeyres, Paasche, Weighted Median)          |
  |  - DGCA Passenger Traffic Weighting & Anomaly Detection (Z-Score >= 2.5)          |
  |  - RESTful API Router (/api/v1)                                                   |
  +------------------------------------+----------------------------------------------+
                                       |
                  +--------------------+--------------------+
                  |                                         |
                  v                                         v
+------------------------------------+    +------------------------------------+
|     Managed PostgreSQL / Timescale |    |         Vercel Edge Network        |
|  - Raw Fare Observations           |    |  - React 19 SPA (Vite + Tailwind)  |
|  - Daily Aggregated Indices        |    |  - Recharts Visualization Suite    |
|  - Route Pair & Window Baselines   |    |  - DGCA Route Analysis Dashboard   |
|  - Alembic Schema Migrations       |    |  - Static Edge CDN Delivery        |
+------------------------------------+    +------------------------------------+
```

---

## 2. FastAPI Backend Deployment on Render

Render hosts the FastAPI ASGI application as an auto-scaling, managed containerized service.

### 2.1 Service Configuration via Render Dashboard
1. Log in to [Render Dashboard](https://dashboard.render.com/) and click **New +** -> **Web Service**.
2. Connect your Git repository (`APIx`) and configure the primary service settings:
   - **Name**: `apix-backend-api`
   - **Region**: `Singapore (ap-southeast-1)` or `Frankfurt` (closest latency to Indian data sources).
   - **Branch**: `main`
   - **Root Directory**: Leave blank (repository root).
   - **Runtime**: `Python 3` (or `Docker` using project Dockerfile).
   - **Build Command**:
     ```bash
     pip install --upgrade pip && pip install -r requirements.txt
     ```
   - **Pre-Deploy Command** (executes database migrations prior to routing live traffic):
     ```bash
     alembic upgrade head
     ```
   - **Start Command**:
     ```bash
     uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT --workers 4 --proxy-headers --forwarded-allow-ips='*'
     ```
   - **Plan**: `Starter` ($7/mo) or `Standard` for persistent multi-core worker processing.

### 2.2 Health Check & Zero-Downtime Deploys
- **Health Check Path**: `/health`
- Render periodically sends `GET /health` requests. The response must return `200 OK` with JSON payload:
  ```json
  {
    "status": "healthy",
    "service": "apix-backend-api",
    "version": "1.0.0",
    "environment": "production"
  }
  ```
- If the pre-deploy migration or health check fails, Render retains the existing container and aborts deployment without downtime.

### 2.3 Managed PostgreSQL / TimescaleDB Provisioning
1. Click **New +** -> **PostgreSQL** on Render (or use an external TimescaleDB provider such as Timescale Cloud or Aiven).
2. Configure database name: `apix_db`, user: `apix_user`.
3. Copy the **Internal Database URL** for services in the same Render region:
   - `postgres://apix_user:<password>@dpg-<id>-a/apix_db`
4. Set both `DATABASE_URL` (using `postgresql+asyncpg://...` or `postgresql://...`) and `DATABASE_URL_SYNC` (using `postgresql://...`).

---

## 3. React Dashboard Deployment on Vercel

Vercel provides edge network hosting for the React 19 single-page application.

### 3.1 Vercel Project Setup
1. Log in to [Vercel](https://vercel.com/) and click **Add New...** -> **Project**.
2. Import the Git repository and configure the framework parameters:
   - **Framework Preset**: `Vite`
   - **Root Directory**: `frontend`
   - **Build Command**: `bun run build` (or `npm run build`)
   - **Output Directory**: `dist`
   - **Install Command**: `bun install` (or `npm install`)

### 3.2 Single Page Application (SPA) Routing Configuration
To avoid HTTP 404 errors when users refresh deep routes (e.g. `/routes/DEL-BOM` or `/analytics`), create `frontend/vercel.json`:
```json
{
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "/index.html"
    }
  ],
  "headers": [
    {
      "source": "/assets/(.*)",
      "headers": [
        {
          "key": "Cache-Control",
          "value": "public, max-age=31536000, immutable"
        }
      ]
    }
  ]
}
```

### 3.3 Frontend Environment Variables
In **Project Settings** -> **Environment Variables**:
- `VITE_API_BASE_URL`: `https://apix-backend-api.onrender.com/api/v1` (Production)
- Configure preview environments to point to staging or preview backend URLs.

---

## 4. Distributed Scraper Automation on GitHub Actions

Scraping runs on ephemeral GitHub Actions runners to provide isolated, burstable browser execution without consuming persistent server memory.

### 4.1 Workflow Overview (`.github/workflows/scrape.yml`)
- **Schedule**: Every day at `02:00 UTC` (`07:30 IST`), coinciding with off-peak DGCA traffic intervals.
- **Manual Trigger**: `workflow_dispatch` allows on-demand execution with parameter selection (`mode: live | synthetic | mock`, `sources: all | easemytrip | amadeus`).
- **Playwright Caching**: Caches `~/.cache/ms-playwright` keyed by `requirements.txt` hash to eliminate redundant browser downloads.
- **Run Artifacts**: Run metrics and summaries generated by `ingestion.orchestrator` are uploaded to GitHub Actions artifacts (`artifacts/run_summary.json`) with 30-day retention.

### 4.2 GitHub Repository Secrets Configuration
Navigate to **Settings** -> **Secrets and variables** -> **Actions** in your GitHub repository and add:

| Secret Name | Description | Example / Target |
|:---|:---|:---|
| `INGESTION_ENDPOINT_URL` | Production FastAPI base URL | `https://apix-backend-api.onrender.com` |
| `INGESTION_API_KEY` | Secret token matching backend config | `apix-prod-ingest-sec-9f8a7b6c5d4e3f2a1` |
| `AMADEUS_CLIENT_ID` | Amadeus Developer API Key | Generated from Amadeus for Developers |
| `AMADEUS_CLIENT_SECRET` | Amadeus Developer API Secret | Generated from Amadeus for Developers |

---

## 5. Environment Variables & Secrets Reference

### 5.1 Backend Service (Render)

| Variable | Required | Default / Example | Purpose |
|:---|:---:|:---|:---|
| `ENVIRONMENT` | Yes | `production` | Execution environment mode |
| `API_HOST` | Yes | `0.0.0.0` | ASGI bind host |
| `API_PORT` | Yes | `8000` (Render overrides with `$PORT`) | ASGI bind port |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity |
| `DATABASE_URL` | Yes | `postgresql://user:pass@host:5432/apix_db` | Connection string for database engine |
| `DATABASE_URL_SYNC` | Yes | `postgresql://user:pass@host:5432/apix_db` | Synchronous URL for Alembic migrations |
| `SECRET_KEY` | Yes | Cryptographic 64-char hex string | JWT token signing & session crypto |
| `INGESTION_API_KEY` | Yes | Cryptographic 64-char hex string | Shared secret for `/api/v1/ingestion/*` |
| `BACKEND_CORS_ORIGINS` | Yes | `https://apix.vercel.app,http://localhost:3000` | Allowed origins for browser CORS |
| `INDEX_BASE_PERIOD` | No | `2026-01` | Baseline reference period for Laspeyres/Fisher index |
| `INDEX_BASE_VALUE` | No | `100.0` | Initial baseline index value |
| `ANOMALY_ZSCORE_THRESHOLD` | No | `2.5` | Threshold for statistical anomaly flag |

### 5.2 Frontend Dashboard (Vercel)

| Variable | Required | Default / Example | Purpose |
|:---|:---:|:---|:---|
| `VITE_API_BASE_URL` | Yes | `https://apix-backend-api.onrender.com/api/v1` | Root endpoint for backend REST API |

### 5.3 Ingestion Runners (GitHub Actions)

| Variable / Secret | Required | Default / Example | Purpose |
|:---|:---:|:---|:---|
| `INGESTION_ENDPOINT_URL` | Yes | `https://apix-backend-api.onrender.com` | Target backend URL for batch delivery |
| `INGESTION_API_KEY` | Yes | Secret matching backend `INGESTION_API_KEY` | Auth header token `X-Ingestion-Key` |
| `AMADEUS_CLIENT_ID` | Yes | Amadeus API key | Amadeus GDS OAuth client ID |
| `AMADEUS_CLIENT_SECRET` | Yes | Amadeus API secret | Amadeus GDS OAuth client secret |
| `PLAYWRIGHT_HEADLESS` | No | `true` | Runs Chromium in headless sandbox |
| `SCRAPER_CONCURRENCY` | No | `4` | Parallel browser tab workers |
| `SCRAPER_TIMEOUT_MS` | No | `30000` | Navigation timeout per route |

---

## 6. Secret Rotation & Security Protocol

To ensure continuous compliance and zero downtime, secrets must follow a defined rotation cadence.

### 6.1 Rotation Schedule
- **Ingestion API Key (`INGESTION_API_KEY`)**: Rotated every 90 days.
- **Amadeus API Credentials**: Rotated every 180 days.
- **Backend Application Key (`SECRET_KEY`)**: Rotated every 180 days.
- **Database Credentials**: Rotated annually or immediately upon suspected compromise.

### 6.2 Zero-Downtime `INGESTION_API_KEY` Rotation Procedure
1. **Prepare Dual-Key Backend**:
   - The backend `verify_ingestion_key` dependency supports validating against primary or secondary keys:
     ```python
     valid_keys = [settings.INGESTION_API_KEY, os.getenv("INGESTION_API_KEY_SECONDARY", "")]
     if request_key not in valid_keys or not request_key:
         raise HTTPException(status_code=403, detail="Invalid ingestion key")
     ```
2. **Generate New Key**:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
3. **Step 1: Set Secondary Key on Render**:
   - Add `INGESTION_API_KEY_SECONDARY=<new_token>` in Render environment settings. Render redeploys seamlessly.
4. **Step 2: Update GitHub Repository Secret**:
   - Update `INGESTION_API_KEY` in GitHub Actions secrets with `<new_token>`.
5. **Step 3: Trigger Scraper Smoke Test**:
   - Run manual workflow dispatch to verify batch delivery with `<new_token>`.
6. **Step 4: Promote New Key on Render**:
   - Update Render `INGESTION_API_KEY=<new_token>` and remove `INGESTION_API_KEY_SECONDARY`.

### 6.3 Emergency Compromise Runbook
If credentials leak:
1. Immediately change `INGESTION_API_KEY` in Render environment variables. This instantly drops active rogue connections.
2. Update GitHub Secrets with the new key.
3. Check PostgreSQL query logs for abnormal write bursts during the compromise window:
   ```sql
   SELECT source, COUNT(*), MIN(scraped_at), MAX(scraped_at) 
   FROM raw_fares 
   WHERE created_at >= NOW() - INTERVAL '24 hours' 
   GROUP BY source;
   ```
4. Quarantine any anomalous batch records by batch ID.

---

## 7. Cold-Start Mitigation & Performance Tuning

### 7.1 Free/Starter Tier Spin-Down Handling
Render starter and free-tier web services enter sleep mode after 15 minutes of inactivity. When a new request arrives, a cold start delay of 30–50 seconds may occur.

#### Mitigation Architecture:
1. **Automated Ping Cron**:
   Configure a periodic lightweight HTTP ping every 10 minutes to `/health`.
   - **Using UptimeRobot / BetterStack**: Create a free HTTPS monitor targeting `https://apix-backend-api.onrender.com/health` with a 5-minute interval.
   - **Using GitHub Actions Scheduled Ping** (optional backup):
     ```yaml
     name: Keepalive Ping
     on:
       schedule:
         - cron: "*/14 * * * *"
     jobs:
       ping:
         runs-on: ubuntu-latest
         steps:
           - run: curl -sf https://apix-backend-api.onrender.com/health || true
     ```
2. **Pre-warmed Engine State**:
   During FastAPI startup lifespan, pre-load route weights and DGCA baseline coefficients into memory:
   ```python
   @asynccontextmanager
   async def lifespan(app: FastAPI):
       # Pre-load static weight dictionaries and route maps
       app.state.routes = load_dgca_routes()
       app.state.weights = load_traffic_weights()
       yield
   ```
3. **Database Connection Pool Tuning**:
   Configure SQLAlchemy connection pooling to handle reconnection gracefully:
   ```python
   engine = create_engine(
       DATABASE_URL,
       pool_size=10,
       max_overflow=20,
       pool_timeout=30,
       pool_recycle=1800,
       pool_pre_ping=True,  # Discards stale disconnected sockets
   )
   ```

---

## 8. Monitoring, Observability & Incident Response

### 8.1 Health & Diagnostics Endpoints
- `GET /health`: Liveness probe verifying process runtime and UTC clock.
- `GET /`: Service metadata, API documentation links, and operational status.
- `GET /api/v1/system/status`: Database connectivity, table row counts, latest ingestion timestamp, and quant index readiness.

### 8.2 Logging Standards
All backend and ingestion logs output formatted structured logs with ISO 8601 timestamps, log level, correlation IDs, and context:
```json
{
  "timestamp": "2026-09-24T02:15:30.124Z",
  "level": "INFO",
  "logger": "ingestion.orchestrator",
  "batch_id": "batch-a1b2c3d4",
  "source": "easemytrip",
  "records_ingested": 184,
  "elapsed_sec": 14.2
}
```

### 8.3 Alerting & Failure Thresholds
1. **Scraper Pipeline Failure**:
   - If GitHub Actions `scrape.yml` fails, GitHub sends automated email alerts to repository maintainers.
   - Run summary JSON records failure reasons per route (`artifacts/run_summary.json`).
2. **Missing Daily Ingestion (Dead-Man's Switch)**:
   - If no raw fare records are ingested for > 28 hours, an automated SQL alert triggers:
     ```sql
     SELECT CASE 
       WHEN MAX(scraped_at) < NOW() - INTERVAL '28 hours' THEN 'ALERT: Ingestion Stalled'
       ELSE 'OK'
     END AS ingestion_health 
     FROM raw_fares;
     ```
3. **Price Anomaly Spikes**:
   - Fares with Z-Score $> 3.5$ or deviation $> 200\%$ from the 30-day moving average are flagged as `is_anomaly = TRUE` and queued for manual verification before index weighting.

---

## 9. Local Containerized Deployment (Docker Compose)

The repository includes a complete local stack orchestration via `docker-compose.yml`.

### 9.1 Starting the Complete Stack
```bash
# Build and run backend, database, and frontend in background
docker compose up -d --build

# Inspect running containers
docker compose ps

# Tail unified service logs
docker compose logs -f
```

### 9.2 Exposed Services
- **FastAPI API & Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Frontend SPA Dashboard**: [http://localhost:3000](http://localhost:3000)
- **PostgreSQL Database**: `localhost:5432` (`user: apix_user`, `password: apix_password`, `database: apix_db`)

### 9.3 Executing Migrations & Seeding in Docker
```bash
# Run database migrations
docker compose exec backend alembic upgrade head

# Seed DGCA baseline routes and traffic weights
docker compose exec backend python -m backend.app.db.seed

# Trigger a sample ingestion run inside the container
docker compose exec backend python -m ingestion.orchestrator --mode synthetic
```

---
*Maintained by APIx Architecture & Engineering Operations (SIH 2026)*
