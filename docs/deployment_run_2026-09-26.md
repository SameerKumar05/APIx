# APIx Deployment Run — 2026-09-26

Operational record of the first public deployment of APIx: FastAPI backend on Google
Compute Engine behind Caddy, Vite SPA on Vercel.

- **Frontend:** https://apix-dashboard-navy.vercel.app
- **Backend API:** https://api.adityaai.dev (TLS: Let's Encrypt, expires 2026-12-25)
- **Backend repo:** `docs/deployment.md` (standing guide) · this file (what actually happened)

---

## 1. Topology

```
Browser ──HTTPS──> Vercel (SPA, static)          apix-dashboard-navy.vercel.app
                        │
                        │ fetch() XHR, Origin: https://apix-dashboard-navy.vercel.app
                        ▼
                  GCP VM 34.131.69.223  (project-dace7531-ac79-4f81-bd2, asia-south2-a)
                        │
                   Caddy :443  ── reverse_proxy ──> 127.0.0.1:8000  (apix-backend)
                        │                                    │
                   Caddy :80   ── ACME HTTP-01 ──┐    apix-db (no host port, bridge net only)
                                                  └── Let's Encrypt
```

The SPA and API are on **different origins**, so the backend must send CORS headers
naming the exact Vercel origin. See §6.

### Why split at all

The repo's `Dockerfile` already ships an nginx stage that serves the SPA *and* proxies
`/api/`, i.e. a single-origin design. The frontend was placed on Vercel because the
dashboard is a static bundle that benefits from an edge CDN, and because the submission
wanted a hosted frontend URL. The cost is cross-origin CORS plus one more deploy target.

---

## 2. Cloud resources

| Resource | Value |
|---|---|
| Project | `project-dace7531-ac79-4f81-bd2` |
| Zone / type | `asia-south2-a` / `e2-standard-2` (2 vCPU, 7.7 GB) |
| Public IP | `34.131.69.223` (static) |
| OS | Ubuntu 26.04.1 LTS |
| Docker | 29.8.1 + compose plugin |
| Deploy path | `/opt/apix` |
| Compose project | `apix-deploy` (isolates volumes/networks from other stacks) |

**This VM is shared.** It already ran Caddy, a full Firecrawl stack (api, rabbitmq,
postgres, redis, playwright), RustDesk (`hbbs`/`hbbr`), a bun MCP service, hermes-agent and
a Vertex ADC proxy. None of it was touched. Verification in §7.

### Firewall

No change was needed. Existing rules already permit the required traffic:

```
allow-http    default INGRESS 1000 0.0.0.0/0 tcp:80
allow-https   default INGRESS 1000 0.0.0.0/0 tcp:443
```

No rule exposes `5432`, so Postgres stays unreachable from the internet as long as it is
not published to a host interface.

---

## 3. DNS

Provider: **Porkbun** (`*.ns.porkbun.com`). Record created:

| host | type | value | TTL |
|---|---|---|---|
| `api` | A | `34.131.69.223` | 600 |

The current Porkbun v3 API puts parameters in a **JSON body**, and the path is
`dns/create/{domain}` — *not* `domains/{domain}/dns/add/...`:

```bash
curl -X POST https://api.porkbun.com/api/json/v3/dns/create/adityaai.dev \
  -H 'Content-Type: application/json' \
  -d "{\"apikey\":\"$APIKEY\",\"secretapikey\":\"$SECRET\",
       \"name\":\"api\",\"type\":\"A\",\"content\":\"34.131.69.223\",\"ttl\":600}"
```

Idempotency: check first with
`POST /api/json/v3/dns/retrieveByNameType/{domain}/A/api` and edit rather than duplicate
if a record already exists.

Current docs: `https://porkbun.com/llms/dns`. The older
`kb.porkbun.com/article/69-dns-api-endpoints` is dead and redirects.

---

## 4. Deploying the backend

