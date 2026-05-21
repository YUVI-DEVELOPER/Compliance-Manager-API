"""Add supplier evaluation AI analysis.

Revision ID: 20260416_0018
Revises: 20260416_0017
Create Date: 2026-04-16 13:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260416_0018"
down_revision = "20260416_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplier_evaluation_analysis",
        sa.Column("analysis_id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("evaluation_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'NOT_STARTED'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_by", sa.String(length=150), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=150), nullable=True),
        sa.Column("prompt_version", sa.String(length=80), nullable=True),
        sa.Column("input_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('NOT_STARTED', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="chk_supplier_evaluation_analysis_status",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"],
            ["supplier_evaluation.evaluation_id"],
            name="fk_supplier_evaluation_analysis_evaluation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("analysis_id"),
    )
    op.create_index(
        "idx_supplier_evaluation_analysis_evaluation_id",
        "supplier_evaluation_analysis",
        ["evaluation_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_evaluation_analysis_status",
        "supplier_evaluation_analysis",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_evaluation_analysis_created_at",
        "supplier_evaluation_analysis",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "supplier_requirement_analysis",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("analysis_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_response_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("requirement_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluated_fit", sa.String(length=30), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("reasoning_text", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "evaluated_fit IN ('MEETS', 'PARTIALLY_MEETS', 'NOT_MEETS')",
            name="chk_supplier_requirement_analysis_evaluated_fit",
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="chk_supplier_requirement_analysis_confidence_score",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["supplier_evaluation_analysis.analysis_id"],
            name="fk_supplier_requirement_analysis_analysis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_response_id"],
            ["supplier_evaluation_response.response_id"],
            name="fk_supplier_requirement_analysis_supplier_response",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["evaluation_requirement_item.requirement_item_id"],
            name="fk_supplier_requirement_analysis_requirement",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_supplier_requirement_analysis_analysis_id",
        "supplier_requirement_analysis",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_requirement_analysis_supplier_response_id",
        "supplier_requirement_analysis",
        ["supplier_response_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_requirement_analysis_requirement_id",
        "supplier_requirement_analysis",
        ["requirement_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_requirement_analysis_evaluated_fit",
        "supplier_requirement_analysis",
        ["evaluated_fit"],
        unique=False,
    )

    op.create_table(
        "supplier_comparison_summary",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("analysis_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("supplier_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=False),
        sa.Column("strengths", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("weaknesses", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risk_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("recommendation_rank", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["supplier_evaluation_analysis.analysis_id"],
            name="fk_supplier_comparison_summary_analysis",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["supplier.supplier_id"],
            name="fk_supplier_comparison_summary_supplier",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_supplier_comparison_summary_analysis_id",
        "supplier_comparison_summary",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_comparison_summary_supplier_id",
        "supplier_comparison_summary",
        ["supplier_id"],
        unique=False,
    )
    op.create_index(
        "idx_supplier_comparison_summary_rank",
        "supplier_comparison_summary",
        ["analysis_id", "recommendation_rank"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_supplier_comparison_summary_rank", table_name="supplier_comparison_summary")
    op.drop_index("idx_supplier_comparison_summary_supplier_id", table_name="supplier_comparison_summary")
    op.drop_index("idx_supplier_comparison_summary_analysis_id", table_name="supplier_comparison_summary")
    op.drop_table("supplier_comparison_summary")

    op.drop_index("idx_supplier_requirement_analysis_evaluated_fit", table_name="supplier_requirement_analysis")
    op.drop_index("idx_supplier_requirement_analysis_requirement_id", table_name="supplier_requirement_analysis")
    op.drop_index("idx_supplier_requirement_analysis_supplier_response_id", table_name="supplier_requirement_analysis")
    op.drop_index("idx_supplier_requirement_analysis_analysis_id", table_name="supplier_requirement_analysis")
    op.drop_table("supplier_requirement_analysis")

    op.drop_index("idx_supplier_evaluation_analysis_created_at", table_name="supplier_evaluation_analysis")
    op.drop_index("idx_supplier_evaluation_analysis_status", table_name="supplier_evaluation_analysis")
    op.drop_index("idx_supplier_evaluation_analysis_evaluation_id", table_name="supplier_evaluation_analysis")
    op.drop_table("supplier_evaluation_analysis")
