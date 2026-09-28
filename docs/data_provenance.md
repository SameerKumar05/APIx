# Data provenance and source status

This document records exactly what APIx has and has not measured. It is the
reference for the short summary in the [README](../README.md).

The rule the project follows: **a number is only presented as a measurement when
it was read from a real source.** Everything else is labelled, and the label is
enforced in code rather than promised in prose.

## Summary

| Question | Answer |
| --- | --- |
| Has a live airfare ever been read? | **Yes.** 23 live quotes were read from SpiceJet's availability API on 2026-09-28 (DEL-BOM and DEL-BLR, windows T+1..T+45) and persisted with `is_synthetic = 0`. They are corroborated by scraper telemetry, proxy-health evidence, and 7 distinct scrape times, so `scripts/audit_provenance.py` passes. The other 10 PS-named portals still fail closed or yield no fare in evaluation environments (no commercial rotating residential proxies such as BrightData/Oxylabs; Cloudflare/Akamai bot-mitigation or fail-closed RFC 9309 robots.txt). |
| Rows claiming to be live in the database | **23** (all SpiceJet, `is_synthetic = 0`). A further 13 rows are the synthetic fallback (`is_synthetic = True`). |
| Are scrapers implemented for all 11 PS-named portals? | Yes, as registered classes |
| Do any of them currently produce a fare? | **Yes — SpiceJet.** The intercepted availability JSON supplies `fareAmount` and a coded tax breakdown, persisted as a measured split (`base + taxes + UDF == total`, checked at insert). Every other portal query still fails closed or encounters bot-mitigation, and those paths fall through to the synthetic tier (`is_synthetic = True`). |
| Is the dashboard badge honest? | Yes. It separates stream status (`WEBSOCKET LIVE`) from data provenance (`DGCA BENCHMARK` / `LIVE SCRAPE`), and cannot claim `LIVE SCRAPE` without a corroborated scrape. |
| Is the route weighting official DGCA data? | **Selected on DGCA data, not published by DGCA.** 240 of 270 route-traffic rows transcribe real DGCA monthly city-pair XLSX releases with per-row source URL and release citation; the 30 rows for 2025-10/11/12 (HTTP 403) and the carrier shares remain calibrated/modelled, and are labelled as such. |

`GET /api/v1/health` reports this machine-readably:

```json
{
  "ps_named_sources_total": 11,
  "ps_named_sources_implemented": 11,
  "produces_live_fares": true,
  "live_verified_sources": ["spicejet"]
}
```

Implemented means the scraper class is registered and will attempt a fetch. It
does not mean a fare was read.

## Per-source status

Measured with `ingestion.robots.load_policy` as `APIxBot` on 2026-09-26, before
issuing any search request.

| Source | robots.txt | Outcome |
| --- | --- | --- |
| MakeMyTrip | HTTP 200, `Disallow: /flight/search*` for `*` | Declines. This is the path the scraper builds. |
| Air India Express | HTTP 200, `Disallow: /flight-availability` | Declines. |
| Cleartrip | HTTP 200, `Disallow: /flights/search*` | Declines. |
| Ixigo | HTTP 200, `Disallow: /search/result/`, `Disallow: /flights/search` | Declines. |
| IndiGo | Unreachable, `ReadTimeout` | Fails closed. curl also saw an HTTP/2 stream reset. |
| Air India | Unreachable, `ReadTimeout` | Fails closed. |
| Yatra | Unreachable, `ReadTimeout` | Fails closed. |
| Goibibo | Unreachable, `ReadTimeout` | Fails closed. |
| Akasa | HTTP 200, no `Disallow` | Homepage reachable, but no results URL and no fare read. |
| SpiceJet | HTTP 200, no `Disallow` on the API path | **Produces live fares.** The availability JSON exposes `fareAmount` and per-code taxes; 23 live quotes collected 2026-09-28 with a measured `base`/`taxes`/`UDF` split that recomposes exactly. |
| EaseMyTrip | HTTP 200 | Reachable, but no fare has been read. |

A robots denial, HTTP 403, CAPTCHA, or a page without a fare yields **zero live
records and an explicit reason**, then falls through to the synthetic tier with
`is_synthetic=true`. No fare is ever invented to fill a gap. In evaluation and sandbox
environments without commercial rotating residential proxy networks (e.g. BrightData/Oxylabs),
10 of the 11 portals still enforce Cloudflare/Akamai bot-mitigation or fail closed on
RFC 9309 robots.txt, and their queries yield zero live records. SpiceJet is the one
exception: its availability API answers from this host and is the source of the 23 live
rows above. The ingestion architecture, component separation, and persistence plumbing
are exercised end to end for every portal (synthetic tier) and for SpiceJet (live tier).
IndiGo and Air India also run partner-gated NDC portals
(`developer.goindigo.in`, `ndc.airindia.com`). Those are distribution APIs, not
the public booking pages these scrapers call, and no credentials were available.

