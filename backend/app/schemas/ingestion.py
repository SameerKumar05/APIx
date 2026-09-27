from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, Field, field_validator


class RawFareRecord(BaseModel):
    airline_code: str = Field(
        ..., description="IATA 2-letter airline code (e.g., 6E, AI, UK, SG, QP)"
    )
    flight_number: str = Field(
        ..., description="Flight number identifier (e.g., 6E-205, AI-806)"
    )
    origin: str = Field(
        ..., description="IATA 3-letter origin airport code (e.g., DEL)"
    )
    destination: str = Field(
        ..., description="IATA 3-letter destination airport code (e.g., BOM)"
    )
    departure_datetime: datetime = Field(
        ..., description="Scheduled departure timestamp in UTC or ISO-8601"
    )
    arrival_datetime: datetime | None = Field(
        None, description="Scheduled arrival timestamp"
    )
    booking_datetime: datetime = Field(
        ..., description="Timestamp when the fare query/booking was recorded"
    )
    fare_inr: float = Field(
        ...,
        gt=0,
        description="Total one-way base fare in INR (inclusive of mandatory fees)",
    )
    base_fare: float | None = Field(
        None,
        ge=0,
        description="Base ticket fare before taxes, fuel surcharges, and fees in INR",
    )
    taxes_and_fees: float | None = Field(
        None,
        ge=0,
        description="Fuel surcharge, passenger service fee, and GST in INR",
    )
    cabin_class: str = Field(
        "economy", description="Cabin class (economy, premium_economy, business)"
    )
    booking_class: str | None = Field(
        None,
        description="Airline booking/fare-basis code (Y, B, M, X). Distinct from cabin_class.",
    )
    udf_fee: float | None = Field(
        None,
        ge=0,
        description="User development fee in INR. Null when the source did not supply it.",
    )
    convenience_fee: float | None = Field(
        None,
        ge=0,
        description="Convenience charge in INR. Null when the source did not supply it.",
    )
    flight_status: str | None = Field(
        None,
        description="scheduled, cancelled, or sold_out. Null when the source did not report a status.",
    )
    fare_split_basis: str | None = Field(
        None,
        description="measured, residual, or estimated. Null when the writer did not classify the split.",
    )
    stops: int = Field(
        0, ge=0, description="Number of layovers/stops (0 for direct flights)"
    )
    source: str = Field(
        "ota_scraper",
        description="Data source provider (e.g., makemytrip, easemytrip, airline_direct)",
    )
    booking_window: int | str | None = Field(
        None, description="Lead time in days or window code (e.g. 7 or 'T+7')"
    )
    is_synthetic: bool = Field(
        False, description="True if generated synthetically, False if from live source"
    )
    source_platform: str | None = Field(
        None, description="Platform identifier (e.g. spicejet, easemytrip, amadeus)"
    )

    @field_validator("origin", "destination")
    @classmethod
    def validate_airport_code(cls, v: str) -> str:
        clean = v.strip().upper()
        if len(clean) != 3:
            raise ValueError("Airport code must be a 3-letter IATA code")
        return clean

    @field_validator("airline_code")
    @classmethod
    def validate_airline_code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("cabin_class")
    @classmethod
    def normalize_cabin_class(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("booking_window", mode="before")
    @classmethod
    def parse_booking_window(cls, v: Any) -> int | str | None:
        if v is None:
            return None
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            clean = v.strip().upper()
            if clean in ("T1", "T+1"):
                return "T+1"
            if clean in ("T7", "T+7"):
                return "T+7"
            if clean in ("T15", "T+15"):
                return "T+15"
            if clean in ("T30", "T+30"):
                return "T+30"
            if clean.isdigit():
                return int(clean)
            return clean
        return cast("int | str | None", v)


class IngestionBatchRequest(BaseModel):
    batch_id: str | None = Field(
        None, description="Client-provided unique UUID or identifier for this batch"
    )
    source: str = Field(..., description="Data pipeline scraper or provider tag")
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Scrape execution timestamp",
    )
    records: list[RawFareRecord] = Field(
        ..., min_length=1, description="List of raw airline fare records"
    )


class IngestionBatchResponse(BaseModel):
    batch_id: str = Field(..., description="Unique batch identifier processed")
    status: str = Field(
        ..., description="Processing status: 'success', 'partial', or 'failed'"
    )
    records_received: int = Field(
        ..., description="Total records provided in the batch request"
    )
    records_valid: int = Field(
        ..., description="Count of validated records successfully accepted"
    )
    inserted_count: int = Field(
        0, description="Count of newly inserted records stored in database"
    )
    duplicate_count: int = Field(
        0, description="Count of duplicate records ignored by idempotent deduplication"
    )
    processing_time_ms: float = Field(
        0.0, description="Total batch processing and insertion time in milliseconds"
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Validation or ingestion error messages, if any",
    )
    message: str = Field(..., description="Human-readable summary message")
