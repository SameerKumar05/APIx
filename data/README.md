# Data Provenance and Integrity Manifest

This directory contains reference datasets, benchmark series, and traffic weights used by APIx.
APIx enforces strict anti-fabrication standards.
No synthetic or calibrated series may be presented as an unverified official government release.

## Summary of Datasets

| File | Status | Provenance | Purpose |
|---|---|---|---|
| `dgca_passenger_traffic_weights.csv` | Mixed: DGCA transcribed (240 rows) + calibrated remainder (30 rows) | Per-row `DGCA` / `calibrated_baseline` | Trunk corridor volume weights |
| `dgca_passenger_traffic_weights.json` | Mixed: DGCA transcribed (240 rows) + calibrated remainder (30 rows) | Per-row `DGCA` / `calibrated_baseline` | Structured route traffic shares |
| `mospi_cpi_historical_2024_2026.csv` | Withdrawn | Withdrawn (`official: false`) | Tombstone for removed invented series |
| `mospi_cpi_historical_2024_2026.json` | Withdrawn | Withdrawn (`official: false`) | Audit log of NSO contradictions |

## DGCA Passenger Traffic Weights

- Files: `dgca_passenger_traffic_weights.csv`, `dgca_passenger_traffic_weights.json`
- Status: MIXED. 240 of 270 rows are transcribed from real DGCA monthly city-pair releases (`provenance: "DGCA"`, `is_synthetic: false`, per-row source URL and release citation). The remaining 30 rows (2025-10, 2025-11, 2025-12) stay `provenance: "calibrated_baseline"` because those three XLSX releases return HTTP 403.
- Official Designation: DGCA-sourced rows cite the DGCA release per row; this file itself is a project transcription, not an official programmatic DGCA feed.

### Publication Scope and Regulatory Context
The Directorate General of Civil Aviation (DGCA) publishes aggregate domestic passenger traffic statistics. These public releases include downloadable monthly city-pair traffic XLSX tables (`DOM CITYPAIR DATA, <MONTH> <YYYY>.xlsx`), monthly top city-pair traffic rankings, and annual civil aviation statistics handbooks.

DGCA does not publish high-frequency programmatic microdata or flight fare feeds. This fact was affirmed in Parliament in Lok Sabha Unstarred Question 1934, answered on 30 July 2026. As stated in that reply, the Tariff Monitoring Unit (TMU) monitors airfares across selected routes by sampling airline websites, but does not publish underlying route fare microdata or programmatic feeds.

### Provenance Status
240 rows (2024-01 through 2026-03, excluding 2025-10/11/12) were transcribed from DGCA's published monthly city-pair XLSX releases by `scripts/ingest_dgca_citypair.py`. Each transcribed row carries `provenance: "DGCA"`, `is_synthetic: false`, a `source_url` pointing at the DGCA release, and a `release_date` citation (HTTP Last-Modified date of the XLSX file).

The 30 rows for 2025-10, 2025-11, and 2025-12 could not be transcribed: all three XLSX files return HTTP 403 on every known URL variant. Those rows retain the prior calibrated values, marked `provenance: "calibrated_baseline"` and `is_synthetic: true`, per the no-relabeling rule (issue #7: any row lacking a real per-row citation stays calibrated). Calibrated rows average ~1.82x the real monthly totals, so expect a material downward correction when those releases become reachable.

### Invariants Maintained
1. Weights across active trunk corridors sum to exactly 1.000000 for every monitored monthly period.
2. Directional pairs both have rows for every period (real data is asymmetric: DEL-BOM and BOM-DEL differ in volume).
3. Every record carries an explicit `provenance` value: `"DGCA"` with `is_synthetic: false` for transcribed rows (source URL + release citation required), `"calibrated_baseline"` with `is_synthetic: true` for the remainder.

## MoSPI CPI Historical Series

- Files: `mospi_cpi_historical_2024_2026.csv`, `mospi_cpi_historical_2024_2026.json`
- Status: WITHDRAWN.
- Official Designation: Unofficial and removed.

### Provenance History
An earlier iteration of the project bundled an unverified series marked `source=MoSPI`.
A rigorous audit against official National Statistics Office (NSO) press releases revealed material discrepancies:
1. January 2024 CPI General Combined: Official NSO press release states 185.5. The withdrawn file recorded 185.2.
2. January 2024 Transport and Communication: Official NSO press release states 166.8. The withdrawn file recorded 174.5.
3. December 2025 CPI General Combined: Official NSO press release states 198.0. The withdrawn file recorded 195.8.
4. January 2026 Rebasing: Effective January 2026, NSO transitioned CPI to base 2024=100 (value 104.46). The withdrawn file erroneously extrapolated base 2012=100 (value 196.4).

### Audit Action Taken
The entire unverified dataset was permanently withdrawn.
The CSV and JSON files serve as immutable audit tombstones.
APIx rejects bare `source=MoSPI` inputs to prevent unverified data from influencing econometric indices.
Demonstration backtesting executes against isolated, reproducible benchmark tables that pass all mathematical invariant gates.
