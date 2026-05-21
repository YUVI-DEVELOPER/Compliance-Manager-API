"""Add audit review scheduler tables.

Revision ID: 20260428_0029
Revises: 20260427_0028
Create Date: 2026-04-28 10:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260428_0029"
down_revision = "20260427_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_review_schedule",
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("vault_dns", sa.String(length=255), nullable=True),
        sa.Column("veeva_instance_name", sa.String(length=150), nullable=True),
        sa.Column("veeva_app_name", sa.String(length=150), nullable=True),
        sa.Column(
            "audit_trail_type",
            sa.String(length=100),
            server_default=sa.text("'login_audit_trail'"),
            nullable=False,
        ),
        sa.Column("frequency", sa.String(length=30), nullable=False),
        sa.Column("review_window_days", sa.Integer(), nullable=True),
        sa.Column("next_run_dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("timezone", sa.String(length=100), server_default=sa.text("'Asia/Kolkata'"), nullable=False),
        sa.Column("business_start_hour", sa.Integer(), nullable=True),
        sa.Column("business_end_hour", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "frequency IN ('DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY', 'HALF_YEARLY', 'ANNUAL')",
            name="chk_audit_review_schedule_frequency",
        ),
        sa.CheckConstraint(
            "review_window_days IS NULL OR review_window_days > 0",
            name="chk_audit_review_schedule_review_window_days",
        ),
        sa.CheckConstraint(
            "business_start_hour IS NULL OR (business_start_hour >= 0 AND business_start_hour <= 23)",
            name="chk_audit_review_schedule_business_start_hour",
        ),
        sa.CheckConstraint(
            "business_end_hour IS NULL OR (business_end_hour >= 1 AND business_end_hour <= 24)",
            name="chk_audit_review_schedule_business_end_hour",
        ),
        sa.CheckConstraint(
            "business_start_hour IS NULL OR business_end_hour IS NULL OR business_end_hour > business_start_hour",
            name="chk_audit_review_schedule_business_hours_order",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset_basic_info.asset_id"],
            name="fk_audit_review_schedule_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_job_id"],
            ["audit_review_job.job_id"],
            name="fk_audit_review_schedule_last_job",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("schedule_id"),
    )
    op.create_index("idx_audit_review_schedule_asset_id", "audit_review_schedule", ["asset_id"], unique=False)
    op.create_index(
        "idx_audit_review_schedule_enabled_next_run",
        "audit_review_schedule",
        ["enabled", "next_run_dt"],
        unique=False,
    )
    op.create_index(
        "idx_audit_review_schedule_last_job_id",
        "audit_review_schedule",
        ["last_job_id"],
        unique=False,
    )

    op.create_table(
        "audit_review_schedule_run",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "run_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('STARTED', 'COMPLETED', 'FAILED', 'SKIPPED')",
            name="chk_audit_review_schedule_run_status",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset_basic_info.asset_id"],
            name="fk_audit_review_schedule_run_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["audit_review_job.job_id"],
            name="fk_audit_review_schedule_run_job",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["audit_review_schedule.schedule_id"],
            name="fk_audit_review_schedule_run_schedule",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index(
        "idx_audit_review_schedule_run_schedule_id",
        "audit_review_schedule_run",
        ["schedule_id"],
        unique=False,
    )
    op.create_index(
        "idx_audit_review_schedule_run_asset_id",
        "audit_review_schedule_run",
        ["asset_id"],
        unique=False,
    )
    op.create_index("idx_audit_review_schedule_run_job_id", "audit_review_schedule_run", ["job_id"], unique=False)
    op.create_index("idx_audit_review_schedule_run_status", "audit_review_schedule_run", ["status"], unique=False)
    op.create_index(
        "idx_audit_review_schedule_run_started_at",
        "audit_review_schedule_run",
        ["started_at"],
        unique=False,
    )
    op.create_index(
        "uq_audit_review_schedule_run_active",
        "audit_review_schedule_run",
        ["schedule_id"],
        unique=True,
        postgresql_where=sa.text("status = 'STARTED' AND completed_at IS NULL"),
    )
    op.create_index(
        "idx_audit_review_job_review_candidate_key",
        "audit_review_job",
        ["review_candidate_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_audit_review_job_review_candidate_key", table_name="audit_review_job")
    op.drop_index("uq_audit_review_schedule_run_active", table_name="audit_review_schedule_run")
    op.drop_index("idx_audit_review_schedule_run_started_at", table_name="audit_review_schedule_run")
    op.drop_index("idx_audit_review_schedule_run_status", table_name="audit_review_schedule_run")
    op.drop_index("idx_audit_review_schedule_run_job_id", table_name="audit_review_schedule_run")
    op.drop_index("idx_audit_review_schedule_run_asset_id", table_name="audit_review_schedule_run")
    op.drop_index("idx_audit_review_schedule_run_schedule_id", table_name="audit_review_schedule_run")
    op.drop_table("audit_review_schedule_run")
    op.drop_index("idx_audit_review_schedule_last_job_id", table_name="audit_review_schedule")
    op.drop_index("idx_audit_review_schedule_enabled_next_run", table_name="audit_review_schedule")
    op.drop_index("idx_audit_review_schedule_asset_id", table_name="audit_review_schedule")
    op.drop_table("audit_review_schedule")
