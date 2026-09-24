from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class RawFareRecord(BaseModel):
    airline_code: str = Field(..., description="IATA 2-letter airline code (e.g., 6E, AI, UK, SG, QP)")
    flight_number: str = Field(..., description="Flight number identifier (e.g., 6E-205, AI-806)")
    origin: str = Field(..., description="IATA 3-letter origin airport code (e.g., DEL)")
    destination: str = Field(..., description="IATA 3-letter destination airport code (e.g., BOM)")
    departure_datetime: datetime = Field(..., description="Scheduled departure timestamp in UTC or ISO-8601")
    arrival_datetime: Optional[datetime] = Field(None, description="Scheduled arrival timestamp")
    booking_datetime: datetime = Field(..., description="Timestamp when the fare query/booking was recorded")
    fare_inr: float = Field(..., gt=0, description="Total one-way base fare in INR (inclusive of mandatory fees)")
    cabin_class: str = Field("economy", description="Cabin class (economy, premium_economy, business)")
    stops: int = Field(0, ge=0, description="Number of layovers/stops (0 for direct flights)")
    source: str = Field("ota_scraper", description="Data source provider (e.g., makemytrip, easemytrip, airline_direct)")
    booking_window: Optional[int] = Field(None, ge=0, description="Lead time in days before departure")

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


class IngestionBatchRequest(BaseModel):
    batch_id: Optional[str] = Field(None, description="Client-provided unique UUID or identifier for this batch")
    source: str = Field(..., description="Data pipeline scraper or provider tag")
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Scrape execution timestamp")
    records: List[RawFareRecord] = Field(..., min_length=1, description="List of raw airline fare records")


class IngestionBatchResponse(BaseModel):
    batch_id: str = Field(..., description="Unique batch identifier processed")
    status: str = Field(..., description="Processing status: 'success', 'partial', or 'failed'")
    records_received: int = Field(..., description="Total records provided in the batch request")
    records_valid: int = Field(..., description="Count of validated records successfully accepted")
    errors: List[str] = Field(default_factory=list, description="Validation or ingestion error messages, if any")
    message: str = Field(..., description="Human-readable summary message")
