"""Add document type to validated document links.

Revision ID: 20260416_0019
Revises: 20260416_0018
Create Date: 2026-04-16 22:40:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_0019"
down_revision = "20260416_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("validated_document_link", sa.Column("document_type", sa.String(length=50), nullable=True))
    op.create_index(
        "idx_validated_document_link_document_type",
        "validated_document_link",
        ["document_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_validated_document_link_document_type", table_name="validated_document_link")
    op.drop_column("validated_document_link", "document_type")
