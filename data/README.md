# Data Provenance and Integrity Manifest

This directory contains reference datasets, benchmark series, and traffic weights used by APIx.
APIx enforces strict anti-fabrication standards.
No synthetic or calibrated series may be presented as an unverified official government release.

## Summary of Datasets

| File | Status | Provenance | Purpose |
|---|---|---|---|
| `dgca_passenger_traffic_weights.csv` | Calibrated Baseline Proxy | Calibrated (`is_synthetic: true`) | Trunk corridor volume weights |
| `dgca_passenger_traffic_weights.json` | Calibrated Baseline Proxy | Calibrated (`is_synthetic: true`) | Structured route traffic shares |
| `mospi_cpi_historical_2024_2026.csv` | Withdrawn | Withdrawn (`official: false`) | Tombstone for removed invented series |
| `mospi_cpi_historical_2024_2026.json` | Withdrawn | Withdrawn (`official: false`) | Audit log of NSO contradictions |

## DGCA Passenger Traffic Weights

- Files: `dgca_passenger_traffic_weights.csv`, `dgca_passenger_traffic_weights.json`
- Status: CALIBRATED BASELINE PROXY.
- Official Designation: Not an official programmatic DGCA feed.

### Publication Scope and Regulatory Context
The Directorate General of Civil Aviation (DGCA) publishes aggregate domestic passenger traffic statistics. These public releases consist of monthly top city-pair traffic rankings and annual civil aviation statistics handbooks.

DGCA does not publish high-frequency programmatic microdata or flight fare feeds. This fact was affirmed in Parliament in Lok Sabha Unstarred Question 1934, answered on 30 July 2026. As stated in that reply, the Tariff Monitoring Unit (TMU) monitors airfares across selected routes by sampling airline websites, but does not publish underlying route fare microdata or programmatic feeds.

### Calibrated Proxy Status
Because programmatic microdata is not published by DGCA, the weights in these files are calibrated proxies derived from published DGCA city-pair traffic rankings and normalized across monitored trunk corridors.

Every record in these files is marked with `provenance: "calibrated_baseline"` and `is_synthetic: true`. These weights reflect calibrated baseline proxies rather than an official programmatic release.

### Invariants Maintained
1. Weights across active trunk corridors sum to exactly 1.000000 for every monitored monthly period.
2. Directional pairs maintain operational symmetry (for example, DEL-BOM and BOM-DEL).
3. Every record explicitly flags `provenance: "calibrated_baseline"` and `is_synthetic: true`.

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
