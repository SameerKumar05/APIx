"""create tables that are not already present

Revision ID: c4a1e0b5e001
Revises:
Create Date: 2026-09-26

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import backend.app.models  # noqa: F401
from backend.app.db.session import Base

revision: str = "c4a1e0b5e001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create missing tables. Does not alter columns on tables that already exist."""
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop tables registered on the metadata. Does not touch unknown tables."""
    Base.metadata.drop_all(bind=op.get_bind())