```bash
# 1. transfer (secrets and build output stay behind)
rsync -az --delete --exclude .git --exclude .venv --exclude node_modules \
      --exclude frontend/dist --exclude '*.db' --exclude evidence/ \
      --exclude artifacts/ volt-rust:/opt/apix/

# 2. secrets, generated ON the VM, mode 600, never committed
ssh volt-rust 'cd /opt/apix && cp .env.deploy.template .env && chmod 600 .env'
#   fill each CHANGEME with: openssl rand -base64 32

# 3. bring up the database first, then migrate, then serve
ssh volt-rust 'cd /opt/apix && docker compose -p apix-deploy \
  -f docker-compose.yml -f docker-compose.deploy.yml up -d db'

# 4. migrations, BEFORE the backend ever starts
ssh volt-rust 'cd /opt/apix && docker compose -p apix-deploy \
  -f docker-compose.yml -f docker-compose.deploy.yml run --rm backend \
  alembic upgrade head'

# 5. seed, then serve
ssh volt-rust 'cd /opt/apix && docker compose -p apix-deploy \
  -f docker-compose.yml -f docker-compose.deploy.yml up -d backend frontend'
```

### Deploy overlay

`docker-compose.deploy.yml` layers on top of `docker-compose.yml`; the base file is never
edited for deploy concerns. It:

- pins `timescale/timescaledb:2.14.2-pg16` (the base file floats on `latest-pg16`);
- clears the db's ports with `!reset []` so nothing binds to the host;
- rebinds backend to `127.0.0.1:8000` and frontend to `127.0.0.1:3001` with `!override`
  (compose *appends* ports by default, so `!override` is required, not optional);
- applies Postgres tuning sized for a shared host (§5);
- caps the backend at 1 GiB;
- runs **only** `db`, `backend`, `frontend`.

`worker`, `scheduler` and `scraper` are deliberately excluded. See §8.

---

## 5. Resource budget

The host has 7.7 GB total but only ~4.4 GB available, shared with Firecrawl's 1.7 GB
Playwright-backed API. Sizing is therefore based on *available* memory, not total.

| Setting | Value | Reasoning |
|---|---|---|
| `shared_buffers` | `512MB` | 25% of the 2 GB container cap, not of 7.7 GB host RAM |
| `effective_cache_size` | `2GB` | ~50% of available; planner hint only, allocates nothing |
| `work_mem` | `8MB` | per sort **per connection**; 40 conns × 8 MB stays inside the cap |
| `maintenance_work_mem` | `128MB` | single maintenance op at a time |
| `max_connections` | `40` | down from 100; each backend is a separate process |
| backend memory cap | `1g` | prevents OOM reaching neighbouring services |
| uvicorn workers | 1 | 8 read-only tabs do not need 4 workers on 2 vCPU |

Measured after deploy: **4.0 GiB available** (was 4.4 GiB) — the whole stack costs ~0.4 GiB.
Swap: 4 GB unused, as a safety net.

---

## 6. Configuration that is easy to get wrong

These four each caused a real failure or a silent misconfiguration during this run.

**`DATABASE_URL` must be a sync driver URL.** `backend/app/db/session.py:28` uses
`create_engine` with `sqlalchemy.orm.Session` — not the async engine. So
`postgresql+asyncpg://` (which `.env.example` used to advertise) raises at engine
creation. Use `postgresql+psycopg2://`.

**The image ships `psycopg2-binary`, not `psycopg`.** SQLAlchemy 2.x resolves a bare
`postgresql://` to psycopg, so the driver must be named explicitly or startup fails with
`ModuleNotFoundError`.

**`BACKEND_CORS_ORIGINS` is a JSON array, not comma-separated.** pydantic-settings parses
it as JSON. `.env.example` previously showed a comma-separated list, which parses to a
single invalid origin. A literal `*` is rejected at startup by
`backend/app/core/config.py`.

**`ENVIRONMENT` gates the ingestion key.** `config.py` raises at import if
`ENVIRONMENT != "development"` while `INGESTION_API_KEY` still equals the published
default `apix-ingestion-secret-key-2026`. A production deploy with the stock key will not
boot. The settings object is constructed at import, so this fails at process start.

---

## 7. Migrations, seeding, verification

### Why `alembic upgrade head` is mandatory

