# Data Provenance and Integrity Manifest

This directory contains reference datasets, benchmark series, and traffic weights used by APIx.
APIx enforces strict anti-fabrication standards.
No synthetic or calibrated series may be presented as an unverified official government release.

## Summary of Datasets

| File | Status | Provenance | Purpose |
|---|---|---|---|
| `dgca_passenger_traffic_weights.csv` | Calibrated / Modelled | Generated (`is_synthetic: true`) | Trunk corridor volume weights |
| `dgca_passenger_traffic_weights.json` | Calibrated / Modelled | Generated (`is_synthetic: true`) | Structured route traffic shares |
| `mospi_cpi_historical_2024_2026.csv` | Withdrawn | Withdrawn (`official: false`) | Tombstone for removed invented series |
| `mospi_cpi_historical_2024_2026.json` | Withdrawn | Withdrawn (`official: false`) | Audit log of NSO contradictions |

## DGCA Passenger Traffic Weights

- Files: `dgca_passenger_traffic_weights.csv`, `dgca_passenger_traffic_weights.json`
- Status: GENERATED / MODELLED BENCHMARK.
- Official Designation: Not an official DGCA publication.

### Description
These files provide monthly domestic passenger volume distributions and route share weights across 10 trunk corridors for 27 monthly periods (2024-01 through 2026-03).
The values model realistic market distributions derived from public airline schedule density and published DGCA airport city-pair totals.

### Invariants Maintained
1. Weights across active trunk corridors sum to exactly 1.000000 for every monitored monthly period.
2. Directional pairs maintain operational symmetry (for example, DEL-BOM and BOM-DEL).
3. Every record explicitly flags `"provenance": "generated"` and `"is_synthetic": true`.

### Transition to Official Releases
DGCA publishes monthly domestic passenger traffic reports (Form A) as public spreadsheets.
When granular sector-level passenger tables are ingested, records will update to `"provenance": "dgca_published"` with reference publication dates.

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
