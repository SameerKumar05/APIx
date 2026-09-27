# Secondary validation of the 35-day back-test window

- Window: 35 daily APIx points (2026-08-20 to 2026-09-23)

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

- Fitted on 28 days, held out 7 days (2026-09-17 to 2026-09-23).
- Train r: 0.9709
- Holdout r: None
- Holdout MAPE: 0.487%
- Holdout MAE: 0.5654
- Holdout worst day: 1.0958%

## Lead-lag stability across sub-windows

- Full window: r(lag 0) = 0.9569, best lag = 6 day(s) with r = 0.9698.
- Best lags by sub-window: [0, 0, -3] (spread 3 day(s), stable: False).

| sub-window | days | r at lag 0 | best lag (days) | r at best lag |
| --- | --- | --- | --- | --- |
| 0..11 | 11 | 0.7723 | 0 | 0.7723 |
| 11..22 | 11 | 0.777 | 0 | 0.777 |
| 22..35 | 13 | 0.4697 | -3 | 0.5584 |

## Scope

Sections beyond the invariants stress the relationship already implied by the three in-window benchmark anchors. They add no MoSPI observations and do not change r=0.9569 over n=3 overlapping months.
