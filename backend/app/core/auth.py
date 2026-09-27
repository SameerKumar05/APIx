"""Authentication dependencies for API boundaries."""

import secrets

from fastapi import Header, HTTPException, status

from backend.app.core.config import settings


async def verify_ingestion_key(
    x_ingestion_key: str | None = Header(None, alias="X-Ingestion-Key"),
) -> str:
    """Require the configured ingestion key for crawler and fare writes."""
    if not x_ingestion_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required authentication header: X-Ingestion-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if not secrets.compare_digest(x_ingestion_key, settings.INGESTION_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-Ingestion-Key API key provided",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_ingestion_key
