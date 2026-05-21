"""Add audit review notification table.

Revision ID: 20260428_0030
Revises: 20260428_0029
Create Date: 2026-04-28 15:45:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260428_0030"
down_revision = "20260428_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_review_notification",
        sa.Column(
            "notification_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.String(length=30), nullable=False),
        sa.Column("rating", sa.String(length=50), nullable=False),
        sa.Column("recipient_role", sa.String(length=150), nullable=False),
        sa.Column("recipient_email", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'READY'"), nullable=False),
        sa.Column("delivery_channel", sa.String(length=30), server_default=sa.text("'IN_APP'"), nullable=False),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "notification_type IN ("
            "'AUDIT_REVIEW_COMPLIANT', "
            "'AUDIT_REVIEW_MINOR_FINDINGS', "
            "'AUDIT_REVIEW_MAJOR_FINDINGS', "
            "'AUDIT_REVIEW_CRITICAL_RISK'"
            ")",
            name="chk_audit_review_notification_type",
        ),
        sa.CheckConstraint(
            "priority IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')",
            name="chk_audit_review_notification_priority",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'READY', 'SENT', 'FAILED', 'DISMISSED')",
            name="chk_audit_review_notification_status",
        ),
        sa.CheckConstraint(
            "delivery_channel IN ('IN_APP', 'EMAIL', 'BOTH')",
            name="chk_audit_review_notification_delivery_channel",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset_basic_info.asset_id"],
            name="fk_audit_review_notification_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["audit_review_job.job_id"],
            name="fk_audit_review_notification_job",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["audit_review_report.report_id"],
            name="fk_audit_review_notification_report",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("notification_id"),
    )
    op.create_index(
        "idx_audit_review_notification_report_id",
        "audit_review_notification",
        ["report_id"],
        unique=False,
    )
    op.create_index(
        "idx_audit_review_notification_job_id",
        "audit_review_notification",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "idx_audit_review_notification_asset_id",
        "audit_review_notification",
        ["asset_id"],
        unique=False,
    )
    op.create_index(
        "idx_audit_review_notification_status",
        "audit_review_notification",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_audit_review_notification_priority",
        "audit_review_notification",
        ["priority"],
        unique=False,
    )
    op.create_index(
        "idx_audit_review_notification_created_dt",
        "audit_review_notification",
        ["created_dt"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_audit_review_notification_created_dt", table_name="audit_review_notification")
    op.drop_index("idx_audit_review_notification_priority", table_name="audit_review_notification")
    op.drop_index("idx_audit_review_notification_status", table_name="audit_review_notification")
    op.drop_index("idx_audit_review_notification_asset_id", table_name="audit_review_notification")
    op.drop_index("idx_audit_review_notification_job_id", table_name="audit_review_notification")
    op.drop_index("idx_audit_review_notification_report_id", table_name="audit_review_notification")
    op.drop_table("audit_review_notification")
