"""add audit review schedule planner fields

Revision ID: 20260520_0038
Revises: 20260520_0037
Create Date: 2026-05-20 19:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260520_0038"
down_revision = "20260520_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_review_schedule", sa.Column("schedule_start_dt", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("schedule_end_dt", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("end_condition", sa.String(length=30), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("end_after_runs", sa.Integer(), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("run_time", sa.String(length=5), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("day_of_week", sa.Integer(), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("day_of_month", sa.Integer(), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("use_last_day_of_month", sa.Boolean(), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("cycle_type", sa.String(length=50), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("run_timing", sa.String(length=50), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("run_month", sa.Integer(), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("custom_cycle_start_month", sa.Integer(), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("fiscal_year_start_month", sa.Integer(), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("audit_retrieval_mode", sa.String(length=40), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("custom_audit_start_dt", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_review_schedule", sa.Column("custom_audit_end_dt", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_review_schedule", "custom_audit_end_dt")
    op.drop_column("audit_review_schedule", "custom_audit_start_dt")
    op.drop_column("audit_review_schedule", "audit_retrieval_mode")
    op.drop_column("audit_review_schedule", "fiscal_year_start_month")
    op.drop_column("audit_review_schedule", "custom_cycle_start_month")
    op.drop_column("audit_review_schedule", "run_month")
    op.drop_column("audit_review_schedule", "run_timing")
    op.drop_column("audit_review_schedule", "cycle_type")
    op.drop_column("audit_review_schedule", "use_last_day_of_month")
    op.drop_column("audit_review_schedule", "day_of_month")
    op.drop_column("audit_review_schedule", "day_of_week")
    op.drop_column("audit_review_schedule", "run_time")
    op.drop_column("audit_review_schedule", "end_after_runs")
    op.drop_column("audit_review_schedule", "end_condition")
    op.drop_column("audit_review_schedule", "schedule_end_dt")
    op.drop_column("audit_review_schedule", "schedule_start_dt")
