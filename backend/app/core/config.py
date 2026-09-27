from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_INGESTION_KEY = "apix-ingestion-secret-key-2026"


class Settings(BaseSettings):
    PROJECT_NAME: str = "APIx - Real-time Airfare Price Index"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    API_RATE_LIMIT_REQUESTS: int = Field(
        default=120,
        ge=0,
        description=(
            "Requests allowed per window per client on the public read API. The problem "
            "statement asks for an API that NSO and RBI can consume, so it has to tolerate "
            "polling without being trivially exhaustible. 0 disables the limiter."
        ),
    )
    API_RATE_LIMIT_WINDOW_SECONDS: int = Field(
        default=60, ge=1, description="Fixed window length for API rate limiting."
    )
    DESCRIPTION: str = (
        "SIH 2026 PS 26056: Real-time Airfare Price Index for India "
        "(Augmenting Official CPI Transportation Sub-Index)"
    )

    # Ingestion Security
    INGESTION_API_KEY: str = INSECURE_DEFAULT_INGESTION_KEY
    INGESTION_HEADER_NAME: str = "X-Ingestion-Key"

    # CORS Configuration
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    @field_validator("BACKEND_CORS_ORIGINS")
    @classmethod
    def reject_wildcard_cors_origins(cls, origins: list[str]) -> list[str]:
        """Reject wildcard origins when credentialed CORS is enabled."""
        if "*" in origins:
            raise ValueError("Wildcard CORS origins are not allowed")
        return origins

    # Database
    DATABASE_URL: str = "sqlite:///./apix.db"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Quant & Index Parameters
    INDEX_BASE_PERIOD: str = "2026-01"
    INDEX_BASE_VALUE: float = 100.0
    ANOMALY_ZSCORE_THRESHOLD: float = 2.5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _reject_published_ingestion_key(self) -> "Settings":
        """Refuse the shipped default outside development.

        The default is committed to the repository, so anyone can read it. Silently
        falling back to it would mean a deployment that forgets to set the variable
        accepts ingestion from anyone who has seen this file.
        """
        if (
            self.INGESTION_API_KEY == INSECURE_DEFAULT_INGESTION_KEY
            and self.ENVIRONMENT != "development"
        ):
            raise ValueError(
                "INGESTION_API_KEY is still the published default. Set a unique value "
                "before running outside development."
            )
        return self


settings = Settings()
