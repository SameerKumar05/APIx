"""Telemetry schemas for scraper health, crawler metrics, proxy pools, and triggers."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class CrawlerHealthItem(BaseModel):
    """Health, uptime, and performance metrics for an individual scraper platform."""

    crawler_name: str = Field(..., description="Canonical crawler identifier (e.g. easemytrip, makemytrip, spicejet)")
    platform: str = Field("OTA", description="Platform type (OTA, Direct Airline, GDS)")
    status: str = Field("ACTIVE", description="Operating status (ACTIVE, HEALTHY, DEGRADED, IDLE, ERROR)")
    uptime_pct: float = Field(100.0, ge=0.0, le=100.0, description="Crawler uptime percentage over query horizon")
    success_count: int = Field(0, ge=0, description="Total successful scrape executions")
    error_count: int = Field(0, ge=0, description="Total failed or timed-out scrape executions")
    error_rate_pct: float = Field(0.0, ge=0.0, le=100.0, description="Failure rate percentage")
    last_run_at: Optional[datetime] = Field(None, description="Timestamp of most recent crawl execution")
    fares_collected: int = Field(0, ge=0, description="Cumulative valid raw fare records collected")
    avg_latency_ms: float = Field(0.0, ge=0.0, description="Average HTTP round-trip latency in milliseconds")
    routes_active: int = Field(10, ge=0, description="Count of distinct route corridors actively monitored")


class ProxyPoolSummary(BaseModel):
    """Aggregate health and latency statistics for proxy pool."""

    total_proxies: int = Field(..., ge=0, description="Total proxy endpoints configured")
    active_proxies: int = Field(..., ge=0, description="Healthy active proxies available for rotation")
    blacklisted_proxies: int = Field(0, ge=0, description="Temporarily blacklisted or banned proxies")
    avg_latency_ms: float = Field(0.0, ge=0.0, description="Average response latency across active proxies")
    p95_latency_ms: float = Field(0.0, ge=0.0, description="95th percentile latency in milliseconds")
    min_latency_ms: float = Field(0.0, ge=0.0, description="Fastest recorded proxy latency in milliseconds")
    max_latency_ms: float = Field(0.0, ge=0.0, description="Slowest recorded proxy latency in milliseconds")


class ProxyHealthItem(BaseModel):
    """Health diagnostic for an individual proxy IP endpoint."""

    proxy_ip: str = Field(..., description="Proxy IP address or host")
    status: str = Field("HEALTHY", description="Status (HEALTHY, DEGRADED, BANNED, TIMEOUT)")
    latency_ms: float = Field(..., ge=0.0, description="Observed round-trip latency in ms")
    success_count: int = Field(0, ge=0, description="Successful requests")
    failure_count: int = Field(0, ge=0, description="Failed requests")
    consecutive_failures: int = Field(0, ge=0, description="Consecutive failure streak")
    last_checked_at: Optional[datetime] = Field(None, description="Last diagnostic ping timestamp")


class IngestionTelemetryResponse(BaseModel):
    """Comprehensive telemetry report for ingestion pipelines, scrapers, and proxies."""

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Report generation timestamp")
    system_health: str = Field("HEALTHY", description="Overall ingestion system health status")
    total_active_scrapers: int = Field(..., ge=0, description="Total active scraper instances")
    total_fares_collected_today: int = Field(0, ge=0, description="Total fares collected in current UTC date")
    scrapers: List[CrawlerHealthItem] = Field(..., description="Per-platform crawler health breakdowns")
    proxy_pool: ProxyPoolSummary = Field(..., description="Proxy infrastructure aggregate health")
    recent_errors: List[str] = Field(default_factory=list, description="Recent crawler or proxy error messages")


class CrawlerTriggerRequest(BaseModel):
    """Payload to trigger an ad-hoc or scheduled crawler job."""

    crawler_name: Optional[str] = Field(None, description="Specific crawler identifier (e.g. makemytrip, spicejet, easemytrip)")
    source: Optional[str] = Field(None, description="Alias for crawler_name")
    route_code: Optional[str] = Field(None, description="Optional target route code (e.g. DEL-BOM)")
    booking_window: Optional[str] = Field(None, description="Optional booking window (e.g. T+1, T+7)")


class CrawlerTriggerResponse(BaseModel):
    """Response confirming trigger dispatch."""

    task_id: str = Field(..., description="Unique asynchronous trigger task identifier")
    status: str = Field("TRIGGERED", description="Execution status ('TRIGGERED', 'QUEUED', 'SUCCESS')")
    crawler_name: str = Field(..., description="Target crawler executed")
    route_code: Optional[str] = Field(None, description="Target route code, if scoped")
    message: str = Field(..., description="Human-readable execution confirmation")
    triggered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Trigger dispatch timestamp")
