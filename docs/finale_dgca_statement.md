# DGCA Data Position Statement (Issue #17, Path B)

A frank statement of what the Directorate General of Civil Aviation publishes, what
it withholds, and what changes in this repository as a result. Companion to the
Path A ingestion that landed real DGCA rows in
`data/dgca_passenger_traffic_weights.{csv,json}` (240 of 270 rows now carry a
per-row source URL and release citation; the other 30 stay
`provenance: calibrated_baseline`).

All fetch results below were observed on 2026-09-28.

## 1. What DGCA publishes (traffic — and what we used)

DGCA publishes monthly domestic city-pair passenger traffic as free XLSX files
with no login and no API key:

- File name: `DOM CITYPAIR DATA, <MONTH> <YYYY>.xlsx`
- Portal deep link (returns 200):
  `https://www.dgca.gov.in/digigov-portal/?page=jsp/dgca/InventoryList/dataReports/aviationDataStatistics/airTransport/domestic/monthly/DOM%20CITYPAIR%20DATA,%20<MONTH>%20<YYYY>.xlsx`
- Underlying object:
  `https://public-prd-dgca.s3.ap-south-1.amazonaws.com/InventoryList/dataReports/aviationDataStatistics/airTransport/domestic/monthly/DOM%20CITYPAIR%20DATA,%20<MONTH>%20<YYYY>.xlsx`

What is inside, verified directly against the files:

- One row per city pair (687 pairs in the March 2026 file), columns for
  city 1, city 2, and both directional flows.
- `PASSENGERS TO CITY 2` means city1 → city2; `PASSENGERS FROM CITY 2` means
  city2 → city1. This direction mapping was cross-checked against dataful.in
  for January–July 2026: 6 of 6 exact matches.
- Data starts on row 3; there is no fare, carrier, or price column of any kind.
- Publication is irregular, so each file's HTTP `Last-Modified` header is the
  release date we cite per row: 2024-01 was published 2024-02-19; 2025-09 was
  not published until 2026-02-16 (~5 months late); 2026-01/02/03 all appeared
  together on 2026-06-01.

What we transcribed from these files: **24 of the 27 months in the weights
table (2024-01 … 2026-03, except 2025-10/11/12) × 10 trunk corridors = 240
rows**, each with:

- `source_url` — the DGCA portal deep link for that month's file,
- `release_date` — the HTTP `Last-Modified` date of that file,
- `source` — report name, XLSX file name, S3 object URL, and the full
  `Last-Modified` timestamp,
- `provenance: DGCA`, `is_synthetic: false`.

14 pinned published values (including both directions of 2024-01 DEL-BOM,
2025-01 and 2025-09 DEL-BOM, 2026-03 DEL-BOM) are asserted against both output
files on every regeneration and by the test suite.

DGCA also publishes monthly aggregate passenger traffic (Form A rankings),
airport statistics, on-time performance, and complaint statistics, plus annual
civil aviation handbooks. None of those contain fares either.

## 2. What DGCA withholds (fares)

No route-level fare dataset exists in any DGCA public release — no monthly
averages, no fare microdata, no advance-booking-window price series, no
machine-readable fare time series. The Ministry of Civil Aviation confirmed the
operational posture in Parliament.

**Lok Sabha Unstarred Question 1934, answered 30 July 2026:**

> "Tariff Monitoring Unit (TMU) has been set up in DGCA which monitors airfares
> on selected 78 routes (72 domestic & 06 international) on random basis by
> using airline websites on monthly basis. The 72 domestic routes covers about
> 27% of the domestic traffic."

That sentence is the whole public record: monitoring exists, but only aggregate
percentages are ever disclosed. No dataset, no route list, no fare values.

Verification status of this citation: the AU1934 PDF itself returned HTTP 500
from sansad.in when fetched on 2026-09-28, so the quotation is preserved from
this repository's own record (`artifacts/DGCA_POSITION_NOTE.md`,
`scripts/backtest_vs_mospi.py`). The identical TMU passage is independently
corroborated in at least four other retrievable sources:

