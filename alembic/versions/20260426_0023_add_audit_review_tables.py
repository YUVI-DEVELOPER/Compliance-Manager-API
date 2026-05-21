"""Add audit review tables.

Revision ID: 20260426_0023
Revises: 20260421_0022
Create Date: 2026-04-26 19:05:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260426_0023"
down_revision = "20260421_0022"
branch_labels = None
depends_on = None


def _ensure_asset_id_fk_target() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            asset_id_attnum integer;
        BEGIN
            SELECT attnum
              INTO asset_id_attnum
              FROM pg_attribute
             WHERE attrelid = 'public.asset_basic_info'::regclass
               AND attname = 'asset_id'
               AND NOT attisdropped;

            IF asset_id_attnum IS NULL THEN
                RAISE EXCEPTION 'asset_basic_info.asset_id does not exist';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                  FROM pg_constraint
                 WHERE conrelid = 'public.asset_basic_info'::regclass
                   AND contype IN ('p', 'u')
                   AND conkey = ARRAY[asset_id_attnum]::smallint[]
            ) THEN
                ALTER TABLE public.asset_basic_info
                    ADD CONSTRAINT uq_asset_basic_info_asset_id_for_audit_review UNIQUE (asset_id);
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    _ensure_asset_id_fk_target()

    op.create_table(
        "audit_review_job",
        sa.Column("job_id", sa.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("asset_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("review_candidate_key", sa.String(length=500), nullable=False),
        sa.Column("vault_dns", sa.String(length=255), nullable=True),
        sa.Column("veeva_instance_name", sa.String(length=150), nullable=True),
        sa.Column("veeva_app_name", sa.String(length=150), nullable=True),
        sa.Column(
            "audit_trail_type",
            sa.String(length=100),
            server_default=sa.text("'login_audit_trail'"),
            nullable=False,
        ),
        sa.Column("review_start_dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_end_dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_basis", sa.String(length=30), server_default=sa.text("'MANUAL'"), nullable=False),
        sa.Column("trigger_mode", sa.String(length=30), server_default=sa.text("'MANUAL'"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "input_snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "extraction_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("analysis_summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("report_summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(length=150), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('CREATED', 'EXTRACTING', 'EXTRACTED', 'FAILED', 'CANCELLED')",
            name="chk_audit_review_job_status",
        ),
        sa.CheckConstraint("review_end_dt > review_start_dt", name="chk_audit_review_job_period"),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset_basic_info.asset_id"],
            name="fk_audit_review_job_asset",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("idx_audit_review_job_asset_id", "audit_review_job", ["asset_id"], unique=False)
    op.create_index("idx_audit_review_job_status", "audit_review_job", ["status"], unique=False)
    op.create_index("idx_audit_review_job_created_dt", "audit_review_job", ["created_dt"], unique=False)

    op.create_table(
        "audit_trail_record",
        sa.Column("record_id", sa.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("source_record_key", sa.String(length=300), nullable=True),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_timezone", sa.String(length=50), nullable=True),
        sa.Column("user_id", sa.String(length=150), nullable=True),
        sa.Column("user_name", sa.String(length=250), nullable=True),
        sa.Column("action_type", sa.String(length=150), nullable=True),
        sa.Column("object_type", sa.String(length=150), nullable=True),
        sa.Column("object_name", sa.String(length=300), nullable=True),
        sa.Column("object_id", sa.String(length=150), nullable=True),
        sa.Column("field_name", sa.String(length=250), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("is_delete_action", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_permission_change", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("record_quality_status", sa.String(length=30), server_default=sa.text("'VALID'"), nullable=False),
        sa.Column(
            "raw_payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "record_quality_status IN ('VALID', 'INCOMPLETE')",
            name="chk_audit_trail_record_quality_status",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset_basic_info.asset_id"],
            name="fk_audit_trail_record_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["audit_review_job.job_id"],
            name="fk_audit_trail_record_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("record_id"),
    )
    op.create_index("idx_audit_trail_record_job_id", "audit_trail_record", ["job_id"], unique=False)
    op.create_index("idx_audit_trail_record_asset_id", "audit_trail_record", ["asset_id"], unique=False)
    op.create_index(
        "idx_audit_trail_record_event_timestamp",
        "audit_trail_record",
        ["event_timestamp"],
        unique=False,
    )
    op.create_index("idx_audit_trail_record_source_key", "audit_trail_record", ["source_record_key"], unique=False)

    op.create_table(
        "audit_review_finding",
        sa.Column("finding_id", sa.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_type", sa.String(length=80), nullable=True),
        sa.Column("severity", sa.String(length=30), nullable=True),
        sa.Column("title", sa.String(length=250), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=30), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset_basic_info.asset_id"],
            name="fk_audit_review_finding_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["audit_review_job.job_id"],
            name="fk_audit_review_finding_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("finding_id"),
    )
    op.create_index("idx_audit_review_finding_job_id", "audit_review_finding", ["job_id"], unique=False)
    op.create_index("idx_audit_review_finding_asset_id", "audit_review_finding", ["asset_id"], unique=False)
    op.create_index("idx_audit_review_finding_severity", "audit_review_finding", ["severity"], unique=False)

    op.create_table(
        "audit_review_score",
        sa.Column("score_id", sa.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("overall_score", sa.Integer(), nullable=True),
        sa.Column("score_status", sa.String(length=30), server_default=sa.text("'NOT_SCORED'"), nullable=False),
        sa.Column(
            "scoring_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset_basic_info.asset_id"],
            name="fk_audit_review_score_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["audit_review_job.job_id"],
            name="fk_audit_review_score_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("score_id"),
    )
    op.create_index("idx_audit_review_score_job_id", "audit_review_score", ["job_id"], unique=True)
    op.create_index("idx_audit_review_score_asset_id", "audit_review_score", ["asset_id"], unique=False)

    op.create_table(
        "audit_review_report",
        sa.Column("report_id", sa.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("report_status", sa.String(length=30), server_default=sa.text("'NOT_GENERATED'"), nullable=False),
        sa.Column(
            "report_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("report_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["asset_basic_info.asset_id"],
            name="fk_audit_review_report_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["audit_review_job.job_id"],
            name="fk_audit_review_report_job",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("report_id"),
    )
    op.create_index("idx_audit_review_report_job_id", "audit_review_report", ["job_id"], unique=True)
    op.create_index("idx_audit_review_report_asset_id", "audit_review_report", ["asset_id"], unique=False)


def downgrade() -> None:
    op.drop_table("audit_review_report")
    op.drop_table("audit_review_score")
    op.drop_table("audit_review_finding")
    op.drop_table("audit_trail_record")
    op.drop_table("audit_review_job")
    op.execute(
        "ALTER TABLE public.asset_basic_info "
        "DROP CONSTRAINT IF EXISTS uq_asset_basic_info_asset_id_for_audit_review"
    )
