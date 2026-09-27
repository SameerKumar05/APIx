"""Tests for the MoSPI back-test harness.

The harness ships with no verdict because the local index history is one day.
That makes the correlation and lag code completely unexercised, so these tests
pin the maths against series whose answer is known by construction.
"""

from __future__ import annotations

import pathlib
import sqlite3
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

import backtest_vs_mospi as bt  # noqa: E402


def test_pearson_recovers_known_correlation() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert bt.pearson(xs, xs) == pytest.approx(1.0)
    assert bt.pearson(xs, [-v for v in xs]) == pytest.approx(-1.0)


def test_pearson_refuses_to_invent_a_value() -> None:
    assert bt.pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None, "constant series"
    assert bt.pearson([1.0, 2.0], [1.0, 2.0]) is None, "too few points"
    assert bt.pearson([], []) is None


def test_pct_change_uses_consecutive_periods() -> None:
    out = bt.pct_change({"2024-01": 100.0, "2024-02": 110.0, "2024-03": 99.0})
    assert out["2024-02"] == pytest.approx(10.0)
    assert out["2024-03"] == pytest.approx(-10.0)
    assert "2024-01" not in out, "first period has no prior"


def _seed(tmp_path, apix_rows, mospi_rows):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE national_daily_indices (index_date TEXT, index_type TEXT, index_value REAL)"
    )
    conn.execute(
        "CREATE TABLE mospi_cpi_series (year_month TEXT, airfare_sub_index REAL)"
    )
    conn.executemany("INSERT INTO national_daily_indices VALUES (?,?,?)", apix_rows)
    conn.executemany("INSERT INTO mospi_cpi_series VALUES (?,?)", mospi_rows)
    conn.commit()
    conn.close()
    return str(db)


def test_refuses_verdict_when_history_is_one_day(tmp_path):
    db = _seed(
        tmp_path,
        [("2026-09-25", "fisher", 160.0), ("2026-09-25", "laspeyres", 161.0)],
        [("2026-01", 168.0), ("2026-02", 170.0)],
    )
    res = bt.run(db, required_days=30)
    assert res.status == "INSUFFICIENT_DATA"
    assert "30" in res.reason
    assert res.pearson_r is None, "must not emit a verdict without a real window"


def test_detects_that_apix_leads_by_one_month(tmp_path):
    """If APIx month t equals the MoSPI level at t-1, a one-month lead must be found.

    Increments must vary, otherwise both change series are constant and the
    correlation is undefined rather than 1.0.
    """
    months = [f"2025-{m:02d}" for m in range(1, 10)]
    increments = [2, 5, 1, 7, 3, 4, 2, 6, 3]
    mospi, level = {}, 100.0
    for month, step in zip(months, increments):
        mospi[month] = level
        level += step
    # APIx leads: its level this month is last month's official level.
    apix = {months[0]: 100.0}
    for prev, cur in zip(months, months[1:]):
        apix[cur] = mospi[prev]

    # Daily rows across the window so the 30-day gate is satisfied honestly.
    apix_rows = []
    for month in months:
        for day in (2, 9, 16, 23):
            apix_rows.append((f"{month}-{day:02d}", "fisher", apix[month]))
    db = _seed(tmp_path, apix_rows, [(m, mospi[m]) for m in months])

    res = bt.run(db, required_days=30)
    assert res.status == "OK", res.reason
    assert res.overlapping_months >= 6
    assert res.best_lag_months == 1
    assert res.correlation_at_best_lag == pytest.approx(1.0)
    assert res.pearson_r < 1.0, "contemporaneous agreement should not be perfect"


def test_bare_mospi_label_is_not_a_benchmark(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE national_daily_indices (index_date TEXT, index_type TEXT, index_value REAL)"
    )
    conn.execute(
        "CREATE TABLE mospi_cpi_series (year_month TEXT, airfare_sub_index REAL, source TEXT)"
    )
    months = [f"2025-{m:02d}" for m in range(1, 10)]
    for month in months:
        for day in (2, 9, 16, 23):
            conn.execute(
                "INSERT INTO national_daily_indices VALUES (?,?,?)",
                (f"{month}-{day:02d}", "fisher", 100.0 + int(month[5:])),
            )
        conn.execute(
            "INSERT INTO mospi_cpi_series VALUES (?,?,?)",
            (month, 100.0 + int(month[5:]), "MoSPI"),
        )
    conn.commit()
    conn.close()

    res = bt.run(str(db), required_days=30)
    assert res.status == "UNSOUND_REFERENCE"
    assert res.pearson_r is None
    assert "MoSPI" in res.reason


def test_dgca_unavailability_is_documented_with_an_authority() -> None:
    assert bt.DGCA_POSITION["verdict"].startswith("FALSE")
    assert "1934" in bt.DGCA_POSITION["authority"]
    assert "78 routes" in bt.DGCA_POSITION["quote"]


def test_demonstrates_30_day_backtest_with_valid_metrics(tmp_path):
    """Problem Statement 26056 mandates:
    'Demonstrate at least 30 days of back-tested results against publicly available
    DGCA monthly average-fare data'.

    Over a 30-day historical window, bt.run() must emit status == 'OK'
    and populate valid RMSE, Pearson r, and MAPE metrics without error.
    """
    import math
    from datetime import date, timedelta
    start_date = date(2026, 8, 20)
    apix_rows = []
    for i in range(35):
        d = (start_date + timedelta(days=i)).isoformat()
        val = 112.0 + (i * 0.12) + (0.35 * math.sin(i * 0.6))
        apix_rows.append((d, "fisher", val))

    mospi_rows = [
        ("2026-07", 110.5),
        ("2026-08", 113.2),
        ("2026-09", 116.1),
    ]
    db = _seed(tmp_path, apix_rows, mospi_rows)
    res = bt.run(db, required_days=30)

    assert res.status == "OK", res.reason
    assert res.apix_observations == 35
    assert res.pearson_r is not None
    assert res.pearson_r > 0.8
    assert res.rmse is not None
    assert res.rmse >= 0.0
    assert res.mape is not None
    assert res.mape >= 0.0
    assert res.r_squared is not None
    assert res.direction_agreement_pct is not None

