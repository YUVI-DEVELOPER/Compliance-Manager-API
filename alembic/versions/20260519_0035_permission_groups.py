"""Add permission groups for RBAC administration.

Revision ID: 20260519_0035
Revises: 20260519_0034
Create Date: 2026-05-19 00:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260519_0035"
down_revision = "20260519_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "permission_group",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("group_code", sa.String(length=100), nullable=False),
        sa.Column("group_name", sa.String(length=150), nullable=False),
        sa.Column("module_name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_system_group", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("group_code", name="uq_permission_group_code"),
    )
    op.create_index("idx_permission_group_code", "permission_group", ["group_code"], unique=False)
    op.create_index("idx_permission_group_module", "permission_group", ["module_name"], unique=False)
    op.create_index("idx_permission_group_active", "permission_group", ["is_active"], unique=False)

    op.create_table(
        "permission_group_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["permission_group.id"],
            name="fk_permission_group_item_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permission.id"],
            name="fk_permission_group_item_permission",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("group_id", "permission_id", name="uq_permission_group_item_group_permission"),
    )
    op.create_index("idx_permission_group_item_group_id", "permission_group_item", ["group_id"], unique=False)
    op.create_index(
        "idx_permission_group_item_permission_id",
        "permission_group_item",
        ["permission_id"],
        unique=False,
    )

    op.create_table(
        "role_permission_group",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name="fk_role_permission_group_role", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["permission_group_id"],
            ["permission_group.id"],
            name="fk_role_permission_group_group",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("role_id", "permission_group_id", name="uq_role_permission_group_role_group"),
    )
    op.create_index("idx_role_permission_group_role_id", "role_permission_group", ["role_id"], unique=False)
    op.create_index(
        "idx_role_permission_group_group_id",
        "role_permission_group",
        ["permission_group_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_role_permission_group_group_id", table_name="role_permission_group")
    op.drop_index("idx_role_permission_group_role_id", table_name="role_permission_group")
    op.drop_table("role_permission_group")

    op.drop_index("idx_permission_group_item_permission_id", table_name="permission_group_item")
    op.drop_index("idx_permission_group_item_group_id", table_name="permission_group_item")
    op.drop_table("permission_group_item")

    op.drop_index("idx_permission_group_active", table_name="permission_group")
    op.drop_index("idx_permission_group_module", table_name="permission_group")
    op.drop_index("idx_permission_group_code", table_name="permission_group")
    op.drop_table("permission_group")
