"""add nullable booking class, udf, convenience fee, and flight status

Revision ID: a4d0f4e5c002
Revises: c4a1e0b5e001
Create Date: 2026-09-26

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4d0f4e5c002"
down_revision: str | Sequence[str] | None = "c4a1e0b5e001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_COLUMNS = (
    ("booking_class", sa.String(length=50)),
    ("udf_fee", sa.Float()),
    ("convenience_fee", sa.Float()),
    ("flight_status", sa.String(length=50)),
)


def upgrade() -> None:
    """Add the four PS columns if a pre-existing raw_fares table lacks them.

    Fresh databases already have the columns from the baseline create_all.
    Existing rows are not rewritten; a missing column is added nullable with
    no default, so prior rows read back as NULL.
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
    """Drop only the four columns this revision added."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("raw_fares"):
        return
    present = {column["name"] for column in inspector.get_columns("raw_fares")}
    for name, _column_type in reversed(_NEW_COLUMNS):
        if name not in present:
            continue
        op.drop_column("raw_fares", name)
