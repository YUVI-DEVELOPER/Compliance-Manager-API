"""Restore audit trail type server default.

Revision ID: 20260426_0027
Revises: 20260426_0026
Create Date: 2026-04-26 23:20:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_0027"
down_revision = "20260426_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "audit_review_job",
        "audit_trail_type",
        existing_type=sa.String(length=100),
        server_default=sa.text("'login_audit_trail'"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "audit_review_job",
        "audit_trail_type",
        existing_type=sa.String(length=100),
        server_default=None,
        existing_nullable=False,
    )
