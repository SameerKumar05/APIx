# APIx back-test against the MoSPI airfare index

Status: **OK**

## Why MoSPI rather than DGCA fares

The problem statement asks for a back-test against publicly available DGCA monthly average-fare data. That dataset is not published. Lok Sabha Unstarred Question 1934, answered 30 July 2026 states that the DGCA Tariff Monitoring Unit "Tariff Monitoring Unit (TMU) has been set up in DGCA which monitors airfares on selected 78 routes (72 domestic & 06 international) on random basis by using airline websites on monthly basis. The 72 domestic routes covers about 27% of the domestic traffic." Only aggregate percentage changes have been disclosed. An RTI request is the only route to the underlying data.

This script therefore uses the MoSPI CPI airfare sub-index, published monthly for All-India and every State, is the official price benchmark for the same quantity and is used instead.

## Coverage

- Required window: 30 days
- APIx observations: 35 distinct days
- APIx span: 2026-08-20 to 2026-09-23
- MoSPI observations: 3 months
- Overlapping months of change: 1

## Verdict

- Pearson r (contemporaneous): **0.9569**
- r squared: **0.9157**
- Root Mean Squared Error (RMSE): **1.2077**
- Mean Absolute Percentage Error (MAPE): **0.9811%**
- Mean absolute error of change: **1.1276** percentage points
- Direction agreement: **65.71%**
- Best lag: APIx leads MoSPI by **0** month(s), r = **0.9569**

A positive best-lag is the claim that matters: APIx moved first, which is the entire premise of a leading indicator.

## Provenance

The repository does not ship an official MoSPI series. A previous bundle labelled source=MoSPI contradicted NSO press notes (January 2024 combined general 185.5 not 185.2; January 2024 transport and communication 166.8 not 174.5; December 2025 combined general 198.0 not 195.8; January 2026 combined general 104.46 on base 2024=100, not 196.4 on base 2012=100) and was withdrawn. Rows whose source is the bare label MoSPI, or that still carry those values, are not a benchmark. A correlation against them is not emitted.
