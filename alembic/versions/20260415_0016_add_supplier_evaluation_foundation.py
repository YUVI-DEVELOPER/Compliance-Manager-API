"""Add supplier evaluation foundation.

Revision ID: 20260415_0016
Revises: 20260415_0015
Create Date: 2026-04-15 19:10:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260415_0016"
down_revision = "20260415_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplier_evaluation",
        sa.Column("evaluation_id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("evaluation_name", sa.String(length=250), nullable=False),
        sa.Column("asset_uuid", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("urs_document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'OPEN_FOR_RESPONSE', 'LOCKED', 'CLOSED')",
            name="chk_supplier_evaluation_status",
        ),
        sa.ForeignKeyConstraint(
            ["asset_uuid"],
            ["asset_basic_info.asset_id"],
            name="fk_supplier_evaluation_asset",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["urs_document_id"],
            ["authored_document.authored_document_id"],
            name="fk_supplier_evaluation_urs_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("evaluation_id"),
    )
    op.create_index("idx_supplier_evaluation_asset_uuid", "supplier_evaluation", ["asset_uuid"], unique=False)
    op.create_index(
        "idx_supplier_evaluation_urs_document_id",
        "supplier_evaluation",
        ["urs_document_id"],
        unique=False,
    )
    op.create_index("idx_supplier_evaluation_status", "supplier_evaluation", ["status"], unique=False)

    op.create_table(
        "supplier_evaluation_response",
        sa.Column("response_id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("evaluation_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "submission_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'NOT_STARTED'"),
        ),
        sa.Column("quotation_reference", sa.String(length=250), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by", sa.String(length=150), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "submission_status IN ('NOT_STARTED', 'IN_PROGRESS', 'SUBMITTED', 'LOCKED')",
            name="chk_supplier_evaluation_response_submission_status",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["supplier_evaluation.evaluation_id"],
            name="fk_supplier_evaluation_response_evaluation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["supplier.supplier_id"],
            name="fk_supplier_evaluation_response_supplier",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("response_id"),
        sa.UniqueConstraint(
            "evaluation_id",
            "supplier_id",
            name="uq_supplier_evaluation_response_evaluation_supplier",
        ),
    )
    op.create_index(
        "idx_supplier_evaluation_response_evaluation_id",
        "supplier_evaluation_response",
        ["evaluation_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_evaluation_response_supplier_id",
        "supplier_evaluation_response",
        ["supplier_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_evaluation_response_submission_status",
        "supplier_evaluation_response",
        ["submission_status"],
        unique=False,
    )

    op.create_table(
        "supplier_response_document",
        sa.Column("document_id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("response_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("document_type", sa.String(length=30), nullable=False),
        sa.Column("source_system", sa.String(length=50), nullable=True),
        sa.Column("external_document_id", sa.String(length=150), nullable=True),
        sa.Column("document_name", sa.String(length=250), nullable=False),
        sa.Column("document_version", sa.String(length=50), nullable=True),
        sa.Column("upload_dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("access_url", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "document_type IN ('QUOTATION', 'TECHNICAL_RESPONSE', 'COMMERCIAL_RESPONSE', 'SUPPORTING_DOCUMENT')",
            name="chk_supplier_response_document_type",
        ),
        sa.ForeignKeyConstraint(
            ["response_id"],
            ["supplier_evaluation_response.response_id"],
            name="fk_supplier_response_document_response",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index(
        "idx_supplier_response_document_response_id",
        "supplier_response_document",
        ["response_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_response_document_type",
        "supplier_response_document",
        ["document_type"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_response_document_source_system",
        "supplier_response_document",
        ["source_system"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_supplier_response_document_source_system", table_name="supplier_response_document")
    op.drop_index("idx_supplier_response_document_type", table_name="supplier_response_document")
    op.drop_index("idx_supplier_response_document_response_id", table_name="supplier_response_document")
    op.drop_table("supplier_response_document")

    op.drop_index(
        "idx_supplier_evaluation_response_submission_status",
        table_name="supplier_evaluation_response",
    )
    op.drop_index("idx_supplier_evaluation_response_supplier_id", table_name="supplier_evaluation_response")
    op.drop_index("idx_supplier_evaluation_response_evaluation_id", table_name="supplier_evaluation_response")
    op.drop_table("supplier_evaluation_response")

    op.drop_index("idx_supplier_evaluation_status", table_name="supplier_evaluation")
    op.drop_index("idx_supplier_evaluation_urs_document_id", table_name="supplier_evaluation")
    op.drop_index("idx_supplier_evaluation_asset_uuid", table_name="supplier_evaluation")
    op.drop_table("supplier_evaluation")
