from backend.app.api.v1.endpoints.ingestion import router as ingestion_router
from backend.app.api.v1.endpoints.indices import router as indices_router
from backend.app.api.v1.endpoints.analytics import router as analytics_router

__all__ = ["ingestion_router", "indices_router", "analytics_router"]
