# What our own audit caught and fixed

Source material for one finale slide. Two episodes, each with the commit that
caused it, the commits that fixed it, and the test that now fails if the mistake
comes back. Every claim names a commit hash or a file and line. Every gate was
run on this branch before this document was written.

## Slide content

### Episode 1: we labelled calibrated weights as an official DGCA release

#### Before

Commit `b73d53a` ("feat(data): ingest official DGCA passenger traffic weights
and calibrate base period", 2026-09-28 00:49) added a `dgca_published`
provenance kind and stamped the corridor weight files with it:

```diff
# ingestion/loaders/traffic_provenance.py
+    DGCA_PUBLISHED = "dgca_published"
-            case TrafficProvenanceKind.DGCA:
+            case TrafficProvenanceKind.DGCA | TrafficProvenanceKind.DGCA_PUBLISHED:
                 return False
```

```diff
# data/dgca_passenger_traffic_weights.csv (every row)
-2024-01,DEL-BOM,DEL,BOM,441875,0.175,1148.0,1,dgca_published,False,...
+2024-01,DEL-BOM,DEL,BOM,441875,0.175,1148.0,1,calibrated_baseline,True,...
```

The label was false. The weights are proxies calibrated to published DGCA
city-pair rankings, not a DGCA microdata release.

#### After

Two fix commits, deliberately left in history because the fixes are the
evidence:

- `a6e181d` (2026-09-28 02:27, "fix(data): mark DGCA traffic weights as
  calibrated baseline proxy") relabelled the CSV and JSON rows to
  `calibrated_baseline` with `is_synthetic=True`. Its message states the reason:
  DGCA publishes aggregate traffic statistics but no programmatic microdata
  (Lok Sabha Unstarred Question 1934, answered 30 July 2026).
- `6fb7220` (2026-09-28 03:24) deleted the dead `dgca_published` branch from
  `ingestion/loaders/traffic_provenance.py`. The command
  `grep -rn "dgca_published" --include="*.py" --include="*.csv" --include="*.json"`
  returns no matches in code or data (this document aside).

#### The gate that now fails if it recurs

- The parser is fail-closed. `ingestion/loaders/traffic_provenance.py:81-94`
  maps any declaration token it does not recognise, a resurrected
  `dgca_published` included, to `modelled` (synthetic). The module docstring at
  `ingestion/loaders/traffic_provenance.py:1-6` says: "A boolean
  is_synthetic=false on its own is not a DGCA declaration."
- Two tests pin the committed files. `tests/test_weight_table_consistency.py:191-197`
  requires `is_synthetic is True` and provenance in
  `("calibrated_baseline", "modelled_dgca_proxy")`. `tests/test_benchmark_loaders_unit.py:310-331`
  requires the same on the committed 2024-01 DEL-BOM record.
- The database audit fails closed. `scripts/audit_provenance.py:37-84` selects
  every row claiming `is_synthetic=False` (line 44) and marks it
  `UNCORROBORATED` unless telemetry or a scrape run exists for that platform,
  a proxy record proves real egress, and capture times are diverse (line 65).
  Any violation forces verdict `FAIL` (line 83), and the command-line entry
  point exits 1 (lines 106-110).
  `tests/test_provenance_audit.py:62-89` asserts exactly that: one
  uncorroborated live row produces `FAIL`.

### Episode 2: we stamped hardcoded fixtures as live fares

#### Before

Commit `0718f45` ("feat(ingestion): enable live fare persistence and
provenance verification", 2026-09-28 02:09) added `_extract_live_fares` with a
hardcoded `corridor_profiles` table of invented SG flights, and built the
records as:

```diff
+                is_synthetic=False,
+                source_platform="spicejet",
```

The commit message asked for "is_synthetic = 0 rows persist into apix.db", and
the test it shipped, `tests/test_live_ingestion.py::test_live_fare_ingestion_stores_non_synthetic_record_in_db`,
asserted that the database contained at least one `is_synthetic == 0` row. The
test itself demanded the fabrication.

#### After

Commit `978e1a6` ("fix(ingestion): honestly report fallback status and verify
persistence plumbing via fixtures", 2026-09-28 02:32):

- Moved the profiles into `get_staged_fixtures()`. Every record it builds
  carries `is_synthetic=True, source_platform="staged_fixture"`
  (`ingestion/crawlers/spicejet.py:798-799`).
- `_extract_live_fares` now returns an empty list when no genuine quotes
  arrive. Its docstring reads "Never fabricates live quotes"
  (`ingestion/crawlers/spicejet.py:537-541`, empty return at line 581).
- `scrape_route` reports only genuinely parsed rows:
  `live_records = [r for r in records if not r.is_synthetic]`
  (`ingestion/crawlers/spicejet.py:884`).
- Replaced the enforcing test with `tests/test_ingestion_persistence_plumbing.py`,
  which asserts the opposite.

#### The gate that now fails if it recurs

`tests/test_ingestion_persistence_plumbing.py`:

- Lines 92-98: fixture records must be `is_synthetic is True` with
  `source_platform == "staged_fixture"`.
- Lines 116-125: rows read back from `apix.db` must have `is_synthetic == 1`
  and platform `staged_fixture`.
- Lines 290-296 (test defined at line 256):
  `test_crawler_honestly_reports_fallback_without_fabricating_live_quotes`
  requires zero records claiming `is_synthetic=False` in a fallback run, and
  every record it does return must be `is_synthetic is True`.

If a fixture row still reaches the database as live, the provenance audit from
episode 1 catches it: a `staged_fixture` row with `is_synthetic=0` has no
telemetry, so the audit reports `UNCORROBORATED` and exits 1.

## Why corridor_profiles is still in the code

`corridor_profiles` stays on purpose. It is fixture data for testing the
persistence plumbing, it is gated behind an explicit flag, and it is flagged
synthetic every time it is built. Concretely:

- The table lives inside `get_staged_fixtures()`
  (`ingestion/crawlers/spicejet.py:583`, table at line 603), whose docstring
  at lines 590-595 states the records "are always marked with
  is_synthetic=True and source_platform='staged_fixture'".
- The records it emits carry exactly that pair
  (`ingestion/crawlers/spicejet.py:798-799`).
- The only way to reach it from code is the `fallback_to_fixture` flag on
  `_extract_live_fares` (`ingestion/crawlers/spicejet.py:576-579`). The sole
  production call site, `scrape_route` at line 881, does not set that flag, so
  the live path returns `[]` (line 581) instead of fixtures. Only the tests at
  `tests/test_ingestion_persistence_plumbing.py:85` and `:139` call
  `get_staged_fixtures()` directly.
- Even if a synthetic row leaked, `scripts/audit_provenance.py` fails the
  database on any `is_synthetic=False` row without supporting telemetry.

Judge-facing demonstration, on demand:

```bash
python -m pytest tests/test_ingestion_persistence_plumbing.py tests/test_provenance_audit.py -q
python -m scripts.audit_provenance apix.db
```

Expected: both test files pass, and the audit prints
`RESULT: PASS - every live claim is corroborated` with exit code 0.

## The 30-second spoken line

Our own audit caught two provenance mistakes before submission. One commit
labelled our calibrated DGCA weights as an official release; another wrote
hardcoded flight fixtures into the database as live fares. We corrected both
and kept the fix commits in history, because the fixes are the evidence, not
something to hide. Two automated gates now block a repeat: the provenance audit
fails any live claim that has no supporting telemetry, and the fixture tests
fail if synthetic data loses its synthetic flag. Caught by us, fixed before the
finale, guarded since.

## Evidence appendix (not for the slide)

### Commits

| Role | Hash | Date (2026-09-28) | Subject |
| --- | --- | --- | --- |
| Episode 1 cause | `b73d53a` | 00:49 | feat(data): ingest official DGCA passenger traffic weights and calibrate base period |
| Episode 1 fix, relabel | `a6e181d` | 02:27 | fix(data): mark DGCA traffic weights as calibrated baseline proxy |
| Episode 1 fix, path removal | `6fb7220` | 03:24 | fix(integrity): remove dead dgca_published provenance path |
| Episode 2 cause | `0718f45` | 02:09 | feat(ingestion): enable live fare persistence and provenance verification |
| Episode 2 fix | `978e1a6` | 02:32 | fix(ingestion): honestly report fallback status and verify persistence plumbing via fixtures |

Full hashes:

- `b73d53aca8f66d6076aa49c2677b9fb7ea86ac75`
- `a6e181d6b93f23765774e741d3be82b899dc0db8`
- `6fb7220a5d98183645456fb212d2d97130d452c3`
- `0718f457605187352481dafc16240115278b6234`
- `978e1a6c1445f006d1e8f573c8240e4e7aaa96e5`

### Verification run on this branch (base `5090984`, repo venv active)

| Command | Result |
| --- | --- |
| `python -m pytest tests/test_provenance_audit.py tests/test_crawlers_unit.py tests/test_ps_portal_scrapers.py` | 71 passed |
| `python -m pytest tests/test_ingestion_persistence_plumbing.py tests/test_weight_table_consistency.py tests/test_benchmark_loaders_unit.py` | 39 passed |
| `python -m pytest` (full suite) | 507 passed, 3 warnings, exit 0 |
| `python -m scripts.audit_provenance apix.db` | exit 0, `rows claiming is_synthetic=false : 0`, `RESULT: PASS` |
| `ruff check .` | All checks passed |
| `black --check .` | 159 files would be left unchanged |

### The gates were proven to bite (each mutation reverted immediately)

1. Episode 1, weight-file mutation. Reintroduced
   `,dgca_published,False,` into row 3 of
   `data/dgca_passenger_traffic_weights.csv`, then ran the two pinning tests:
   both FAILED (`assert january.provenance in {"calibrated_baseline",
   "modelled_dgca_proxy"}` at `tests/test_benchmark_loaders_unit.py:328`,
   pytest exit 1). The file was restored with `git checkout --`.
2. Episode 2, fixture-flag mutation. Flipped `is_synthetic=True` to `False` at
   `ingestion/crawlers/spicejet.py:798`, then ran
   `tests/test_ingestion_persistence_plumbing.py`:
   `test_batch_ingestion_persists_fare_records_with_component_splits` FAILED
   (pytest exit 1). The file was restored with `git checkout --`.
3. Episode 1, database mutation. Inserted one row with
   `is_synthetic=0, source_platform='staged_fixture'` into `apix.db`, then ran
   `python -m scripts.audit_provenance apix.db`:
   `staged_fixture rows=1 times=1 telemetry=False run=False -> UNCORROBORATED`,
   `RESULT: FAIL`, exit 1. The row was deleted and the audit returned to
   `RESULT: PASS`, exit 0.

No history was rewritten. The cause and fix commits both remain on the branch.
