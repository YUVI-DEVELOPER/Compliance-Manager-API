"""Add audit review report approval workflow.

Revision ID: 20260427_0028
Revises: 20260426_0027
Create Date: 2026-04-27 00:45:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260427_0028"
down_revision = "20260426_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_review_report", sa.Column("submitted_by", sa.String(length=150), nullable=True))
    op.add_column("audit_review_report", sa.Column("submitted_dt", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_review_report", sa.Column("reviewed_by", sa.String(length=150), nullable=True))
    op.add_column("audit_review_report", sa.Column("reviewed_dt", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_review_report", sa.Column("reviewer_comments", sa.Text(), nullable=True))
    op.add_column(
        "audit_review_report",
        sa.Column("approval_decision_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.drop_constraint("chk_audit_review_report_status", "audit_review_report", type_="check")
    op.create_check_constraint(
        "chk_audit_review_report_status",
        "audit_review_report",
        "report_status IN ('NOT_GENERATED', 'DRAFT', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'SUPERSEDED')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_audit_review_report_status", "audit_review_report", type_="check")
    op.execute(
        "UPDATE audit_review_report "
        "SET report_status = 'DRAFT' "
        "WHERE report_status IN ('UNDER_REVIEW', 'APPROVED', 'REJECTED')"
    )
    op.create_check_constraint(
        "chk_audit_review_report_status",
        "audit_review_report",
        "report_status IN ('NOT_GENERATED', 'DRAFT', 'SUPERSEDED')",
    )

    op.drop_column("audit_review_report", "approval_decision_json")
    op.drop_column("audit_review_report", "reviewer_comments")
    op.drop_column("audit_review_report", "reviewed_dt")
    op.drop_column("audit_review_report", "reviewed_by")
    op.drop_column("audit_review_report", "submitted_dt")
    op.drop_column("audit_review_report", "submitted_by")
