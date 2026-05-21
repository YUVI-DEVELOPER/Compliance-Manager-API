"""Align org_structure.deleted_at with UTC-aware audit timestamps.

Revision ID: 20260409_0005
Revises: 20260402_0004
Create Date: 2026-04-09 12:25:00

"""

from __future__ import annotations

from alembic import op


revision = "20260409_0005"
down_revision = "20260402_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.org_structure
        ALTER COLUMN deleted_at
        TYPE TIMESTAMPTZ
        USING deleted_at AT TIME ZONE 'UTC'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.org_structure
        ALTER COLUMN deleted_at
        TYPE TIMESTAMP WITHOUT TIME ZONE
        USING deleted_at AT TIME ZONE 'UTC'
        """
    )
