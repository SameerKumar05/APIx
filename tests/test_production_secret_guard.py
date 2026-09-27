"""The committed default ingestion key must not survive into production.

INGESTION_API_KEY shipped as a literal in the source, so it is readable by anyone
who clones the repository. A deployment that forgets to override it would accept
ingestion from anyone who has seen the file. The default is still allowed in
development so local runs need no configuration.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.core.config import INSECURE_DEFAULT_INGESTION_KEY, Settings


def test_development_may_use_the_published_default() -> None:
    assert (
        Settings(ENVIRONMENT="development").INGESTION_API_KEY
        == INSECURE_DEFAULT_INGESTION_KEY
    )


def test_production_refuses_the_published_default() -> None:
    with pytest.raises(ValidationError, match="INGESTION_API_KEY"):
        Settings(ENVIRONMENT="production")


@pytest.mark.parametrize("environment", ["staging", "prod", "production"])
def test_any_non_development_environment_refuses_it(environment: str) -> None:
    with pytest.raises(ValidationError, match="INGESTION_API_KEY"):
        Settings(ENVIRONMENT=environment)


def test_production_accepts_a_real_key() -> None:
    cfg = Settings(ENVIRONMENT="production", INGESTION_API_KEY="a-unique-operator-key")
    assert cfg.INGESTION_API_KEY == "a-unique-operator-key"


@pytest.mark.asyncio
async def test_verify_ingestion_key_dependency() -> None:
    from fastapi import HTTPException

    from backend.app.core.auth import verify_ingestion_key

    # Valid key accepted
    accepted = await verify_ingestion_key(
        x_ingestion_key=INSECURE_DEFAULT_INGESTION_KEY
    )
    assert accepted == INSECURE_DEFAULT_INGESTION_KEY

    # Missing key rejected with 401
    with pytest.raises(HTTPException) as exc_info:
        await verify_ingestion_key(x_ingestion_key=None)
    assert exc_info.value.status_code == 401

    # Invalid key rejected with 401
    with pytest.raises(HTTPException) as exc_info:
        await verify_ingestion_key(x_ingestion_key="wrong-key")
    assert exc_info.value.status_code == 401
