#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
for _p in (str(_PROJECT_ROOT), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import backtest_vs_mospi as bt  # noqa: E402

from backend.app.services.index_engine import (  # noqa: E402
    DEFAULT_BOOKING_WINDOW_WEIGHTS,
    DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
    calculate_fisher_index,
    calculate_laspeyres_index,
    calculate_paasche_index,
    calculate_route_composite_fare,
    weighted_median_values,
)

HOLDOUT_DAYS = 7
MAX_LAG_DAYS = 7
SUBWINDOW_COUNT = 3
INVARIANT_ABS_TOL = 1e-9

_BASE_BASKET: dict[str, float] = {
    "DEL-BOM": 5500.0,
    "BOM-DEL": 5450.0,
    "BLR-DEL": 6200.0,
    "DEL-BLR": 6150.0,
    "BOM-BLR": 4100.0,
    "BLR-BOM": 4050.0,
    "DEL-CCU": 4800.0,
    "CCU-DEL": 4750.0,
    "DEL-HYD": 4500.0,
    "HYD-DEL": 4450.0,
}


def load_daily_pairs(db_path: str) -> list[tuple[str, float, float]]:
    conn = sqlite3.connect(db_path)
    try:
        daily = bt.load_apix_daily(conn)
        mospi = bt.load_mospi(conn)
    finally:
        conn.close()
    points = bt.build_bench_points(mospi)
    if not points:
        return []
    pairs: list[tuple[str, float, float]] = []
    for d_str, a_val in daily:
        try:
            o = date.fromisoformat(d_str[:10]).toordinal()
        except ValueError:
            continue
        pairs.append((d_str, a_val, bt.bench_value_at(points, o)))
    return pairs


def ols_fit(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return my - slope * mx, slope


def holdout_report(
    pairs: list[tuple[str, float, float]], holdout_days: int = HOLDOUT_DAYS
) -> dict[str, Any]:
    if len(pairs) < 2 * holdout_days:
        return {
            "status": "skipped",
            "reason": (
                f"needs at least {2 * holdout_days} daily points to train on "
                f"{len(pairs) - holdout_days} and hold out {holdout_days}"
            ),
        }
    train, test = pairs[:-holdout_days], pairs[-holdout_days:]
    fit = ols_fit([b for _, _, b in train], [a for _, a, _ in train])
    if fit is None:
        return {"status": "skipped", "reason": "training fit is degenerate"}
    intercept, slope = fit
    preds = [intercept + slope * b for _, _, b in test]
    actual = [a for _, a, _ in test]
    train_r = bt.pearson([b for _, _, b in train], [a for _, a, _ in train])
    holdout_r = bt.pearson(actual, preds)
    abs_pct = [abs(p - a) / abs(a) * 100.0 for p, a in zip(preds, actual) if a != 0]
    report: dict[str, Any] = {
        "status": "computed",
        "train_days": len(train),
        "holdout_days": len(test),
        "holdout_span": [test[0][0], test[-1][0]],
        "fitted_intercept": round(intercept, 6),
        "fitted_slope": round(slope, 6),
        "train_r": None if train_r is None else round(train_r, 4),
        "holdout_r": None if holdout_r is None else round(holdout_r, 4),
        "holdout_mape_pct": round(sum(abs_pct) / len(abs_pct), 4) if abs_pct else None,
        "holdout_mae": round(
            sum(abs(p - a) for p, a in zip(preds, actual)) / len(actual), 4
        ),
        "holdout_max_abs_pct": round(max(abs_pct), 4) if abs_pct else None,
        "note": (
            "Relationship fitted on the first "
            f"{len(train)} days predicts the final {len(test)} days; the three "
            "in-window benchmark anchors are the only external input."
        ),
    }
    if holdout_r is None:
        report["holdout_r_reason"] = (
            "prediction is constant across the holdout week, so correlation is "
            "undefined; the benchmark interpolant is clamped at the last anchor "
            "(mid-month of the final benchmark month) and has no variation "
            "inside the holdout week. Level agreement is reported as MAPE/MAE."
        )
    return report


def lagged_pearson(a: list[float], b: list[float], lag: int) -> float | None:
    n = len(a)
    if lag > 0:
        xs, ys = a[lag:], b[: n - lag]
    elif lag < 0:
        xs, ys = a[: n + lag], b[-lag:]
    else:
        xs, ys = a, b
    return bt.pearson(xs, ys)


def _best_lag(
    a: list[float], b: list[float], max_lag: int
) -> tuple[int | None, float | None]:
    best_lag, best_r = 0, lagged_pearson(a, b, 0)
    for lag in range(1, max_lag + 1):
        for cand_lag in (lag, -lag):
            cand = lagged_pearson(a, b, cand_lag)
            if cand is None:
                continue
            if best_r is None or cand > best_r + 1e-12:
                best_lag, best_r = cand_lag, cand
            elif (
                best_r is not None
                and abs(cand - best_r) <= 1e-12
                and abs(cand_lag) < abs(best_lag)
            ):
                best_lag, best_r = cand_lag, cand
    return best_lag, best_r


def lead_lag_report(
    apix: list[float],
    bench: list[float],
    subwindow_count: int = SUBWINDOW_COUNT,
    max_lag: int = MAX_LAG_DAYS,
) -> dict[str, Any]:
    n = len(apix)
    if n < subwindow_count * 3:
        return {"status": "skipped", "reason": f"only {n} daily points"}
    size = n // subwindow_count
    windows = []
    for i in range(subwindow_count):
        start = i * size
        end = n if i == subwindow_count - 1 else (i + 1) * size
        sub_a, sub_b = apix[start:end], bench[start:end]
        window_lag = min(max_lag, max(1, len(sub_a) // 4))
        best_lag, best_r = _best_lag(sub_a, sub_b, window_lag)
        windows.append(
            {
                "start": start,
                "end": end,
                "days": len(sub_a),
                "r_at_lag_0": _round(lagged_pearson(sub_a, sub_b, 0)),
                "best_lag_days": best_lag,
                "r_at_best_lag": _round(best_r),
                "max_lag_searched": window_lag,
            }
        )
    full_lag = min(max_lag, max(1, n // 4))
    full_best_lag, full_best_r = _best_lag(apix, bench, full_lag)
    best_lags = [w["best_lag_days"] for w in windows]
    return {
        "status": "computed",
        "days": n,
        "full_window": {
            "r_at_lag_0": _round(lagged_pearson(apix, bench, 0)),
            "best_lag_days": full_best_lag,
            "r_at_best_lag": _round(full_best_r),
            "max_lag_searched": full_lag,
        },
        "subwindows": windows,
        "best_lags": best_lags,
        "best_lag_spread_days": (
            (max(best_lags) - min(best_lags)) if best_lags else None
        ),
        "best_lag_stable": len(set(best_lags)) == 1,
        "note": (
            "Positive lag means the APIx value at t+lag matches the benchmark at t, "
            "i.e. APIx moved first. Uses only the three in-window anchors."
        ),
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def invariant_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, max_error: float, detail: str = "") -> None:
        checks.append(
            {
                "name": name,
                "max_abs_error": max_error,
                "tolerance": INVARIANT_ABS_TOL,
                "passed": bool(max_error <= INVARIANT_ABS_TOL),
                "detail": detail,
            }
        )

    scaling_errors = []
    for alpha in (1.20, 1.10, 0.85, 1.50):
        scaled = {r: f * alpha for r, f in _BASE_BASKET.items()}
        for weights in (DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES, None):
            idx = calculate_laspeyres_index(
                current_fares=scaled,
                base_fares=_BASE_BASKET,
                route_weights=weights,
                base_value=100.0,
            )
            scaling_errors.append(abs(idx - alpha * 100.0))
    add(
        "uniform_scaling_linearity",
        max(scaling_errors),
        "all prices x alpha moves the Laspeyres index by exactly alpha*100",
    )

    lasp = calculate_laspeyres_index(
        current_fares=dict(_BASE_BASKET),
        base_fares=_BASE_BASKET,
        route_weights=DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
        base_value=100.0,
    )
    paas = calculate_paasche_index(
        current_fares=dict(_BASE_BASKET),
        base_fares=_BASE_BASKET,
        current_traffic_weights=DEFAULT_DGCA_ROUTE_TRAFFIC_SHARES,
        base_value=100.0,
    )
    fisher = calculate_fisher_index(laspeyres=lasp, paasche=paas)
    add(
        "base_period_identity",
        max(abs(lasp - 100.0), abs(paas - 100.0), abs(fisher - 100.0)),
        "P_t == P_0 implies Laspeyres == Paasche == Fisher == 100",
    )

    fisher_errors = []
    for l_val, p_val in ((110.0, 108.0), (120.0, 115.0), (95.0, 92.0), (100.0, 100.0)):
        f_val = calculate_fisher_index(laspeyres=l_val, paasche=p_val)
        fisher_errors.append(abs(f_val - math.sqrt(l_val * p_val)))
        fisher_errors.append(
            max(0.0, min(l_val, p_val) - f_val, f_val - max(l_val, p_val))
        )
    add(
        "fisher_geometric_mean_and_bounds",
        max(fisher_errors),
        "Fisher == sqrt(L*P) and stays within [min(L,P), max(L,P)]",
    )

    add(
        "booking_window_weights_sum_to_one",
        abs(sum(DEFAULT_BOOKING_WINDOW_WEIGHTS.values()) - 1.0),
        "T1+T7+T15+T30+T45 shares total 1.0",
    )

    median_errors = []
    for scalar in (1500.0, 5420.75, 48500.0):
        for weights in (
            [0.2] * 5,
            [0.62, 0.20, 0.08, 0.05, 0.04],
            [0.95, 0.02, 0.01, 0.01, 0.01],
            [1.0],
        ):
            got = weighted_median_values([scalar] * len(weights), weights)
            median_errors.append(abs(got - scalar))
    add(
        "weighted_median_scalar_identity",
        max(median_errors),
        "equal prices collapse the weighted median to that price",
    )

    homogeneity_errors = []
    base_fares = {
        "T+1": 11500.0,
        "T+7": 8400.0,
        "T+15": 6200.0,
        "T+30": 4800.0,
        "T+45": 3900.0,
    }
    base_composite = calculate_route_composite_fare(base_fares)
    for alpha in (0.5, 1.25, 2.0):
        scaled = {k: v * alpha for k, v in base_fares.items()}
        homogeneity_errors.append(
            abs(calculate_route_composite_fare(scaled) - base_composite * alpha)
        )
    add(
        "composite_fare_homogeneity",
        max(homogeneity_errors),
        "C(alpha*P) == alpha*C(P) across booking windows",
    )

    return checks


def build_report(db_path: str) -> dict[str, Any]:
    pairs = load_daily_pairs(db_path)
    invariants = invariant_checks()
    report: dict[str, Any] = {
        "db": str(db_path),
        "window": {
            "apix_days": len(pairs),
            "apix_span": [pairs[0][0], pairs[-1][0]] if pairs else None,
        },
        "invariants": {
            "scope": (
                "pure index-engine mathematics; no MoSPI, DGCA or other external "
                "data involved"
            ),
            "checks": invariants,
            "all_passed": all(c["passed"] for c in invariants),
        },
        "holdout_week": holdout_report(pairs),
        "lead_lag": lead_lag_report([a for _, a, _ in pairs], [b for _, _, b in pairs]),
        "scope_note": (
            "Sections beyond the invariants stress the relationship already "
            "implied by the three in-window benchmark anchors. They add no MoSPI "
            "observations and do not change r=0.9569 over n=3 overlapping months."
        ),
    }
    report["all_checks_passed"] = bool(
        report["invariants"]["all_passed"]
        and report["holdout_week"]["status"] == "computed"
        and report["lead_lag"]["status"] == "computed"
    )
    return report


def render_markdown(report: dict[str, Any]) -> str:
    window = report["window"]
    inv = report["invariants"]
    hold = report["holdout_week"]
    lag = report["lead_lag"]
    lines = [
        "# Secondary validation of the 35-day back-test window",
        "",
        (
            f"- Window: {window['apix_days']} daily APIx points "
            f"({window['apix_span'][0]} to {window['apix_span'][1]})"
            if window["apix_span"]
            else f"- Window: {window['apix_days']} daily APIx points"
        ),
        "",
        "## Internal-consistency invariants (MoSPI-independent)",
        "",
        f"Scope: {inv['scope']}.",
        "",
        "| check | max abs error | tolerance | passed |",
        "| --- | --- | --- | --- |",
    ]
    for c in inv["checks"]:
        lines.append(
            f"| {c['name']} | {c['max_abs_error']:.3e} | {c['tolerance']:.0e} | "
            f"{'yes' if c['passed'] else 'NO'} |"
        )
    lines += ["", f"All invariants passed: **{inv['all_passed']}**", ""]
    lines += ["## Holdout-week replication", ""]
    if hold["status"] == "computed":
        lines += [
            f"- Fitted on {hold['train_days']} days, held out {hold['holdout_days']} days "
            f"({hold['holdout_span'][0]} to {hold['holdout_span'][1]}).",
            f"- Train r: {hold['train_r']}",
            f"- Holdout r: {hold['holdout_r']}",
            f"- Holdout MAPE: {hold['holdout_mape_pct']}%",
            f"- Holdout MAE: {hold['holdout_mae']}",
            f"- Holdout worst day: {hold['holdout_max_abs_pct']}%",
            "",
        ]
    else:
        lines += [f"Skipped: {hold['reason']}", ""]
    lines += ["## Lead-lag stability across sub-windows", ""]
    if lag["status"] == "computed":
        fw = lag["full_window"]
        lines += [
            f"- Full window: r(lag 0) = {fw['r_at_lag_0']}, best lag = "
            f"{fw['best_lag_days']} day(s) with r = {fw['r_at_best_lag']}.",
            f"- Best lags by sub-window: {lag['best_lags']} "
            f"(spread {lag['best_lag_spread_days']} day(s), stable: "
            f"{lag['best_lag_stable']}).",
            "",
            "| sub-window | days | r at lag 0 | best lag (days) | r at best lag |",
            "| --- | --- | --- | --- | --- |",
        ]
        for w in lag["subwindows"]:
            lines.append(
                f"| {w['start']}..{w['end']} | {w['days']} | {w['r_at_lag_0']} | "
                f"{w['best_lag_days']} | {w['r_at_best_lag']} |"
            )
        lines.append("")
    else:
        lines += [f"Skipped: {lag['reason']}", ""]
    lines += ["## Scope", "", report["scope_note"], ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Secondary validation of the back-test window: index-engine "
            "invariants, holdout-week replication and lead-lag stability."
        )
    )
    parser.add_argument("--db", default="apix.db", help="SQLite database path")
    parser.add_argument("--json-out", default=None, help="Write the report as JSON")
    parser.add_argument("--md-out", default=None, help="Write a markdown summary")
    args = parser.parse_args()

    report = build_report(args.db)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=2, default=str))
    if args.md_out:
        Path(args.md_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md_out).write_text(render_markdown(report))

    inv = report["invariants"]
    hold = report["holdout_week"]
    lag = report["lead_lag"]
    print("secondary validation:")
    print(f"  daily points       : {report['window']['apix_days']}")
    print(f"  invariants passed  : {inv['all_passed']} ({len(inv['checks'])} checks)")
    for c in inv["checks"]:
        marker = "ok " if c["passed"] else "FAIL"
        print(
            f"    [{marker}] {c['name']}: max abs err "
            f"{c['max_abs_error']:.3e} (tol {c['tolerance']:.0e})"
        )
    if hold["status"] == "computed":
        print(
            f"  holdout week       : r={hold['holdout_r']}, "
            f"MAPE={hold['holdout_mape_pct']}% "
            f"(train r={hold['train_r']} on {hold['train_days']} days)"
        )
    else:
        print(f"  holdout week       : skipped - {hold['reason']}")
    if lag["status"] == "computed":
        fw = lag["full_window"]
        print(
            f"  lead-lag           : full r(lag0)={fw['r_at_lag_0']}, best lag "
            f"{fw['best_lag_days']}d, sub-window lags {lag['best_lags']} "
            f"(stable={lag['best_lag_stable']})"
        )
    else:
        print(f"  lead-lag           : skipped - {lag['reason']}")
    print(f"  all checks passed  : {report['all_checks_passed']}")
    return 0 if report["all_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
