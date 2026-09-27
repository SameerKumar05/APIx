# Data Provenance and Baseline Calibrations

This directory contains reference datasets and calibrated baseline weights for APIx.

## DGCA Domestic Passenger Traffic Data

The files `dgca_passenger_traffic_weights.csv` and `dgca_passenger_traffic_weights.json` provide corridor weights and passenger volume baselines.

### Publication Scope and Regulatory Context

The Directorate General of Civil Aviation (DGCA) publishes aggregate domestic passenger traffic statistics. These public releases consist of monthly top city-pair traffic rankings and annual civil aviation statistics handbooks.

DGCA does not publish high-frequency programmatic microdata or flight fare feeds. This fact was affirmed in Parliament in Lok Sabha Unstarred Question 1934, answered on 30 July 2026. As stated in that reply, the Tariff Monitoring Unit (TMU) monitors airfares across selected routes by sampling airline websites, but does not publish underlying route fare microdata or programmatic feeds.

### Calibrated Proxy Status

Because programmatic microdata is not published by DGCA, the weights in these files are calibrated proxies. They are derived from published DGCA city-pair traffic rankings and normalized across monitored trunk corridors.

Every record in these files is marked with `provenance: "calibrated_baseline"` and `is_synthetic: true`. These weights reflect calibrated baseline proxies rather than an official programmatic release.

## Bundled Datasets

1. `dgca_passenger_traffic_weights.csv`: Calibrated monthly city-pair traffic proxy weights across monitored trunk routes.
2. `dgca_passenger_traffic_weights.json`: JSON format of the calibrated city-pair traffic proxy dataset.
3. `mospi_cpi_historical_2024_2026.csv`: Historical CPI reference table.
4. `mospi_cpi_historical_2024_2026.json`: MoSPI CPI benchmark records with explicit status tracking.