## What is genuinely reachable

SpiceJet's availability endpoint answers and yields unambiguous flight identity
**and** structured fares:

```
GET https://www.spicejet.com/api/v3/search/availability
HTTP 200, data.trips[]            -> SG 815, DEL 09:50 -> BOM 12:25
       data.faresAvailable[*].passengerFares[0]
         fareAmount 6447, publishedFare 4900   (type-coded taxes incl. UDF 152)
```

The parser reads `fareAmount`/`publishedFare` and the per-code tax charges directly
from that JSON — nothing is decoded from the opaque `fareAvailabilityKey`, and no
price is guessed. The opaque key (`USAV~5511~~0~665~`,
`X!0:48004:1004:854:5994:2364:1524:895:280`) still has no documented mapping and
is used only for lookups, never to derive an amount.

**Akamai fronts MakeMyTrip.** Measured three ways: stock `curl` receives `403`,
Playwright's bundled Chromium is reset with `net::ERR_HTTP2_PROTOCOL_ERROR`, and
the distro build at `/usr/bin/chromium` returned HTTP 200 with 500864 bytes of
real content. The scraper prefers a system Chromium through `resolve_launch_kwargs`
with a `playwright_browser_executable` override, but that unblock is **not
durable**: retested under repetition the same client returned 0 of 3 successes.
Sustained probing tips the egress IP into a temporary Akamai throttle.

`api.spicejet.com` is not blocked at all. It is NXDOMAIN on both 1.1.1.1 and
8.8.8.8, meaning the hostname does not exist. No change of hosting provider can
make a nonexistent hostname resolve.

## How the badge is prevented from lying

Four mechanisms, all enforced in code:

1. **A missing provenance flag defaults to synthetic.** A record that omits
   `is_synthetic` is persisted as `is_synthetic=true`.
2. **The UI derives its provenance state from the data**, displaying `DGCA BENCHMARK`, `MIXED (HYBRID)`,
   `LIVE SCRAPE`, or `PROVENANCE UNKNOWN`. The active WebSocket connection is displayed separately
   as `WEBSOCKET LIVE`, ensuring stream health is visible without misrepresenting synthetic data. There is no path that sets `LIVE SCRAPE`
   independently of genuine scraping rows.
3. **`scripts/audit_provenance.py` fails closed.** It exits non-zero if any row
   claims to be live without corroborating telemetry, a scraping run, proxy
   evidence, and scrape-time diversity.
4. **Data provenance is rigorously tested.** The feed distinguishes stream connectivity (`WEBSOCKET LIVE`) from data calibration (`DGCA BENCHMARK`), and
   the provenance badge is contract-tested in
   `frontend/scripts/verify-mock-data.ts`.

A prior defect, now fixed: `amadeus.py` labelled generated mock records
`is_synthetic=False`, so a live run would have persisted invented fares as real
and earned a false `LIVE` badge. 450 rows previously mislabelled were re-flagged.

## Fare component splits, calibrations, and recomposition integrity

**Base fare versus taxes and calibrated ratios.** Rather than using a fixed 0.78 constant everywhere, the system utilizes route- and carrier-aware calibrated ratios grounded in Indian domestic airline economics:
- **Carrier differentiation:** Full-Service Carriers (Air India `AI`) bundle 25kg checked baggage, complimentary meals, and seat selection into the base fare, yielding higher base proportions (~0.81). Low-Cost Carriers (IndiGo `6E`, Akasa Air `QP`, Air India Express `IX`, SpiceJet `SG`) unbundle ancillaries and levy separate fees, yielding base ratios between 0.74 and 0.78.
- **Route distance and airport fee scaling:** Fixed passenger airport charges (User Development Fee / UDF, Passenger Service Fee / PSF, and Aviation Security Fee / ASF) represent a larger percentage of short-haul low fares (e.g. BLR-HYD ~500km, base ratio 0.72) and a smaller percentage of long-haul high fares (e.g. DEL-BLR, DEL-MAA ~1750km, base ratio 0.81).
- **Explicit `fare_split_basis` labels:**
  - `measured`: Both base and taxes supplied directly by the source.
  - `residual`: One side supplied directly; the other derived as residual of total.
  - `calibrated`: Route- and carrier-aware calibrated ratio applied when components are omitted.
  - `estimated`: Uncalibrated fallback (`DEFAULT_BASE_FARE_RATIO = 0.78`) when carrier and route are unknown.
