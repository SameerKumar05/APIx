import logging
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from backend.app.api.v1.api import api_router
from backend.app.core.config import settings
from backend.app.db.session import get_db, init_db, probe_database_readiness

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        init_db()
    except SQLAlchemyError:
        logger.exception("Database schema initialization failed")
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan,
)

# CORS Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "X-Ingestion-Key",
    ],
    expose_headers=["X-Process-Time"],
)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window per-client limiter for the public read API.

    The PS expects an API that NSO and RBI can poll, so it must not be
    exhaustible. This is deliberately dependency-free and process-local: it is a
    guard against accidental hammering, not a distributed quota. A multi-worker
    deployment needs a shared store, which is recorded as open in the docs.
    """

    def __init__(self, app: ASGIApp, requests: int, window_seconds: int) -> None:
        super().__init__(app)
        self._limit = requests
        self._window = window_seconds
        self._hits: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if self._limit <= 0:
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        bucket = [t for t in self._hits.get(client, []) if now - t < self._window]

        if len(bucket) >= self._limit:
            retry_after = max(1, int(self._window - (now - bucket[0])))
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Retry after the window resets."},
            )
            response.headers["Retry-After"] = str(retry_after)
            response.headers["X-RateLimit-Limit"] = str(self._limit)
            response.headers["X-RateLimit-Remaining"] = "0"
            return response

        bucket.append(now)
        self._hits[client] = bucket
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self._limit - len(bucket)))
        return response


app.add_middleware(
    RateLimitMiddleware,
    requests=settings.API_RATE_LIMIT_REQUESTS,
    window_seconds=settings.API_RATE_LIMIT_WINDOW_SECONDS,
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    return response


# Global Exception Handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "status_code": exc.status_code,
            "detail": exc.detail,
            "path": request.url.path,
        },
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    formatted_errors = []
    for err in exc.errors():
        field = " -> ".join(str(loc) for loc in err.get("loc", []))
        formatted_errors.append(f"{field}: {err.get('msg', 'validation error')}")

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": True,
            "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "detail": "Request payload validation failed",
            "errors": formatted_errors,
            "path": request.url.path,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "detail": "An internal server error occurred.",
            "path": request.url.path,
        },
    )


@app.get(
    "/health",
    tags=["System"],
    summary="Service Health Check",
    description="Returns service availability, timestamp, and version metadata.",
)
async def health_check(db: Session = Depends(get_db)):
    try:
        probe_database_readiness(db)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    return {
        "status": "healthy",
        "service": "apix-backend-api",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.get(
    "/",
    tags=["System"],
    summary="Root Service Index",
    description="Provides entrypoint metadata and API discovery URLs.",
)
async def root():
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": f"{settings.API_V1_STR}/docs",
        "redoc": f"{settings.API_V1_STR}/redoc",
        "api_v1": settings.API_V1_STR,
        "status": "operational",
    }


# Include V1 API Router
app.include_router(api_router, prefix=settings.API_V1_STR)

# Convenience root WebSocket mounts for streaming clients
from backend.app.api.v1.endpoints.stream import router as stream_router
app.include_router(stream_router, prefix="/stream", tags=["Streaming"])
app.include_router(stream_router, prefix="/ws", tags=["Streaming"])
