#!/usr/bin/env python3
"""Transcribe published DGCA monthly city-pair XLSX releases into the weights table.

Implements issue #17 Path A: real DGCA city-pair statistics for 24 of the 27
months in data/dgca_passenger_traffic_weights.csv, each row carrying a source
URL and a release citation. The three months whose XLSX is unreachable (HTTP
403: 2025-10, 2025-11, 2025-12) keep their existing calibrated_baseline rows
verbatim -- never relabel (issue #7).

Direction semantics (cross-checked against dataful.in Jan-Jul 2026, exact):
    PASSENGERS TO CITY 2   = CITY1 -> CITY2
    PASSENGERS FROM CITY 2 = CITY2 -> CITY1

release_date is the HTTP Last-Modified date of the DGCA object (HEAD-verifiable).

XLSX reading is stdlib-only (zipfile + ElementTree); no openpyxl required.

Usage:
    .venv/bin/python scripts/ingest_dgca_citypair.py --xlsx-dir /tmp/opencode/dgca
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from email.utils import parsedate_to_datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ingestion.loaders.dgca_traffic_loader import (  # noqa: E402
    CORRIDOR_DISTANCE_MAP,
    DgcaTrafficLoader,
)

# ---------------------------------------------------------------------------
# Minimal stdlib XLSX sheet reader
# ---------------------------------------------------------------------------

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        raw = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(raw)
    return [
        "".join(t.text or "" for t in si.iter(f"{NS}t"))
        for si in root.findall(f"{NS}si")
    ]


def _col_index(ref: str) -> int:
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return -1
    idx = 0
    for ch in m.group(1):
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def read_rows(path: Path) -> list[list[str]]:
    with zipfile.ZipFile(path) as z:
        strings = _shared_strings(z)
        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in root.iter(f"{NS}row"):
        vals: dict[int, str] = {}
        for c in row.findall(f"{NS}c"):
            ci = _col_index(c.get("r") or "")
            t = c.get("t")
            v = c.find(f"{NS}v")
            if t == "inlineStr":
                is_el = c.find(f"{NS}is")
                text = (
                    "".join(x.text or "" for x in is_el.iter(f"{NS}t"))
                    if is_el is not None
                    else ""
                )
            elif v is None or v.text is None:
                text = ""
            elif t == "s":
                text = strings[int(v.text)]
            else:
                text = v.text or ""
            vals[ci] = text
        width = max(vals) + 1 if vals else 0
        rows.append([vals.get(i, "") for i in range(width)])
    return rows


# ---------------------------------------------------------------------------
# City normalisation (2024/2025 files are ALL-CAPS; 2026 files add
# "Mumbai (Mumbai)" vs "Mumbai (Navi Mumbai)" which are distinct airports)
# ---------------------------------------------------------------------------

CITY_IATA = {
    "DELHI": "DEL",
    "MUMBAI": "BOM",
    "BENGALURU": "BLR",
    "BANGALORE": "BLR",
    "KOLKATA": "CCU",
    "CALCUTTA": "CCU",
    "HYDERABAD": "HYD",
    "CHENNAI": "MAA",
    "MADRAS": "MAA",
}


def norm_city(s: str) -> str:
    s = (s or "").strip().upper()
    if s.startswith("MUMBAI"):
        return "NMI" if "NAVI" in s else "BOM"
    base = s.split("(")[0].strip()
    return CITY_IATA.get(base, base)


# ---------------------------------------------------------------------------
# The 10 directional corridors transcribed from every month
# ---------------------------------------------------------------------------

CORRIDORS = [
    "DEL-BOM",
    "BOM-DEL",
    "DEL-BLR",
    "BLR-DEL",
    "BOM-BLR",
    "BLR-BOM",
    "DEL-CCU",
    "CCU-DEL",
    "DEL-HYD",
    "HYD-DEL",
]

MONTH_NAMES = [
    "JANUARY",
    "FEBRUARY",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUGUST",
    "SEPTEMBER",
    "OCTOBER",
    "NOVEMBER",
    "DECEMBER",
]

PORTAL_URL = (
    "https://www.dgca.gov.in/digigov-portal/?page=jsp/dgca/InventoryList/"
    "dataReports/aviationDataStatistics/airTransport/domestic/monthly/"
    "DOM%20CITYPAIR%20DATA,%20{month}%20{year}.xlsx"
)
S3_OBJECT_URL = (
    "https://public-prd-dgca.s3.ap-south-1.amazonaws.com/InventoryList/"
    "dataReports/aviationDataStatistics/airTransport/domestic/monthly/"
    "DOM%20CITYPAIR%20DATA,%20{month}%20{year}.xlsx"
)

# HTTP Last-Modified of each DGCA object, as observed on HEAD/download.
# release_date = date part of this value.
RELEASE_HTTP_DATES: dict[str, str] = {
    "2024-01": "Mon, 19 Feb 2024 05:44:15 GMT",
    "2024-02": "Thu, 21 Mar 2024 05:41:42 GMT",
    "2024-03": "Thu, 25 Apr 2024 07:17:39 GMT",
    "2024-04": "Mon, 27 May 2024 05:45:49 GMT",
    "2024-05": "Wed, 03 Jul 2024 18:10:03 GMT",
    "2024-06": "Tue, 23 Jul 2024 06:11:31 GMT",
    "2024-07": "Mon, 19 Aug 2024 10:56:55 GMT",
    "2024-08": "Mon, 23 Sep 2024 07:11:36 GMT",
    "2024-09": "Mon, 28 Oct 2024 12:44:33 GMT",
    "2024-10": "Mon, 16 Dec 2024 15:49:33 GMT",
    "2024-11": "Thu, 02 Jan 2025 04:13:48 GMT",
    "2024-12": "Tue, 11 Feb 2025 12:58:50 GMT",
    "2025-01": "Mon, 10 Mar 2025 16:56:55 GMT",
    "2025-02": "Mon, 07 Apr 2025 10:26:02 GMT",
    "2025-03": "Tue, 29 Apr 2025 17:35:38 GMT",
    "2025-04": "Tue, 03 Jun 2025 12:27:00 GMT",
    "2025-05": "Tue, 01 Jul 2025 10:39:29 GMT",
    "2025-06": "Wed, 20 Aug 2025 09:09:11 GMT",
    "2025-07": "Thu, 11 Sep 2025 04:51:38 GMT",
    "2025-08": "Wed, 01 Oct 2025 17:01:41 GMT",
    "2025-09": "Mon, 16 Feb 2026 06:47:00 GMT",
    "2026-01": "Mon, 01 Jun 2026 11:32:41 GMT",
    "2026-02": "Mon, 01 Jun 2026 11:33:58 GMT",
    "2026-03": "Mon, 01 Jun 2026 11:32:35 GMT",
}

# Months whose XLSX returns HTTP 403: kept verbatim from the existing table.
CALIBRATED_MONTHS = {"2025-10", "2025-11", "2025-12"}

# Values pinned to the published XLSX files (verified by extraction).
PINNED: dict[tuple[str, str], int] = {
    ("2024-01", "DEL-BOM"): 284143,
    ("2024-01", "BOM-DEL"): 289788,
    ("2024-01", "DEL-BLR"): 201415,
    ("2024-01", "BLR-DEL"): 202724,
    ("2024-01", "DEL-CCU"): 119251,
    ("2024-01", "CCU-DEL"): 118865,
    ("2024-01", "DEL-HYD"): 125954,
    ("2024-01", "HYD-DEL"): 131108,
    ("2024-01", "BOM-BLR"): 193499,
    ("2024-01", "BLR-BOM"): 185646,
    ("2025-01", "DEL-BOM"): 279457,
    ("2025-09", "DEL-BOM"): 248779,
    ("2026-03", "DEL-BOM"): 271231,
    # Calibrated remainder (kept verbatim, never relabelled):
    ("2025-10", "DEL-BOM"): 562463,
}

CSV_FIELDS = [
    "year_month",
    "route_code",
    "origin",
    "destination",
    "pax_volume",
    "share_weight",
    "distance_km",
    "period_rank",
    "is_synthetic",
    "provenance",
    "source",
    "source_url",
    "release_date",
]


def extract_flows(path: Path) -> dict[tuple[str, str], int]:
    """Return {(origin_iata, destination_iata): pax} for one month's XLSX."""
    rows = read_rows(path)
    flows: dict[tuple[str, str], int] = {}
    for r in rows[3:]:
        if len(r) < 5 or not r[1] or not r[2]:
            continue
        try:
            to2 = int(float(r[3]))
            from2 = int(float(r[4]))
        except (ValueError, TypeError):
            continue
        c1, c2 = norm_city(r[1]), norm_city(r[2])
        if c1 == c2:
            continue
        flows[(c1, c2)] = flows.get((c1, c2), 0) + to2
        flows[(c2, c1)] = flows.get((c2, c1), 0) + from2
    return flows