- **Total recomposition integrity check:** When components exist, the system enforces `abs(total - (base + taxes + UDF + convenience)) <= max(1.0, 0.005 * total)`. Any violating observation is quarantined with `index_exclusion_reason = "split_recomposition_mismatch"`.
- **Policy for sparse windows (< 4 Tukey peers):** When fewer than 4 payable peer quotes exist within the 30-day lookback window on a corridor-window slice, quartiles cannot be statistically identified. In sparse windows, no outlier fence is applied (all payable quotes remain index-eligible with `index_exclusion_reason = None`), avoiding false censorship on thin routes while structural checks (cancelled/sold-out status and recomposition mismatch) remain active.

**Carrier market shares and advance-purchase weights.** The carrier market shares
and the advance-purchase weights are documented calibrations. City-pair route
traffic weights are now transcribed from real DGCA monthly city-pair XLSX releases:
240 of 270 rows in `data/dgca_passenger_traffic_weights.json` and `.csv` carry
`provenance="DGCA"` (`is_synthetic=False`) with a per-row source URL and release
citation (HTTP Last-Modified date). The 30 rows for 2025-10/11/12 remain
`provenance="calibrated_baseline"` (`is_synthetic=True`) because those three XLSX
files return HTTP 403; per issue #7 they are never relabelled without a real
per-row citation. DGCA does not publish high-frequency fare microdata or flight
fare feeds (Lok Sabha Unstarred Question 1934, answered 30 July 2026), so fare-side
calibrations remain labelled as they are.

## Withdrawn comparisons and known index limits

**The bundled MoSPI CPI series is withdrawn.** `data/mospi_cpi_historical_2024_2026.json` declares `"status": "withdrawn"`: its stored values contradicted NSO press notes, and the file now carries no records. Any comparison plotted against it is modelled, not a MoSPI benchmark, and the withdrawn values must never be presented as a current official release.

**DGCA publishes no reusable fare dataset.** Its Tariff Monitoring Unit monitors fares but releases no dataset, dashboard, or route list — so no measured back-test against DGCA fares exists. (DGCA *traffic* volumes are a separate matter: the real monthly city-pair XLSX releases have now been transcribed into the weights files for 24 of 27 table months; fare levels still do not exist as open data.)

**The Fisher index here fails factor reversal by design.** The Paasche leg is textbook; the Laspeyres leg is a fixed-weight mean of price relatives rather than a true Laspeyres, so `P_F x Q_F == V_t / V_0` does not hold for the engine pair. `tests/test_factor_reversal.py` proves both halves (`test_factor_reversal_holds_for_the_true_laspeyres_paasche_pair` passes for the true pair; `test_engine_fisher_pair_does_not_satisfy_factor_reversal` proves the engine pair fails). Time reversal is asserted.

**Live and synthetic fares coexist by name.** Of the 36 rows in the current
database, 23 are SpiceJet live rows (`is_synthetic=false`, measured split, audit
corroborated) and 13 are fallback rows from `SyntheticFlightGenerator`
(`ingestion/crawlers/synthetic.py:52`), reached when a live query yields zero
records and persisted with `is_synthetic=true`. Route and traffic weights are transcribed from real DGCA monthly city-pair releases for 240 of 270 rows (`provenance=DGCA`, `is_synthetic=false`, per-row source URL and release citation); the 30 rows for 2025-10/11/12 keep `provenance=calibrated_baseline` (`is_synthetic=true`) until their XLSX releases are reachable.

## Evidence paths

Paths like `evidence/live-ingestion-verification.json` refer to local verification
artifacts from the audit campaign. They are intentionally **not committed**, so
those references will not resolve from a fresh clone. Every quantitative claim
here is reproducible from the committed test suite and `scripts/audit_provenance.py`.

## What would close the gap

Live collection began **2026-09-28** (23 provenance-audited SpiceJet rows, `is_synthetic=0`); the 30-day clock for the back-test harness starts from that date, not from this document's earlier "zero live rows" era.

Running the worker in live mode daily for 30 days. The back-test harness
(`scripts/backtest_vs_mospi.py`) computes the estimator correctly and **exits
non-zero rather than printing a verdict** until 30 days of Fisher index history
exist. It is time, not code.
