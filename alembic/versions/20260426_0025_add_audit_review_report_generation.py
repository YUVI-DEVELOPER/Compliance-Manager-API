"""Add audit review report generation support.

Revision ID: 20260426_0025
Revises: 20260426_0024
Create Date: 2026-04-26 21:45:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_0025"
down_revision = "20260426_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("chk_audit_review_job_status", "audit_review_job", type_="check")
    op.create_check_constraint(
        "chk_audit_review_job_status",
        "audit_review_job",
        (
            "status IN ('CREATED', 'EXTRACTING', 'EXTRACTED', 'ANALYZING', 'ANALYZED', "
            "'REPORT_GENERATING', 'REPORT_DRAFTED', 'FAILED', 'CANCELLED')"
        ),
    )

    op.add_column("audit_review_report", sa.Column("report_markdown", sa.Text(), nullable=True))
    op.drop_index("idx_audit_review_report_job_id", table_name="audit_review_report")
    op.create_index("idx_audit_review_report_job_id", "audit_review_report", ["job_id"], unique=False)
    op.create_check_constraint(
        "chk_audit_review_report_status",
        "audit_review_report",
        "report_status IN ('NOT_GENERATED', 'DRAFT', 'SUPERSEDED')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_audit_review_report_status", "audit_review_report", type_="check")
    op.drop_index("idx_audit_review_report_job_id", table_name="audit_review_report")
    op.execute(
        """
        DELETE FROM audit_review_report report
        USING (
            SELECT
                report_id,
                row_number() OVER (
                    PARTITION BY job_id
                    ORDER BY created_dt DESC, report_id DESC
                ) AS row_number
            FROM audit_review_report
        ) ranked
        WHERE report.report_id = ranked.report_id
          AND ranked.row_number > 1;
        """
    )
    op.create_index("idx_audit_review_report_job_id", "audit_review_report", ["job_id"], unique=True)
    op.drop_column("audit_review_report", "report_markdown")

    op.drop_constraint("chk_audit_review_job_status", "audit_review_job", type_="check")
    op.execute("UPDATE audit_review_job SET status = 'ANALYZED' WHERE status IN ('REPORT_GENERATING', 'REPORT_DRAFTED')")
    op.create_check_constraint(
        "chk_audit_review_job_status",
        "audit_review_job",
        "status IN ('CREATED', 'EXTRACTING', 'EXTRACTED', 'ANALYZING', 'ANALYZED', 'FAILED', 'CANCELLED')",
    )
