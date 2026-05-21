"""Add multi audit type GxP review support.

Revision ID: 20260512_0032
Revises: 20260428_0031
Create Date: 2026-05-12 18:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260512_0032"
down_revision = "20260428_0031"
branch_labels = None
depends_on = None


_SUPPORTED_JOB_STATUSES = (
    "'CREATED', 'EXTRACTING', 'EXTRACTED', 'PARTIAL_EXTRACTION', 'ANALYZING', 'ANALYZED', "
    "'REPORT_GENERATING', 'REPORT_DRAFTED', 'FAILED', 'CANCELLED'"
)


def upgrade() -> None:
    op.drop_constraint("chk_audit_review_job_status", "audit_review_job", type_="check")
    op.create_check_constraint(
        "chk_audit_review_job_status",
        "audit_review_job",
        f"status IN ({_SUPPORTED_JOB_STATUSES})",
    )

    op.add_column(
        "audit_review_job",
        sa.Column("review_scope", sa.String(length=50), server_default=sa.text("'LOGIN_ONLY'"), nullable=False),
    )
    op.add_column(
        "audit_review_job",
        sa.Column(
            "selected_audit_trail_types_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[\"login_audit_trail\"]'::jsonb"),
            nullable=False,
        ),
    )

    op.execute(
        """
        UPDATE audit_review_job
           SET selected_audit_trail_types_json =
                   jsonb_build_array(COALESCE(NULLIF(audit_trail_type, ''), 'login_audit_trail')),
               review_scope =
                   CASE COALESCE(NULLIF(audit_trail_type, ''), 'login_audit_trail')
                       WHEN 'login_audit_trail' THEN 'LOGIN_ONLY'
                       WHEN 'document_audit_trail' THEN 'DOCUMENT_ONLY'
                       WHEN 'object_audit_trail' THEN 'OBJECT_ONLY'
                       WHEN 'system_audit_trail' THEN 'SYSTEM_ONLY'
                       WHEN 'domain_audit_trail' THEN 'DOMAIN_ONLY'
                       ELSE 'CUSTOM'
                   END
        """
    )

    op.add_column(
        "audit_trail_record",
        sa.Column(
            "audit_trail_type",
            sa.String(length=100),
            server_default=sa.text("'login_audit_trail'"),
            nullable=False,
        ),
    )
    op.add_column("audit_trail_record", sa.Column("event_status", sa.String(length=80), nullable=True))
    op.add_column("audit_trail_record", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column("audit_trail_record", sa.Column("change_control_id", sa.String(length=150), nullable=True))
    op.add_column("audit_trail_record", sa.Column("ip_address", sa.String(length=100), nullable=True))
    op.add_column("audit_trail_record", sa.Column("session_id", sa.String(length=150), nullable=True))
    op.add_column("audit_trail_record", sa.Column("auth_method", sa.String(length=100), nullable=True))
    op.add_column("audit_trail_record", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column(
        "audit_trail_record",
        sa.Column("is_export_action", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "audit_trail_record",
        sa.Column("is_configuration_change", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "audit_trail_record",
        sa.Column(
            "normalized_extra_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index("idx_audit_trail_record_audit_trail_type", "audit_trail_record", ["audit_trail_type"])
    op.execute(
        """
        UPDATE audit_trail_record record
           SET audit_trail_type = COALESCE(NULLIF(job.audit_trail_type, ''), 'login_audit_trail')
          FROM audit_review_job job
         WHERE record.job_id = job.job_id
        """
    )

    op.add_column("audit_review_finding", sa.Column("audit_trail_type", sa.String(length=100), nullable=True))
    op.add_column("audit_review_finding", sa.Column("parameter_code", sa.String(length=80), nullable=True))
    op.add_column("audit_review_finding", sa.Column("checkpoint_code", sa.String(length=80), nullable=True))
    op.create_index("idx_audit_review_finding_audit_trail_type", "audit_review_finding", ["audit_trail_type"])
    op.create_index("idx_audit_review_finding_parameter_code", "audit_review_finding", ["parameter_code"])
    op.create_index("idx_audit_review_finding_checkpoint_code", "audit_review_finding", ["checkpoint_code"])

    op.add_column(
        "audit_review_score",
        sa.Column("score_scope", sa.String(length=50), server_default=sa.text("'CHECKPOINT'"), nullable=False),
    )
    op.add_column(
        "audit_review_score",
        sa.Column("audit_trail_type", sa.String(length=100), server_default=sa.text("'ALL'"), nullable=False),
    )
    op.add_column("audit_review_score", sa.Column("score_label", sa.String(length=150), nullable=True))
    op.add_column("audit_review_score", sa.Column("applicability", sa.String(length=30), nullable=True))
    op.add_column(
        "audit_review_score",
        sa.Column("evaluated_record_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "audit_review_score",
        sa.Column("skipped_record_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "audit_review_score",
        sa.Column("no_data_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.execute(
        """
        UPDATE audit_review_score
           SET score_scope = CASE WHEN check_code = 'OVERALL' THEN 'OVERALL' ELSE 'CHECKPOINT' END,
               audit_trail_type = 'ALL',
               score_label = check_name,
               applicability = score_status,
               evaluated_record_count = source_record_count
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_audit_review_score_job_check_code")
    op.create_index(
        "uq_audit_review_score_scope_type_check",
        "audit_review_score",
        ["job_id", "score_scope", "audit_trail_type", "check_code"],
        unique=True,
    )

    op.add_column(
        "audit_review_schedule",
        sa.Column("review_scope", sa.String(length=50), server_default=sa.text("'LOGIN_ONLY'"), nullable=False),
    )
    op.add_column(
        "audit_review_schedule",
        sa.Column(
            "selected_audit_trail_types_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[\"login_audit_trail\"]'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE audit_review_schedule
           SET selected_audit_trail_types_json =
                   jsonb_build_array(COALESCE(NULLIF(audit_trail_type, ''), 'login_audit_trail')),
               review_scope =
                   CASE COALESCE(NULLIF(audit_trail_type, ''), 'login_audit_trail')
                       WHEN 'login_audit_trail' THEN 'LOGIN_ONLY'
                       WHEN 'document_audit_trail' THEN 'DOCUMENT_ONLY'
                       WHEN 'object_audit_trail' THEN 'OBJECT_ONLY'
                       WHEN 'system_audit_trail' THEN 'SYSTEM_ONLY'
                       WHEN 'domain_audit_trail' THEN 'DOMAIN_ONLY'
                       ELSE 'CUSTOM'
                   END
        """
    )


def downgrade() -> None:
    op.drop_column("audit_review_schedule", "selected_audit_trail_types_json")
    op.drop_column("audit_review_schedule", "review_scope")

    op.drop_index("uq_audit_review_score_scope_type_check", table_name="audit_review_score")
    op.execute("DELETE FROM audit_review_score WHERE score_scope = 'AUDIT_TYPE'")
    op.create_index(
        "uq_audit_review_score_job_check_code",
        "audit_review_score",
        ["job_id", "check_code"],
        unique=True,
    )
    op.drop_column("audit_review_score", "no_data_count")
    op.drop_column("audit_review_score", "skipped_record_count")
    op.drop_column("audit_review_score", "evaluated_record_count")
    op.drop_column("audit_review_score", "applicability")
    op.drop_column("audit_review_score", "score_label")
    op.drop_column("audit_review_score", "audit_trail_type")
    op.drop_column("audit_review_score", "score_scope")

    op.drop_index("idx_audit_review_finding_checkpoint_code", table_name="audit_review_finding")
    op.drop_index("idx_audit_review_finding_parameter_code", table_name="audit_review_finding")
    op.drop_index("idx_audit_review_finding_audit_trail_type", table_name="audit_review_finding")
    op.drop_column("audit_review_finding", "checkpoint_code")
    op.drop_column("audit_review_finding", "parameter_code")
    op.drop_column("audit_review_finding", "audit_trail_type")

    op.drop_index("idx_audit_trail_record_audit_trail_type", table_name="audit_trail_record")
    op.drop_column("audit_trail_record", "normalized_extra_json")
    op.drop_column("audit_trail_record", "is_configuration_change")
    op.drop_column("audit_trail_record", "is_export_action")
    op.drop_column("audit_trail_record", "failure_reason")
    op.drop_column("audit_trail_record", "auth_method")
    op.drop_column("audit_trail_record", "session_id")
    op.drop_column("audit_trail_record", "ip_address")
    op.drop_column("audit_trail_record", "change_control_id")
    op.drop_column("audit_trail_record", "reason")
    op.drop_column("audit_trail_record", "event_status")
    op.drop_column("audit_trail_record", "audit_trail_type")

    op.drop_column("audit_review_job", "selected_audit_trail_types_json")
    op.drop_column("audit_review_job", "review_scope")

    op.drop_constraint("chk_audit_review_job_status", "audit_review_job", type_="check")
    op.execute("UPDATE audit_review_job SET status = 'EXTRACTED' WHERE status = 'PARTIAL_EXTRACTION'")
    op.create_check_constraint(
        "chk_audit_review_job_status",
        "audit_review_job",
        (
            "status IN ('CREATED', 'EXTRACTING', 'EXTRACTED', 'ANALYZING', 'ANALYZED', "
            "'REPORT_GENERATING', 'REPORT_DRAFTED', 'FAILED', 'CANCELLED')"
        ),
    )
