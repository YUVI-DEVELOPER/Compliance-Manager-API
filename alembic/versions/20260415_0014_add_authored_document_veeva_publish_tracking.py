"""Add authored document Veeva publish tracking.

Revision ID: 20260415_0014
Revises: 20260415_0013
Create Date: 2026-04-15 12:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260415_0014"
down_revision = "20260415_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "authored_document",
        sa.Column(
            "publish_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'NOT_PUBLISHED'"),
        ),
    )
    op.add_column("authored_document", sa.Column("last_publish_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("authored_document", sa.Column("last_publish_attempt_by", sa.String(length=150), nullable=True))
    op.add_column("authored_document", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("authored_document", sa.Column("published_by", sa.String(length=150), nullable=True))
    op.add_column("authored_document", sa.Column("external_system", sa.String(length=50), nullable=True))
    op.add_column("authored_document", sa.Column("external_document_id", sa.String(length=150), nullable=True))
    op.add_column("authored_document", sa.Column("external_document_name", sa.String(length=250), nullable=True))
    op.add_column("authored_document", sa.Column("external_document_version", sa.String(length=50), nullable=True))
    op.add_column("authored_document", sa.Column("external_document_url", sa.Text(), nullable=True))
    op.add_column("authored_document", sa.Column("external_source_reference", sa.String(length=500), nullable=True))
    op.add_column("authored_document", sa.Column("publish_error_message", sa.Text(), nullable=True))

    op.create_check_constraint(
        "chk_authored_document_publish_status",
        "authored_document",
        "publish_status IN ('NOT_PUBLISHED', 'PUBLISH_PENDING', 'PUBLISHED', 'PUBLISH_FAILED')",
    )
    op.create_index("idx_authored_document_publish_status", "authored_document", ["publish_status"], unique=False)
    op.create_index("idx_authored_document_external_system", "authored_document", ["external_system"], unique=False)
    op.create_index(
        "idx_authored_document_external_document_id",
        "authored_document",
        ["external_document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_authored_document_external_document_id", table_name="authored_document")
    op.drop_index("idx_authored_document_external_system", table_name="authored_document")
    op.drop_index("idx_authored_document_publish_status", table_name="authored_document")
    op.drop_constraint("chk_authored_document_publish_status", "authored_document", type_="check")

    op.drop_column("authored_document", "publish_error_message")
    op.drop_column("authored_document", "external_source_reference")
    op.drop_column("authored_document", "external_document_url")
    op.drop_column("authored_document", "external_document_version")
    op.drop_column("authored_document", "external_document_name")
    op.drop_column("authored_document", "external_document_id")
    op.drop_column("authored_document", "external_system")
    op.drop_column("authored_document", "published_by")
    op.drop_column("authored_document", "published_at")
    op.drop_column("authored_document", "last_publish_attempt_by")
    op.drop_column("authored_document", "last_publish_attempt_at")
    op.drop_column("authored_document", "publish_status")
