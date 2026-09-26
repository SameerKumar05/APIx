import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.v1.endpoints.analytics import router as analytics_router
from backend.app.api.v1.endpoints.arbitrage import router as arbitrage_router
from backend.app.api.v1.endpoints.econometrics import router as econometrics_router
from backend.app.api.v1.endpoints.indices import router as indices_router
from backend.app.api.v1.endpoints.ingestion import router as ingestion_router
from backend.app.api.v1.endpoints.stream import router as stream_router
from backend.app.api.v1.endpoints.telemetry import router as telemetry_router
from backend.app.db.session import get_db, probe_database_readiness
from backend.app.models.raw_fare import RawFare
from backend.app.models.telemetry import ScraperTelemetry

api_router = APIRouter()


@api_router.get("/health", tags=["System"], summary="API System Health")
async def api_health(db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    recent_cutoff = now - timedelta(hours=24)
    started_at = time.perf_counter()

    try:
        probe_database_readiness(db)
        records_ingested_today = int(
            db.scalar(
                select(func.count(RawFare.id)).where(RawFare.scraped_at >= midnight)
            )
            or 0
        )
        active_scrapers = int(
            db.scalar(
                select(func.count(func.distinct(ScraperTelemetry.crawler_name))).where(
                    ScraperTelemetry.created_at >= recent_cutoff,
                    ScraperTelemetry.status.in_(("SUCCESS", "TRIGGERED", "PARTIAL")),
                )
            )
            or 0
        )
        last_scraped_at = db.scalar(select(func.max(RawFare.scraped_at)))
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc

    latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
    timestamp = now.isoformat()
    return {
        "status": "HEALTHY",
        "system_health": "HEALTHY",
        "active_scrapers": active_scrapers,
        "records_ingested_today": records_ingested_today,
        "last_sync_timestamp": last_scraped_at.isoformat() if last_scraped_at else "",
        "supported_airlines": ["6E", "AI", "IX", "QP", "SG"],
        "supported_sources": ["makemytrip", "easemytrip", "spicejet"],
        "source_types": {
            "makemytrip": "ota",
            "easemytrip": "ota",
            "spicejet": "airline_direct",
        },
        "ps_named_sources_total": 11,
        "ps_named_sources_implemented": 3,
        "latency_ms": latency_ms,
        "service": "apix-backend-api",
        "timestamp": timestamp,
    }


# Ingestion and Telemetry endpoints
api_router.include_router(ingestion_router, prefix="/ingestion", tags=["Ingestion"])
api_router.include_router(telemetry_router, prefix="/ingestion", tags=["Telemetry"])
api_router.include_router(telemetry_router, prefix="/telemetry", tags=["Telemetry"])

# Indices endpoints
api_router.include_router(indices_router, prefix="/indices", tags=["Indices"])

# Analytics and Arbitrage endpoints
api_router.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])
api_router.include_router(arbitrage_router, prefix="/analytics", tags=["Arbitrage"])
api_router.include_router(arbitrage_router, prefix="/arbitrage", tags=["Arbitrage"])


# Econometrics, CPI Gap Analytics, and DGCA Surveillance endpoints
api_router.include_router(econometrics_router, prefix="/econometrics", tags=["Econometrics"])
api_router.include_router(econometrics_router, prefix="/anomalies", tags=["Anomalies"])
# Real-time Streaming WebSocket and diagnostics endpoints
api_router.include_router(stream_router, prefix="/stream", tags=["Streaming"])
