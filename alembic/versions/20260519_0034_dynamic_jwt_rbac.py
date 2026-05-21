"""Add dynamic JWT RBAC.

Revision ID: 20260519_0034
Revises: 20260514_0033
Create Date: 2026-05-19 00:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260519_0034"
down_revision = "20260514_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("app_user", "user_id", new_column_name="id")
    op.alter_column("app_user", "created_dt", new_column_name="created_at")
    op.alter_column("app_user", "modified_dt", new_column_name="updated_at")
    op.add_column("app_user", sa.Column("designation", sa.String(length=150), nullable=True))
    op.add_column("app_user", sa.Column("department", sa.String(length=150), nullable=True))
    op.add_column("app_user", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column(
        "app_user",
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "app_user",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("app_user", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("app_user", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("app_user", sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("app_user", sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("idx_app_user_locked", "app_user", ["is_locked"], unique=False)

    op.create_table(
        "role",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("role_code", sa.String(length=80), nullable=False),
        sa.Column("role_name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system_role", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("role_code", name="uq_role_code"),
    )
    op.create_index("idx_role_code", "role", ["role_code"], unique=False)
    op.create_index("idx_role_active", "role", ["is_active"], unique=False)

    op.create_table(
        "permission",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("permission_code", sa.String(length=100), nullable=False),
        sa.Column("permission_name", sa.String(length=150), nullable=False),
        sa.Column("module_name", sa.String(length=80), nullable=False),
        sa.Column("action_name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system_permission", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("permission_code", name="uq_permission_code"),
    )
    op.create_index("idx_permission_code", "permission", ["permission_code"], unique=False)
    op.create_index("idx_permission_module", "permission", ["module_name"], unique=False)
    op.create_index("idx_permission_active", "permission", ["is_active"], unique=False)

    op.create_table(
        "role_permission",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name="fk_role_permission_role", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permission.id"],
            name="fk_role_permission_permission",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission_role_permission"),
    )
    op.create_index("idx_role_permission_role_id", "role_permission", ["role_id"], unique=False)
    op.create_index("idx_role_permission_permission_id", "role_permission", ["permission_id"], unique=False)

    op.create_table(
        "user_role",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], name="fk_user_role_user", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name="fk_user_role_role", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role_user_role"),
    )
    op.create_index("idx_user_role_user_id", "user_role", ["user_id"], unique=False)
    op.create_index("idx_user_role_role_id", "user_role", ["role_id"], unique=False)

    op.create_table(
        "login_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.String(length=150), nullable=False),
        sa.Column("login_time", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("logout_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=100), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("login_status", sa.String(length=20), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], name="fk_login_audit_log_user", ondelete="SET NULL"),
    )
    op.create_index("idx_login_audit_log_email", "login_audit_log", ["email"], unique=False)
    op.create_index("idx_login_audit_log_user_id", "login_audit_log", ["user_id"], unique=False)
    op.create_index("idx_login_audit_log_status", "login_audit_log", ["login_status"], unique=False)
    op.create_index("idx_login_audit_log_login_time", "login_audit_log", ["login_time"], unique=False)

    op.drop_constraint("chk_audit_review_report_status", "audit_review_report", type_="check")
    op.create_check_constraint(
        "chk_audit_review_report_status",
        "audit_review_report",
        "report_status IN ('NOT_GENERATED', 'DRAFT', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'CHANGES_REQUESTED', 'SUPERSEDED')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_audit_review_report_status", "audit_review_report", type_="check")
    op.execute("UPDATE audit_review_report SET report_status = 'REJECTED' WHERE report_status = 'CHANGES_REQUESTED'")
    op.create_check_constraint(
        "chk_audit_review_report_status",
        "audit_review_report",
        "report_status IN ('NOT_GENERATED', 'DRAFT', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'SUPERSEDED')",
    )

    op.drop_index("idx_login_audit_log_login_time", table_name="login_audit_log")
    op.drop_index("idx_login_audit_log_status", table_name="login_audit_log")
    op.drop_index("idx_login_audit_log_user_id", table_name="login_audit_log")
    op.drop_index("idx_login_audit_log_email", table_name="login_audit_log")
    op.drop_table("login_audit_log")

    op.drop_index("idx_user_role_role_id", table_name="user_role")
    op.drop_index("idx_user_role_user_id", table_name="user_role")
    op.drop_table("user_role")

    op.drop_index("idx_role_permission_permission_id", table_name="role_permission")
    op.drop_index("idx_role_permission_role_id", table_name="role_permission")
    op.drop_table("role_permission")

    op.drop_index("idx_permission_active", table_name="permission")
    op.drop_index("idx_permission_module", table_name="permission")
    op.drop_index("idx_permission_code", table_name="permission")
    op.drop_table("permission")

    op.drop_index("idx_role_active", table_name="role")
    op.drop_index("idx_role_code", table_name="role")
    op.drop_table("role")

    op.drop_index("idx_app_user_locked", table_name="app_user")
    op.drop_column("app_user", "updated_by")
    op.drop_column("app_user", "created_by")
    op.drop_column("app_user", "password_changed_at")
    op.drop_column("app_user", "last_login_at")
    op.drop_column("app_user", "failed_login_count")
    op.drop_column("app_user", "is_locked")
    op.drop_column("app_user", "phone")
    op.drop_column("app_user", "department")
    op.drop_column("app_user", "designation")
    op.alter_column("app_user", "updated_at", new_column_name="modified_dt")
    op.alter_column("app_user", "created_at", new_column_name="created_dt")
    op.alter_column("app_user", "id", new_column_name="user_id")
