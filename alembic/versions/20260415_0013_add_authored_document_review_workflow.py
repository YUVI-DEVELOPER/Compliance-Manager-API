"""Add authored document review workflow.

Revision ID: 20260415_0013
Revises: 20260415_0012
Create Date: 2026-04-15 00:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260415_0013"
down_revision = "20260415_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE authored_document
            SET status = 'IN_REVIEW'
            WHERE status = 'READY_FOR_REVIEW'
            """
        )
    )

    op.drop_constraint("chk_authored_document_status", "authored_document", type_="check")
    op.add_column("authored_document", sa.Column("reviewer_name", sa.String(length=150), nullable=True))
    op.add_column("authored_document", sa.Column("approver_name", sa.String(length=150), nullable=True))
    op.create_check_constraint(
        "chk_authored_document_status",
        "authored_document",
        "status IN ('DRAFT', 'IN_REVIEW', 'CHANGES_REQUESTED', 'APPROVED', 'REJECTED')",
    )

    op.create_table(
        "authored_document_review_action",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("authored_document_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("action_by", sa.String(length=150), nullable=True),
        sa.Column("action_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("comment_text", sa.Text(), nullable=True),
        sa.Column("from_status", sa.String(length=30), nullable=False),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(
            ["authored_document_id"],
            ["authored_document.authored_document_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "action_type IN ('SUBMIT_FOR_REVIEW', 'REQUEST_CHANGES', 'APPROVE', 'REJECT', 'COMMENT')",
            name="chk_authored_document_review_action_type",
        ),
        sa.CheckConstraint(
            "from_status IN ('DRAFT', 'IN_REVIEW', 'CHANGES_REQUESTED', 'APPROVED', 'REJECTED')",
            name="chk_authored_document_review_action_from_status",
        ),
        sa.CheckConstraint(
            "to_status IN ('DRAFT', 'IN_REVIEW', 'CHANGES_REQUESTED', 'APPROVED', 'REJECTED')",
            name="chk_authored_document_review_action_to_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_authored_document_review_action_document_id",
        "authored_document_review_action",
        ["authored_document_id"],
        unique=False,
    )
    op.create_index(
        "idx_authored_document_review_action_action_type",
        "authored_document_review_action",
        ["action_type"],
        unique=False,
    )
    op.create_index(
        "idx_authored_document_review_action_action_dt",
        "authored_document_review_action",
        ["action_dt"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_authored_document_review_action_action_dt", table_name="authored_document_review_action")
    op.drop_index("idx_authored_document_review_action_action_type", table_name="authored_document_review_action")
    op.drop_index("idx_authored_document_review_action_document_id", table_name="authored_document_review_action")
    op.drop_table("authored_document_review_action")

    op.drop_constraint("chk_authored_document_status", "authored_document", type_="check")
    op.drop_column("authored_document", "approver_name")
    op.drop_column("authored_document", "reviewer_name")
    op.execute(
        sa.text(
            """
            UPDATE authored_document
            SET status = CASE
                WHEN status = 'DRAFT' THEN 'DRAFT'
                ELSE 'READY_FOR_REVIEW'
            END
            """
        )
    )
    op.create_check_constraint(
        "chk_authored_document_status",
        "authored_document",
        "status IN ('DRAFT', 'READY_FOR_REVIEW')",
    )
