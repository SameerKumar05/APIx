from fastapi import APIRouter

from backend.app.api.v1.endpoints.analytics import router as analytics_router
from backend.app.api.v1.endpoints.arbitrage import router as arbitrage_router
from backend.app.api.v1.endpoints.econometrics import router as econometrics_router
from backend.app.api.v1.endpoints.indices import router as indices_router
from backend.app.api.v1.endpoints.ingestion import router as ingestion_router
from backend.app.api.v1.endpoints.stream import router as stream_router
from backend.app.api.v1.endpoints.telemetry import router as telemetry_router

api_router = APIRouter()

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
