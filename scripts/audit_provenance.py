"""Provenance audit: fail closed if any row claims to be live without evidence.

Run:  python -m scripts.audit_provenance [path/to.db]

Exit code 0 means every row claiming is_synthetic=False is corroborated by
ingestion telemetry. Exit code 1 means at least one such row is uncorroborated,
which is the signature of generated data wearing a live label.

Corroboration signals checked per claimed-live source platform:
  1. scraper_telemetry rows attributed to that platform
  2. scraping_runs rows for that platform
  3. proxy_health_records, proving real egress was configured
  4. scraped_at diversity, since a generator stamps a constant timestamp while a
     real scrape produces many distinct capture times
"""

from __future__ import annotations

import sys
from collections import defaultdict

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import backend.app.models  # noqa: F401
from backend.app.db.session import Base
from backend.app.models.raw_fare import RawFare
from backend.app.models.scraping import ScrapingRun
from backend.app.models.telemetry import ProxyHealthRecord, ScraperTelemetry


def audit(db: Session) -> dict:
    live_rows = db.execute(
        select(RawFare.source_platform, func.count(RawFare.id), func.count(func.distinct(RawFare.scraped_at)))
        .where(RawFare.is_synthetic.is_(False))
        .group_by(RawFare.source_platform)
    ).all()

    telemetry = {
        (r.crawler_name or "").strip().lower()
        for r in db.execute(select(ScraperTelemetry.crawler_name)).all()
    }
    runs = {
        (r.source_platform or "").strip().lower()
        for r in db.execute(select(ScrapingRun.source_platform)).all()
    }
    proxy_records = db.scalar(select(func.count(ProxyHealthRecord.id))) or 0

    per_source = []
    violations = []
    for platform, rows, distinct_times in sorted(live_rows):
        key = (platform or "").strip().lower()
        has_telemetry = key in telemetry
        has_run = key in runs
        distinct_ok = distinct_times > 1
        corroborated = (has_telemetry or has_run) and proxy_records > 0 and distinct_ok
        entry = {
            "source_platform": platform,
            "rows_claiming_live": rows,
            "distinct_scraped_at": distinct_times,
            "scraper_telemetry_present": has_telemetry,
            "scraping_run_present": has_run,
            "proxy_records": proxy_records,
            "verdict": "CORROBORATED" if corroborated else "UNCORROBORATED",
        }
        per_source.append(entry)
        if not corroborated:
            violations.append(entry)

    return {
        "rows_claiming_live_total": sum(e["rows_claiming_live"] for e in per_source),
        "per_source": per_source,
        "violations": violations,
        "verdict": "PASS" if not violations else "FAIL",
    }


def main(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else "apix.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    try:
        report = audit(db)
    finally:
        db.close()
        engine.dispose()

    print(f"provenance audit: {path}")
    print(f"  rows claiming is_synthetic=false : {report['rows_claiming_live_total']}")
    for e in report["per_source"]:
        print(
            f"    {e['source_platform']:22} rows={e['rows_claiming_live']:<5} "
            f"times={e['distinct_scraped_at']:<4} telemetry={str(e['scraper_telemetry_present']):5} "
            f"run={str(e['scraping_run_present']):5} -> {e['verdict']}"
        )
    if report["violations"]:
        print("  RESULT: FAIL - a live claim is uncorroborated, so a LIVE badge would be false")
        return 1
    print("  RESULT: PASS - every live claim is corroborated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
