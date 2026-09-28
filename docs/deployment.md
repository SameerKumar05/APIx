# APIx Production Deployment Guide
**SIH 2026 Problem Statement 26056: Real-time Airfare Price Index for India**  
*Augmenting the Official Consumer Price Index (CPI) Transportation Sub-Index*

---

## Table of Contents
1. [Architecture & Deployment Topology](#1-architecture--deployment-topology)
2. [FastAPI Backend Deployment on Google Compute Engine](#2-fastapi-backend-deployment-on-google-compute-engine)
3. [React Dashboard Deployment on Vercel](#3-react-dashboard-deployment-on-vercel)
4. [Distributed Scraper Automation on GitHub Actions](#4-distributed-scraper-automation-on-github-actions)
5. [Production Proxy Pool & Scraping Infrastructure](#5-production-proxy-pool--scraping-infrastructure)
6. [Audit Archive & Regulatory Retention (DGCA Rule 135)](#6-audit-archive--regulatory-retention-dgca-rule-135)
7. [Caddy Reverse Proxy & WebSocket Streaming Gateway](#7-caddy-reverse-proxy--websocket-streaming-gateway)
8. [Environment Variables & Secrets Reference](#8-environment-variables--secrets-reference)
9. [Secret Rotation & Security Protocol](#9-secret-rotation--security-protocol)
10. [Availability & Performance Tuning](#10-availability--performance-tuning)
11. [Monitoring, Observability & Incident Response](#11-monitoring-observability--incident-response)
12. [Local Containerized Deployment (Docker Compose)](#12-local-containerized-deployment-docker-compose)

---

## 1. Architecture & Deployment Topology

> **Live deployment (2026-09-26).** Frontend: `https://apix-dashboard-navy.vercel.app`
> (Vercel) · API: `https://api.adityaai.dev` (FastAPI on a Google Compute Engine VM
> behind Caddy). There is no Render deployment and no `onrender.com` URL anywhere in
> this system. This guide explains the concepts: architecture, prerequisites,
> schema/migrations, operational behaviour. The literal command sequence that produced
> the live system is the runbook [`deployment_run_2026-09-26.md`](deployment_run_2026-09-26.md);
> the auto-deploy wiring is [`ci_deploy.md`](ci_deploy.md) (backend) and
> [`ci_deploy_frontend.md`](ci_deploy_frontend.md) (frontend). One source of truth per
> concern: read the runbook for commands, this guide for understanding.
>
> **Data honesty.** The dashboard is live; the fare data is mixed: 23 live SpiceJet
> rows (2026-09-28, provenance-audited) plus synthetic fallback rows for the portals
> that fail closed. Route and carrier weights are modelled, not published
> DGCA figures. See the runbook §9 and `docs/data_provenance.md`.

The APIx platform is a decoupled system: ingestion on ephemeral runners, the API on a
single GCE VM behind Caddy, the dashboard on the Vercel edge network:

```mermaid
flowchart TD
    subgraph Ingestion["GitHub Actions Runner (Scheduled Cron 02:00 UTC / 07:30 IST)"]
        Scraper["Playwright Chromium Scrapers<br/>(EaseMyTrip, MakeMyTrip, SpiceJet)"]
        GDS["Amadeus GDS Flight Offers Client<br/>(Tier 2 Fallback)"]
        Synthetic["DGCA Deterministic Synthetic Generator<br/>(Tier 3 Fallback)"]
        Orch["Ingestion Orchestrator<br/>(50 Discrete Slots: 10 Routes x 5 Horizons)"]
        Scraper --> Orch
        GDS --> Orch
        Synthetic --> Orch
    end

    subgraph Backend["GCE VM (FastAPI ASGI / Uvicorn behind Caddy)"]
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

## 2. FastAPI Backend Deployment on Google Compute Engine

The production backend is a containerised FastAPI service on a shared Google Compute
Engine VM (`/opt/apix`, compose project `apix-deploy`). It listens on the host loopback
only (`127.0.0.1:8000`); Caddy terminates TLS for `https://api.adityaai.dev` and
reverse-proxies to it. Postgres runs in the same compose project with no host port
published, so it is unreachable from the internet. The VM is shared with unrelated
services, so every `docker compose` invocation is scoped with `-p apix-deploy` and
names only the services it touches, never an unscoped `down`.

### 2.1 Deploy path: CI-gated auto-deploy (primary)

Pushes to `main` deploy automatically. `.github/workflows/deploy-backend.yml` fires on
`workflow_run` completion of the `APIx CI / Quality Gate` workflow and proceeds only
when CI succeeded on `main` in this repository; `workflow_dispatch` allows a manual
re-deploy. The workflow rsyncs the repo to `/opt/apix` (excluding the VM's gitignored
`.env`, which holds the live secrets), builds the backend image, runs
`alembic upgrade head` in a one-off container while the old backend still serves,
recreates the backend, then polls `http://127.0.0.1:8000/health` until it returns 200.
The full wiring is documented in [`ci_deploy.md`](ci_deploy.md). So "push to main to
deploy" is accurate; a manual `pip install` on a server is not the production path.
the `pip`/`uvicorn` commands in §12 are the local-development path.

### 2.2 Health Check & Rollout Gating
- **Health Check Path**: `/health`
- The deploy workflow polls `GET /health` after recreating the backend, and any monitor
  can do the same against `https://api.adityaai.dev/health`. When ready the response returns `200 OK` with JSON payload:
  ```json
  {
    "status": "healthy",
    "service": "apix-backend-api",
    "version": "1.0.0",
    "environment": "production"
  }
  ```
  (plus a `timestamp`; evidence: `backend/app/main.py:175-190`).
- Unhealthy states return 503: `Database unavailable` on unreachable DB or reachable-but-uninitialized schema, and the trigger path returns 503 `No active crawler worker available` without a fresh `worker_heartbeats` lease. Trigger returns 401 without a key and 202 `QUEUED` only after a committed `crawler_jobs` row plus fresh heartbeat (evidence: `.omo/ulw-research/20260925-180203/evidence/api-8015-final.json`, `evidence/trigger-liveness-8014.json`, `evidence/trigger-idempotency-8014.json`, `tests/test_runtime_boundaries.py:93-106`).
- If the migration or the post-restart health gate fails, the deploy workflow fails loudly; the old container keeps serving until `up -d backend` recreates it, and data survives in named volumes regardless.

### 2.3 PostgreSQL / TimescaleDB in Compose
1. Postgres runs as the `db` service of the compose project (TimescaleDB image, pinned to `timescale/timescaledb:2.14.2-pg16` in `docker-compose.deploy.yml`), with data in a named volume. On the VM it publishes no host port.
2. Database name, user and password come from `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` (defaults `apix_user` / `apix_db`).
3. Set `DATABASE_URL` to a synchronous `postgresql+psycopg2://` URI (e.g. `postgresql+psycopg2://apix_user:<password>@db:5432/apix_db`), matching the sync `create_engine()` in `backend/app/db/session.py:28`. `DATABASE_URL_SYNC` is read by nothing. `migrations/env.py` resolves `DATABASE_URL` only, so it is a no-op placeholder; see §8.1.

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
`frontend/vercel.json` contains only the SPA rewrite, no `headers` cache block, no
`cleanUrls`, no `cname`:
```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "rewrites": [
    {
      "source": "/(.*)",
      "destination": "/index.html"
    }
  ]
}
```
Vercel's Vite preset serves the static bundle but does not add SPA history fallback on
its own, so without this rewrite a hard refresh (or a directly opened link) to any of
the dashboard's 8 tabs would return 404 instead of loading `index.html` and letting
the client-side router take over.

### 3.3 Frontend Environment Variables
In **Project Settings** -> **Environment Variables**:
- `VITE_API_BASE_URL`: `https://api.adityaai.dev` (Production, bare origin only; `frontend/src/services/apiClient.ts:35-46` appends `/api/v1` when the value lacks that suffix)
- Configure preview environments to point to staging or preview backend URLs.

---

## 4. Distributed Scraper Automation on GitHub Actions

Scraping runs on ephemeral GitHub Actions runners to provide isolated, burstable browser execution without consuming persistent server memory.

### 4.1 Workflow Overview (`.github/workflows/scrape.yml`)
- **Schedule**: Every day at `02:00 UTC` (`07:30 IST`).
- **Command**: `python -m ingestion.scheduler --run-once`. The env var is `SCRAPER_SOURCE` (singular). `all` is mapped to `multi_source`. The old `SCRAPER_SOURCES` name was ignored.
- **Once per UTC day**: a completion marker under `artifacts/scheduler` is cached by date. A second run the same day exits without scraping unless `force` is true.
- **Manual Trigger**: `workflow_dispatch` with `mode` and a single `sources` value.
- **Playwright Caching**: Caches `~/.cache/ms-playwright` keyed by `requirements.txt` hash.
- **Do not also run the Compose scheduler** against the same database. That is a second sweep. Pick one.

### 4.2 GitHub Repository Secrets Configuration
Navigate to **Settings** -> **Secrets and variables** -> **Actions** in your GitHub repository and add:

| Secret Name | Description | Example / Target |
|:---|:---|:---|
| `INGESTION_ENDPOINT_URL` | Production FastAPI base URL | `https://api.adityaai.dev` |
| `INGESTION_API_KEY` | Secret token matching backend config | `apix-prod-ingest-sec-9f8a7b6c5d4e3f2a1` |
| `AMADEUS_CLIENT_ID` | Amadeus Developer API Key | Generated from Amadeus for Developers |
| `AMADEUS_CLIENT_SECRET` | Amadeus Developer API Secret | Generated from Amadeus for Developers |

### 4.3 Turning daily extraction on

Two deployments run the schedule. Use one.

**Compose (always on).** `docker compose up -d` starts `apix-scheduler`. It holds a flock in `/var/lib/apix/scheduler` and, at `SCHEDULER_CRON` (default `0 2 * * *` UTC), enqueues one job per route-window. `apix-worker` claims those jobs. A second scheduler process exits because the flock is held. A misfired slot does not enqueue twice: the slot marker is an exclusive create for that UTC day.

```bash
docker compose up -d
# confirm the next fire without scraping
docker compose run --rm --no-deps scheduler python -m ingestion.scheduler --print-next --cron "0 2 * * *"
```

`INGESTION_MODE` defaults to `synthetic`. Set `INGESTION_MODE=live` and `SCRAPER_SOURCE` (`spicejet`, `easemytrip`, `makemytrip`, or `multi_source`) to extract from portals. The worker must be up; enqueue does nothing until it claims.

**GitHub Actions (ephemeral).** The workflow above is the other switch. It scrapes in the runner and posts to `INGESTION_ENDPOINT_URL`. It does not share the Compose flock.

**Session reuse** is off unless `SCRAPER_SESSION_REUSE=1`. Jars live in `SCRAPER_SESSION_DIR`, expire after `SCRAPER_SESSION_MAX_AGE_SECONDS` (43200), and are refused above `SCRAPER_SESSION_MAX_BYTES` (262144). Reuse does not skip `robots_gate` or the rate limiter. A challenge page discards the jar.

**CAPTCHA.** A challenge page is `blocked_by_captcha` on the scrape result (`metadata.outcome`), telemetry status `CAPTCHA`, and `error_details` `blocked_by_captcha`. No records are ingested, including synthetic fallback. The process backs off that origin for 900 seconds and does not solve the challenge.

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
3. **Emergency unblacklisting fallback**: To prevent scraping pipeline deadlocks during network volatility, if the available active proxy count drops below a minimum threshold ($N_{\text{active}} < 3$), the orchestrator executes an emergency flush that re-enlists the oldest quarantined proxies with an elevated latency penalty.

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
| **Tier 2 (Warm)** | GitHub Actions Artifacts & S3/R2 Bucket | 30 Days (GHA) / 90 Days (Staging) | Compressed JSONL (`run_summary_YYYY-MM-DD.json.gz`), 50 discrete slots | Telemetry audit, provider SLA tracking, route-level fallback analysis |
| **Tier 3 (Cold / WORM)** | S3 Glacier Deep Archive | 7 Years (2,555 Days statutory) | Encrypted Apache Parquet with Write-Once-Read-Many (WORM) Object Lock | Court-admissible tariff compliance audits, MoSPI macroeconomic verification |

### 6.3 Tamper-Evident Cryptographic Provenance
Each ingestion batch is stamped with a cryptographic SHA-256 digest:

$$\text{BatchDigest} = \text{SHA256}\left(\sum_{k=1}^M \text{SHA256}(\text{fare\_id}_k \mathbin{\Vert} \text{price}_k \mathbin{\Vert} \text{carrier}_k \mathbin{\Vert} \text{timestamp}_k)\right)$$

Digests are logged in the `ingestion_batches` audit table, enabling cryptographic proof of non-repudiation and chain of custody for regulatory inspection. (Note: no `ingestion_batches` table exists in `backend/app/models/` as of this writing, so this digest logging is a design prescription, not verified behaviour.)

---

## 7. Caddy Reverse Proxy & WebSocket Streaming Gateway

### 7.1 Real-Time Streaming Protocol Requirement
The APIx frontend dashboard consumes high-frequency fare observations and price updates via WebSockets at `/api/v1/stream/fares` (RFC 6455). Standard HTTP reverse proxies assume short-lived request/response transactions and will terminate or buffer persistent connections unless configured with explicit protocol upgrade handshakes.

### 7.2 Production edge: Caddy on the VM
Public traffic terminates at Caddy on the GCE VM, which holds the Let's Encrypt certificate for `api.adityaai.dev` and reverse-proxies to the backend on the host loopback (`127.0.0.1:8000`); Postgres has no host binding. The Caddyfile lives on the VM at `/opt/caddy/Caddyfile`. It is not in this repo, and Caddy is shared with unrelated vhosts, so its config is applied with `caddy validate` then `caddy reload`, never a restart. Full detail, including the rollback procedure, is in the runbook (`deployment_run_2026-09-26.md` §§1, 10), and the loopback binding plus pinned DB image are in `docker-compose.deploy.yml:41-46`.

### 7.3 Compose-local Nginx frontend server
The config below is the compose-local frontend static server (`Dockerfile` Stage 3, `frontend` service). It serves the SPA and proxies `/api/` for single-origin local deploys. It is not the production edge:

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

### 7.4 Technical Directives Breakdown
- `proxy_http_version 1.1`: Crucial because Nginx defaults to HTTP/1.0 for upstream connections, which strips hop-by-hop headers required for WebSocket handshakes.
- `proxy_set_header Upgrade $http_upgrade`: Passes the client's `Upgrade: websocket` header to the ASGI backend (FastAPI/Uvicorn).
- `proxy_set_header Connection "upgrade"`: Signals the backend that the connection is transitioning from HTTP/1.1 to full-duplex WebSocket framing.
- `proxy_read_timeout 86400s` & `proxy_send_timeout 86400s`: Extends timeout from Nginx's default 60 seconds to 24 hours, ensuring idle keepalive tickers or quiet night hours do not cause unintended disconnections.
- `proxy_buffering off`: Ensures WebSocket frames and streaming SSE responses are transmitted immediately with zero intermediary buffering latency.

---

## 8. Environment Variables & Secrets Reference

### 8.1 Backend Service (GCE VM / Compose)

CORS: `BACKEND_CORS_ORIGINS` defaults to `http://localhost:3000`, `http://localhost:5173`, `http://127.0.0.1:3000`, `http://127.0.0.1:5173` with credentials; evil origin `https://evil.example` is not reflected, evil preflight returns 400, and wildcard `*` raises ValidationError (evidence: `evidence/cors-and-trigger-8014.json`, `backend/app/core/config.py`). No deployment credentials are invented here.

| Variable | Required | Default / Example | Purpose |
|:---|:---:|:---|:---|
| `ENVIRONMENT` | Yes | `production` | Execution environment mode (`development` \| `production` \| `testing`) |
| `API_HOST` | Yes | `0.0.0.0` | ASGI bind host |
| `API_PORT` | Yes | `8000` (served on `127.0.0.1:8000` on the VM via the deploy overlay; no `$PORT` indirection) | ASGI bind port |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG` \| `INFO` \| `WARNING` \| `ERROR`) |
| `DATABASE_URL` | Yes | `postgresql+psycopg2://user:pass@host:5432/apix_db` | Sync connection string for the sync `create_engine` in `backend/app/db/session.py:28`. An `asyncpg` URL yields an async dialect whose first connection raises (`MissingGreenlet`), so the backend could never pass its DB health check |
| `DATABASE_URL_SYNC` | No (unused) | `postgresql+psycopg2://user:pass@host:5432/apix_db` | **Read by nothing.** No Python code references it (`migrations/env.py:29-40` resolves `DATABASE_URL` only); kept as a no-op placeholder in compose/`.env.example`. Name the `psycopg2` driver explicitly. It is the driver the image ships (`requirements.txt`) |
| `SECRET_KEY` | Yes | Cryptographic 64-char hex string | JWT token signing & session crypto |
| `INGESTION_API_KEY` | Yes | `apix-prod-ingest-sec-9f8a7b6c5d4e3f2a1` | Shared secret for `/api/v1/ingestion/*` (`X-Ingestion-Key`) |
| `BACKEND_CORS_ORIGINS` | Yes | `["https://apix-dashboard-navy.vercel.app"]` | JSON array of allowed browser origins. `backend/app/core/config.py:33-46` declares `list[str]`, which pydantic-settings parses as JSON. A comma-separated string parses to one invalid origin and every browser preflight fails; a literal `*` is rejected at startup |
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
| `VITE_API_BASE_URL` | Yes | `https://api.adityaai.dev` | Bare backend origin; the client appends `/api/v1` (`frontend/src/services/apiClient.ts:35-46`) |

### 8.3 Ingestion Runners (GitHub Actions)

| Variable / Secret | Required | Default / Example | Purpose |
|:---|:---:|:---|:---|
| `INGESTION_ENDPOINT_URL` | Yes | `https://api.adityaai.dev` | Target backend URL for batch delivery |
| `INGESTION_API_KEY` | Yes | Secret matching backend `INGESTION_API_KEY` | Auth header token `X-Ingestion-Key` |
| `AMADEUS_CLIENT_ID` | Yes | Amadeus API key | Amadeus GDS OAuth client ID |
| `AMADEUS_CLIENT_SECRET` | Yes | Amadeus API secret | Amadeus GDS OAuth client secret |
| `PLAYWRIGHT_HEADLESS` | No | `true` | Runs Chromium in headless sandbox |
| `SCRAPER_CONCURRENCY` | No | `4` | Parallel browser tab workers |
| `SCRAPER_TIMEOUT_MS` | No | `30000` | Navigation timeout per route |

---

## 9. Secret Rotation & Security Protocol

To ensure continuous compliance, secrets must follow a defined rotation cadence. (Note: ingestion-key rotation is not zero-downtime. See §9.2.)

### 9.1 Rotation Schedule
- **Ingestion API Key (`INGESTION_API_KEY`)**: Rotated every 90 days.
- **Amadeus API Credentials**: Rotated every 180 days.
- **Backend Application Key (`SECRET_KEY`)**: Rotated every 180 days.
- **Database Credentials**: Rotated annually or immediately upon suspected compromise.

### 9.2 `INGESTION_API_KEY` Rotation Procedure
The backend checks a single key: `verify_ingestion_key` compares `X-Ingestion-Key`
against `settings.INGESTION_API_KEY` only (`backend/app/core/auth.py:8-24`). There is
no `INGESTION_API_KEY_SECONDARY` dual-key support in the code, so rotation swaps the
key rather than overlapping two valid keys. Plan a minute of rejected ingestion
traffic, not zero downtime:
1. **Generate New Key**:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
2. **Step 1: Set the new key on the VM**:
   - Update `INGESTION_API_KEY` in `/opt/apix/.env` (mode 600) and recreate the backend (`docker compose -p apix-deploy -f docker-compose.yml -f docker-compose.deploy.yml up -d backend`). Note `ENVIRONMENT != "development"` refuses to boot with the published default key (`backend/app/core/config.py:65-81`), so never rotate *to* the default.
3. **Step 2: Update GitHub Repository Secret**:
   - Update `INGESTION_API_KEY` in Settings -> Secrets and variables -> Actions so the next scrape run posts with the new key.
4. **Step 3: Trigger Scraper Smoke Test**:
   - Run manual workflow dispatch to verify batch delivery with the new key; the old key now returns 401.

### 9.3 Emergency Compromise Runbook
If credentials leak:
1. Immediately change `INGESTION_API_KEY` in the VM's `/opt/apix/.env` (mode 600) and recreate the backend container. This instantly drops active rogue connections.
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

## 10. Availability & Performance Tuning

### 10.1 No cold starts on this deployment
Earlier revisions of this section described Render free/starter-tier sleep (15 minutes
of inactivity, then a 30–50 s cold start) with keepalive-ping mitigations. None of
that applies here: the backend is a persistent container on a GCE VM
(`restart: unless-stopped` in both compose files), so there is nothing to keep warm
and no UptimeRobot/GitHub-ping cron is needed. The rollout gate is the deploy
workflow's post-restart `/health` poll (§2.2), which fails the deploy loudly instead
of leaving a half-migrated stack serving.

### 10.2 Database Connection Pool Tuning
The app sets `pool_pre_ping=True` so stale sockets are discarded
(`backend/app/db/session.py:28-33`). If the pool needs further tuning under load, the
knobs are the standard `create_engine` arguments:
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
- `GET /health`: Readiness probe. Runs `probe_database_readiness` against `routes`, `crawler_jobs` and `worker_heartbeats` and returns 503 `Database unavailable` when the DB is unreachable or the schema is uninitialised (`backend/app/main.py:175-183`). This is what the deploy health-gate polls, not a process-clock check.
- `GET /api/v1/health`: Richer API health under the versioned router. The same DB probe plus `records_ingested_today`, `active_scrapers` and `last_sync_timestamp` (`backend/app/api/v1/api.py:24-69`).
- `GET /`: Service metadata with the versioned docs links (`backend/app/main.py:199-207`).
- Interactive docs live at `/api/v1/docs` (and `/api/v1/redoc`); bare `/docs` 404s (`backend/app/main.py:38`).
- Telemetry: `GET /api/v1/ingestion/telemetry` (also mounted at `/api/v1/telemetry/telemetry`) for crawler and proxy-pool health; `POST /api/v1/ingestion/trigger` (also `/api/v1/telemetry/trigger`) enqueues a scrape run, gated on `X-Ingestion-Key`. There is no `GET /api/v1/system/status`.

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
- **FastAPI API & Docs**: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
- **Frontend SPA Dashboard**: [http://localhost:3000](http://localhost:3000)
- **PostgreSQL Database**: `localhost:5432` (`user: apix_user`, `password: apix_password`, `database: apix_db`)

### 12.3 Executing Migrations & Seeding in Docker
```bash
# Run database migrations from the repo root, pointed at the Compose DB.
# (The backend image ships only backend/, ingestion/ and pyproject.toml
# per Dockerfile:36-39, so alembic.ini/migrations/ are not inside the
# container; the production deploy bind-mounts them for the same reason.
# See .github/workflows/deploy-backend.yml.)
DATABASE_URL="postgresql+psycopg2://apix_user:apix_password@localhost:5432/apix_db" alembic upgrade head

# Seed DGCA baseline routes and traffic weights
docker compose exec backend python -m backend.app.db.seed

# Trigger a sample ingestion run inside the container
docker compose exec backend python -m ingestion.orchestrator --mode synthetic
```

### 12.4 Scheduler and worker

`docker compose up -d` starts `apix-worker` (`python -m ingestion.worker`) and `apix-scheduler` (`python -m ingestion.scheduler`). The scheduler does not scrape. It enqueues. The worker scrapes, classifies challenges, and posts. `restart: on-failure` on the scheduler means a duplicate that exits 0 is not respawned into a hot loop.

```bash
docker compose run --rm --no-deps scheduler python -m ingestion.scheduler --print-next --cron "0 2 * * *"
docker compose run --rm --no-deps scheduler python -m ingestion.scheduler --dry-tick
```

`--print-next` prints the next UTC fire time and exits. `--dry-tick` starts the engine, waits for one interval tick, and exits. Neither scrapes.

The profile-gated `scraper` service is an on-demand orchestrator run. It is not the daily schedule. Leave it off when the scheduler service is up.

### 12.5 Crawler Worker Service
The Compose `apix-worker` service runs `command: ["python", "-m", "ingestion.worker"]` (`docker-compose.yml`) and consumes the durable `crawler_jobs` queue with `worker_heartbeats` leases (`ingestion/worker.py`). Run standalone as `python -m ingestion.worker`. The API trigger requires this worker: without a fresh heartbeat it returns 503, and 202 `QUEUED` follows a committed job row (evidence: `evidence/trigger-liveness-8014.json`, `evidence/trigger-idempotency-8014.json`). Live execution through the worker is verified for SpiceJet (airline-direct, 23 live rows persisted 2026-09-28); no OTA portal has been crawled live (synthetic-mode fallback only). Retention cleanup uses `synchronize_session="fetch"` (evidence: `.debug-journal.md` 2026-09-25T14:40Z). Current suite is 511 passed (`pytest -q`, matching the README badge); older 460/388/226 counts are historical. **Live scraping: what is real and what is blocked.** Genuine data does arrive, fares included. The SpiceJet availability endpoint (`https://www.spicejet.com/api/v3/search/availability`, HTTP 200) yields flight identity (`SG 815`, DEL 09:50 to BOM 12:25) and structured fares (`fareAmount`, `publishedFare`, per-code taxes); on 2026-09-28 it produced 23 live rows with a measured split that recomposes exactly, corroborated by `scripts/audit_provenance.py`. One blocker remains for the OTA portals: client-side bot defence: `makemytrip.com` resolves and serves pages from this host, but Akamai rejects the request. Measured three ways: stock `curl` gets `403`, Playwright's bundled Chromium is reset with `net::ERR_HTTP2_PROTOCOL_ERROR`, and driving the distro build at `/usr/bin/chromium` returned HTTP 200 with 500864 bytes of real page content. The scraper now prefers a system Chromium via `resolve_launch_kwargs` with a `playwright_browser_executable` override, but that unblock is not durable: retested under repetition the same client returned 0 of 3 successes, so sustained probing tips the egress IP into a temporary Akamai throttle. Separately, `api.spicejet.com` is not blocked at all, it is NXDOMAIN on both 1.1.1.1 and 8.8.8.8, meaning the hostname does not exist; no provider change can make a nonexistent hostname resolve. The opaque `fareAvailabilityKey` (`USAV~5511~~0~665~`, `X!0:48004:1004:854:5994:2364:1524:895:280`) still has no documented mapping and is never used to derive an amount: the parser reads only structured `fareAmount`/`publishedFare` fields, so no fare is guessed. Separately, a critical provenance defect was found and fixed: `amadeus.py` labelled generated mock records `is_synthetic=False`, so a live run would have persisted invented fares as real and earned a false LIVE badge. Provenance now follows the payload, and `scripts/audit_provenance.py` fails closed if any row claims to be live without corroborating telemetry, a scraping run, proxy evidence and scrape-time diversity (evidence: `evidence/live-ingestion-verification.json`, `evidence/provenance-audit.json`). Preserved limitations include sparse FKs, role-separation and false-success residuals, unknown-route 200 behavior, and duplicate WebSocket mounts. **CRITICAL, partially fixed: `GET /api/v1/indices/routes` served fabricated airfares as measured data.** **Fixed:** the swallowed `except Exception: pass` that returned the entire hardcoded seed list on any failure is replaced by a 503 `Database unavailable`, and a reachable database with no active routes now reports zero coverage instead of seven invented corridors. Verified at runtime on a current-source instance and locked by two regression tests (`test_routes_overview_does_not_fabricate_when_database_is_unavailable`, `test_routes_overview_reports_no_coverage_instead_of_seeded_corridors`). **Still open:** a route that has no `RouteDailyIndex` is still replaced by its hardcoded `DOMESTIC_ROUTES_SEED` entry or an invented `avg_fare_inr=5000.0` default, and `/api/v1/indices/routes/{route_code}/history` applies the same seed fallback including an invented base index of 108.0. On a sparse database 7 of 7 served routes matched the hardcoded literals exactly, so the whole response was invented. That part needs a product decision, because `RouteOverviewItem` requires `current_index` and `avg_fare_inr` (evidence: `evidence/indices-routes-fabricated-fares.json`). The frontend was re-measured directly against the frozen production build (24 of 24 tab renders, zero console errors, focus contrast minimum 17.93:1), which is first-party measurement rather than an independent reviewer pass, so no independent visual PASS or Lighthouse result is claimed.

---
*Maintained by APIx Architecture & Engineering Operations (SIH 2026)*

## Browser binary for OTA scraping

Tier 1 scrapers drive Chromium through Playwright. Akamai fingerprints the HTTP/2 frame and resets Playwright's bundled build with `net::ERR_HTTP2_PROTOCOL_ERROR` while accepting the distro build of the same browser. `resolve_launch_kwargs` in `ingestion/crawlers/makemytrip.py` therefore prefers an executable system Chromium, checking `/usr/bin/chromium`, `/usr/bin/chromium-browser`, `/usr/bin/google-chrome` and `/usr/bin/google-chrome-stable` in order. Set `INGESTION_PLAYWRIGHT_BROWSER_EXECUTABLE` to pin a specific binary. When no candidate is executable the scraper falls back to the bundled build.

This is a mitigation, not a guarantee. The upstream edge can still throttle the egress IP, and a page that loads without yielding a fare XHR falls through to the synthetic tier and is labelled `is_synthetic=True`. Never treat a successful page load as evidence of a live fare.

### Fare decomposition is an estimate, not a measurement

`raw_fares` has separate `base_fare`, `taxes_and_fees` and `total_fare` columns. When a source supplies the split it is stored as measured: the 23 live SpiceJet rows (2026-09-28) carry a measured `base`/`taxes`/`UDF` split parsed from the availability JSON and checked at insert. When a source omits the split, it is estimated from route- and carrier-aware calibrated ratios in `backend/app/core/fare_components.py` (fallback `DEFAULT_BASE_FARE_RATIO = 0.78`); the 13 synthetic fallback rows in the current database are all exactly 0.78 x total. Do not present estimated base-versus-tax figures as measured.

## Schema migrations

`init_db()` calls `Base.metadata.create_all()`, which creates missing tables. It does **not** add columns to
tables that already exist. Any deployment against an existing database must therefore run the migration chain first:

```bash
DATABASE_URL="postgresql+psycopg2://..." alembic upgrade head
```

`migrations/env.py` resolves the URL from the `DATABASE_URL` environment variable and falls back to the app's
`Settings.DATABASE_URL`, so it always targets the same database the app uses. It overrides any `sqlalchemy.url`
set directly on an Alembic `Config`, which means scripts and tests must set the environment variable rather than
the config object.

Skipping this step is not a soft failure. The ORM selects every mapped column, so a database missing a column
fails every read that hydrates a full row, not just the new feature. `tests/test_migration_drift.py` asserts that
`alembic upgrade head` produces exactly the schema the ORM declares, and that upgrading a pre-populated table is
additive.