The app calls `Base.metadata.create_all` in its lifespan handler but **swallows the
error**, and `create_all` never adds columns to an existing table. On a re-deploy against
an existing Postgres volume the app therefore comes up "healthy" while every full-row read
503s. The repo documents this itself in `tests/test_migration_drift.py`:

> `create_all` creates missing tables. It does not add columns to existing ones. So a
> green suite proves nothing about a deployed database, and a deployment that skips
> `alembic upgrade head` breaks every full-row read.

Run migrations against a genuinely empty database *before* the first backend start, or
`create_all` wins the race and `upgrade head` fails with `DuplicateTable`.

Result: revision `b8c3d2e7a004 (head)`, **17 tables**, `alembic_version` populated.

### Seeded dataset

`python -m backend.app.db.seed` then `SyntheticFlightGenerator` →
`bulk_insert_raw_fares` → `run_daily_index_pipeline` for 2026-09-26:

| Table | Rows |
|---|---|
| `routes` | 10 |
| `airlines` | 5 |
| `raw_fares` | 272 |
| `route_daily_indices` | 60 |
| `national_daily_indices` | 3 |
| `econometric_indices` | 1 |

> **This is synthetic data, not live airfares.** See §9.

### Verification performed

| Check | Result |
|---|---|
| `https://api.adityaai.dev/health` | 200, `environment: production` |
| 15 frontend-called endpoints, from the Vercel origin | all 200, all with `access-control-allow-origin` |
| TLS chain | Let's Encrypt, SAN `api.adityaai.dev`, valid to 2026-12-25 |
| `mcp.adityaai.dev/healthz`, `/setup.md` | 200, 200 (no regression) |
| `review.adityaai.dev/` | 302 (no regression) |
| Headless browser, 8 deep links | all 200 and rendered |
| Browser API calls | 15/15 returned 200 |
| Console errors / failed requests | 0 / 0 |
| Postgres port binding | none |
| Backend binding | `127.0.0.1:8000` only |
| Pre-existing containers | all `Up` at host uptime — never restarted |
| `apix` memory cost | ~0.4 GiB |

---

## 8. What is intentionally not running

`scraper`, `worker` and `scheduler` are excluded from the VM deploy.

**Scraping cannot work from this host.** Airline sites block datacenter IP ranges, so the
scrapers need rotating residential proxies, which cost real money. The proxy settings in
`.env` (`PROXY_ROTATION_STRATEGY`, `PROXY_EWMA_ALPHA`, `PROXY_COOLDOWN_SEC`) are built for
that and are untested here. Running Playwright would also have competed with Firecrawl's
existing browser stack for the ~4 GB of free memory.

The scheduler still exists as a GitHub Actions cron (`.github/workflows/scrape.yml`).

---

## 9. Honesty caveats

The dashboard is live and fully functional, but be precise about what it shows:

- **The fare data is synthetic**, generated by `SyntheticFlightGenerator`. There are **no
  live airfare rows**. MakeMyTrip is robots-disallowed, SpiceJet publishes no structured
  fares, and DGCA offers no reusable fare dataset.
- **The CPI comparison is modelled.** The official MoSPI series was withdrawn after the
  data contradicted NSO press notes.
- **Route weights are modelled**, not a DGCA download — the loader reports
  `provenance=generated`.
- **Fisher factor reversal still fails** by design; it is a known model defect, not a
  regression.

A first-time visitor with no context may read the dashboard as a live airfare feed. It is
not. Consider a banner stating the data provenance on the dashboard itself.

---

## 10. Rollback

```bash
# stop the APIx stack only; never run unscoped `docker compose down`
ssh volt-rust 'cd /opt/apix && docker compose -p apix-deploy \
  -f docker-compose.yml -f docker-compose.deploy.yml down'
# data survives: the named volumes are untouched unless you add `-v`

# remove the public route, keeping mcp./review. serving
ssh volt-rust 'sudo cp /opt/apix/Caddyfile.bak-<ts> /opt/caddy/Caddyfile && \
  sudo docker exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && \
  sudo docker exec caddy caddy reload  --config /etc/caddy/Caddyfile --adapter caddyfile'

# frontend
cd frontend && vercel --prod --scope aditya-ai-architects-projects rollback
```

