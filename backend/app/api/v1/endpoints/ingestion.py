import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status

from backend.app.core.config import settings
from backend.app.schemas.ingestion import (
    IngestionBatchRequest,
    IngestionBatchResponse,
)

router = APIRouter()


async def verify_ingestion_key(
    x_ingestion_key: Optional[str] = Header(None, alias="X-Ingestion-Key"),
) -> str:
    if not x_ingestion_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required authentication header: X-Ingestion-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if x_ingestion_key != settings.INGESTION_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-Ingestion-Key API key provided",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_ingestion_key


@router.post(
    "/batch",
    response_model=IngestionBatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest batch of raw flight fare records",
    description="Secured endpoint accepting high-throughput scraped flight fare records from ingestion pipelines.",
)
async def ingest_fare_batch(
    payload: IngestionBatchRequest,
    _: str = Depends(verify_ingestion_key),
) -> IngestionBatchResponse:
    batch_id = payload.batch_id or f"batch-{uuid.uuid4().hex[:12]}"
    errors = []
    valid_count = 0

    for idx, record in enumerate(payload.records):
        if record.origin == record.destination:
            errors.append(f"Record #{idx}: Origin and destination cannot be identical ({record.origin})")
            continue
        if record.fare_inr <= 0:
            errors.append(f"Record #{idx}: Fare INR must be greater than zero")
            continue
        valid_count += 1

    status_str = "success" if valid_count == len(payload.records) else ("partial" if valid_count > 0 else "failed")
    message = f"Processed {len(payload.records)} records: {valid_count} valid, {len(errors)} rejected."

    return IngestionBatchResponse(
        batch_id=batch_id,
        status=status_str,
        records_received=len(payload.records),
        records_valid=valid_count,
        errors=errors,
        message=message,
    )
