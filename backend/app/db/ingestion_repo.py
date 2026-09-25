"""Repository for raw fare ingestion, scraping run tracking, and retention pruning.

Provides high-throughput bulk insertion with cryptographic idempotency
(ON CONFLICT (hash_id) DO NOTHING), scraping execution telemetry, automated
retention cleanup (90-day pruning preserving daily aggregated indices), and
time-series query helpers for downstream index computation and elasticity models.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from backend.app.models.raw_fare import RawFare
from backend.app.models.scraping import ScrapingRun

logger = logging.getLogger("backend.app.db.ingestion_repo")


def compute_dedup_hash(
    airline_code: str,
    flight_number: str,
    origin: str,
    destination: str,
    departure_time: Union[datetime, str, None],
    booking_window: str,
    flight_date: Union[date, str, None] = None,
) -> str:
    """Generate deterministic SHA-256 hash for raw fare deduplication.

    Format matches canonical key across pipeline crawlers:
    `{airline_code}:{flight_number}:{origin}:{destination}:{departure_time}:{booking_window}`
    """
    dep_str = ""
    if isinstance(departure_time, datetime):
        dep_str = departure_time.isoformat()
    elif departure_time is not None:
        dep_str = str(departure_time)
    elif flight_date is not None:
        dep_str = str(flight_date)

    key = f"{airline_code.upper()}:{flight_number.upper()}:{origin.upper()}:{destination.upper()}:{dep_str}:{booking_window}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _normalize_fare_record(
    raw: Union[Dict[str, Any], Any],
    default_batch_id: str,
    now_utc: datetime,
) -> Dict[str, Any]:
    """Normalize dictionary, Pydantic model, or dataclass into a clean RawFare dictionary."""
    if hasattr(raw, "model_dump"):
        data = raw.model_dump()
    elif hasattr(raw, "to_dict"):
        data = raw.to_dict()
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        # Generic object attribute access
        data = {k: getattr(raw, k) for k in dir(raw) if not k.startswith("_")}

    # Extract or fallback identifiers
    batch_id = data.get("batch_id") or default_batch_id
    origin = str(data.get("origin") or data.get("origin_iata") or "").strip().upper()
    destination = str(data.get("destination") or data.get("destination_iata") or "").strip().upper()
    airline_code = str(data.get("airline_code") or "").strip().upper()
    flight_number = str(data.get("flight_number") or "").strip().upper()
    raw_bw = data.get("booking_window")
    if raw_bw is not None:
        if isinstance(raw_bw, int):
            booking_window = f"T+{raw_bw}"
        else:
            bw_clean = str(raw_bw).strip().upper()
            if bw_clean.isdigit():
                booking_window = f"T+{bw_clean}"
            elif bw_clean in ("T1", "T+1"):
                booking_window = "T+1"
            elif bw_clean in ("T7", "T+7"):
                booking_window = "T+7"
            elif bw_clean in ("T15", "T+15"):
                booking_window = "T+15"
            elif bw_clean in ("T30", "T+30"):
                booking_window = "T+30"
            else:
                booking_window = bw_clean
    else:
        booking_window = "T+1"

    # Dates and times
    departure_val = data.get("departure_time") or data.get("departure_datetime")
    arrival_val = data.get("arrival_time") or data.get("arrival_datetime")
    scraped_at_val = (
        data.get("scraped_at")
        or data.get("booking_datetime")
        or data.get("search_timestamp")
        or now_utc
    )

    dep_dt: Optional[datetime] = None
    if isinstance(departure_val, datetime):
        dep_dt = departure_val
    elif isinstance(departure_val, str) and departure_val:
        try:
            dep_dt = datetime.fromisoformat(departure_val)
        except ValueError:
            dep_dt = None

    arr_dt: Optional[datetime] = None
    if isinstance(arrival_val, datetime):
        arr_dt = arrival_val
    elif isinstance(arrival_val, str) and arrival_val:
        try:
            arr_dt = datetime.fromisoformat(arrival_val)
        except ValueError:
            arr_dt = None

    scraped_dt: datetime = now_utc
    if isinstance(scraped_at_val, datetime):
        scraped_dt = scraped_at_val
    elif isinstance(scraped_at_val, str) and scraped_at_val:
        try:
            scraped_dt = datetime.fromisoformat(scraped_at_val)
        except ValueError:
            scraped_dt = now_utc

    # Flight date
    fdate_val = data.get("flight_date")
    fdate: date
    if isinstance(fdate_val, date) and not isinstance(fdate_val, datetime):
        fdate = fdate_val
    elif isinstance(fdate_val, datetime):
        fdate = fdate_val.date()
    elif isinstance(fdate_val, str) and fdate_val:
        try:
            fdate = date.fromisoformat(fdate_val[:10])
        except ValueError:
            fdate = dep_dt.date() if dep_dt else now_utc.date()
    elif dep_dt:
        fdate = dep_dt.date()
    else:
        fdate = now_utc.date()

    # Pricing calculations
    total_fare = float(data.get("total_fare") or data.get("fare_inr") or 0.0)
    base_fare = float(data.get("base_fare") or (total_fare * 0.85))
    taxes_and_fees = float(data.get("taxes_and_fees") or (total_fare - base_fare))

    stops = int(data.get("stops") or 0)
    fare_class = str(data.get("fare_class") or data.get("cabin_class") or "Economy").strip()
    source_platform = str(
        data.get("source_platform") or data.get("source") or "synthetic"
    ).strip()
    is_synthetic = source_platform.lower() == "synthetic" or bool(data.get("is_synthetic", True))

    # Hash dedup
    hash_id = str(data.get("hash_id") or data.get("dedup_hash") or "").strip()
    if not hash_id:
        hash_id = compute_dedup_hash(
            airline_code=airline_code,
            flight_number=flight_number,
            origin=origin,
            destination=destination,
            departure_time=dep_dt or departure_val,
            booking_window=booking_window,
            flight_date=fdate,
        )

    duration_minutes = data.get("duration_minutes")
    if duration_minutes is not None:
        duration_minutes = int(duration_minutes)
    elif dep_dt and arr_dt:
        duration_minutes = max(0, int((arr_dt - dep_dt).total_seconds() // 60))

    return {
        "batch_id": batch_id,
        "origin": origin,
        "destination": destination,
        "flight_date": fdate,
        "booking_window": booking_window,
        "airline_code": airline_code,
        "flight_number": flight_number,
        "departure_time": dep_dt,
        "arrival_time": arr_dt,
        "duration_minutes": duration_minutes,
        "stops": stops,
        "fare_class": fare_class,
        "base_fare": base_fare,
        "taxes_and_fees": taxes_and_fees,
        "total_fare": total_fare,
        "source_platform": source_platform,
        "scraped_at": scraped_dt,
        "hash_id": hash_id,
        "is_synthetic": is_synthetic,
    }


def bulk_insert_raw_fares(
    db: Session,
    records: Sequence[Union[Dict[str, Any], Any]],
    batch_id: Optional[str] = None,
    batch_size: int = 500,
    commit: bool = True,
) -> Dict[str, int]:
    """Bulk insert raw flight fare records with idempotent deduplication.

    Executes `INSERT ... ON CONFLICT (hash_id) DO NOTHING` across batches
    using the appropriate dialect (PostgreSQL or SQLite). Duplicate records
    within the input batch or conflicting with existing database records
    are safely skipped without error.

    Args:
        db: Active SQLAlchemy Session.
        records: Collection of raw fare dicts, dataclasses, or Pydantic records.
        batch_id: Optional batch/run identifier to associate with all records.
        batch_size: Maximum records per chunked SQL execution.
        commit: If True, commits the transaction upon completion.

    Returns:
        Summary dict containing:
          - 'received': Total records submitted.
          - 'inserted': Count of new unique records stored.
          - 'duplicates': Count of duplicate records rejected (in-batch + db conflicts).
    """
    total_received = len(records)
    if total_received == 0:
        return {"received": 0, "inserted": 0, "duplicates": 0}

    now_utc = datetime.now(timezone.utc)
    effective_batch_id = batch_id or f"batch-{int(now_utc.timestamp())}"

    # Normalize records and eliminate in-batch duplicates early for accuracy
    normalized_records: List[Dict[str, Any]] = []
    seen_hashes: set[str] = set()
    in_batch_duplicates = 0

    for rec in records:
        norm = _normalize_fare_record(rec, effective_batch_id, now_utc)
        h = norm["hash_id"]
        if h in seen_hashes:
            in_batch_duplicates += 1
            continue
        seen_hashes.add(h)
        normalized_records.append(norm)

    inserted_count = 0
    bind = db.get_bind()
    dialect_name = bind.dialect.name if bind else "sqlite"

    # Process in chunks of batch_size
    for i in range(0, len(normalized_records), batch_size):
        chunk = normalized_records[i : i + batch_size]
        if not chunk:
            continue

        if dialect_name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = (
                pg_insert(RawFare)
                .values(chunk)
                .on_conflict_do_nothing(index_elements=["hash_id"])
            )
        else:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            stmt = (
                sqlite_insert(RawFare)
                .values(chunk)
                .on_conflict_do_nothing(index_elements=["hash_id"])
            )

        res = db.execute(stmt)
        # res.rowcount returns the number of newly inserted rows
        if res.rowcount is not None and res.rowcount >= 0:
            inserted_count += res.rowcount
        else:
            # Fallback if driver doesn't populate rowcount
            inserted_count += len(chunk)

    if commit:
        db.commit()

    total_duplicates = total_received - inserted_count
    return {
        "received": total_received,
        "inserted": inserted_count,
        "duplicates": total_duplicates,
    }


def create_scraping_run(
    db: Session,
    batch_id: str,
    source_platform: str,
    status: str = "PENDING",
    routes_attempted: int = 0,
    routes_succeeded: int = 0,
    fares_collected: int = 0,
    fares_deduplicated: int = 0,
    error_message: Optional[str] = None,
    started_at: Optional[datetime] = None,
    commit: bool = True,
) -> ScrapingRun:
    """Create a new ScrapingRun telemetry record."""
    run = ScrapingRun(
        batch_id=batch_id,
        source_platform=source_platform,
        status=status,
        routes_attempted=routes_attempted,
        routes_succeeded=routes_succeeded,
        fares_collected=fares_collected,
        fares_deduplicated=fares_deduplicated,
        error_message=error_message,
        started_at=started_at or datetime.now(timezone.utc),
    )
    db.add(run)
    if commit:
        db.commit()
        db.refresh(run)
    return run


def update_scraping_run(
    db: Session,
    batch_id: str,
    status: Optional[str] = None,
    routes_attempted: Optional[int] = None,
    routes_succeeded: Optional[int] = None,
    fares_collected: Optional[int] = None,
    fares_deduplicated: Optional[int] = None,
    error_message: Optional[str] = None,
    completed_at: Optional[datetime] = None,
    duration_seconds: Optional[float] = None,
    commit: bool = True,
) -> Optional[ScrapingRun]:
    """Update execution metrics and status for an existing ScrapingRun."""
    stmt = select(ScrapingRun).where(ScrapingRun.batch_id == batch_id)
    run = db.scalars(stmt).first()
    if not run:
        return None

    if status is not None:
        run.status = status
    if routes_attempted is not None:
        run.routes_attempted = routes_attempted
    if routes_succeeded is not None:
        run.routes_succeeded = routes_succeeded
    if fares_collected is not None:
        run.fares_collected = fares_collected
    if fares_deduplicated is not None:
        run.fares_deduplicated = fares_deduplicated
    if error_message is not None:
        run.error_message = error_message
    if completed_at is not None:
        run.completed_at = completed_at
    elif status in ("COMPLETED", "FAILED") and run.completed_at is None:
        run.completed_at = datetime.now(timezone.utc)

    if duration_seconds is not None:
        run.duration_seconds = duration_seconds
    elif run.completed_at and run.started_at:
        c_at = run.completed_at
        s_at = run.started_at
        if c_at.tzinfo is not None and s_at.tzinfo is None:
            s_at = s_at.replace(tzinfo=timezone.utc)
        elif c_at.tzinfo is None and s_at.tzinfo is not None:
            c_at = c_at.replace(tzinfo=timezone.utc)
        run.duration_seconds = max(0.0, (c_at - s_at).total_seconds())
    return run


def record_scraping_run(
    db: Session,
    batch_id: str,
    source_platform: str,
    status: str,
    routes_attempted: int = 0,
    routes_succeeded: int = 0,
    fares_collected: int = 0,
    fares_deduplicated: int = 0,
    error_message: Optional[str] = None,
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
    commit: bool = True,
) -> ScrapingRun:
    """Upsert scraping run metadata."""
    stmt = select(ScrapingRun).where(ScrapingRun.batch_id == batch_id)
    run = db.scalars(stmt).first()

    if run is None:
        return create_scraping_run(
            db=db,
            batch_id=batch_id,
            source_platform=source_platform,
            status=status,
            routes_attempted=routes_attempted,
            routes_succeeded=routes_succeeded,
            fares_collected=fares_collected,
            fares_deduplicated=fares_deduplicated,
            error_message=error_message,
            started_at=started_at,
            commit=commit,
        )

    return update_scraping_run(  # type: ignore[return-value]
        db=db,
        batch_id=batch_id,
        status=status,
        routes_attempted=routes_attempted,
        routes_succeeded=routes_succeeded,
        fares_collected=fares_collected,
        fares_deduplicated=fares_deduplicated,
        error_message=error_message,
        completed_at=completed_at,
        commit=commit,
    )


def get_scraping_run(db: Session, batch_id: str) -> Optional[ScrapingRun]:
    """Retrieve ScrapingRun telemetry by batch_id."""
    stmt = select(ScrapingRun).where(ScrapingRun.batch_id == batch_id)
    return db.scalars(stmt).first()


def list_scraping_runs(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    source_platform: Optional[str] = None,
) -> List[ScrapingRun]:
    """Query scraping runs ordered newest first."""
    stmt = select(ScrapingRun)
    if status:
        stmt = stmt.where(ScrapingRun.status == status)
    if source_platform:
        stmt = stmt.where(ScrapingRun.source_platform == source_platform)
    stmt = stmt.order_by(ScrapingRun.started_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt).all())


def cleanup_old_raw_fares(
    db: Session,
    days: int = 90,
    cutoff_datetime: Optional[datetime] = None,
    commit: bool = True,
) -> int:
    """Automated retention pruning: remove raw fare records older than N days.

    Preserves daily aggregated index tables (RouteDailyIndex, NationalDailyIndex)
    while reclaiming database storage from stale high-frequency scraped observations.

    Args:
        db: Active SQLAlchemy Session.
        days: Retention horizon in days (default: 90).
        cutoff_datetime: Optional explicit cutoff override. If omitted,
            calculated as `now_utc - timedelta(days=days)`.
        commit: If True, commits the transaction.

    Returns:
        Number of raw fare rows successfully pruned.
    """
    if cutoff_datetime is None:
        cutoff_datetime = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_date = cutoff_datetime.date()

    # Records are pruned if their capture time or flight departure precedes the retention threshold
    stmt = delete(RawFare).where(
        or_(
            RawFare.scraped_at < cutoff_datetime,
            RawFare.flight_date < cutoff_date,
        )
    )
    res = db.execute(stmt.execution_options(synchronize_session="fetch"))
    pruned_count = res.rowcount if res.rowcount is not None and res.rowcount >= 0 else 0

    if commit:
        db.commit()

    logger.info(
        "Pruned %d raw fares older than %d days (cutoff: %s). Daily indices preserved.",
        pruned_count,
        days,
        cutoff_datetime.isoformat(),
    )
    return pruned_count


def get_raw_fares(
    db: Session,
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    booking_window: Optional[str] = None,
    flight_date: Optional[Union[date, str]] = None,
    start_date: Optional[Union[date, str]] = None,
    end_date: Optional[Union[date, str]] = None,
    airline_code: Optional[str] = None,
    source_platform: Optional[str] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> List[RawFare]:
    """Query raw fare observations by route, booking window, date range, and carrier."""
    stmt = select(RawFare)

    if origin:
        stmt = stmt.where(RawFare.origin == origin.strip().upper())
    if destination:
        stmt = stmt.where(RawFare.destination == destination.strip().upper())
    if booking_window:
        stmt = stmt.where(RawFare.booking_window == booking_window.strip())
    if airline_code:
        stmt = stmt.where(RawFare.airline_code == airline_code.strip().upper())
    if source_platform:
        stmt = stmt.where(RawFare.source_platform == source_platform.strip())

    # Date filters
    if flight_date is not None:
        d = (
            date.fromisoformat(str(flight_date)[:10])
            if isinstance(flight_date, str)
            else flight_date
        )
        stmt = stmt.where(RawFare.flight_date == d)
    if start_date is not None:
        sd = (
            date.fromisoformat(str(start_date)[:10])
            if isinstance(start_date, str)
            else start_date
        )
        stmt = stmt.where(RawFare.flight_date >= sd)
    if end_date is not None:
        ed = (
            date.fromisoformat(str(end_date)[:10])
            if isinstance(end_date, str)
            else end_date
        )
        stmt = stmt.where(RawFare.flight_date <= ed)

    # Order by flight_date and total_fare for deterministic time-series retrieval
    stmt = stmt.order_by(RawFare.flight_date.asc(), RawFare.total_fare.asc())

    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)

    return list(db.scalars(stmt).all())


def get_raw_fares_for_calculation(
    db: Session,
    origin: str,
    destination: str,
    booking_window: str,
    calculation_date: Union[date, str, datetime],
    limit: Optional[int] = None,
) -> List[RawFare]:
    """Fetch raw fares for a corridor, booking window, and calculation/flight date.

    Utilizes the composite index `ix_raw_fares_route_window_date` for sub-millisecond
    lookup speeds when computing daily indices.
    """
    calc_date: date
    if isinstance(calculation_date, datetime):
        calc_date = calculation_date.date()
    elif isinstance(calculation_date, str):
        calc_date = date.fromisoformat(calculation_date[:10])
    else:
        calc_date = calculation_date

    stmt = (
        select(RawFare)
        .where(
            RawFare.origin == origin.strip().upper(),
            RawFare.destination == destination.strip().upper(),
            RawFare.booking_window == booking_window.strip(),
            RawFare.flight_date == calc_date,
        )
        .order_by(RawFare.total_fare.asc())
    )

    if limit is not None:
        stmt = stmt.limit(limit)

    return list(db.scalars(stmt).all())


def count_raw_fares(
    db: Session,
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    booking_window: Optional[str] = None,
    flight_date: Optional[Union[date, str]] = None,
) -> int:
    """Return count of matching raw fares."""
    stmt = select(func.count(RawFare.id))
    if origin:
        stmt = stmt.where(RawFare.origin == origin.strip().upper())
    if destination:
        stmt = stmt.where(RawFare.destination == destination.strip().upper())
    if booking_window:
        stmt = stmt.where(RawFare.booking_window == booking_window.strip())
    if flight_date is not None:
        d = (
            date.fromisoformat(str(flight_date)[:10])
            if isinstance(flight_date, str)
            else flight_date
        )
        stmt = stmt.where(RawFare.flight_date == d)

    return db.scalar(stmt) or 0


class IngestionRepo:
    """Object-oriented repository wrapper for Ingestion operations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def bulk_insert(
        self,
        records: Sequence[Union[Dict[str, Any], Any]],
        batch_id: Optional[str] = None,
        batch_size: int = 500,
        commit: bool = True,
    ) -> Dict[str, int]:
        return bulk_insert_raw_fares(
            self.db,
            records=records,
            batch_id=batch_id,
            batch_size=batch_size,
            commit=commit,
        )

    def create_run(
        self,
        batch_id: str,
        source_platform: str,
        status: str = "PENDING",
        **kwargs: Any,
    ) -> ScrapingRun:
        return create_scraping_run(
            self.db,
            batch_id=batch_id,
            source_platform=source_platform,
            status=status,
            **kwargs,
        )

    def update_run(self, batch_id: str, **kwargs: Any) -> Optional[ScrapingRun]:
        return update_scraping_run(self.db, batch_id=batch_id, **kwargs)

    def record_run(
        self,
        batch_id: str,
        source_platform: str,
        status: str,
        **kwargs: Any,
    ) -> ScrapingRun:
        return record_scraping_run(
            self.db,
            batch_id=batch_id,
            source_platform=source_platform,
            status=status,
            **kwargs,
        )

    def get_run(self, batch_id: str) -> Optional[ScrapingRun]:
        return get_scraping_run(self.db, batch_id=batch_id)

    def cleanup_old_fares(
        self,
        days: int = 90,
        cutoff_datetime: Optional[datetime] = None,
        commit: bool = True,
    ) -> int:
        return cleanup_old_raw_fares(
            self.db,
            days=days,
            cutoff_datetime=cutoff_datetime,
            commit=commit,
        )

    def get_fares_for_calculation(
        self,
        origin: str,
        destination: str,
        booking_window: str,
        calculation_date: Union[date, str, datetime],
        limit: Optional[int] = None,
    ) -> List[RawFare]:
        return get_raw_fares_for_calculation(
            self.db,
            origin=origin,
            destination=destination,
            booking_window=booking_window,
            calculation_date=calculation_date,
            limit=limit,
        )

    def query_fares(self, **kwargs: Any) -> List[RawFare]:
        return get_raw_fares(self.db, **kwargs)

    def count(self, **kwargs: Any) -> int:
        return count_raw_fares(self.db, **kwargs)
