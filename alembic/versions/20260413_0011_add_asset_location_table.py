"""Add asset location extension table.

Revision ID: 20260413_0011
Revises: 20260413_0010
Create Date: 2026-04-13 01:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_0011"
down_revision = "20260413_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "asset_location",
        sa.Column("location_id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "asset_uuid",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("asset_basic_info.asset_id", name="fk_asset_location_asset", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("building_reference", sa.String(length=100), nullable=False),
        sa.Column("floor_reference", sa.String(length=60), nullable=False),
        sa.Column("local_reference", sa.String(length=150), nullable=False),
        sa.Column("remarks", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "char_length(btrim(building_reference)) > 0",
            name="chk_asset_location_building_reference_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(btrim(floor_reference)) > 0",
            name="chk_asset_location_floor_reference_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(btrim(local_reference)) > 0",
            name="chk_asset_location_local_reference_not_blank",
        ),
        sa.PrimaryKeyConstraint("location_id"),
        sa.UniqueConstraint("asset_uuid", name="uq_asset_location_asset_uuid"),
    )


def downgrade() -> None:
    op.drop_table("asset_location")
