from __future__ import annotations

import pathlib
import random
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import backtest_secondary_validation as sv  # noqa: E402
import backtest_vs_mospi as bt  # noqa: E402


def test_invariants_all_pass() -> None:
    checks = sv.invariant_checks()
    failed = [c["name"] for c in checks if not c["passed"]]
    assert failed == [], f"invariant breach: {failed}"
    names = {c["name"] for c in checks}
    assert {"uniform_scaling_linearity", "base_period_identity"} <= names


def test_holdout_recovers_exact_linear_relationship() -> None:
    rng = random.Random(7)
    start = date(2026, 8, 20)
    pairs = []
    for i in range(35):
        bench = 100.0 + rng.uniform(-5.0, 5.0)
        day = (start + timedelta(days=i)).isoformat()
        pairs.append((day, 10.0 + 1.5 * bench, bench))

    report = sv.holdout_report(pairs)
    assert report["status"] == "computed"
    assert report["train_days"] == 28
    assert report["holdout_days"] == 7
    assert report["holdout_r"] == pytest.approx(1.0, abs=1e-9)
    assert report["holdout_mape_pct"] == pytest.approx(0.0, abs=1e-9)


def test_holdout_explains_undefined_r_on_flat_benchmark_segment() -> None:
    start = date(2026, 8, 20)
    pairs = []
    for i in range(35):
        bench = 100.0 + i if i < 28 else 100.0
        day = (start + timedelta(days=i)).isoformat()
        pairs.append((day, 110.0 + 0.5 * i, bench))

    report = sv.holdout_report(pairs)
    assert report["status"] == "computed"
    assert report["holdout_r"] is None
    assert "clamped" in report["holdout_r_reason"]


def test_lead_lag_recovers_known_two_day_shift() -> None:
    rng = random.Random(42)
    bench = [rng.uniform(100.0, 120.0) for _ in range(35)]
    apix = [bench[i - 2] if i >= 2 else bench[i] for i in range(35)]

    report = sv.lead_lag_report(apix, bench)
    assert report["status"] == "computed"
    assert report["full_window"]["best_lag_days"] == 2
    assert report["best_lags"] == [2, 2, 2]
    assert report["best_lag_stable"] is True


def test_build_report_on_demonstration_db_passes(tmp_path) -> None:
    db = tmp_path / "demo.db"
    assert bt.ensure_demonstration_data(str(db)) is True

    report = sv.build_report(str(db))
    assert report["window"]["apix_days"] == 35
    assert report["invariants"]["all_passed"] is True
    assert report["holdout_week"]["status"] == "computed"
    assert report["lead_lag"]["status"] == "computed"
    assert report["all_checks_passed"] is True
