"""Add audit review AI summary fields.

Revision ID: 20260428_0031
Revises: 20260428_0030
Create Date: 2026-04-28 17:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260428_0031"
down_revision = "20260428_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_review_report",
        sa.Column("ai_summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("audit_review_report", sa.Column("ai_summary_markdown", sa.Text(), nullable=True))
    op.add_column("audit_review_report", sa.Column("ai_generation_status", sa.String(length=30), nullable=True))
    op.add_column("audit_review_report", sa.Column("ai_generated_by", sa.String(length=150), nullable=True))
    op.add_column("audit_review_report", sa.Column("ai_generated_dt", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_review_report", sa.Column("ai_model_name", sa.String(length=150), nullable=True))
    op.add_column("audit_review_report", sa.Column("ai_error_message", sa.Text(), nullable=True))
    op.create_check_constraint(
        "chk_audit_review_report_ai_generation_status",
        "audit_review_report",
        "ai_generation_status IS NULL OR ai_generation_status IN ('NOT_REQUESTED', 'GENERATING', 'GENERATED', 'FAILED')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_audit_review_report_ai_generation_status", "audit_review_report", type_="check")
    op.drop_column("audit_review_report", "ai_error_message")
    op.drop_column("audit_review_report", "ai_model_name")
    op.drop_column("audit_review_report", "ai_generated_dt")
    op.drop_column("audit_review_report", "ai_generated_by")
    op.drop_column("audit_review_report", "ai_generation_status")
    op.drop_column("audit_review_report", "ai_summary_markdown")
    op.drop_column("audit_review_report", "ai_summary_json")
