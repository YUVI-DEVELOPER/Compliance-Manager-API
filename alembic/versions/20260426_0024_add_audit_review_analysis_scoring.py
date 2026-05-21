"""Add audit review analysis and scoring fields.

Revision ID: 20260426_0024
Revises: 20260426_0023
Create Date: 2026-04-26 20:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_0024"
down_revision = "20260426_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("chk_audit_review_job_status", "audit_review_job", type_="check")
    op.create_check_constraint(
        "chk_audit_review_job_status",
        "audit_review_job",
        "status IN ('CREATED', 'EXTRACTING', 'EXTRACTED', 'ANALYZING', 'ANALYZED', 'FAILED', 'CANCELLED')",
    )

    op.add_column("audit_review_finding", sa.Column("primary_record_id", sa.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "audit_review_finding",
        sa.Column("check_code", sa.String(length=80), server_default=sa.text("'UNSPECIFIED'"), nullable=False),
    )
    op.add_column(
        "audit_review_finding",
        sa.Column("check_name", sa.String(length=150), server_default=sa.text("'Unspecified Finding'"), nullable=False),
    )
    op.add_column(
        "audit_review_finding",
        sa.Column("score_impact", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("audit_review_finding", sa.Column("finding_title", sa.String(length=250), nullable=True))
    op.add_column("audit_review_finding", sa.Column("finding_summary", sa.Text(), nullable=True))
    op.add_column(
        "audit_review_finding",
        sa.Column("source_record_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_foreign_key(
        "fk_audit_review_finding_primary_record",
        "audit_review_finding",
        "audit_trail_record",
        ["primary_record_id"],
        ["record_id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_audit_review_finding_check_code", "audit_review_finding", ["check_code"], unique=False)
    op.create_index(
        "idx_audit_review_finding_primary_record_id",
        "audit_review_finding",
        ["primary_record_id"],
        unique=False,
    )

    op.drop_index("idx_audit_review_score_job_id", table_name="audit_review_score")
    op.add_column(
        "audit_review_score",
        sa.Column("check_code", sa.String(length=80), server_default=sa.text("'OVERALL'"), nullable=False),
    )
    op.add_column(
        "audit_review_score",
        sa.Column(
            "check_name",
            sa.String(length=150),
            server_default=sa.text("'Overall Compliance Score'"),
            nullable=False,
        ),
    )
    op.add_column("audit_review_score", sa.Column("rating", sa.String(length=30), nullable=True))
    op.add_column(
        "audit_review_score",
        sa.Column("source_record_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "audit_review_score",
        sa.Column("finding_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "audit_review_score",
        sa.Column("penalty_per_finding", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "audit_review_score",
        sa.Column("penalty_cap", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "audit_review_score",
        sa.Column("raw_penalty", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "audit_review_score",
        sa.Column("applied_penalty", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "audit_review_score",
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_index("idx_audit_review_score_job_id", "audit_review_score", ["job_id"], unique=False)
    op.create_index("idx_audit_review_score_check_code", "audit_review_score", ["check_code"], unique=False)
    op.create_index(
        "uq_audit_review_score_job_check_code",
        "audit_review_score",
        ["job_id", "check_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_audit_review_score_job_check_code", table_name="audit_review_score")
    op.drop_index("idx_audit_review_score_check_code", table_name="audit_review_score")
    op.drop_index("idx_audit_review_score_job_id", table_name="audit_review_score")
    op.execute("DELETE FROM audit_review_score WHERE check_code <> 'OVERALL'")
    op.drop_column("audit_review_score", "sort_order")
    op.drop_column("audit_review_score", "applied_penalty")
    op.drop_column("audit_review_score", "raw_penalty")
    op.drop_column("audit_review_score", "penalty_cap")
    op.drop_column("audit_review_score", "penalty_per_finding")
    op.drop_column("audit_review_score", "finding_count")
    op.drop_column("audit_review_score", "source_record_count")
    op.drop_column("audit_review_score", "rating")
    op.drop_column("audit_review_score", "check_name")
    op.drop_column("audit_review_score", "check_code")
    op.create_index("idx_audit_review_score_job_id", "audit_review_score", ["job_id"], unique=True)

    op.drop_index("idx_audit_review_finding_primary_record_id", table_name="audit_review_finding")
    op.drop_index("idx_audit_review_finding_check_code", table_name="audit_review_finding")
    op.drop_constraint("fk_audit_review_finding_primary_record", "audit_review_finding", type_="foreignkey")
    op.drop_column("audit_review_finding", "source_record_count")
    op.drop_column("audit_review_finding", "finding_summary")
    op.drop_column("audit_review_finding", "finding_title")
    op.drop_column("audit_review_finding", "score_impact")
    op.drop_column("audit_review_finding", "check_name")
    op.drop_column("audit_review_finding", "check_code")
    op.drop_column("audit_review_finding", "primary_record_id")

    op.drop_constraint("chk_audit_review_job_status", "audit_review_job", type_="check")
    op.execute("UPDATE audit_review_job SET status = 'EXTRACTED' WHERE status IN ('ANALYZING', 'ANALYZED')")
    op.create_check_constraint(
        "chk_audit_review_job_status",
        "audit_review_job",
        "status IN ('CREATED', 'EXTRACTING', 'EXTRACTED', 'FAILED', 'CANCELLED')",
    )
