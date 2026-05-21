"""Add asset grouping tables.

Revision ID: 20260413_0010
Revises: 20260413_0009
Create Date: 2026-04-13 00:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_0010"
down_revision = "20260413_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "asset_group",
        sa.Column("group_id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "parent_group_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("asset_group.group_id", name="fk_asset_group_parent", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "org_node_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("org_structure.id", name="fk_asset_group_org_node", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("group_name", sa.String(length=150), nullable=False),
        sa.Column("group_code", sa.String(length=50), nullable=True),
        sa.Column("group_type", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("(parent_group_id IS NULL) OR (parent_group_id <> group_id)", name="chk_asset_group_no_self_parent"),
        sa.CheckConstraint("group_type IN ('SYSTEM', 'SUB_SYSTEM')", name="chk_asset_group_type"),
        sa.CheckConstraint("(group_type <> 'SYSTEM') OR (parent_group_id IS NULL)", name="chk_asset_group_system_parent"),
        sa.PrimaryKeyConstraint("group_id"),
        sa.UniqueConstraint("group_code", name="uq_asset_group_code"),
    )
    op.create_index("idx_asset_group_parent", "asset_group", ["parent_group_id"], unique=False)
    op.create_index("idx_asset_group_type", "asset_group", ["group_type"], unique=False)
    op.create_index("idx_asset_group_org_node", "asset_group", ["org_node_id"], unique=False)
    op.create_index("idx_asset_group_active", "asset_group", ["is_active"], unique=False)
    op.create_index("idx_asset_group_name", "asset_group", ["group_name"], unique=False)

    op.create_table(
        "asset_group_membership",
        sa.Column("membership_id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "group_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("asset_group.group_id", name="fk_asset_group_membership_group", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_uuid",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("asset_basic_info.asset_id", name="fk_asset_group_membership_asset", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("membership_id"),
        sa.UniqueConstraint("group_id", "asset_uuid", name="uq_asset_group_membership_group_asset"),
    )
    op.create_index("idx_asset_group_membership_group", "asset_group_membership", ["group_id"], unique=False)
    op.create_index("idx_asset_group_membership_asset", "asset_group_membership", ["asset_uuid"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_asset_group_membership_asset", table_name="asset_group_membership")
    op.drop_index("idx_asset_group_membership_group", table_name="asset_group_membership")
    op.drop_table("asset_group_membership")

    op.drop_index("idx_asset_group_name", table_name="asset_group")
    op.drop_index("idx_asset_group_active", table_name="asset_group")
    op.drop_index("idx_asset_group_org_node", table_name="asset_group")
    op.drop_index("idx_asset_group_type", table_name="asset_group")
    op.drop_index("idx_asset_group_parent", table_name="asset_group")
    op.drop_table("asset_group")
