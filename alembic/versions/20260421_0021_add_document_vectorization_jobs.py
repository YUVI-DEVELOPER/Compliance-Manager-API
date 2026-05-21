"""Add document vectorization job tracking.

Revision ID: 20260421_0021
Revises: 20260418_0020
Create Date: 2026-04-21 17:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260421_0021"
down_revision = "20260418_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = 'public.validated_document_link'::regclass
                  AND contype = 'p'
            ) THEN
                IF EXISTS (
                    SELECT 1
                    FROM public.validated_document_link
                    WHERE document_link_id IS NULL
                ) THEN
                    RAISE EXCEPTION
                        'Cannot add primary key: validated_document_link.document_link_id contains NULL values';
                END IF;

                IF EXISTS (
                    SELECT document_link_id
                    FROM public.validated_document_link
                    GROUP BY document_link_id
                    HAVING count(*) > 1
                ) THEN
                    RAISE EXCEPTION
                        'Cannot add primary key: validated_document_link.document_link_id contains duplicate values';
                END IF;

                ALTER TABLE public.validated_document_link
                ADD CONSTRAINT validated_document_link_pkey PRIMARY KEY (document_link_id);
            END IF;
        END $$;
        """
    )
    op.create_table(
        "document_vectorization_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_link_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rag_document_id", sa.String(length=150), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("weaviate_collection", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_dt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("modified_dt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_link_id"],
            ["validated_document_link.document_link_id"],
            name="fk_document_vectorization_job_document_link",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_document_vectorization_job_document_link_id",
        "document_vectorization_job",
        ["document_link_id"],
        unique=False,
    )
    op.create_index(
        "idx_document_vectorization_job_is_active",
        "document_vectorization_job",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "idx_document_vectorization_job_status",
        "document_vectorization_job",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_document_vectorization_job_document_link",
        "document_vectorization_job",
        ["document_link_id"],
        unique=True,
        postgresql_where=sa.text("document_link_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_document_vectorization_job_document_link", table_name="document_vectorization_job")
    op.drop_index("idx_document_vectorization_job_status", table_name="document_vectorization_job")
    op.drop_index("idx_document_vectorization_job_is_active", table_name="document_vectorization_job")
    op.drop_index("idx_document_vectorization_job_document_link_id", table_name="document_vectorization_job")
    op.drop_table("document_vectorization_job")
