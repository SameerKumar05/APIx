"""Database package for APIx."""

from backend.app.db.ingestion_repo import (
    IngestionRepo,
    bulk_insert_raw_fares,
    cleanup_old_raw_fares,
    compute_dedup_hash,
    count_raw_fares,
    create_scraping_run,
    get_raw_fares,
    get_raw_fares_for_calculation,
    get_scraping_run,
    list_scraping_runs,
    record_scraping_run,
    update_scraping_run,
)
from backend.app.db.session import (
    Base,
    SessionLocal,
    drop_db,
    engine,
    get_db,
    init_db,
)

__all__ = [
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "init_db",
    "drop_db",
    "IngestionRepo",
    "bulk_insert_raw_fares",
    "create_scraping_run",
    "update_scraping_run",
    "record_scraping_run",
    "get_scraping_run",
    "list_scraping_runs",
    "cleanup_old_raw_fares",
    "get_raw_fares",
    "get_raw_fares_for_calculation",
    "count_raw_fares",
    "compute_dedup_hash",
]
