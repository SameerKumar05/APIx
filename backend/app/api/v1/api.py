from fastapi import APIRouter

from backend.app.api.v1.endpoints.ingestion import router as ingestion_router
from backend.app.api.v1.endpoints.indices import router as indices_router
from backend.app.api.v1.endpoints.analytics import router as analytics_router

api_router = APIRouter()

api_router.include_router(ingestion_router, prefix="/ingestion", tags=["Ingestion"])
api_router.include_router(indices_router, prefix="/indices", tags=["Indices"])
api_router.include_router(analytics_router, prefix="/analytics", tags=["Analytics"])
