"""Add asset release table.

Revision ID: 20260402_0002
Revises: 20260402_0001
Create Date: 2026-04-02 15:05:00

"""

from __future__ import annotations

from alembic import op


revision = "20260402_0002"
down_revision = "20260402_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.asset_release (
            release_id UUID NOT NULL DEFAULT gen_random_uuid(),
            asset_id UUID NOT NULL,
            version VARCHAR(50) NOT NULL,
            system_config_report TEXT,
            created_by VARCHAR(150),
            created_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            modified_by VARCHAR(150),
            modified_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            end_dt TIMESTAMPTZ,
            CONSTRAINT asset_release_pkey PRIMARY KEY (release_id),
            CONSTRAINT uq_asset_release_asset_version UNIQUE (asset_id, version),
            CONSTRAINT fk_asset_release_asset FOREIGN KEY (asset_id)
                REFERENCES public.asset_basic_info(asset_id) ON DELETE CASCADE,
            CONSTRAINT chk_asset_release_end_dt CHECK (end_dt IS NULL OR end_dt >= created_dt)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_asset_release_asset_id ON public.asset_release USING btree (asset_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_asset_release_version ON public.asset_release USING btree (version)")
    op.execute("DROP TRIGGER IF EXISTS trg_set_asset_release_modified_dt ON public.asset_release")
    op.execute(
        "CREATE TRIGGER trg_set_asset_release_modified_dt BEFORE UPDATE ON public.asset_release "
        "FOR EACH ROW EXECUTE FUNCTION public.set_modified_dt()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_set_asset_release_modified_dt ON public.asset_release")
    op.execute("DROP TABLE IF EXISTS public.asset_release")
