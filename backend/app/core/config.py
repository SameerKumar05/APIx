from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "APIx - Real-time Airfare Price Index"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    DESCRIPTION: str = (
        "SIH 2026 PS 26056: Real-time Airfare Price Index for India "
        "(Augmenting Official CPI Transportation Sub-Index)"
    )

    # Ingestion Security
    INGESTION_API_KEY: str = "apix-ingestion-secret-key-2026"
    INGESTION_HEADER_NAME: str = "X-Ingestion-Key"

    # CORS Configuration
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "*",
    ]

    # Database
    DATABASE_URL: str = "sqlite:///./apix.db"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
