"""Add validated document link table.

Revision ID: 20260402_0003
Revises: 20260402_0002
Create Date: 2026-04-02 20:30:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260402_0003"
down_revision = "20260402_0002"
branch_labels = None
depends_on = None

OMS_SOURCE_SYSTEM_LOOKUP_KEY = "OMS_SOURCE_SYSTEM"
OMS_SOURCE_SYSTEM_VALUES = (
    ("VEEVA_VAULT", "Veeva Vault", 1, True),
    ("MANUAL_URL", "Manual URL", 2, True),
    ("SHAREPOINT", "SharePoint", 3, True),
    ("OTHER", "Other", 4, True),
)


def _seed_oms_source_system_lookup() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO public.lookup_master (lookup_key, description, is_active, created_by)
            VALUES (:lookup_key, :description, TRUE, 'alembic')
            ON CONFLICT (lookup_key) DO UPDATE
            SET description = EXCLUDED.description,
                is_active = EXCLUDED.is_active,
                modified_by = 'alembic',
                modified_dt = now()
            """
        ),
        {
            "lookup_key": OMS_SOURCE_SYSTEM_LOOKUP_KEY,
            "description": "Supported source systems for external document links",
        },
    )

    for code, display_name, sort_order, is_active in OMS_SOURCE_SYSTEM_VALUES:
        bind.execute(
            sa.text(
                """
                INSERT INTO public.lookup_value (
                    lookup_id,
                    code,
                    display_name,
                    sort_order,
                    is_active,
                    created_by
                )
                SELECT lm.id, :code, :display_name, :sort_order, :is_active, 'alembic'
                FROM public.lookup_master lm
                WHERE lm.lookup_key = :lookup_key
                ON CONFLICT (lookup_id, code) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    sort_order = EXCLUDED.sort_order,
                    is_active = EXCLUDED.is_active,
                    modified_by = 'alembic',
                    modified_dt = now()
                """
            ),
            {
                "lookup_key": OMS_SOURCE_SYSTEM_LOOKUP_KEY,
                "code": code,
                "display_name": display_name,
                "sort_order": sort_order,
                "is_active": is_active,
            },
        )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.validated_document_link (
            document_link_id UUID NOT NULL DEFAULT gen_random_uuid(),
            asset_id UUID,
            release_id UUID,
            source_system VARCHAR(50) NOT NULL,
            external_document_id VARCHAR(150) NOT NULL,
            document_name VARCHAR(250) NOT NULL,
            document_version VARCHAR(50) NOT NULL,
            upload_dt TIMESTAMPTZ NOT NULL,
            access_url TEXT NOT NULL,
            source_reference VARCHAR(500),
            notes TEXT,
            created_by VARCHAR(150),
            created_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            modified_by VARCHAR(150),
            modified_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT validated_document_link_pkey PRIMARY KEY (document_link_id),
            CONSTRAINT fk_validated_document_link_asset FOREIGN KEY (asset_id)
                REFERENCES public.asset_basic_info(asset_id) ON DELETE CASCADE,
            CONSTRAINT fk_validated_document_link_release FOREIGN KEY (release_id)
                REFERENCES public.asset_release(release_id) ON DELETE CASCADE,
            CONSTRAINT chk_validated_document_link_exactly_one_target CHECK (
                (asset_id IS NOT NULL AND release_id IS NULL)
                OR
                (asset_id IS NULL AND release_id IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_validated_document_link_asset_id "
        "ON public.validated_document_link USING btree (asset_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_validated_document_link_release_id "
        "ON public.validated_document_link USING btree (release_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_validated_document_link_source_system "
        "ON public.validated_document_link USING btree (source_system)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_validated_document_link_external_document_id "
        "ON public.validated_document_link USING btree (external_document_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vdl_asset_ext_doc "
        "ON public.validated_document_link USING btree (asset_id, source_system, external_document_id) "
        "WHERE asset_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vdl_release_ext_doc "
        "ON public.validated_document_link USING btree (release_id, source_system, external_document_id) "
        "WHERE release_id IS NOT NULL"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_set_validated_document_link_modified_dt ON public.validated_document_link")
    op.execute(
        "CREATE TRIGGER trg_set_validated_document_link_modified_dt "
        "BEFORE UPDATE ON public.validated_document_link "
        "FOR EACH ROW EXECUTE FUNCTION public.set_modified_dt()"
    )
    _seed_oms_source_system_lookup()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_set_validated_document_link_modified_dt ON public.validated_document_link")
    op.execute("DROP TABLE IF EXISTS public.validated_document_link")
    op.execute(
        """
        DELETE FROM public.lookup_value
        WHERE lookup_id IN (
            SELECT id FROM public.lookup_master WHERE lookup_key = 'OMS_SOURCE_SYSTEM'
        )
        """
    )
    op.execute("DELETE FROM public.lookup_master WHERE lookup_key = 'OMS_SOURCE_SYSTEM'")
