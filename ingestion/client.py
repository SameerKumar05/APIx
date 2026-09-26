"""HTTP client for dispatching raw fare batches to APIx Backend ingestion endpoint.

Posts batches to POST /api/v1/ingestion/batch authenticated by X-Ingestion-Key header,
with automatic chunking, retry backoff, and dual-backend support (httpx with urllib fallback).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError

from ingestion.base import RawFareRecord
from ingestion.config import IngestionConfig

logger = logging.getLogger("ingestion.client")

# Attempt importing httpx for async / high-performance HTTP
try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    httpx = None  # type: ignore
    HAS_HTTPX = False


class IngestionClient:
    """Production client for APIx Ingestion API."""

    def __init__(
        self,
        config: IngestionConfig | None = None,
        base_url: str | None = None,
        ingestion_key: str | None = None,
    ) -> None:
        self.config = config or IngestionConfig()
        self.base_url = (
            base_url or os.getenv("INGESTION_ENDPOINT_URL") or self.config.api_base_url
        ).rstrip("/")
        self.ingestion_key = ingestion_key or self.config.ingestion_key
        self.batch_endpoint = f"{self.base_url}/api/v1/ingestion/batch"

    def _format_payload(
        self,
        records: list[RawFareRecord],
        source: str,
        batch_id: str | None = None,
        scraped_at: str | None = None,
    ) -> dict[str, Any]:
        """Formats payload conforming to IngestionBatchRequest schema."""
        b_id = batch_id or f"batch-{uuid.uuid4().hex[:12]}"
        scrape_time = scraped_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

        serialized_records = []
        for r in records:
            rec_dict = r.to_dict()
            bw = rec_dict.get("booking_window")
            if isinstance(bw, str):
                match = re.search(r"\d+", bw)
                rec_dict["booking_window"] = int(match.group()) if match else None
            serialized_records.append(rec_dict)

        return {
            "batch_id": b_id,
            "source": source,
            "scraped_at": scrape_time,
            "records": serialized_records,
        }

    def _post_with_urllib(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Dispatches batch using standard library urllib."""
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url=self.batch_endpoint,
            data=data_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Ingestion-Key": self.ingestion_key,
                "User-Agent": "APIx-IngestionClient/1.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
            resp_body = resp.read().decode("utf-8")
            return json.loads(resp_body)

    def _post_with_httpx(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Dispatches batch using httpx."""
        headers = {
            "Content-Type": "application/json",
            "X-Ingestion-Key": self.ingestion_key,
            "User-Agent": "APIx-IngestionClient/1.0",
        }
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(self.batch_endpoint, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

    def post_batch(
        self,
        records: list[RawFareRecord],
        source: str = "synthetic",
        batch_id: str | None = None,
        scraped_at: str | None = None,
    ) -> dict[str, Any]:
        """Posts a single batch of records with retry and exponential backoff.

        Returns server response dict.
        """
        payload = self._format_payload(
            records=records,
            source=source,
            batch_id=batch_id,
            scraped_at=scraped_at,
        )

        retries = self.config.max_retries
        backoff = self.config.retry_backoff_factor

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                logger.info(
                    "Posting batch %s (%d records) to %s (attempt %d/%d)",
                    payload["batch_id"],
                    len(records),
                    self.batch_endpoint,
                    attempt,
                    retries,
                )
                if HAS_HTTPX:
                    return self._post_with_httpx(payload)
                else:
                    return self._post_with_urllib(payload)

            except (HTTPError, URLError, Exception) as exc:
                last_error = exc
                if attempt == retries:
                    logger.error(
                        "Failed to post batch %s after %d attempts: %s",
                        payload["batch_id"],
                        retries,
                        exc,
                    )
                    raise
                wait_time = backoff ** (attempt - 1)
                logger.warning(
                    "Post batch %s failed (%s); retrying in %.2fs...",
                    payload["batch_id"],
                    exc,
                    wait_time,
                )
                time.sleep(wait_time)

        raise RuntimeError(f"Unexpected exit posting batch: {last_error}")

    async def post_batch_async(
        self,
        records: list[RawFareRecord],
        source: str = "synthetic",
        batch_id: str | None = None,
        scraped_at: str | None = None,
    ) -> dict[str, Any]:
        """Asynchronously posts a batch using httpx AsyncClient."""
        if not HAS_HTTPX:
            # Fall back to synchronous post if httpx is not installed
            return self.post_batch(
                records, source=source, batch_id=batch_id, scraped_at=scraped_at
            )

        payload = self._format_payload(
            records=records,
            source=source,
            batch_id=batch_id,
            scraped_at=scraped_at,
        )
        headers = {
            "Content-Type": "application/json",
            "X-Ingestion-Key": self.ingestion_key,
            "User-Agent": "APIx-IngestionClient/1.0",
        }
        async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
            response = await client.post(
                self.batch_endpoint, json=payload, headers=headers
            )
            response.raise_for_status()
            return response.json()

    def post_records_chunked(
        self,
        records: list[RawFareRecord],
        source: str = "synthetic",
        chunk_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """Splits large record lists into chunk_size batches and posts each sequentially.

        Returns list of batch responses.
        """
        size = chunk_size or self.config.batch_size
        results: list[dict[str, Any]] = []

        total = len(records)
        for i in range(0, total, size):
            chunk = records[i : i + size]
            chunk_batch_id = f"batch-{uuid.uuid4().hex[:8]}-{i // size + 1}"
            res = self.post_batch(records=chunk, source=source, batch_id=chunk_batch_id)
            results.append(res)

        return results