Caddy backups live at `/opt/caddy/Caddyfile.bak-<timestamp>`.

> **Never `docker restart caddy`, `caddy stop`, or recreate the container.** Caddy serves
> `mcp.adityaai.dev` and `review.adityaai.dev` from the same config; any of those would
> drop both. `caddy validate` then `caddy reload` is non-disruptive. Note that Caddy
> **ignores `SIGHUP`** — use `caddy reload`, and re-specify `--config` every time because
> it does not watch the file on disk.

---

## 11. Secrets

| Secret | Where | Action needed |
|---|---|---|
| `POSTGRES_PASSWORD` | `/opt/apix/.env` (600) | rotate if the VM is ever exposed |
| `INGESTION_API_KEY` | `/opt/apix/.env` (600) | already freshly generated; rotate on any suspected leak |
| `SECRET_KEY` | `/opt/apix/.env` (600) | same |
| Porkbun API key/secret | `~/Work/woventech/domain-creds.txt` | **was mode 644 (world-readable) — `chmod 600` and rotate** |

`POSTGRES_PASSWORD` only takes effect on first init of an empty data directory. Changing it
in `.env` afterwards does nothing to an existing volume; you must `ALTER USER` inside the
container.

A Docker named volume is persistence, **not** a backup. Take dated `pg_dump` copies off
the VM:

```bash
ssh volt-rust 'sudo docker exec apix-db pg_dump -U postgres -Fc -f /tmp/apix.dump apix_db && \
  sudo docker cp apix-db:/tmp/apix.dump /opt/apix/backups/apix-$(date +%F).dump'
```

---

## 12. Repo bugs found and fixed during this run

1. **`.env.example` advertised `postgresql+asyncpg://`** while the app uses a sync engine.
   Startup would have crashed for anyone copying it. Now `postgresql+psycopg2://`, with a
   comment explaining why.
2. **`.env.example` showed `BACKEND_CORS_ORIGINS` as a comma-separated list.** It must be a
   JSON array. Fixed, with the parser and the wildcard rejection documented inline.
3. **`Dockerfile` pinned `oven/bun:1.2-alpine` (bun 1.2.23)** but `frontend/bun.lock` is
   `lockfileVersion: 2`, which needs bun ≥ 1.3. Reproduced on the VM:
   `error: Unknown lockfile version`. Bumped to `oven/bun:1.4-alpine`; the frontend image
   now builds (276 packages) and serves 200. Vercel was never affected — it uses its own
   newer bun.
4. **`BACKEND_CORS_ORIGINS` in the live `.env` named the API's own origin** instead of the
   Vercel frontend origin, so every browser call failed preflight with HTTP 400. Corrected
   to the real deployment origin.
5. **Port collision:** the base `docker-compose.yml` publishes the frontend on `3000`, which
   on this VM is already held by the node process backing `review.adityaai.dev`. The
   overlay rebinds it to `3001`. Left as-is on the VM rather than touching that service.

---

## 13. Ongoing operations

```bash
# logs
ssh volt-rust 'sudo docker logs apix-backend --tail 100'

# resource usage
ssh volt-rust 'sudo docker stats --no-stream apix-db apix-backend apix-frontend; free -h'

# apply a future migration
ssh volt-rust 'cd /opt/apix && docker compose -p apix-deploy \
  -f docker-compose.yml -f docker-compose.deploy.yml run --rm backend alembic upgrade head'

# redeploy after a code change
rsync -az --delete --exclude .git --exclude .venv --exclude node_modules \
  --exclude frontend/dist volt-rust:/opt/apix/
ssh volt-rust 'cd /opt/apix && docker compose -p apix-deploy \
  -f docker-compose.yml -f docker-compose.deploy.yml up -d --build backend'
```

Both stacks use `restart: unless-stopped`, so they survive a reboot. Certificate renewal
is automatic via Caddy's ACME maintenance task.
