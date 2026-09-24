"""Repository for scraper telemetry, crawler uptime/error metrics, and proxy health monitoring."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.models.telemetry import ProxyHealthRecord, ScraperTelemetry

logger = logging.getLogger("backend.app.db.telemetry_repo")

# Recognized status classifications
SUCCESS_STATUS_VALUES = {
    "SUCCESS",
    "COMPLETED",
    "PARTIAL",
    "FALLBACK_AMADEUS",
    "FALLBACK_SYNTHETIC",
}

FAILURE_STATUS_VALUES = {
    "FAILED",
    "ERROR",
    "TIMEOUT",
    "BLOCKED",
    "BANNED",
    "RATE_LIMITED",
    "CAPTCHA",
}


def _is_success_status(status: str) -> bool:
    """Determine whether a status string represents a successful or degraded-successful run."""
    normalized = status.strip().upper()
    if normalized in SUCCESS_STATUS_VALUES:
        return True
    if normalized.startswith("FALLBACK_"):
        return True
    return normalized not in FAILURE_STATUS_VALUES


# ============================================================================
# Scraper Telemetry Logging and Querying
# ============================================================================

def log_scraper_telemetry(
    db: Session,
    crawler_name: str,
    route: str,
    booking_window: str,
    status: str,
    response_time_ms: float = 0.0,
    records_extracted: int = 0,
    proxy_ip: str | None = None,
    error_details: str | None = None,
    created_at: datetime | None = None,
    commit: bool = True,
) -> ScraperTelemetry:
    """Create and persist an individual scraper execution telemetry event.

    Args:
        db: Active SQLAlchemy Session.
        crawler_name: Name of crawler (e.g. 'makemytrip', 'spicejet', 'easemytrip', 'amadeus', 'synthetic').
        route: Origin-destination route pair (e.g. 'DEL-BOM').
        booking_window: Booking horizon (e.g. 'T+1', 'T+7', 'T+15', 'T+30').
        status: Execution status ('SUCCESS', 'FAILED', 'PARTIAL', 'fallback_amadeus', etc.).
        response_time_ms: Round-trip crawler duration in milliseconds.
        records_extracted: Count of price quotes extracted.
        proxy_ip: Optional IP or URL of the proxy used.
        error_details: Traceback or error details if execution failed.
        created_at: Optional custom timestamp override (defaults to current UTC).
        commit: If True, commits the transaction immediately.

    Returns:
        The persisted ScraperTelemetry model instance.
    """
    telemetry = ScraperTelemetry(
        crawler_name=crawler_name,
        route=route,
        booking_window=booking_window,
        status=status,
        response_time_ms=max(0.0, float(response_time_ms)),
        records_extracted=max(0, int(records_extracted)),
        proxy_ip=proxy_ip,
        error_details=error_details,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(telemetry)
    if commit:
        db.commit()
        db.refresh(telemetry)
    return telemetry


def bulk_log_scraper_telemetry(
    db: Session,
    records: Sequence[dict[str, Any] | ScraperTelemetry],
    commit: bool = True,
) -> int:
    """Bulk insert scraper execution telemetry events.

    Args:
        db: Active SQLAlchemy Session.
        records: Collection of dicts or ScraperTelemetry instances.
        commit: If True, commits the transaction.

    Returns:
        Number of telemetry records inserted.
    """
    if not records:
        return 0

    to_add: list[ScraperTelemetry] = []
    now_utc = datetime.now(timezone.utc)

    for item in records:
        if isinstance(item, ScraperTelemetry):
            to_add.append(item)
        elif isinstance(item, dict):
            to_add.append(
                ScraperTelemetry(
                    crawler_name=str(item.get("crawler_name", "unknown")),
                    route=str(item.get("route", "UNKNOWN")),
                    booking_window=str(item.get("booking_window", "T+1")),
                    status=str(item.get("status", "SUCCESS")),
                    response_time_ms=max(0.0, float(item.get("response_time_ms", 0.0))),
                    records_extracted=max(0, int(item.get("records_extracted", 0))),
                    proxy_ip=item.get("proxy_ip"),
                    error_details=item.get("error_details"),
                    created_at=item.get("created_at") or now_utc,
                )
            )

    db.add_all(to_add)
    if commit:
        db.commit()

    return len(to_add)


def get_scraper_telemetry(
    db: Session,
    crawler_name: str | None = None,
    route: str | None = None,
    booking_window: str | None = None,
    status: str | None = None,
    proxy_ip: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ScraperTelemetry]:
    """Query scraper telemetry observations with flexible filtering.

    Args:
        db: Active SQLAlchemy Session.
        crawler_name: Filter by crawler identifier.
        route: Filter by route corridor.
        booking_window: Filter by booking window.
        status: Filter by execution status.
        proxy_ip: Filter by proxy IP address.
        start_time: Filter records created on or after this timestamp.
        end_time: Filter records created on or before this timestamp.
        limit: Maximum records to return (default 100).
        offset: Record offset for pagination.

    Returns:
        List of matching ScraperTelemetry instances ordered newest first.
    """
    stmt = select(ScraperTelemetry)
    if crawler_name:
        stmt = stmt.where(ScraperTelemetry.crawler_name == crawler_name)
    if route:
        stmt = stmt.where(ScraperTelemetry.route == route)
    if booking_window:
        stmt = stmt.where(ScraperTelemetry.booking_window == booking_window)
    if status:
        stmt = stmt.where(ScraperTelemetry.status == status)
    if proxy_ip:
        stmt = stmt.where(ScraperTelemetry.proxy_ip == proxy_ip)
    if start_time:
        stmt = stmt.where(ScraperTelemetry.created_at >= start_time)
    if end_time:
        stmt = stmt.where(ScraperTelemetry.created_at <= end_time)

    stmt = stmt.order_by(ScraperTelemetry.created_at.desc(), ScraperTelemetry.id.desc())
    stmt = stmt.offset(max(0, offset)).limit(max(1, limit))
    return list(db.scalars(stmt).all())


def count_scraper_telemetry(
    db: Session,
    crawler_name: str | None = None,
    route: str | None = None,
    status: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> int:
    """Count scraper telemetry records matching specified filters."""
    stmt = select(func.count(ScraperTelemetry.id))
    if crawler_name:
        stmt = stmt.where(ScraperTelemetry.crawler_name == crawler_name)
    if route:
        stmt = stmt.where(ScraperTelemetry.route == route)
    if status:
        stmt = stmt.where(ScraperTelemetry.status == status)
    if start_time:
        stmt = stmt.where(ScraperTelemetry.created_at >= start_time)
    if end_time:
        stmt = stmt.where(ScraperTelemetry.created_at <= end_time)
    return db.scalar(stmt) or 0


# ============================================================================
# Crawler Metrics Aggregations (Uptime, Error Rates, Summaries)
# ============================================================================

def calculate_crawler_uptime(
    db: Session,
    crawler_name: str | None = None,
    window_hours: float = 24.0,
    since: datetime | None = None,
) -> dict[str, Any]:
    """Calculate scraper uptime percentage and execution counts over a time horizon.

    Args:
        db: Active SQLAlchemy Session.
        crawler_name: Specific crawler to analyze, or None for aggregate over all crawlers.
        window_hours: Rolling time window in hours (default: 24.0).
        since: Explicit cutoff timestamp override (defaults to UTC now - window_hours).

    Returns:
        Dictionary with uptime_pct, total_runs, successful_runs, failed_runs,
        avg_response_time_ms, total_records_extracted, and per-crawler breakdown.
    """
    cutoff = since or (datetime.now(timezone.utc) - timedelta(hours=window_hours))

    # Base query for all matching records within the window
    stmt = select(
        ScraperTelemetry.crawler_name,
        ScraperTelemetry.status,
        ScraperTelemetry.response_time_ms,
        ScraperTelemetry.records_extracted,
    ).where(ScraperTelemetry.created_at >= cutoff)

    if crawler_name:
        stmt = stmt.where(ScraperTelemetry.crawler_name == crawler_name)

    rows = db.execute(stmt).all()

    total_runs = len(rows)
    if total_runs == 0:
        return {
            "crawler_name": crawler_name,
            "window_hours": window_hours,
            "since": cutoff.isoformat(),
            "uptime_pct": 100.0,
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "avg_response_time_ms": 0.0,
            "total_records_extracted": 0,
            "crawlers": {},
        }

    successful_runs = 0
    failed_runs = 0
    total_time_ms = 0.0
    total_records = 0

    crawler_stats: dict[str, dict[str, Any]] = {}

    for row in rows:
        c_name = row.crawler_name
        st = row.status
        r_time = float(row.response_time_ms or 0.0)
        recs = int(row.records_extracted or 0)

        total_time_ms += r_time
        total_records += recs

        if c_name not in crawler_stats:
            crawler_stats[c_name] = {
                "total_runs": 0,
                "successful_runs": 0,
                "failed_runs": 0,
                "total_time_ms": 0.0,
                "total_records": 0,
            }

        cs = crawler_stats[c_name]
        cs["total_runs"] += 1
        cs["total_time_ms"] += r_time
        cs["total_records"] += recs

        if _is_success_status(st):
            successful_runs += 1
            cs["successful_runs"] += 1
        else:
            failed_runs += 1
            cs["failed_runs"] += 1

    uptime_pct = round((successful_runs / total_runs) * 100.0, 2)
    avg_response_time_ms = round(total_time_ms / total_runs, 2)

    # Format per-crawler metrics
    per_crawler_result: dict[str, dict[str, Any]] = {}
    for c_name, cs in crawler_stats.items():
        c_total = cs["total_runs"]
        c_succ = cs["successful_runs"]
        per_crawler_result[c_name] = {
            "uptime_pct": round((c_succ / c_total) * 100.0, 2) if c_total > 0 else 100.0,
            "total_runs": c_total,
            "successful_runs": c_succ,
            "failed_runs": cs["failed_runs"],
            "avg_response_time_ms": round(cs["total_time_ms"] / c_total, 2) if c_total > 0 else 0.0,
            "total_records_extracted": cs["total_records"],
        }

    return {
        "crawler_name": crawler_name,
        "window_hours": window_hours,
        "since": cutoff.isoformat(),
        "uptime_pct": uptime_pct,
        "total_runs": total_runs,
        "successful_runs": successful_runs,
        "failed_runs": failed_runs,
        "avg_response_time_ms": avg_response_time_ms,
        "total_records_extracted": total_records,
        "crawlers": per_crawler_result,
    }


def calculate_crawler_error_rate(
    db: Session,
    crawler_name: str | None = None,
    window_hours: float = 24.0,
    since: datetime | None = None,
) -> dict[str, Any]:
    """Calculate error rates and failure distributions for scrapers over a time window.

    Args:
        db: Active SQLAlchemy Session.
        crawler_name: Specific crawler to analyze, or None for aggregate.
        window_hours: Rolling time window in hours (default: 24.0).
        since: Explicit cutoff timestamp override.

    Returns:
        Dictionary with error_rate_pct, total_runs, error_runs,
        errors_by_status, errors_by_crawler, and recent error samples.
    """
    cutoff = since or (datetime.now(timezone.utc) - timedelta(hours=window_hours))

    stmt = select(ScraperTelemetry).where(ScraperTelemetry.created_at >= cutoff)
    if crawler_name:
        stmt = stmt.where(ScraperTelemetry.crawler_name == crawler_name)

    stmt = stmt.order_by(ScraperTelemetry.created_at.desc())
    records = list(db.scalars(stmt).all())

    total_runs = len(records)
    if total_runs == 0:
        return {
            "crawler_name": crawler_name,
            "window_hours": window_hours,
            "since": cutoff.isoformat(),
            "error_rate_pct": 0.0,
            "total_runs": 0,
            "error_runs": 0,
            "errors_by_status": {},
            "errors_by_crawler": {},
            "recent_errors": [],
        }

    error_runs = 0
    errors_by_status: dict[str, int] = {}
    errors_by_crawler: dict[str, int] = {}
    recent_errors: list[dict[str, Any]] = []

    for r in records:
        if not _is_success_status(r.status):
            error_runs += 1
            st_key = r.status.upper()
            errors_by_status[st_key] = errors_by_status.get(st_key, 0) + 1
            errors_by_crawler[r.crawler_name] = errors_by_crawler.get(r.crawler_name, 0) + 1

            if len(recent_errors) < 10:
                recent_errors.append({
                    "id": r.id,
                    "crawler_name": r.crawler_name,
                    "route": r.route,
                    "booking_window": r.booking_window,
                    "status": r.status,
                    "proxy_ip": r.proxy_ip,
                    "error_details": r.error_details,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                })

    error_rate_pct = round((error_runs / total_runs) * 100.0, 2)

    return {
        "crawler_name": crawler_name,
        "window_hours": window_hours,
        "since": cutoff.isoformat(),
        "error_rate_pct": error_rate_pct,
        "total_runs": total_runs,
        "error_runs": error_runs,
        "errors_by_status": errors_by_status,
        "errors_by_crawler": errors_by_crawler,
        "recent_errors": recent_errors,
    }


def get_crawler_summary(
    db: Session,
    window_hours: float = 24.0,
) -> dict[str, Any]:
    """Retrieve comprehensive crawler operations summary for API monitoring endpoints.

    Integrates uptime, error rate, throughput, and status distribution.
    """
    uptime_data = calculate_crawler_uptime(db, crawler_name=None, window_hours=window_hours)
    error_data = calculate_crawler_error_rate(db, crawler_name=None, window_hours=window_hours)

    return {
        "window_hours": window_hours,
        "since": uptime_data["since"],
        "overall_uptime_pct": uptime_data["uptime_pct"],
        "overall_error_rate_pct": error_data["error_rate_pct"],
        "total_runs": uptime_data["total_runs"],
        "successful_runs": uptime_data["successful_runs"],
        "failed_runs": uptime_data["failed_runs"],
        "avg_response_time_ms": uptime_data["avg_response_time_ms"],
        "total_records_extracted": uptime_data["total_records_extracted"],
        "errors_by_status": error_data["errors_by_status"],
        "errors_by_crawler": error_data["errors_by_crawler"],
        "crawlers": uptime_data["crawlers"],
        "recent_errors": error_data["recent_errors"][:5],
    }


# ============================================================================
# Proxy Health Monitoring and Latency Statistics
# ============================================================================

def log_proxy_health(
    db: Session,
    proxy_ip: str,
    status: str = "HEALTHY",
    latency_ms: float = 0.0,
    success_count: int = 0,
    failure_count: int = 0,
    consecutive_failures: int = 0,
    last_checked_at: datetime | None = None,
    error_message: str | None = None,
    created_at: datetime | None = None,
    commit: bool = True,
) -> ProxyHealthRecord:
    """Create and persist an individual proxy health diagnostic observation."""
    now_utc = datetime.now(timezone.utc)
    record = ProxyHealthRecord(
        proxy_ip=proxy_ip,
        status=status.upper(),
        latency_ms=max(0.0, float(latency_ms)),
        success_count=max(0, int(success_count)),
        failure_count=max(0, int(failure_count)),
        consecutive_failures=max(0, int(consecutive_failures)),
        last_checked_at=last_checked_at or now_utc,
        error_message=error_message,
        created_at=created_at or now_utc,
    )
    db.add(record)
    if commit:
        db.commit()
        db.refresh(record)
    return record


def upsert_proxy_health(
    db: Session,
    proxy_ip: str,
    status: str | None = None,
    latency_ms: float = 0.0,
    is_success: bool | None = None,
    error_message: str | None = None,
    last_checked_at: datetime | None = None,
    circuit_break_threshold: int = 3,
    commit: bool = True,
) -> ProxyHealthRecord:
    """Update existing proxy health status or insert a new record with automatic state tracking.

    Automatically manages success/failure counters, consecutive failures for circuit breaking,
    and transitions status (e.g. to DEGRADED or BANNED on consecutive failures).

    Args:
        db: Active SQLAlchemy Session.
        proxy_ip: IP or URL of the proxy server.
        status: Explicit status override (e.g. 'HEALTHY', 'DEGRADED', 'BANNED', 'TIMEOUT').
        latency_ms: Most recent measured latency in milliseconds.
        is_success: True if check succeeded, False if check failed.
        error_message: Optional error message on failure.
        circuit_break_threshold: Consecutive failures before auto-marking DEGRADED (default: 3).
        commit: If True, commits changes immediately.

    Returns:
        The updated or newly created ProxyHealthRecord.
    """
    now_utc = datetime.now(timezone.utc)
    stmt = (
        select(ProxyHealthRecord)
        .where(ProxyHealthRecord.proxy_ip == proxy_ip)
        .order_by(ProxyHealthRecord.last_checked_at.desc(), ProxyHealthRecord.id.desc())
    )
    record = db.scalars(stmt).first()

    if record is None:
        # Determine initial counts
        consec_fail = 1 if is_success is False else 0
        succ_cnt = 1 if is_success is True else 0
        fail_cnt = 1 if is_success is False else 0

        initial_status = status.upper() if status else ("HEALTHY" if is_success is not False else "DEGRADED")
        record = ProxyHealthRecord(
            proxy_ip=proxy_ip,
            status=initial_status,
            latency_ms=max(0.0, float(latency_ms)),
            success_count=succ_cnt,
            failure_count=fail_cnt,
            consecutive_failures=consec_fail,
            last_checked_at=last_checked_at or now_utc,
            error_message=error_message,
            created_at=now_utc,
        )
        db.add(record)
    else:
        # Update existing record
        record.latency_ms = max(0.0, float(latency_ms))
        record.last_checked_at = last_checked_at or now_utc

        if is_success is True:
            record.success_count += 1
            record.consecutive_failures = 0
            record.status = status.upper() if status else "HEALTHY"
            record.error_message = None
        elif is_success is False:
            record.failure_count += 1
            record.consecutive_failures += 1
            if status:
                record.status = status.upper()
            elif record.consecutive_failures >= circuit_break_threshold:
                record.status = "DEGRADED"
            if error_message:
                record.error_message = error_message
        elif status:
            record.status = status.upper()
            if error_message is not None:
                record.error_message = error_message

    if commit:
        db.commit()
        db.refresh(record)
    return record


def get_proxy_health_records(
    db: Session,
    proxy_ip: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ProxyHealthRecord]:
    """Retrieve proxy health records ordered by most recent check first."""
    stmt = select(ProxyHealthRecord)
    if proxy_ip:
        stmt = stmt.where(ProxyHealthRecord.proxy_ip == proxy_ip)
    if status:
        stmt = stmt.where(ProxyHealthRecord.status == status.upper())

    stmt = stmt.order_by(ProxyHealthRecord.last_checked_at.desc(), ProxyHealthRecord.id.desc())
    stmt = stmt.offset(max(0, offset)).limit(max(1, limit))
    return list(db.scalars(stmt).all())


def get_active_healthy_proxies(
    db: Session,
    max_latency_ms: float | None = None,
    max_consecutive_failures: int = 3,
    limit: int = 50,
) -> list[ProxyHealthRecord]:
    """Retrieve active healthy proxies suitable for scraper pool rotation."""
    stmt = (
        select(ProxyHealthRecord)
        .where(
            ProxyHealthRecord.status == "HEALTHY",
            ProxyHealthRecord.consecutive_failures < max_consecutive_failures,
        )
    )
    if max_latency_ms is not None:
        stmt = stmt.where(ProxyHealthRecord.latency_ms <= max_latency_ms)

    stmt = stmt.order_by(ProxyHealthRecord.latency_ms.asc(), ProxyHealthRecord.last_checked_at.desc())
    stmt = stmt.limit(max(1, limit))
    return list(db.scalars(stmt).all())


def get_proxy_latency_stats(
    db: Session,
    proxy_ip: str | None = None,
    window_hours: float = 24.0,
    status: str | None = None,
    since: datetime | None = None,
) -> dict[str, Any]:
    """Calculate proxy latency statistics and health status distribution.

    Args:
        db: Active SQLAlchemy Session.
        proxy_ip: Specific proxy to analyze, or None for aggregate over all proxies.
        window_hours: Rolling time window in hours (default: 24.0).
        status: Filter by specific proxy health status.
        since: Explicit cutoff timestamp override.

    Returns:
        Dictionary with count, avg_latency_ms, min_latency_ms, max_latency_ms,
        p95_latency_ms, status breakdown, healthy/degraded/banned/dead counts.
    """
    cutoff = since or (datetime.now(timezone.utc) - timedelta(hours=window_hours))

    stmt = select(ProxyHealthRecord).where(ProxyHealthRecord.last_checked_at >= cutoff)
    if proxy_ip:
        stmt = stmt.where(ProxyHealthRecord.proxy_ip == proxy_ip)
    if status:
        stmt = stmt.where(ProxyHealthRecord.status == status.upper())

    records = list(db.scalars(stmt).all())

    count = len(records)
    if count == 0:
        return {
            "proxy_ip": proxy_ip,
            "window_hours": window_hours,
            "since": cutoff.isoformat(),
            "count": 0,
            "avg_latency_ms": 0.0,
            "min_latency_ms": 0.0,
            "max_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "healthy_count": 0,
            "degraded_count": 0,
            "banned_count": 0,
            "dead_count": 0,
            "status_breakdown": {},
            "total_successes": 0,
            "total_failures": 0,
        }

    latencies = sorted([float(r.latency_ms) for r in records])
    avg_latency = round(sum(latencies) / count, 2)
    min_latency = round(latencies[0], 2)
    max_latency = round(latencies[-1], 2)

    # 95th percentile latency
    p95_idx = int(0.95 * (count - 1))
    p95_latency = round(latencies[p95_idx], 2)

    status_breakdown: dict[str, int] = {}
    healthy_count = 0
    degraded_count = 0
    banned_count = 0
    dead_count = 0
    total_successes = 0
    total_failures = 0

    for r in records:
        st = r.status.upper()
        status_breakdown[st] = status_breakdown.get(st, 0) + 1
        total_successes += r.success_count
        total_failures += r.failure_count

        if st == "HEALTHY":
            healthy_count += 1
        elif st == "DEGRADED":
            degraded_count += 1
        elif st in ("BANNED", "RATE_LIMITED", "BLOCKED"):
            banned_count += 1
        elif st in ("DEAD", "TIMEOUT", "UNREACHABLE"):
            dead_count += 1

    return {
        "proxy_ip": proxy_ip,
        "window_hours": window_hours,
        "since": cutoff.isoformat(),
        "count": count,
        "avg_latency_ms": avg_latency,
        "min_latency_ms": min_latency,
        "max_latency_ms": max_latency,
        "p95_latency_ms": p95_latency,
        "healthy_count": healthy_count,
        "degraded_count": degraded_count,
        "banned_count": banned_count,
        "dead_count": dead_count,
        "status_breakdown": status_breakdown,
        "total_successes": total_successes,
        "total_failures": total_failures,
    }


def get_proxy_summary(
    db: Session,
    window_hours: float = 24.0,
) -> dict[str, Any]:
    """Retrieve comprehensive proxy pool operations summary for API monitoring endpoints."""
    stats = get_proxy_latency_stats(db, proxy_ip=None, window_hours=window_hours)
    # Distinct active proxies count
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    stmt = (
        select(func.count(func.distinct(ProxyHealthRecord.proxy_ip)))
        .where(ProxyHealthRecord.last_checked_at >= cutoff)
    )
    distinct_proxies = db.scalar(stmt) or 0

    return {
        "window_hours": window_hours,
        "since": stats["since"],
        "distinct_proxies": distinct_proxies,
        "total_health_checks": stats["count"],
        "healthy_count": stats["healthy_count"],
        "degraded_count": stats["degraded_count"],
        "banned_count": stats["banned_count"],
        "dead_count": stats["dead_count"],
        "avg_latency_ms": stats["avg_latency_ms"],
        "p95_latency_ms": stats["p95_latency_ms"],
        "status_breakdown": stats["status_breakdown"],
        "total_successes": stats["total_successes"],
        "total_failures": stats["total_failures"],
    }


# ============================================================================
# Retention and Storage Cleanup
# ============================================================================

def cleanup_old_telemetry(
    db: Session,
    retention_days: int = 30,
    cutoff_datetime: datetime | None = None,
    commit: bool = True,
) -> dict[str, int]:
    """Automated retention pruning: remove telemetry and proxy checks older than N days.

    Args:
        db: Active SQLAlchemy Session.
        retention_days: Retention horizon in days (default: 30).
        cutoff_datetime: Optional explicit cutoff override.
        commit: If True, commits the transaction.

    Returns:
        Dictionary with pruned counts for scraper_telemetry and proxy_health_records.
    """
    if cutoff_datetime is None:
        cutoff_datetime = datetime.now(timezone.utc) - timedelta(days=retention_days)

    # 1. Prune scraper telemetry
    stmt_telemetry = delete(ScraperTelemetry).where(ScraperTelemetry.created_at < cutoff_datetime)
    res_t = db.execute(stmt_telemetry)
    telemetry_pruned = res_t.rowcount if res_t.rowcount is not None and res_t.rowcount >= 0 else 0

    # 2. Prune proxy health records
    stmt_proxy = delete(ProxyHealthRecord).where(ProxyHealthRecord.created_at < cutoff_datetime)
    res_p = db.execute(stmt_proxy)
    proxy_pruned = res_p.rowcount if res_p.rowcount is not None and res_p.rowcount >= 0 else 0

    if commit:
        db.commit()
    db.expunge_all()
    logger.info(
        "Pruned %d scraper telemetry records and %d proxy health records older than %d days (cutoff: %s).",
        telemetry_pruned,
        proxy_pruned,
        retention_days,
        cutoff_datetime.isoformat(),
    )

    return {
        "scraper_telemetry_pruned": telemetry_pruned,
        "proxy_health_pruned": proxy_pruned,
        "total_pruned": telemetry_pruned + proxy_pruned,
    }


# ============================================================================
# Object-Oriented Repository Wrapper
# ============================================================================

class TelemetryRepo:
    """Object-oriented repository wrapper for scraper telemetry and proxy health operations.

    Provides a clean instance interface initialized with a SQLAlchemy Session,
    matching the IngestionRepo pattern.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def log_telemetry(self, **kwargs: Any) -> ScraperTelemetry:
        """Log a scraper telemetry event."""
        return log_scraper_telemetry(self.db, **kwargs)

    def bulk_log_telemetry(self, records: Sequence[dict[str, Any] | ScraperTelemetry], commit: bool = True) -> int:
        """Bulk log scraper telemetry events."""
        return bulk_log_scraper_telemetry(self.db, records=records, commit=commit)

    def get_telemetry(self, **kwargs: Any) -> list[ScraperTelemetry]:
        """Query scraper telemetry observations."""
        return get_scraper_telemetry(self.db, **kwargs)

    def count_telemetry(self, **kwargs: Any) -> int:
        """Count scraper telemetry records."""
        return count_scraper_telemetry(self.db, **kwargs)

    def get_crawler_uptime(self, **kwargs: Any) -> dict[str, Any]:
        """Calculate scraper uptime percentage."""
        return calculate_crawler_uptime(self.db, **kwargs)

    def get_crawler_error_rate(self, **kwargs: Any) -> dict[str, Any]:
        """Calculate scraper error rate metrics."""
        return calculate_crawler_error_rate(self.db, **kwargs)

    def get_crawler_summary(self, **kwargs: Any) -> dict[str, Any]:
        """Retrieve aggregated crawler summary."""
        return get_crawler_summary(self.db, **kwargs)

    def log_proxy(self, **kwargs: Any) -> ProxyHealthRecord:
        """Log a proxy health observation."""
        return log_proxy_health(self.db, **kwargs)

    def upsert_proxy(self, **kwargs: Any) -> ProxyHealthRecord:
        """Upsert a proxy health record."""
        return upsert_proxy_health(self.db, **kwargs)

    def get_proxy_records(self, **kwargs: Any) -> list[ProxyHealthRecord]:
        """Query proxy health records."""
        return get_proxy_health_records(self.db, **kwargs)

    def get_healthy_proxies(self, **kwargs: Any) -> list[ProxyHealthRecord]:
        """Query healthy proxies for scraping rotation."""
        return get_active_healthy_proxies(self.db, **kwargs)

    def get_proxy_stats(self, **kwargs: Any) -> dict[str, Any]:
        """Calculate proxy latency statistics."""
        return get_proxy_latency_stats(self.db, **kwargs)

    def get_proxy_summary(self, **kwargs: Any) -> dict[str, Any]:
        """Retrieve aggregated proxy pool summary."""
        return get_proxy_summary(self.db, **kwargs)

    def cleanup(self, **kwargs: Any) -> dict[str, int]:
        """Prune stale telemetry and health records."""
        return cleanup_old_telemetry(self.db, **kwargs)
