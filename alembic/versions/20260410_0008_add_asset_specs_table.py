"""Add asset specs catalog table.

Revision ID: 20260410_0008
Revises: 20260409_0007
Create Date: 2026-04-10 00:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260410_0008"
down_revision = "20260409_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS public.asset_specs_parameter_seq_seq")

    op.create_table(
        "asset_specs",
        sa.Column("asset_spec_id", sa.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "asset_sub_category_id",
            sa.Integer(),
            sa.ForeignKey("lookup_value.id", name="fk_asset_specs_sub_category", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "parameter_seq",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("nextval('public.asset_specs_parameter_seq_seq'::regclass)"),
        ),
        sa.Column("parameter_grouping", sa.String(length=50), nullable=False),
        sa.Column("parameter_name", sa.String(length=50), nullable=False),
        sa.Column("parameter_value", sa.String(length=150), nullable=False),
        sa.Column("guidelines", sa.String(length=150), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("parameter_seq", name="uq_asset_specs_parameter_seq"),
    )

    op.create_index("idx_asset_specs_sub_category", "asset_specs", ["asset_sub_category_id"], unique=False)
    op.create_index(
        "idx_asset_specs_sub_category_grouping",
        "asset_specs",
        ["asset_sub_category_id", "parameter_grouping"],
        unique=False,
    )
    op.create_index("idx_asset_specs_grouping", "asset_specs", ["parameter_grouping"], unique=False)
    op.create_index("idx_asset_specs_active", "asset_specs", ["is_active"], unique=False)
    op.create_index(
        "uq_asset_specs_active_group_name",
        "asset_specs",
        ["asset_sub_category_id", "parameter_grouping", "parameter_name"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    op.execute("ALTER SEQUENCE public.asset_specs_parameter_seq_seq OWNED BY public.asset_specs.parameter_seq")


def downgrade() -> None:
    op.drop_index("uq_asset_specs_active_group_name", table_name="asset_specs")
    op.drop_index("idx_asset_specs_active", table_name="asset_specs")
    op.drop_index("idx_asset_specs_grouping", table_name="asset_specs")
    op.drop_index("idx_asset_specs_sub_category_grouping", table_name="asset_specs")
    op.drop_index("idx_asset_specs_sub_category", table_name="asset_specs")
    op.drop_table("asset_specs")
    op.execute("DROP SEQUENCE IF EXISTS public.asset_specs_parameter_seq_seq")
