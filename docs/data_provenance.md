# Data provenance and source status

This document records exactly what APIx has and has not measured. It is the
reference for the short summary in the [README](../README.md).

The rule the project follows: **a number is only presented as a measurement when
it was read from a real source.** Everything else is labelled, and the label is
enforced in code rather than promised in prose.

## Summary

| Question | Answer |
| --- | --- |
| Has a live airfare ever been read? | **No.** Not one. |
| Rows claiming to be live in the database | **0** |
| Are scrapers implemented for all 11 PS-named portals? | Yes, as registered classes |
| Do any of them currently produce a fare? | **No.** Every one is blocked or fare-less. |
| Is the dashboard badge honest? | Yes. It separates stream status (`WEBSOCKET LIVE`) from data provenance (`DGCA BENCHMARK` / `LIVE SCRAPE`), and cannot claim `LIVE SCRAPE` without a corroborated scrape. |
| Is the route weighting official DGCA data? | **No.** It is modelled, and labelled as such. |

`GET /api/v1/health` reports this machine-readably:

```json
{
  "ps_named_sources_total": 11,
  "ps_named_sources_implemented": 11,
  "produces_live_fares": false,
  "live_verified_sources": []
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
| SpiceJet | HTTP 200, no `Disallow` on the API path | Reachable, but publishes no structured fare. |
| EaseMyTrip | HTTP 200 | Reachable, but no fare has been read. |

A robots denial, HTTP 403, CAPTCHA, or a page without a fare yields **zero live
records and an explicit reason**, then falls through to the synthetic tier with
`is_synthetic=true`. No fare is ever invented to fill a gap.

IndiGo and Air India also run partner-gated NDC portals
(`developer.goindigo.in`, `ndc.airindia.com`). Those are distribution APIs, not
the public booking pages these scrapers call, and no credentials were available.

## What is genuinely reachable

SpiceJet's availability endpoint answers and yields unambiguous flight identity:

```
GET https://www.spicejet.com/api/v3/search/availability
HTTP 200, 17777 bytes, data.trips[]
  -> SG 815, DEL 09:50 -> BOM 12:25
```

Two things stop that becoming a fare.

**There is no structured fare field.** The price is embedded in an opaque key that
decodes to fragments such as `USAV~5511~~0~665~` and
`X!0:48004:1004:854:5994:2364:1524:895:280`. The mapping is undocumented, so no
fare was guessed.

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

## Two things that are estimates, not measurements

**Base fare versus taxes.** The columns exist and are separate, but when a source
does not supply the split it is synthesised by a single documented constant,
`ESTIMATED_BASE_FARE_RATIO = 0.78`. Do not present base-versus-tax figures as
measured. UDF and convenience charges stay `NULL` unless a source reports them.

**Carrier market shares and advance-purchase weights.** The carrier market shares
and the advance-purchase weights are documented calibrations. City-pair route
traffic weights and passenger volumes are now ingested from official DGCA Form A
Monthly Scheduled Domestic Passenger Traffic releases into
`data/dgca_passenger_traffic_weights.json` and `.csv` under explicit
`provenance="dgca_published"` (`is_synthetic=False`), sourced from the DGCA
Air Traffic Statistics Portal (`https://www.dgca.gov.in/digigov-portal/?page=4264/4206/servicename`).

## Withdrawn comparisons and known index limits

**The bundled MoSPI CPI series is withdrawn.** `data/mospi_cpi_historical_2024_2026.json` declares `"status": "withdrawn"`: its stored values contradicted NSO press notes, and the file now carries no records. Any comparison plotted against it is modelled, not a MoSPI benchmark, and the withdrawn values must never be presented as a current official release.

**DGCA publishes no reusable fare dataset.** Its Tariff Monitoring Unit monitors fares but releases no dataset, dashboard, or route list — so no measured back-test against DGCA fares exists. (DGCA *traffic* volumes are a separate matter: real monthly city-pair XLSX files exist and are the intended replacement for the modelled weights above; fare levels do not.)

**The Fisher index here fails factor reversal by design.** The Paasche leg is textbook; the Laspeyres leg is a fixed-weight mean of price relatives rather than a true Laspeyres, so `P_F x Q_F == V_t / V_0` does not hold for the engine pair. `tests/test_factor_reversal.py` proves both halves (`test_factor_reversal_holds_for_the_true_laspeyres_paasche_pair` passes for the true pair; `test_engine_fisher_pair_does_not_satisfy_factor_reversal` proves the engine pair fails). Time reversal is asserted.

**Deployed fares are synthetic by name.** The fallback that produces every fare in the system today is `SyntheticFlightGenerator` (`ingestion/crawlers/synthetic.py:52`), reached only after the live scrapers yield zero records, and its output is persisted with `is_synthetic=true`. Route and traffic weights carry verified `provenance=dgca_published` from official DGCA Form A releases.

## Evidence paths

Paths like `evidence/live-ingestion-verification.json` refer to local verification
artifacts from the audit campaign. They are intentionally **not committed**, so
those references will not resolve from a fresh clone. Every quantitative claim
here is reproducible from the committed test suite and `scripts/audit_provenance.py`.

## What would close the gap

Running the worker in live mode daily for 30 days. The back-test harness
(`scripts/backtest_vs_mospi.py`) computes the estimator correctly and **exits
non-zero rather than printing a verdict** until 30 days of Fisher index history
exist. It is time, not code.
