"""Add supplier requirement response matrix.

Revision ID: 20260416_0017
Revises: 20260415_0016
Create Date: 2026-04-16 10:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260416_0017"
down_revision = "20260415_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluation_requirement_item",
        sa.Column(
            "requirement_item_id",
            sa.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("evaluation_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("urs_document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("requirement_key", sa.String(length=100), nullable=True),
        sa.Column("requirement_section", sa.String(length=250), nullable=True),
        sa.Column("requirement_text", sa.Text(), nullable=False),
        sa.Column("requirement_order", sa.Integer(), nullable=True),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["supplier_evaluation.evaluation_id"],
            name="fk_evaluation_requirement_item_evaluation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["urs_document_id"],
            ["authored_document.authored_document_id"],
            name="fk_evaluation_requirement_item_urs_document",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("requirement_item_id"),
    )
    op.create_index(
        "idx_evaluation_requirement_item_evaluation_id",
        "evaluation_requirement_item",
        ["evaluation_id"],
        unique=False,
    )
    op.create_index(
        "idx_evaluation_requirement_item_urs_document_id",
        "evaluation_requirement_item",
        ["urs_document_id"],
        unique=False,
    )
    op.create_index(
        "idx_evaluation_requirement_item_order",
        "evaluation_requirement_item",
        ["evaluation_id", "requirement_order"],
        unique=False,
    )

    op.create_table(
        "supplier_requirement_response",
        sa.Column(
            "requirement_response_id",
            sa.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("response_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("requirement_item_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("fit_status", sa.String(length=30), nullable=False),
        sa.Column("supplier_response_text", sa.Text(), nullable=True),
        sa.Column("evidence_reference", sa.String(length=1000), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "fit_status IN ('MEETS', 'PARTIALLY_MEETS', 'NOT_MEETS')",
            name="chk_supplier_requirement_response_fit_status",
        ),
        sa.ForeignKeyConstraint(
            ["response_id"],
            ["supplier_evaluation_response.response_id"],
            name="fk_supplier_requirement_response_response",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_item_id"],
            ["evaluation_requirement_item.requirement_item_id"],
            name="fk_supplier_requirement_response_requirement_item",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("requirement_response_id"),
        sa.UniqueConstraint(
            "response_id",
            "requirement_item_id",
            name="uq_supplier_requirement_response_response_requirement",
        ),
    )
    op.create_index(
        "idx_supplier_requirement_response_response_id",
        "supplier_requirement_response",
        ["response_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_requirement_response_requirement_item_id",
        "supplier_requirement_response",
        ["requirement_item_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_requirement_response_fit_status",
        "supplier_requirement_response",
        ["fit_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_supplier_requirement_response_fit_status",
        table_name="supplier_requirement_response",
    )
    op.drop_index(
        "idx_supplier_requirement_response_requirement_item_id",
        table_name="supplier_requirement_response",
    )
    op.drop_index(
        "idx_supplier_requirement_response_response_id",
        table_name="supplier_requirement_response",
    )
    op.drop_table("supplier_requirement_response")

    op.drop_index("idx_evaluation_requirement_item_order", table_name="evaluation_requirement_item")
    op.drop_index("idx_evaluation_requirement_item_urs_document_id", table_name="evaluation_requirement_item")
    op.drop_index("idx_evaluation_requirement_item_evaluation_id", table_name="evaluation_requirement_item")
    op.drop_table("evaluation_requirement_item")
