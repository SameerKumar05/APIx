# APIx Production Deployment Guide
**SIH 2026 Problem Statement 26056: Real-time Airfare Price Index for India**  
*Augmenting the Official Consumer Price Index (CPI) Transportation Sub-Index*

---

## Table of Contents
1. [Architecture & Deployment Topology](#1-architecture--deployment-topology)
2. [FastAPI Backend Deployment on Render](#2-fastapi-backend-deployment-on-render)
3. [React Dashboard Deployment on Vercel](#3-react-dashboard-deployment-on-vercel)
4. [Distributed Scraper Automation on GitHub Actions](#4-distributed-scraper-automation-on-github-actions)
5. [Production Proxy Pool & Scraping Infrastructure](#5-production-proxy-pool--scraping-infrastructure)
6. [Audit Archive & Regulatory Retention (DGCA Rule 135)](#6-audit-archive--regulatory-retention-dgca-rule-135)
7. [Nginx Reverse Proxy & WebSocket Streaming Gateway](#7-nginx-reverse-proxy--websocket-streaming-gateway)
8. [Environment Variables & Secrets Reference](#8-environment-variables--secrets-reference)
9. [Secret Rotation & Security Protocol](#9-secret-rotation--security-protocol)
10. [Cold-Start Mitigation & Performance Tuning](#10-cold-start-mitigation--performance-tuning)
11. [Monitoring, Observability & Incident Response](#11-monitoring-observability--incident-response)
12. [Local Containerized Deployment (Docker Compose)](#12-local-containerized-deployment-docker-compose)

---

## 1. Architecture & Deployment Topology

The APIx platform is designed as a cloud-native, decoupled system distributed across resilient managed providers to achieve high availability, cost efficiency, and zero maintenance overhead:

```mermaid
flowchart TD
    subgraph Ingestion["GitHub Actions Runner (Scheduled Cron 02:00 UTC / 07:30 IST)"]
        Scraper["Playwright Chromium Scrapers<br/>(EaseMyTrip, MakeMyTrip, SpiceJet)"]
        GDS["Amadeus GDS Flight Offers Client<br/>(Tier 2 Fallback)"]
        Synthetic["DGCA Deterministic Synthetic Generator<br/>(Tier 3 Fallback)"]
        Orch["Ingestion Orchestrator<br/>(40 Discrete Slots: 10 Routes x 4 Horizons)"]
        Scraper --> Orch
        GDS --> Orch
        Synthetic --> Orch
    end

    subgraph Backend["Render Web Service (FastAPI ASGI / Uvicorn 4 Workers)"]
        API["REST & WebSocket API Gateway<br/>(/api/v1)"]
        Dedup["Streaming Deduplication Engine<br/>(SHA-256 Content Hashing)"]
        Quant["Quant Econometric & Index Engine<br/>(Fisher, Laspeyres, Paasche, Anomaly Z-Score)"]
        API --> Dedup
        Dedup --> Quant
    end

    subgraph Database["Managed Database Infrastructure"]
        DB[("PostgreSQL 16 / TimescaleDB<br/>16 Tables on Fresh Startup (14 Domain + 2 Queue)")]
    end

    subgraph Edge["Vercel Edge Network"]
        UI["React 19 SPA + Recharts Analytics Dashboard<br/>(Vite + Tailwind CSS)"]
    end

    Orch -->|"HTTPS POST /api/v1/ingestion/batch<br/>Header: X-Ingestion-Key"| API
    Quant -->|"Persist Fares, Indices & Spikes"| DB
    DB -.->|"Query Baselines & Traffic Weights"| Quant
    UI -->|"HTTPS REST Queries"| API
    UI -.->|"WSS /api/v1/stream/fares<br/>(Live Ticker Broadcast)"| API
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
    - **Pre-Deploy Command** (executes schema initialization via `init_db()` calling `create_all`, then seeds DGCA baseline routes, traffic weights, and carrier market shares prior to routing live traffic. Fresh `init_db()` on an empty SQLite file creates 16 tables including `crawler_jobs` and `worker_heartbeats`; `create_all` is not a migration system; evidence: `/tmp/opencode/apix-verify/startup-empty.db`):
     ```bash
     python -m backend.app.db.seed
     ```
   - **Start Command**:
     ```bash
     uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT --workers 4 --proxy-headers --forwarded-allow-ips='*'
     ```
   - **Plan**: `Starter` ($7/mo) or `Standard` for persistent multi-core worker processing.

### 2.2 Health Check & Zero-Downtime Deploys
- **Health Check Path**: `/health`
- Render periodically sends `GET /health` requests. When ready the response returns `200 OK` with JSON payload:
  ```json
  {
    "status": "healthy",
    "service": "apix-backend-api",
    "version": "1.0.0",
    "environment": "production"
  }
  ```
- Unhealthy states return 503: `Database unavailable` on unreachable DB or reachable-but-uninitialized schema, and the trigger path additionally returns 503 `No active crawler worker available` without a fresh `worker_heartbeats` lease. Trigger returns 401 without a key and 202 `QUEUED` only after a committed `crawler_jobs` row plus fresh heartbeat (evidence: `.omo/ulw-research/20260925-180203/evidence/api-8015-final.json`, `evidence/trigger-liveness-8014.json`, `evidence/trigger-idempotency-8014.json`, `tests/test_runtime_boundaries.py:93-106`).
- If the pre-deploy migration or health check fails, Render retains the existing container and aborts deployment without downtime.

### 2.3 Managed PostgreSQL / TimescaleDB Provisioning
1. Click **New +** -> **PostgreSQL** on Render (or use an external TimescaleDB provider such as Timescale Cloud or Aiven).
2. Configure database name: `apix_db`, user: `apix_user`.
3. Copy the **Internal Database URL** for services in the same Render region:
   - `postgres://apix_user:<password>@dpg-<id>-a/apix_db`
4. Set `DATABASE_URL` using standard synchronous `postgresql://` URI (e.g. `postgresql://apix_user:<password>@.../apix_db`) matching SQLAlchemy 2.0 `create_engine()` connection requirements. Set `DATABASE_URL_SYNC` to the same URI.

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

## 5. Production Proxy Pool & Scraping Infrastructure

### 5.1 Architecture & Multi-Source Routing
The Tier 1 live multi-source scraping engine (targeting EaseMyTrip, MakeMyTrip, and SpiceJet) operates through an adaptive, self-healing proxy pool. This insulates scrapers from IP-based rate limiting, cloud provider CIDR blocks, and Cloudflare/Akamai bot-management systems while maintaining full compliance with DGCA surveillance mandates.

```mermaid
flowchart LR
    Scraper["Scraper Worker"] --> Selector["EWMA Proxy Selector"]
    Selector -->|"Score-Weighted Route"| Pool[("Active Proxy Pool")]
    Pool --> Target["Domestic Travel Portals"]
    Target -->|"HTTP 200 OK"| Feedback["Latency Scorer"]
    Target -->|"HTTP 429 / 403 / Timeout"| Blacklist["Quarantine Manager"]
    Feedback -->|"Update EWMA"| Pool
    Blacklist -->|"300s Cooldown"| Pool
```

### 5.2 EWMA Latency Scoring Engine
To ensure requests are dispatched through the lowest-latency, highest-reliability proxies, the proxy manager dynamically maintains an Exponentially Weighted Moving Average (EWMA) score for each node $i$:

$$\text{Score}_i^{(t)} = \alpha \cdot \text{Latency}_i^{(t)} + (1 - \alpha) \cdot \text{Score}_i^{(t-1)} + \text{Penalty}_i$$

Where:
- $\alpha = 0.3$: Smoothing parameter giving 30% weight to instantaneous latency and 70% to historical performance.
- $\text{Latency}_i^{(t)}$: Measured round-trip response time in milliseconds from TCP connect to first byte received (TTFB).
- $\text{Penalty}_i = 1000\,\text{ms}$: Applied on soft errors (HTTP 429 Too Many Requests, connection timeout, non-200 responses).
- Node Selection: Proxies with lower composite scores are prioritized in round-robin and weighted selection queues.

### 5.3 Dynamic Blacklisting & Cooldown Lifecycle
1. **Quarantine Threshold**: A proxy that records 3 consecutive connection failures, HTTP 403 Forbidden, or HTTP 429 Too Many Requests is automatically quarantined into the blacklisted pool.
2. **Cooldown Window**: Quarantined proxies remain quarantined for a configurable 300-second (5-minute) cooldown window (`PROXY_COOLDOWN_SEC=300`), after which they receive a single low-impact health-check probe.
3. **Emergency Unblacklisting Fallback**: To prevent catastrophic scraping pipeline deadlocks during network volatility, if the available active proxy count drops below a minimum threshold ($N_{\text{active}} < 3$), the orchestrator executes an emergency flush—re-enlisting the oldest quarantined proxies with an elevated latency penalty.

### 5.4 Anti-Bot Jitter & Behavioral Masking
- **Request Jitter**: Request intervals incorporate an intentional random uniform jitter:
  $$\Delta t \sim \mathcal{U}(5.0\,\text{s},\, 15.0\,\text{s})$$
  between consecutive calls to the same domestic travel portal.
- **Fingerprint Randomization**: Headless Chromium instances employ Playwright stealth configurations, randomized viewport dimensions ($1920\times1080$, $1440\times900$, $1366\times768$), and rotating modern User-Agent strings matching recent Chrome and Edge releases on Linux and Windows.

---

## 6. Audit Archive & Regulatory Retention (DGCA Rule 135)

### 6.1 Statutory Authority & Regulatory Mandate
Under the Aircraft Rules 1937, Rule 135(1-3), the Directorate General of Civil Aviation (DGCA) Tariff Monitoring Unit (TMU) is empowered to monitor airline fare tariffs to prevent predatory pricing, dynamic surge exploitation during natural calamities, and anti-competitive cartelization. Airfare data collected by APIx serves as official empirical evidence for regulatory investigations, requiring tamper-evident auditability.

### 6.2 3-Tier Storage Hierarchy

| Storage Tier | Storage Medium | Retention Period | Data Scope & Format | Purpose |
|:---|:---|:---:|:---|:---|
| **Tier 1 (Hot)** | PostgreSQL / TimescaleDB | 30 Days (raw fares) / Permanent (indices) | Relational SQL schema, 16 tables on fresh startup (14 domain + `crawler_jobs` + `worker_heartbeats`) | Live dashboard queries, quant index computation, anomaly detection |
| **Tier 2 (Warm)** | GitHub Actions Artifacts & S3/R2 Bucket | 30 Days (GHA) / 90 Days (Staging) | Compressed JSONL (`run_summary_YYYY-MM-DD.json.gz`), 40 discrete slots | Telemetry audit, provider SLA tracking, route-level fallback analysis |
| **Tier 3 (Cold / WORM)** | S3 Glacier Deep Archive | 7 Years (2,555 Days statutory) | Encrypted Apache Parquet with Write-Once-Read-Many (WORM) Object Lock | Court-admissible tariff compliance audits, MoSPI macroeconomic verification |

### 6.3 Tamper-Evident Cryptographic Provenance
Each ingestion batch is stamped with a cryptographic SHA-256 digest:

$$\text{BatchDigest} = \text{SHA256}\left(\sum_{k=1}^M \text{SHA256}(\text{fare\_id}_k \mathbin{\Vert} \text{price}_k \mathbin{\Vert} \text{carrier}_k \mathbin{\Vert} \text{timestamp}_k)\right)$$

Digests are logged in the `ingestion_batches` audit table, enabling cryptographic proof of non-repudiation and chain of custody for regulatory inspection.

---

## 7. Nginx Reverse Proxy & WebSocket Streaming Gateway

### 7.1 Real-Time Streaming Protocol Requirement
The APIx frontend dashboard consumes high-frequency fare observations and price updates via WebSockets at `/api/v1/stream/fares` (RFC 6455). Standard HTTP reverse proxies assume short-lived request/response transactions and will terminate or buffer persistent connections unless configured with explicit protocol upgrade handshakes.

### 7.2 Production Nginx Configuration
The production Alpine Nginx web server (`Dockerfile` Stage 3) is configured as follows:

```nginx
server {
    listen 80;
    server_name localhost;

    # Frontend SPA static distribution
    location / {
        root /usr/share/nginx/html;
        index index.html index.htm;
        try_files $uri $uri/ /index.html;
    }

    # Backend REST & WebSocket reverse proxy
    location /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Extended timeouts for persistent WebSocket streaming
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_buffering off;
    }

    error_page 500 502 503 504 /50x.html;
    location = /50x.html {
        root /usr/share/nginx/html;
    }
}
```

### 7.3 Technical Directives Breakdown
- `proxy_http_version 1.1`: Crucial because Nginx defaults to HTTP/1.0 for upstream connections, which strips hop-by-hop headers required for WebSocket handshakes.
- `proxy_set_header Upgrade $http_upgrade`: Passes the client's `Upgrade: websocket` header to the ASGI backend (FastAPI/Uvicorn).
- `proxy_set_header Connection "upgrade"`: Signals the backend that the connection is transitioning from HTTP/1.1 to full-duplex WebSocket framing.
- `proxy_read_timeout 86400s` & `proxy_send_timeout 86400s`: Extends timeout from Nginx's default 60 seconds to 24 hours, ensuring idle keepalive tickers or quiet night hours do not cause unintended disconnections.
- `proxy_buffering off`: Ensures WebSocket frames and streaming SSE responses are transmitted immediately with zero intermediary buffering latency.

---

## 8. Environment Variables & Secrets Reference

### 8.1 Backend Service (Render)

CORS: `BACKEND_CORS_ORIGINS` defaults to `http://localhost:3000`, `http://localhost:5173`, `http://127.0.0.1:3000`, `http://127.0.0.1:5173` with credentials; evil origin `https://evil.example` is not reflected, evil preflight returns 400, and wildcard `*` raises ValidationError (evidence: `evidence/cors-and-trigger-8014.json`, `backend/app/core/config.py`). No deployment credentials are invented here.

| Variable | Required | Default / Example | Purpose |
|:---|:---:|:---|:---|
| `ENVIRONMENT` | Yes | `production` | Execution environment mode (`development` \| `production` \| `testing`) |
| `API_HOST` | Yes | `0.0.0.0` | ASGI bind host |
| `API_PORT` | Yes | `8000` (Render overrides with `$PORT`) | ASGI bind port |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG` \| `INFO` \| `WARNING` \| `ERROR`) |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://user:pass@host:5432/apix_db` | Async connection string for FastAPI backend engine |
| `DATABASE_URL_SYNC` | Yes | `postgresql://user:pass@host:5432/apix_db` | Synchronous URL for Alembic migrations & seed scripts |
| `SECRET_KEY` | Yes | Cryptographic 64-char hex string | JWT token signing & session crypto |
| `INGESTION_API_KEY` | Yes | `apix-prod-ingest-sec-9f8a7b6c5d4e3f2a1` | Shared secret for `/api/v1/ingestion/*` (`X-Ingestion-Key`) |
| `BACKEND_CORS_ORIGINS` | Yes | `https://apix.vercel.app,http://localhost:3000,http://localhost:5173` | Allowed origins for browser CORS |
| `INDEX_BASE_PERIOD` | No | `2026-01` | Baseline reference period for Laspeyres/Fisher index |
| `INDEX_BASE_VALUE` | No | `100.0` | Initial baseline index value |
| `ANOMALY_ZSCORE_THRESHOLD` | No | `2.5` | Threshold for statistical anomaly flag |
| `PROXY_ROTATION_STRATEGY` | No | `ewma_latency` | Strategy for proxy pool node selection |
| `PROXY_EWMA_ALPHA` | No | `0.3` | EWMA smoothing parameter |
| `PROXY_FAILURE_THRESHOLD` | No | `3` | Consecutive failures before quarantine |
| `PROXY_COOLDOWN_SEC` | No | `300` | Cooldown period before re-probing |
| `AUDIT_ARCHIVE_STORAGE` | No | `local` (`s3` \| `gcs` \| `r2`) | Target storage provider for audit archives |
| `AUDIT_RETENTION_DAYS` | No | `2555` | Statutory retention period (7 years) |

### 8.2 Frontend Dashboard (Vercel)

| Variable | Required | Default / Example | Purpose |
|:---|:---:|:---|:---|
| `VITE_API_BASE_URL` | Yes | `https://apix-backend-api.onrender.com/api/v1` | Root endpoint for backend REST API |

### 8.3 Ingestion Runners (GitHub Actions)

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

## 9. Secret Rotation & Security Protocol

To ensure continuous compliance and zero downtime, secrets must follow a defined rotation cadence.

### 9.1 Rotation Schedule
- **Ingestion API Key (`INGESTION_API_KEY`)**: Rotated every 90 days.
- **Amadeus API Credentials**: Rotated every 180 days.
- **Backend Application Key (`SECRET_KEY`)**: Rotated every 180 days.
- **Database Credentials**: Rotated annually or immediately upon suspected compromise.

### 9.2 Zero-Downtime `INGESTION_API_KEY` Rotation Procedure
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

### 9.3 Emergency Compromise Runbook
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

## 10. Cold-Start Mitigation & Performance Tuning

### 10.1 Free/Starter Tier Spin-Down Handling
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

## 11. Monitoring, Observability & Incident Response

### 11.1 Health & Diagnostics Endpoints
- `GET /health`: Liveness probe verifying process runtime and UTC clock.
- `GET /`: Service metadata, API documentation links, and operational status.
- `GET /api/v1/system/status`: Database connectivity, table row counts, latest ingestion timestamp, and quant index readiness.

### 11.2 Logging Standards
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

### 11.3 Alerting & Failure Thresholds
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

## 12. Local Containerized Deployment (Docker Compose)

The repository includes a complete local stack orchestration via `docker-compose.yml`.

### 12.1 Starting the Complete Stack
```bash
# Build and run backend, database, and frontend in background
docker compose up -d --build

# Inspect running containers
docker compose ps

# Tail unified service logs
docker compose logs -f
```

### 12.2 Exposed Services
- **FastAPI API & Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Frontend SPA Dashboard**: [http://localhost:3000](http://localhost:3000)
- **PostgreSQL Database**: `localhost:5432` (`user: apix_user`, `password: apix_password`, `database: apix_db`)

### 12.3 Executing Migrations & Seeding in Docker
```bash
# Run database migrations
docker compose exec backend alembic upgrade head

# Seed DGCA baseline routes and traffic weights
docker compose exec backend python -m backend.app.db.seed

# Trigger a sample ingestion run inside the container
docker compose exec backend python -m ingestion.orchestrator --mode synthetic
```

### 12.4 Crawler Worker Service
The Compose `apix-worker` service runs `command: ["python", "-m", "ingestion.worker"]` (`docker-compose.yml`) and consumes the durable `crawler_jobs` queue with `worker_heartbeats` leases (`ingestion/worker.py`). Run standalone as `python -m ingestion.worker`. The API trigger requires this worker: without a fresh heartbeat it returns 503, and 202 `QUEUED` follows a committed job row (evidence: `evidence/trigger-liveness-8014.json`, `evidence/trigger-idempotency-8014.json`). Live OTA execution through the worker is unverified (synthetic-mode run only). Retention cleanup uses `synchronize_session="fetch"` (evidence: `.debug-journal.md` 2026-09-25T14:40Z). Current isolated suite is 226 passed with one Starlette TestClient deprecation warning on `/tmp/opencode/apix-verify/final3.db`; older counts are historical. **Live scraping: what is real and what is blocked.** Genuine data does arrive. Playwright captures `https://www.spicejet.com/api/v3/search/availability` (HTTP 200, 17777 bytes, `data.trips[]`) and flight identity extracts unambiguously (`SG 815`, DEL 09:50 to BOM 12:25). Two blockers stop a live fare from being persisted. First, client-side bot defence: `makemytrip.com` resolves and serves pages from this host, but Akamai rejects the request. Measured three ways: stock `curl` gets `403`, Playwright's bundled Chromium is reset with `net::ERR_HTTP2_PROTOCOL_ERROR`, and driving the distro build at `/usr/bin/chromium` returned HTTP 200 with 500864 bytes of real page content. The scraper now prefers a system Chromium via `resolve_launch_kwargs` with a `playwright_browser_executable` override, but that unblock is not durable: retested under repetition the same client returned 0 of 3 successes, so sustained probing tips the egress IP into a temporary Akamai throttle. Separately, `api.spicejet.com` is not blocked at all, it is NXDOMAIN on both 1.1.1.1 and 8.8.8.8, meaning the hostname does not exist; no provider change can make a nonexistent hostname resolve. Second, SpiceJet publishes no structured fare field; the price is embedded in an opaque key decoding to fragments such as `USAV~5511~~0~665~` and `X!0:48004:1004:854:5994:2364:1524:895:280`, and the mapping is undocumented, so no fare was guessed. Separately, a critical provenance defect was found and fixed: `amadeus.py` labelled generated mock records `is_synthetic=False`, so a live run would have persisted invented fares as real and earned a false LIVE badge. Provenance now follows the payload, and `scripts/audit_provenance.py` fails closed if any row claims to be live without corroborating telemetry, a scraping run, proxy evidence and scrape-time diversity (evidence: `evidence/live-ingestion-verification.json`, `evidence/provenance-audit.json`). Preserved limitations include sparse FKs, role-separation and false-success residuals, unknown-route 200 behavior, and duplicate WebSocket mounts. **CRITICAL, partially fixed: `GET /api/v1/indices/routes` served fabricated airfares as measured data.** **Fixed:** the swallowed `except Exception: pass` that returned the entire hardcoded seed list on any failure is replaced by a 503 `Database unavailable`, and a reachable database with no active routes now reports zero coverage instead of seven invented corridors. Verified at runtime on a current-source instance and locked by two regression tests (`test_routes_overview_does_not_fabricate_when_database_is_unavailable`, `test_routes_overview_reports_no_coverage_instead_of_seeded_corridors`). **Still open:** a route that has no `RouteDailyIndex` is still replaced by its hardcoded `DOMESTIC_ROUTES_SEED` entry or an invented `avg_fare_inr=5000.0` default, and `/api/v1/indices/routes/{route_code}/history` applies the same seed fallback including an invented base index of 108.0. On a sparse database 7 of 7 served routes matched the hardcoded literals exactly, so the whole response was invented. That part needs a product decision, because `RouteOverviewItem` requires `current_index` and `avg_fare_inr` (evidence: `evidence/indices-routes-fabricated-fares.json`). The frontend was re-measured directly against the frozen production build (24 of 24 tab renders, zero console errors, focus contrast minimum 17.93:1), which is first-party measurement rather than an independent reviewer pass, so no independent visual PASS or Lighthouse result is claimed.

---
*Maintained by APIx Architecture & Engineering Operations (SIH 2026)*

## Browser binary for OTA scraping

Tier 1 scrapers drive Chromium through Playwright. Akamai fingerprints the HTTP/2 frame and resets Playwright's bundled build with `net::ERR_HTTP2_PROTOCOL_ERROR` while accepting the distro build of the same browser. `resolve_launch_kwargs` in `ingestion/crawlers/makemytrip.py` therefore prefers an executable system Chromium, checking `/usr/bin/chromium`, `/usr/bin/chromium-browser`, `/usr/bin/google-chrome` and `/usr/bin/google-chrome-stable` in order. Set `INGESTION_PLAYWRIGHT_BROWSER_EXECUTABLE` to pin a specific binary. When no candidate is executable the scraper falls back to the bundled build.

This is a mitigation, not a guarantee. The upstream edge can still throttle the egress IP, and a page that loads without yielding a fare XHR falls through to the synthetic tier and is labelled `is_synthetic=True`. Never treat a successful page load as evidence of a live fare.
