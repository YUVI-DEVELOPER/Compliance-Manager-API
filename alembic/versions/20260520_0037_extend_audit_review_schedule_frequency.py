"""Extend audit review schedule frequencies.

Revision ID: 20260520_0037
Revises: 20260520_0036
Create Date: 2026-05-20 00:00:00

"""

from __future__ import annotations

from alembic import op


revision = "20260520_0037"
down_revision = "20260520_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("chk_audit_review_schedule_frequency", "audit_review_schedule", type_="check")
    op.create_check_constraint(
        "chk_audit_review_schedule_frequency",
        "audit_review_schedule",
        "frequency IN ('DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY', 'HALF_YEARLY', 'ANNUAL')",
    )
    op.drop_constraint("chk_audit_review_schedule_review_window_days", "audit_review_schedule", type_="check")
    op.create_check_constraint(
        "chk_audit_review_schedule_review_window_days",
        "audit_review_schedule",
        "review_window_days IS NULL OR (review_window_days > 0 AND review_window_days <= 366)",
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE audit_review_schedule
           SET frequency = 'QUARTERLY'
         WHERE frequency IN ('HALF_YEARLY', 'ANNUAL')
        """
    )
    op.execute(
        """
        UPDATE audit_review_schedule
           SET review_window_days = 30
         WHERE review_window_days > 30
        """
    )
    op.drop_constraint("chk_audit_review_schedule_review_window_days", "audit_review_schedule", type_="check")
    op.create_check_constraint(
        "chk_audit_review_schedule_review_window_days",
        "audit_review_schedule",
        "review_window_days IS NULL OR review_window_days > 0",
    )
    op.drop_constraint("chk_audit_review_schedule_frequency", "audit_review_schedule", type_="check")
    op.create_check_constraint(
        "chk_audit_review_schedule_frequency",
        "audit_review_schedule",
        "frequency IN ('DAILY', 'WEEKLY', 'MONTHLY', 'QUARTERLY')",
    )
