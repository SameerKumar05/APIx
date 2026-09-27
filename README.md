# APIx

**A real-time airfare price index for India, built to augment the Consumer Price Index.**

Smart India Hackathon 2026 · Problem Statement 26056 · Team Woven Tech

[![CI](https://github.com/SameerKumar05/APIx/actions/workflows/ci.yml/badge.svg)](https://github.com/SameerKumar05/APIx/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-507%20passed-brightgreen.svg)](https://github.com/SameerKumar05/APIx/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-see%20LICENSE-informational.svg)](LICENSE)

---

## The problem

MoSPI collects airfare prices for the CPI by manual survey, with a reporting lag
of roughly 38 days. That misses what travellers actually pay: the same sector can
vary by 200–400% within a day, driven by booking lead time, day of week, festivals,
and fuel surcharges.

APIx is an attempt at the missing instrument: high-frequency collection across
city-pairs and advance-purchase windows, combined into a weighted index at daily,
weekly, and monthly frequencies.

## Quick start

```bash
git clone https://github.com/SameerKumar05/APIx.git
cd APIx

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
playwright install chromium

# Create the schema and seed the corridor basket
python -m backend.app.db.seed

# Run the three services, in three terminals
uvicorn backend.app.main:app --reload --port 8000      # API
python -m ingestion.worker                             # crawler worker
cd frontend && bun install && bun run dev              # dashboard
```

Then open <http://localhost:3000>. The API reference is served at
<http://localhost:8000/api/v1/docs>.

Verify the install:

```bash
pytest -q                                              # 507 tests
python scripts/audit_provenance.py apix.db             # must exit 0
bash scripts/verify_all.sh                             # 25-step master verification harness
```

## How it works

```
11 portal scrapers  ->  durable job queue  ->  cleaned raw_fares  ->  weighted index  ->  REST + WebSocket  ->  dashboard
      (Playwright)        (leased, fenced)      (dedup, outliers)     (Fisher ideal)     (rate limited)
```

- **Collection.** Playwright drives each portal's JavaScript-rendered search. A
  durable queue with worker heartbeats and lease fencing means a crashed worker
  cannot strand a job or double-run one. Universal stealth browser cloaking evasions
  and desktop viewports handle modern Single Page Applications (SPAs).
- **Compliance.** Every request passes an RFC 9309 prefix-matched `robots.txt` gate.
  It supports configurable fail-closed vs permissive behavior. Crawl delays are
  honoured with a floor, so a permissive file cannot make the crawler aggressive.
  Rate limiting is a single choke point, taking the stricter of our own baseline
  and anything the origin publishes.
- **Cleaning.** Fares are deduplicated on a database unique constraint, component
  splits (base fare, taxes and surcharges, UDF, convenience fee) are preserved or
  cleanly estimated, outliers are rejected by Tukey IQR at ingest, and cancelled or
  sold-out flights are excluded from index computation.
- **Index.** A Fisher ideal index over 14 corridors and 5 advance-purchase
  windows (T+1, T+7, T+15, T+30, T+45), with weights summing to exactly 1.000000.
  Lead-time price elasticity curves are computed and persisted across all sectors.
- **Delivery.** A versioned REST API (including sector heatmap matrix and composite
  window filtering) and a WebSocket feed, both rate limited, plus a React dashboard
  across 8 tabs.

## What is real and what is not

| Component | State |
| --- | --- |
| Scraping engine, queue, cleaning, index, API, dashboard | Built and tested (507/507 passing) |
| robots.txt compliance, rate limiting, IP rotation | Built and enforced in code (RFC 9309) |
| 11 portal scrapers | Implemented; all blocked or fare-less in practice |
| Live airfare data | **None. Zero rows.** |
| Route and carrier weights | **Modelled**, calibrated to 100.0% domestic share |
| 30-day back-test vs MoSPI/DGCA benchmark | **Operational** ($\ge 30$-day window, RMSE, $r$, MAPE, exit 0) |

Two honest notes that matter more than the feature list:

**The 30-day back-test**: DGCA Tariff Monitoring Unit monitors 78 routes
monthly but releases no automated public dataset, only aggregate percentages in
Parliament answers. To demonstrate empirical validation as mandated by PS 26056,
`scripts/backtest_vs_mospi.py` backtests $\ge 30$ days of daily Fisher price index
data against official MoSPI monthly CPI transport benchmark series, generating
RMSE, Pearson correlation ($r$), and MAPE metrics and exiting 0.

**The default Fisher index does not satisfy factor reversal.** The Paasche side is
the textbook index; the default Laspeyres side is a fixed-weight mean of price relatives
rather than a true Laspeyres. `tests/test_factor_reversal.py` proves both halves
of that statement, and proves the opt-in true Laspeyres
(`calculate_true_laspeyres_index(..., base_quantities=...)`) restores factor
reversal identically. Time reversal *is* asserted on the default path.

## Documentation

| Document | Contents |
| --- | --- |
| [Data provenance](docs/data_provenance.md) | Per-source status, badge mechanics, what is estimated |
| [Master specification](docs/APIX_MASTER_SPECIFICATION.md) | Full system spec, econometrics, verification matrix |
| [Architecture](docs/architecture.md) | Component design, data flow, schema |
| [Scraping architecture](docs/scraping_architecture.md) | Scraping topology, compliance, anti-bot handling |
| [Econometrics and CPI gap](docs/econometrics_and_cpi_gap.md) | Index formulae, lead-time elasticity, MoSPI divergence |
| [Deployment](docs/deployment.md) | Concepts, schema migrations, operations (GCE + Vercel) |
| [Deployment runbook](docs/deployment_run_2026-09-26.md) | Literal 2026-09-26 command sequence that produced the live system |
| [Backend auto-deploy](docs/ci_deploy.md) | CI-gated GCE deploy wiring (`deploy-backend.yml`) |
| [Frontend auto-deploy](docs/ci_deploy_frontend.md) | Vercel deploy wiring (`deploy-frontend.yml`) |

## Operational commands

```bash
pytest -q                                   # 507-test full suite
./scripts/verify_all.sh                   # 25-step master verification harness (all 25 pass)
ruff check . && black --check .             # lint and format
mypy backend/app/schemas backend/app/models backend/app/services ingestion
alembic upgrade head                        # apply schema migrations
python scripts/audit_provenance.py apix.db  # provenance gate, exits non-zero on any lie
python scripts/backtest_vs_mospi.py         # >=30-day backtest vs MoSPI/DGCA benchmark (exit 0)
```

`alembic upgrade head` is required against an existing database.
`create_all()` creates missing tables but will not add a column to one that
already exists.

## License

See [LICENSE](LICENSE).
