"""Add audit review report workflow metadata.

Revision ID: 20260520_0036
Revises: 20260519_0035
Create Date: 2026-05-20 00:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260520_0036"
down_revision = "20260519_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_review_report", sa.Column("review_type", sa.String(length=30), nullable=True))
    op.add_column("audit_review_report", sa.Column("trigger_source", sa.String(length=30), nullable=True))
    op.add_column("audit_review_report", sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("audit_review_report", sa.Column("schedule_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "audit_review_report",
        sa.Column("workflow_metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("audit_review_report", sa.Column("is_e_signed", sa.Boolean(), nullable=True))
    op.add_column("audit_review_report", sa.Column("e_signed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_review_report", sa.Column("e_signed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("audit_review_report", sa.Column("is_locked", sa.Boolean(), nullable=True))
    op.add_column("audit_review_report", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_review_report", sa.Column("locked_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("audit_review_report", sa.Column("final_pdf_path", sa.Text(), nullable=True))
    op.add_column("audit_review_report", sa.Column("final_pdf_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_review_report", sa.Column("report_version", sa.String(length=30), nullable=True))

    op.create_index("idx_audit_review_report_schedule_id", "audit_review_report", ["schedule_id"], unique=False)
    op.create_index(
        "idx_audit_review_report_schedule_run_id",
        "audit_review_report",
        ["schedule_run_id"],
        unique=False,
    )
    op.create_index("idx_audit_review_report_is_locked", "audit_review_report", ["is_locked"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_audit_review_report_is_locked", table_name="audit_review_report")
    op.drop_index("idx_audit_review_report_schedule_run_id", table_name="audit_review_report")
    op.drop_index("idx_audit_review_report_schedule_id", table_name="audit_review_report")

    op.drop_column("audit_review_report", "report_version")
    op.drop_column("audit_review_report", "final_pdf_hash")
    op.drop_column("audit_review_report", "final_pdf_path")
    op.drop_column("audit_review_report", "locked_by_user_id")
    op.drop_column("audit_review_report", "locked_at")
    op.drop_column("audit_review_report", "is_locked")
    op.drop_column("audit_review_report", "e_signed_by_user_id")
    op.drop_column("audit_review_report", "e_signed_at")
    op.drop_column("audit_review_report", "is_e_signed")
    op.drop_column("audit_review_report", "workflow_metadata_json")
    op.drop_column("audit_review_report", "schedule_run_id")
    op.drop_column("audit_review_report", "schedule_id")
    op.drop_column("audit_review_report", "trigger_source")
    op.drop_column("audit_review_report", "review_type")
