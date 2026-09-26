"""add index exclusion reason and fare split basis

Revision ID: b8c3d2e7a004
Revises: a4d0f4e5c002
Create Date: 2026-09-26

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c3d2e7a004"
down_revision: str | Sequence[str] | None = "a4d0f4e5c002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_COLUMNS = (
    ("index_exclusion_reason", sa.String(length=32)),
    ("fare_split_basis", sa.String(length=16)),
)


def upgrade() -> None:
    """Add cleaning columns if a pre-existing raw_fares table lacks them.

    Fresh databases already have the columns from the baseline create_all.
    Existing rows are not rewritten. A missing column is added nullable with
    no default, so prior rows read back as NULL rather than as measured or
    index-eligible by invention.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("raw_fares"):
        return
    present = {column["name"] for column in inspector.get_columns("raw_fares")}
    for name, column_type in _NEW_COLUMNS:
        if name in present:
            continue
        op.add_column("raw_fares", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    """Drop only the columns this revision added."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("raw_fares"):
        return
    present = {column["name"] for column in inspector.get_columns("raw_fares")}
    for name, _column_type in reversed(_NEW_COLUMNS):
        if name not in present:
            continue
        op.drop_column("raw_fares", name)
