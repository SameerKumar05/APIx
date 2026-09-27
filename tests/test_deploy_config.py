"""Tests for deployment configuration, overlay specs, and environment templates."""

from pathlib import Path

import yaml

from backend.app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_env_deploy_template_structure_and_safety():
    template_path = REPO_ROOT / ".env.deploy.template"
    assert template_path.is_file(), ".env.deploy.template must exist"

    content = template_path.read_text(encoding="utf-8")
    required_keys = [
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "SECRET_KEY",
        "INGESTION_API_KEY",
        "ENVIRONMENT",
        "BACKEND_CORS_ORIGINS",
    ]
    for key in required_keys:
        assert f"{key}=" in content, f"Missing key {key} in .env.deploy.template"

    # Ensure no committed credentials (must contain CHANGEME placeholders)
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, val = line.split("=", 1)
        assert "CHANGEME" in val, f"Key {key} contains non-placeholder value {val}"


def test_docker_compose_deploy_overlay_spec():
    overlay_path = REPO_ROOT / "docker-compose.deploy.yml"
    assert overlay_path.is_file(), "docker-compose.deploy.yml must exist"

    raw = overlay_path.read_text(encoding="utf-8")
    assert "127.0.0.1:8000:8000" in raw, "Backend must bind to loopback 127.0.0.1:8000"
    assert "127.0.0.1:3001:80" in raw, "Frontend must bind to loopback 127.0.0.1:3001"
    assert "!reset" in raw, "DB ports must be reset for isolation"


def test_settings_validation_with_deploy_template_contract():
    # Validates that setting production variables matching the deploy template contract
    # passes Pydantic validation without error
    custom_env = {
        "POSTGRES_USER": "test_user",
        "POSTGRES_PASSWORD": "test_password_12345",
        "POSTGRES_DB": "test_db",
        "ENVIRONMENT": "production",
        "INGESTION_API_KEY": "a-strong-custom-ingestion-secret-key-32b",
        "SECRET_KEY": "a-strong-custom-jwt-secret-key-32-bytes",
        "BACKEND_CORS_ORIGINS": ["https://apix.adityaai.dev"],
        "DATABASE_URL": "postgresql+psycopg2://test_user:test_password_12345@db:5432/test_db",
    }
    settings = Settings(**custom_env)
    assert settings.ENVIRONMENT == "production"
    assert settings.INGESTION_API_KEY == "a-strong-custom-ingestion-secret-key-32b"
    assert settings.BACKEND_CORS_ORIGINS == ["https://apix.adityaai.dev"]
