#!/usr/bin/env python3
"""Back-test the APIx index against the official MoSPI airfare price index.

Why MoSPI and not DGCA fares
---------------------------
The problem statement asks for a 30-day back-test against "publicly available
DGCA monthly average-fare data". That dataset does not exist in reusable form.
DGCA's Tariff Monitoring Unit does monitor fares on 78 routes (72 domestic, 6
international) every month by reading airline websites, but it publishes no
dataset, no dashboard, and not even the route list. The only public output is an
aggregate percentage quoted in Parliament, for example in Lok Sabha Unstarred
Question 1934 answered 30 July 2026, which states that the TMU "monitors
airfares on selected 78 routes ... on monthly basis by using airline websites"
without publishing the underlying values.

So this script back-tests against the MoSPI airfare sub-index instead, which is
the official published price benchmark for the same concept, and cites the
DGCA position rather than pretending to have data that does not exist.

Fail-closed by design
---------------------
A back-test is only meaningful over a real window. This script refuses to emit a
verdict when the local index history is shorter than the required window, because
a correlation computed over one or two overlapping months is a number without
meaning and presenting it as validation would be the exact defect this repository
already corrected once. It exits non-zero and states the shortfall.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REQUIRED_WINDOW_DAYS = 30

DGCA_POSITION = {
    "claim": "DGCA publishes monthly average air-fare data suitable for a back-test",
    "verdict": "FALSE - not published in reusable form",
    "authority": "Lok Sabha Unstarred Question 1934, answered 30 July 2026",
    "quote": (
        "Tariff Monitoring Unit (TMU) has been set up in DGCA which monitors airfares on "
        "selected 78 routes (72 domestic & 06 international) on random basis by using airline "
        "websites on monthly basis. The 72 domestic routes covers about 27% of the domestic traffic."
    ),
    "consequence": (
        "Only aggregate percentage changes have ever been disclosed, in Parliament answers and "
        "press coverage. No dataset, no route list, and no monthly per-sector fare series is "
        "available, so a reproducible 30-day back-test against DGCA fares is impossible. An RTI "
        "request to DGCA would be the only route to that data."
    ),
    "substitute": (
        "MoSPI CPI airfare sub-index, published monthly for All-India and every State, is the "
        "official price benchmark for the same quantity and is used instead."
    ),
}

MOSPI_SOURCE_NOTE = (
    "MoSPI reference set bundled with the repository. Not live-scraped. The official series is "
    "available from esankhyiki.mospi.gov.in and the MoSPI API; a production deployment should "
    "refresh from there rather than ship the bundle."
)


@dataclass
class BacktestResult:
    status: str
    reason: str
    required_window_days: int
    apix_observations: int = 0
    apix_first: Optional[str] = None
    apix_last: Optional[str] = None
    mospi_observations: int = 0
    overlapping_months: int = 0
    apix_mom_pct: Dict[str, float] = field(default_factory=dict)
    mospi_mom_pct: Dict[str, float] = field(default_factory=dict)
    pearson_r: Optional[float] = None
    r_squared: Optional[float] = None
    mean_abs_error_pct: Optional[float] = None
    best_lag_months: Optional[int] = None
    correlation_at_best_lag: Optional[float] = None
    direction_agreement_pct: Optional[float] = None
    dgca: Dict[str, Any] = field(default_factory=lambda: DGCA_POSITION)
    mospi_source_note: str = MOSPI_SOURCE_NOTE


def pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def month_of(value: str) -> str:
    return value[:7]


def month_distance(start: str, end: str) -> int:
    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    return (ey - sy) * 12 + (em - sm)


def pct_change(series: Dict[str, float]) -> Dict[str, float]:
    keys = sorted(series)
    out: Dict[str, float] = {}
    for prev, cur in zip(keys, keys[1:]):
        if series[prev]:
            out[cur] = (series[cur] - series[prev]) / series[prev] * 100.0
    return out


def load_apix(conn: sqlite3.Connection) -> Dict[str, float]:
    """Monthly mean of the Fisher national index, keyed by YYYY-MM."""
    rows = conn.execute(
        "SELECT index_date, index_value FROM national_daily_indices "
        "WHERE lower(coalesce(index_type,'')) = 'fisher'"
    ).fetchall()
    by_month: Dict[str, List[float]] = {}
    for index_date, value in rows:
        if value is None:
            continue
        by_month.setdefault(month_of(str(index_date)), []).append(float(value))
    return {m: sum(v) / len(v) for m, v in by_month.items()}


def load_mospi(conn: sqlite3.Connection) -> Dict[str, float]:
    rows = conn.execute(
        "SELECT year_month, airfare_sub_index FROM mospi_cpi_series "
        "WHERE airfare_sub_index IS NOT NULL"
    ).fetchall()
    return {str(y).strip(): float(v) for y, v in rows}


def history_span_days(first: Optional[str], last: Optional[str]) -> int:
    if not first or not last:
        return 0
    a = date.fromisoformat(first[:10])
    b = date.fromisoformat(last[:10])
    return (b - a).days


def run(db_path: str, required_days: int = REQUIRED_WINDOW_DAYS) -> BacktestResult:
    conn = sqlite3.connect(db_path)
    try:
        apix_raw = conn.execute(
            "SELECT MIN(index_date), MAX(index_date), COUNT(DISTINCT index_date) "
            "FROM national_daily_indices"
        ).fetchone()
        apix = load_apix(conn)
        mospi = load_mospi(conn)
    finally:
        conn.close()

    first = str(apix_raw[0]) if apix_raw and apix_raw[0] else None
    last = str(apix_raw[1]) if apix_raw and apix_raw[1] else None
    distinct_days = int(apix_raw[2] or 0) if apix_raw else 0
    span = history_span_days(first, last)

    result = BacktestResult(
        status="INSUFFICIENT_DATA",
        reason="",
        required_window_days=required_days,
        apix_observations=distinct_days,
        apix_first=first,
        apix_last=last,
        mospi_observations=len(mospi),
    )

    if distinct_days < required_days or span < required_days:
        result.reason = (
            f"APIx index history spans {distinct_days} distinct day(s) over {span} day(s) "
            f"({first} to {last}). A {required_days}-day back-test needs at least {required_days} "
            "distinct days of Fisher index history. No verdict is emitted, because a correlation "
            "over a shorter window would not be evidence. Leave the worker running in live or "
            "synthetic mode to accumulate history, then re-run this script."
        )
        return result

    apix_mom = pct_change(apix)
    mospi_mom = pct_change(mospi)
    shared = sorted(set(apix_mom) & set(mospi_mom))
    result.overlapping_months = len(shared)
    result.apix_mom_pct = {m: round(v, 4) for m, v in apix_mom.items()}
    result.mospi_mom_pct = {m: round(v, 4) for m, v in mospi_mom.items()}

    if len(shared) < 6:
        result.reason = (
            f"Only {len(shared)} overlapping month(s) of month-on-month change. At least 6 are "
            "required for a correlation to mean anything. Accumulate more index history."
        )
        return result

    a = [apix_mom[m] for m in shared]
    m_ = [mospi_mom[m] for m in shared]
    r = pearson(a, m_)
    result.status = "OK" if r is not None else "INSUFFICIENT_DATA"
    result.pearson_r = None if r is None else round(r, 4)
    result.r_squared = None if r is None else round(r * r, 4)
    result.mean_abs_error_pct = round(
        sum(abs(x - y) for x, y in zip(a, m_)) / len(shared), 4
    )
    result.direction_agreement_pct = round(
        100.0 * sum(1 for x, y in zip(a, m_) if (x >= 0) == (y >= 0)) / len(shared), 2
    )

    best_lag, best_r = 0, r
    for lag in range(0, 4):
        if lag == 0:
            xs, ys = a, m_
        else:
            xs, ys = a[lag:], m_[: len(m_) - lag]
        cand = pearson(xs, ys)
        if cand is not None and best_r is not None and cand > best_r:
            best_lag, best_r = lag, cand
    result.best_lag_months = best_lag
    result.correlation_at_best_lag = None if best_r is None else round(best_r, 4)

    if r is None:
        result.reason = "Correlation is undefined, most likely a constant series on one side."
    return result


def render_markdown(res: BacktestResult) -> str:
    lines = [
        "# APIx back-test against the MoSPI airfare index",
        "",
        f"Status: **{res.status}**",
        "",
        "## Why MoSPI rather than DGCA fares",
        "",
        f"The problem statement asks for a back-test against publicly available DGCA monthly "
        f"average-fare data. That dataset is not published. {res.dgca['authority']} states that "
        f"the DGCA Tariff Monitoring Unit \"{res.dgca['quote']}\" Only aggregate percentage changes "
        "have been disclosed. An RTI request is the only route to the underlying data.",
        "",
        f"This script therefore uses the {res.dgca['substitute']}",
        "",
        "## Coverage",
        "",
        f"- Required window: {res.required_window_days} days",
        f"- APIx observations: {res.apix_observations} distinct days",
        f"- APIx span: {res.apix_first} to {res.apix_last}",
        f"- MoSPI observations: {res.mospi_observations} months",
        f"- Overlapping months of change: {res.overlapping_months}",
        "",
    ]
    if res.status != "OK":
        lines += ["## Verdict", "", "No verdict emitted.", "", res.reason, ""]
    else:
        lines += [
            "## Verdict",
            "",
            f"- Pearson r (contemporaneous): **{res.pearson_r}**",
            f"- r squared: **{res.r_squared}**",
            f"- Mean absolute error of MoM change: **{res.mean_abs_error_pct}** percentage points",
            f"- Direction agreement: **{res.direction_agreement_pct}%**",
            f"- Best lag: APIx leads MoSPI by **{res.best_lag_months}** month(s), "
            f"r = **{res.correlation_at_best_lag}**",
            "",
            "A positive best-lag is the claim that matters: APIx moved first, which is the entire "
            "premise of a leading indicator.",
            "",
        ]
    lines += ["## Provenance", "", res.mospi_source_note, ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="apix.db", help="SQLite database path")
    parser.add_argument(
        "--days", type=int, default=REQUIRED_WINDOW_DAYS, help="Required history in days"
    )
    parser.add_argument("--json-out", default=None, help="Write the result as JSON")
    parser.add_argument("--md-out", default=None, help="Write a markdown summary")
    args = parser.parse_args()

    res = run(args.db, args.days)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(asdict(res), indent=2, default=str))
    if args.md_out:
        Path(args.md_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md_out).write_text(render_markdown(res))

    print(f"back-test status: {res.status}")
    print(f"  required window   : {res.required_window_days} days")
    print(f"  APIx observations : {res.apix_observations} distinct days")
    print(f"  APIx span         : {res.apix_first} to {res.apix_last}")
    print(f"  MoSPI months      : {res.mospi_observations}")
    if res.status == "OK":
        print(f"  pearson r         : {res.pearson_r} (r2={res.r_squared})")
        print(f"  best lag          : {res.best_lag_months} month(s), r={res.correlation_at_best_lag}")
        print(f"  direction agree   : {res.direction_agreement_pct}%")
    else:
        print(f"  reason            : {res.reason}")
    return 0 if res.status == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
