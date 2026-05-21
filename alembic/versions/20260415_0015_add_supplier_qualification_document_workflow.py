"""Add supplier qualification document workflow.

Revision ID: 20260415_0015
Revises: 20260415_0014
Create Date: 2026-04-15 16:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260415_0015"
down_revision = "20260415_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplier_qualification_document",
        sa.Column(
            "qualification_document_id",
            sa.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("qualification_type", sa.String(length=10), nullable=False),
        sa.Column("asset_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("release_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("supplier_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("document_name", sa.String(length=250), nullable=False),
        sa.Column("document_version", sa.String(length=50), nullable=True),
        sa.Column("source_system", sa.String(length=50), nullable=True),
        sa.Column("external_document_id", sa.String(length=150), nullable=True),
        sa.Column("document_url", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("submission_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'SUBMITTED'"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "(asset_id IS NOT NULL OR release_id IS NOT NULL)",
            name="chk_supplier_qualification_document_target",
        ),
        sa.CheckConstraint(
            "qualification_type IN ('IQ', 'OQ', 'PQ')",
            name="chk_supplier_qualification_document_type",
        ),
        sa.CheckConstraint(
            "status IN ('SUBMITTED', 'IN_REVIEW', 'ACCEPTED', 'REJECTED', 'NEEDS_CLARIFICATION')",
            name="chk_supplier_qualification_document_status",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset_basic_info.asset_id"],
            name="fk_supplier_qualification_document_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["asset_release.release_id"],
            name="fk_supplier_qualification_document_release",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["supplier.supplier_id"],
            name="fk_supplier_qualification_document_supplier",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("qualification_document_id"),
    )
    op.create_index(
        "idx_supplier_qualification_document_asset_id",
        "supplier_qualification_document",
        ["asset_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_qualification_document_release_id",
        "supplier_qualification_document",
        ["release_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_qualification_document_supplier_id",
        "supplier_qualification_document",
        ["supplier_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_qualification_document_type",
        "supplier_qualification_document",
        ["qualification_type"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_qualification_document_status",
        "supplier_qualification_document",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_qualification_document_source_system",
        "supplier_qualification_document",
        ["source_system"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_qualification_document_external_document_id",
        "supplier_qualification_document",
        ["external_document_id"],
        unique=False,
    )

    op.create_table(
        "supplier_qualification_document_action",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("qualification_document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("action_by", sa.String(length=150), nullable=True),
        sa.Column("action_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("comment_text", sa.Text(), nullable=True),
        sa.Column("from_status", sa.String(length=30), nullable=False),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.CheckConstraint(
            "action_type IN ('REGISTER', 'SUBMIT_FOR_REVIEW', 'ACCEPT', 'REJECT', 'REQUEST_CLARIFICATION')",
            name="chk_supplier_qualification_document_action_type",
        ),
        sa.CheckConstraint(
            "from_status IN ('SUBMITTED', 'IN_REVIEW', 'ACCEPTED', 'REJECTED', 'NEEDS_CLARIFICATION')",
            name="chk_supplier_qualification_document_action_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('SUBMITTED', 'IN_REVIEW', 'ACCEPTED', 'REJECTED', 'NEEDS_CLARIFICATION')",
            name="chk_supplier_qualification_document_action_to_status",
        ),
        sa.ForeignKeyConstraint(
            ["qualification_document_id"],
            ["supplier_qualification_document.qualification_document_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_supplier_qualification_document_action_document_id",
        "supplier_qualification_document_action",
        ["qualification_document_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_qualification_document_action_type",
        "supplier_qualification_document_action",
        ["action_type"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_qualification_document_action_dt",
        "supplier_qualification_document_action",
        ["action_dt"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_supplier_qualification_document_action_dt", table_name="supplier_qualification_document_action")
    op.drop_index("idx_supplier_qualification_document_action_type", table_name="supplier_qualification_document_action")
    op.drop_index(
        "idx_supplier_qualification_document_action_document_id",
        table_name="supplier_qualification_document_action",
    )
    op.drop_table("supplier_qualification_document_action")

    op.drop_index(
        "idx_supplier_qualification_document_external_document_id",
        table_name="supplier_qualification_document",
    )
    op.drop_index("idx_supplier_qualification_document_source_system", table_name="supplier_qualification_document")
    op.drop_index("idx_supplier_qualification_document_status", table_name="supplier_qualification_document")
    op.drop_index("idx_supplier_qualification_document_type", table_name="supplier_qualification_document")
    op.drop_index("idx_supplier_qualification_document_supplier_id", table_name="supplier_qualification_document")
    op.drop_index("idx_supplier_qualification_document_release_id", table_name="supplier_qualification_document")
    op.drop_index("idx_supplier_qualification_document_asset_id", table_name="supplier_qualification_document")
    op.drop_table("supplier_qualification_document")