def xlsx_name(ym: str) -> str:
    year, month = ym.split("-")
    return f"DOMCITYPAIRDATA_{MONTH_NAMES[int(month) - 1]}{year}.xlsx"


def release_date(ym: str) -> str:
    return parsedate_to_datetime(RELEASE_HTTP_DATES[ym]).date().isoformat()


def citation(ym: str) -> str:
    year, month = ym.split("-")
    label = f"{MONTH_NAMES[int(month) - 1]} {year}"
    obj = f"DOM CITYPAIR DATA, {label}.xlsx"
    return (
        f"DGCA Monthly City-Pair Traffic Report {label} ({obj}); "
        f"object: {S3_OBJECT_URL.format(month=MONTH_NAMES[int(month) - 1], year=year)}; "
        f"HTTP Last-Modified: {RELEASE_HTTP_DATES[ym]}"
    )


def portal_url(ym: str) -> str:
    year, month = ym.split("-")
    return PORTAL_URL.format(month=MONTH_NAMES[int(month) - 1], year=year)


def read_existing_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise SystemExit(
            f"existing table not found: {csv_path}\n"
            "the calibrated remainder (2025-10/11/12) is carried verbatim from it"
        )
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].lstrip().lower().startswith("# provenance:"):
        lines = lines[1:]
    return list(csv.DictReader(lines))


