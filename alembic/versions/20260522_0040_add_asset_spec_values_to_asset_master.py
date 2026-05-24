"""Add asset spec values snapshot to asset master.

Revision ID: 20260522_0040
Revises: 20260522_0039
Create Date: 2026-05-22 19:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260522_0040"
down_revision = "20260522_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asset_basic_info",
        sa.Column("asset_spec_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("asset_basic_info", "asset_spec_values")