- [LS UQ 747, answered 24 July 2025](https://sansad.in/getFile/loksabhaquestions/annex/185/AU747_7QIMtj.pdf?source=pqals) — same 78 routes / 27% sentence.
- [LS UQ 2127, answered 12 February 2026](https://sansad.in/getFile/loksabhaquestions/annex/187/AU2127_whdYfO.pdf?source=pqals) — same 78 routes / 27% sentence.
- [LS UQ 3414, answered 12 March 2026](https://sansad.in/getFile/loksabhaquestions/annex/187/AU3414_aXtOwZ.pdf?source=pqals) — TMU monitors airfares monthly from airline websites.
- [PTI report, 8 December 2025](https://www.newkerala.com/news/o/dgcas-tariff-monitoring-unit-keeping-airfares-78-routes-check-437) — "78 routes … 27 per cent of the domestic traffic".

Consequences for this project:

- The 30-day back-test cannot target DGCA fares because the data does not
  exist in open form; `scripts/backtest_vs_mospi.py` instead back-tests against
  the official MoSPI CPI airfare sub-index and cites the DGCA position rather
  than pretending (see `artifacts/DGCA_POSITION_NOTE.md`).
- Carrier-level and fare-level splits in the system remain documented
  calibrations or synthetic fallbacks and are labelled as such.

One access gap, distinct from policy: the XLSX files for **2025-10, 2025-11 and
2025-12 return HTTP 403** on every known URL variant (portal deep link and S3
object). DGCA publishes the surrounding months normally. Until those three
files are reachable, their 30 rows cannot be cited, so they stay calibrated.

## 3. What changed when real data landed

All 240 transcribed rows differ from the calibrated values they replaced —
none coincidentally matched. The calibrated table was not merely unverified; it
was quantitatively wrong.

| Metric | Calibrated (before) | DGCA (after) |
| --- | --- | --- |
| Monthly total, mean of the 24 shared months | 2,760,432 | 1,784,630 (old = **1.55×**) |
| Monthly total, range | 2,366,438 – 3,314,720 | 1,631,427 – 1,905,742 |
| Cumulative overstatement over those 24 months | **+23,419,230 passengers** | — |
| Directional symmetry | forced (DEL-BOM = BOM-DEL = 441,875 in 2024-01) | real (2024-01: 284,143 / 289,788) |

Row-level change across the 240 transcribed rows:

- mean **−28.7%**, median **−35.8%**,
- worst overstatement: **−54.2%** (2025-05 BLR-DEL, 381,838 → 174,792),
- rare understatement: **+36.8%** (2024-07 DEL-HYD, 106,490 → 145,674),
- headline corridor: 2024-01 DEL-BOM 441,875 → 284,143 (−35.7%);
  2025-09 DEL-BOM 478,955 → 248,779 (−48.1%).

`share_weight` and `period_rank` are recomputed by the loader from the real
flows, so weights now reflect genuine directional asymmetry instead of the
modelled 50/50 split. Every period's weights still sum to exactly 1.000000.

## 4. What will change when the 403 files land

The 30 rows for 2025-10/11/12 are the only rows that would still change. They
were left byte-for-byte identical to the previous table and keep
`provenance: calibrated_baseline`, `is_synthetic: true` (issue #7: no
relabeling without a real per-row citation).

They are currently far above the real run rate:

| | Calibrated value | Real reference |
| --- | --- | --- |
| Monthly total 2025-10 / 11 / 12 | 3,247,500 / 3,202,750 / 3,314,720 (mean 3,254,990) | 24 transcribed months average 1,784,630 (**1.82×**) |
| Same three months vs their neighbours | — | adjacent real months (2025-09, 2026-01) average 1,734,110 (**1.87×**) |
| DEL-BOM 2025-10 | 562,463 | 2025-09 actual: 248,779 (**2.26×**) |

If the three files match their neighbours when they become reachable, these
rows should fall by roughly 45–50% — a correction this repository will take
only from the XLSX itself, never by estimation. That is the precise meaning of
"which rows would change on real ingestion": 240 already did, 30 are pending
behind HTTP 403, and nothing else in the table is expected to move.

## 5. Available in the same files, deliberately not transcribed

- **4 of the 14 index-basket corridors** (DEL-MAA, MAA-DEL, BLR-HYD,
  HYD-BLR) exist in the monthly XLSX releases (the March 2026 file contains
  the Chennai–Delhi and Bengaluru–Hyderabad pairs) but were not added: the
  weights table's scope is the 10-corridor trunk basket, and expanding it
  (270 → 378 rows) is out of scope for issue #17.
- **2026-04 … 2026-07 XLSX files** are downloadable, but the table's period
  window ends at 2026-03 (27 months) by decision; extending it requires new
  `RELEASE_HTTP_DATES` entries, not a change of method.

## 6. Refresh procedure

```bash
# 1. Download the month's file (name pattern below) into any directory
curl -L -o DOMCITYPAIRDATA_JANUARY2026.xlsx \
  "https://www.dgca.gov.in/digigov-portal/?page=jsp/dgca/InventoryList/dataReports/aviationDataStatistics/airTransport/domestic/monthly/DOM%20CITYPAIR%20DATA,%20JANUARY%202026.xlsx"

# 2. Record its release stamp
curl -sI "<same url>" | grep -i last-modified

# 3. Regenerate both weight files (re-verifies counts, provenance split,
#    pinned values, per-row citations, and that every period sums to 1.0)
.venv/bin/python scripts/ingest_dgca_citypair.py --xlsx-dir /path/to/downloads
```

New months must be added to `RELEASE_HTTP_DATES` in
`scripts/ingest_dgca_citypair.py` with their observed `Last-Modified` value.
Clearing the calibrated remainder works the same way: when 2025-10/11/12 start
returning 200, add their stamps, remove them from `CALIBRATED_MONTHS`, and
re-run — only then may those 30 rows carry `provenance: DGCA`.

## 7. Guarantees

- **Never relabel (issue #7).** No row gets `provenance: DGCA` without a
  per-row `source_url` and `release_date`. Enforced three ways: the ingest
  script's `verify()` aborts on any missing citation or altered calibrated
  anchor; `tests/test_weight_table_consistency.py` asserts the 270-row
  composition, pinned values, per-kind citation contract, and per-period weight
  sums; `tests/test_benchmark_loaders_unit.py` round-trips source citations
  through export/reparse. The file-level `# provenance:` directive remains
  `calibrated_baseline` as the conservative fallback — row-level provenance
  always wins.
- **`release_date` means the file's HTTP `Last-Modified` date**, i.e. when DGCA
  published that XLSX, not the traffic month it covers.
- **Verification:** 508 tests pass, `ruff check .` and `black --check .` are
  clean, and `python -m scripts.audit_provenance apix.db` reports
  `RESULT: PASS`.