def build_intermediate_rows(
    xlsx_dir: Path, existing_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for ym in sorted(RELEASE_HTTP_DATES):
        path = xlsx_dir / xlsx_name(ym)
        if not path.exists():
            raise SystemExit(f"missing XLSX for {ym}: {path}")
        flows = extract_flows(path)
        cit, url, rel = citation(ym), portal_url(ym), release_date(ym)
        for rc in CORRIDORS:
            orig, dest = rc.split("-")
            pax = flows.get((orig, dest))
            if not pax or pax <= 0:
                raise SystemExit(f"{ym}: corridor {rc} missing or zero in {path.name}")
            rows.append(
                {
                    "year_month": ym,
                    "route_code": rc,
                    "origin": orig,
                    "destination": dest,
                    "pax_volume": str(pax),
                    "share_weight": "",
                    "distance_km": str(CORRIDOR_DISTANCE_MAP[rc]),
                    "period_rank": "",
                    "is_synthetic": "False",
                    "provenance": "DGCA",
                    "source": cit,
                    "source_url": url,
                    "release_date": rel,
                }
            )

    carried = [r for r in existing_rows if r.get("year_month") in CALIBRATED_MONTHS]
    found = {r.get("year_month") for r in carried}
    if found != CALIBRATED_MONTHS or len(carried) != 30:
        raise SystemExit(
            f"expected 30 calibrated rows for {sorted(CALIBRATED_MONTHS)}, "
            f"got {len(carried)} covering {sorted(found)}"
        )
    rows.extend(carried)
    return rows


def verify(loader: DgcaTrafficLoader, label: str) -> None:
    prov = loader.provenance
    counts = prov["provenance_counts"]
    if prov["record_count"] != 270:
        raise SystemExit(f"{label}: expected 270 records, got {prov['record_count']}")
    if counts != {"DGCA": 240, "calibrated_baseline": 30}:
        raise SystemExit(f"{label}: unexpected provenance split {counts}")

    by_key = {(r.year_month, r.route_code): r for r in loader._records}
    for key, want in PINNED.items():
        got = by_key.get(key)
        if got is None:
            raise SystemExit(f"{label}: missing row {key}")
        if got.pax_volume != want:
            raise SystemExit(f"{label}: {key} pax {got.pax_volume} != published {want}")

    anchor = by_key[("2025-10", "DEL-BOM")]
    if anchor.provenance != "calibrated_baseline" or anchor.is_synthetic is not True:
        raise SystemExit(f"{label}: calibrated anchor relabelled")

    for r in loader._records:
        if r.provenance == "DGCA":
            if r.is_synthetic is not False:
                raise SystemExit(f"{label}: DGCA row still synthetic: {r}")
            if not r.source_url.startswith("https://www.dgca.gov.in"):
                raise SystemExit(f"{label}: DGCA row missing portal source_url: {r}")
            if not r.release_date:
                raise SystemExit(f"{label}: DGCA row missing release_date: {r}")
            if ".xlsx" not in r.source:
                raise SystemExit(f"{label}: DGCA row source names no XLSX: {r}")
        elif r.provenance == "calibrated_baseline":
            if r.is_synthetic is not True:
                raise SystemExit(f"{label}: calibrated row relabelled: {r}")
        else:
            raise SystemExit(f"{label}: unexpected provenance {r.provenance}")

    for ym, weights in loader._weights_by_period.items():
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-6:
            raise SystemExit(f"{label}: weights for {ym} sum to {total}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--xlsx-dir",
        type=Path,
        required=True,
        help="directory holding DOMCITYPAIRDATA_<MONTH><YEAR>.xlsx downloads",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPO_ROOT / "data",
        help="target data directory (default: repo data/)",
    )
    args = parser.parse_args()

    csv_path = args.data_dir / "dgca_passenger_traffic_weights.csv"
    json_path = args.data_dir / "dgca_passenger_traffic_weights.json"

    existing = read_existing_rows(csv_path)
    interim_rows = build_intermediate_rows(args.xlsx_dir, existing)

    with tempfile.TemporaryDirectory() as tmp:
        interim = Path(tmp) / "interim.csv"
        with open(interim, "w", encoding="utf-8", newline="") as f:
            f.write("# provenance: calibrated_baseline\n")
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(interim_rows)

        loader = DgcaTrafficLoader(data_path=interim)
        verify(loader, "interim")
        loader.export_csv(csv_path)
        loader.export_json(json_path)

    reloaded_csv = DgcaTrafficLoader(data_path=csv_path)
    verify(reloaded_csv, "exported csv")
    reloaded_json = DgcaTrafficLoader(data_path=json_path)
    verify(reloaded_json, "exported json")

    counts = reloaded_csv.provenance["provenance_counts"]
    print(
        f"wrote {csv_path.relative_to(REPO_ROOT)} and {json_path.relative_to(REPO_ROOT)}"
    )
    print(
        f"  270 rows = 240 DGCA (24 months x 10 corridors) + "
        f"30 calibrated_baseline (2025-10/11/12): {counts}"
    )
    print(
        f"  periods {reloaded_csv.provenance['first_period']}.."
        f"{reloaded_csv.provenance['last_period']}, all weight sums == 1.0"
    )
    print(f"  {len(PINNED)} pinned published values verified against both files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
