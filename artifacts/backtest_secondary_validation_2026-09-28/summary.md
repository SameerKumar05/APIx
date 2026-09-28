# Secondary validation of the 35-day back-test window

- Window: 36 daily APIx points (2026-08-20 to 2026-09-28)

## Internal-consistency invariants (MoSPI-independent)

Scope: pure index-engine mathematics; no MoSPI, DGCA or other external data involved.

| check | max abs error | tolerance | passed |
| --- | --- | --- | --- |
| uniform_scaling_linearity | 0.000e+00 | 1e-09 | yes |
| base_period_identity | 0.000e+00 | 1e-09 | yes |
| fisher_geometric_mean_and_bounds | 0.000e+00 | 1e-09 | yes |
| booking_window_weights_sum_to_one | 0.000e+00 | 1e-09 | yes |
| weighted_median_scalar_identity | 0.000e+00 | 1e-09 | yes |
| composite_fare_homogeneity | 0.000e+00 | 1e-09 | yes |

All invariants passed: **True**

## Holdout-week replication

- Fitted on 29 days, held out 7 days (2026-09-18 to 2026-09-28).
- Train r: 0.9726
- Holdout r: None
- Holdout MAPE: 4.5014%
- Holdout MAE: 7.0021
- Holdout worst day: 28.1519%

## Lead-lag stability across sub-windows

- Full window: r(lag 0) = 0.3324, best lag = -3 day(s) with r = 0.9578.
- Best lags by sub-window: [0, 3, 3] (spread 3 day(s), stable: False).

| sub-window | days | r at lag 0 | best lag (days) | r at best lag |
| --- | --- | --- | --- | --- |
| 0..12 | 12 | 0.8243 | 0 | 0.8243 |
| 12..24 | 12 | 0.8213 | 3 | 0.8914 |
| 24..36 | 12 | 0.1358 | 3 | 0.196 |

## Scope

Sections beyond the invariants stress the relationship already implied by the three in-window benchmark anchors. They add no MoSPI observations and do not change r=0.9569 over n=3 overlapping months.
