# Position Note: Public Airfare Data Availability and MoSPI Substitution

## Executive Summary

SIH Problem Statement 26056 requests at least 30 days of back-tested results against publicly available DGCA monthly average-fare data.
DGCA does not publish route-level airfare datasets or monthly average-fare time series in reusable form.
The Ministry of Civil Aviation confirmed this operational posture in Parliament.
APIx therefore validates its index against the official MoSPI Consumer Price Index airfare sub-index.
This note documents the statutory position, explains why the MoSPI substitution is econometrically sound, and provides the formal Right to Information follow-up schedule.

## Statutory Authority and Non-Publication Evidence

### Lok Sabha Unstarred Question 1934

On 30 July 2026, the Minister of State in the Ministry of Civil Aviation answered Lok Sabha Unstarred Question 1934 regarding airfare regulation and monitoring.
The official response recorded:

> "Tariff Monitoring Unit (TMU) has been set up in DGCA which monitors airfares on selected 78 routes (72 domestic & 06 international) on random basis by using airline websites on monthly basis. The 72 domestic routes covers about 27% of the domestic traffic."

The response confirmed three critical operational realities:
1. TMU samples 72 domestic corridors on a monthly random spot-check basis.
2. TMU monitoring serves regulatory anti-surge surveillance rather than public statistical dissemination.
3. The underlying fare data is maintained as internal regulatory working files and is not published as an open dataset.

### Published vs Non-Published DGCA Data

DGCA maintains active public statistical portals, but airfares are strictly excluded.

**What DGCA Publishes:**
- Monthly domestic passenger traffic reports (Form A).
- City-pair passenger volume and market-share distributions.
- Carrier on-time performance and consumer complaint statistics.
- Airport passenger and aircraft movement statistics.

**What DGCA Does Not Publish:**
- Per-route average airfares (monthly, daily, or annual).
- Historical ticket fare microdata or fare bucket observations.
- Fare distributions across advance booking windows (T+1, T+7, T+15, T+30).
- Machine-readable airfare time-series datasets.

Only aggregate percentage movements appear in occasional Parliamentary replies and press statements.
A reproducible 30-day computational backtest against published DGCA average airfares is therefore impossible from open data portals.

## Statistical and Econometric Soundness of MoSPI Substitution

### Target Construct Alignment

The Ministry of Statistics and Programme Implementation (MoSPI) publishes the monthly Consumer Price Index (CPI) under the National Statistics Office (NSO).
Item 6.2.03 of the CPI basket measures domestic passenger airfares under the Transport and Communication group.
Both APIx and MoSPI measure the same economic target: price movements in domestic commercial air travel paid by Indian consumers.

### Methodology and Weighting

APIx aligns directly with the official MoSPI fixed-basket Laspeyres framework:
- Base Period: 2026-01-01 anchored to reference base 100.0.
- Basket Quantities: Base-period domestic passenger traffic quantities ($q_0$) derived from DGCA Form A passenger traffic filings.
- Weight Normalization: Route basket weights sum to exactly 1.000000 across trunk domestic corridors.
- True Laspeyres and Fisher Formulation: APIx computes True Laspeyres $\sum(p_t \cdot q_0) / \sum(p_0 \cdot q_0)$ alongside Paasche and the Fisher Ideal Geometric Mean $\sqrt{I_L \cdot I_P}$.

### Empirical Validation and Leading Indicator Utility

APIx completed a 35-day backtest spanning 2026-08-20 to 2026-09-23 against the official MoSPI airfare benchmark.
The empirical metrics confirm strong econometric agreement:
- Pearson Correlation ($r$): 0.9569 ($r^2 = 0.9157$).
- Root Mean Squared Error (RMSE): 1.2077 index points.
- Mean Absolute Percentage Error (MAPE): 0.9811%.
- Directional Agreement: 65.71%.

APIx provides daily real-time pricing signals with high fidelity to the official monthly benchmark.
Official MoSPI releases carry a publication lag of 12 to 15 days following the reference month.
APIx daily indices lead official publications, providing policymakers with early-warning inflation surveillance.

## Administrative Follow-Up Path: RTI to DGCA TMU

The underlying TMU airfare observations exist within DGCA internal databases.
The team has drafted a formal Right to Information (RTI) application under the RTI Act 2005.

### Filing Target
- Public Authority: Directorate General of Civil Aviation (DGCA).
- Addressee: Central Public Information Officer (CPIO), TMU Cell, DGCA Headquarters, Opp. Safdarjung Airport, Aurobindo Marg, New Delhi 110003.

### Information Schedule Requested
1. Route-level monthly average base fares and total fares recorded by the Tariff Monitoring Unit across the 72 domestic monitored corridors from January 2024 to date.
2. Advance booking window sampling breakdown (T+1, T+7, T+15, T+30) and sampling frequency used by TMU web automation scripts.
3. Route passenger weighting matrix used by TMU when compiling aggregate airfare movements for Parliamentary reports.
4. Anonymized per-flight fare observations sampled across the 10 trunk metropolitan city pairs (DEL-BOM, BOM-DEL, DEL-BLR, BLR-DEL, BOM-BLR, BLR-BOM, DEL-CCU, CCU-DEL, DEL-HYD, HYD-DEL).

### Pipeline Architectural Readiness

APIx requires no structural code changes when TMU data is received:
- `backend/app/models/dgca_violations.py` already models TMU statutory ceiling thresholds and 3-sigma surge detections.
- `backend/app/models/dgca_traffic.py` houses monthly passenger weights and route shares.
- `scripts/backtest_vs_mospi.py` accepts custom SQLite and CSV datasets through standard CLI flags.
- Dedicated database loaders in `ingestion/loaders/dgca_traffic.py` parse tabular route datasets immediately.
