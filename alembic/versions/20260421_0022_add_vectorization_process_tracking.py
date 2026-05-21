"""Add vectorization process stage tracking.

Revision ID: 20260421_0022
Revises: 20260421_0021
Create Date: 2026-04-21 22:45:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260421_0022"
down_revision = "20260421_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_vectorization_job", sa.Column("queue_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_vectorization_job", sa.Column("chunking_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_vectorization_job", sa.Column("chunking_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_vectorization_job", sa.Column("embedding_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_vectorization_job", sa.Column("embedding_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_vectorization_job", sa.Column("weaviate_write_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_vectorization_job", sa.Column("weaviate_write_completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_vectorization_job", sa.Column("current_stage", sa.String(length=80), nullable=True))
    op.add_column(
        "document_vectorization_job",
        sa.Column(
            "process_log_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("document_vectorization_job", "process_log_json")
    op.drop_column("document_vectorization_job", "current_stage")
    op.drop_column("document_vectorization_job", "weaviate_write_completed_at")
    op.drop_column("document_vectorization_job", "weaviate_write_started_at")
    op.drop_column("document_vectorization_job", "embedding_completed_at")
    op.drop_column("document_vectorization_job", "embedding_started_at")
    op.drop_column("document_vectorization_job", "chunking_completed_at")
    op.drop_column("document_vectorization_job", "chunking_started_at")
    op.drop_column("document_vectorization_job", "queue_started_at")
