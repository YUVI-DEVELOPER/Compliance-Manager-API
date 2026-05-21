"""Extend asset release with documentation fields and impact assessment table.

Revision ID: 20260402_0004
Revises: 20260402_0003
Create Date: 2026-04-02 21:45:00

"""

from __future__ import annotations

from alembic import op


revision = "20260402_0004"
down_revision = "20260402_0003"
branch_labels = None
depends_on = None

LEGACY_DOCUMENTATION_PLACEHOLDER = "Legacy release record migrated without captured release documentation."


def upgrade() -> None:
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS documentation_mode VARCHAR(20)")
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS documentation_text TEXT")
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS documentation_source_url TEXT")
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS documentation_fetched_at TIMESTAMPTZ")

    op.execute(
        f"""
        UPDATE public.asset_release
        SET documentation_mode = COALESCE(documentation_mode, 'MANUAL'),
            documentation_text = CASE
                WHEN documentation_text IS NOT NULL AND btrim(documentation_text) <> '' THEN documentation_text
                WHEN system_config_report IS NOT NULL AND btrim(system_config_report) <> '' THEN system_config_report
                ELSE '{LEGACY_DOCUMENTATION_PLACEHOLDER}'
            END,
            documentation_source_url = CASE
                WHEN COALESCE(documentation_mode, 'MANUAL') = 'ONLINE_FETCH' THEN documentation_source_url
                ELSE NULL
            END,
            documentation_fetched_at = CASE
                WHEN COALESCE(documentation_mode, 'MANUAL') = 'ONLINE_FETCH' THEN documentation_fetched_at
                ELSE NULL
            END
        WHERE documentation_mode IS NULL
           OR documentation_text IS NULL
           OR btrim(documentation_text) = ''
        """
    )
    op.execute("ALTER TABLE public.asset_release ALTER COLUMN documentation_mode SET NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_asset_release_documentation_mode'
            ) THEN
                ALTER TABLE public.asset_release
                ADD CONSTRAINT chk_asset_release_documentation_mode
                CHECK (documentation_mode IN ('MANUAL', 'ONLINE_FETCH'));
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'chk_asset_release_documentation_payload'
            ) THEN
                ALTER TABLE public.asset_release
                ADD CONSTRAINT chk_asset_release_documentation_payload
                CHECK (
                    (
                        documentation_mode = 'MANUAL'
                        AND documentation_text IS NOT NULL
                        AND btrim(documentation_text) <> ''
                    )
                    OR
                    (
                        documentation_mode = 'ONLINE_FETCH'
                        AND documentation_source_url IS NOT NULL
                        AND btrim(documentation_source_url) <> ''
                        AND documentation_text IS NOT NULL
                        AND btrim(documentation_text) <> ''
                    )
                );
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.release_impact_assessment (
            assessment_id UUID NOT NULL DEFAULT gen_random_uuid(),
            release_id UUID NOT NULL,
            previous_release_id UUID,
            report_title VARCHAR(250) NOT NULL,
            report_content TEXT NOT NULL,
            report_format VARCHAR(20) NOT NULL DEFAULT 'MARKDOWN',
            diff_summary JSONB,
            impact_level VARCHAR(50),
            generated_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by VARCHAR(150),
            CONSTRAINT release_impact_assessment_pkey PRIMARY KEY (assessment_id),
            CONSTRAINT fk_release_impact_assessment_release FOREIGN KEY (release_id)
                REFERENCES public.asset_release(release_id) ON DELETE CASCADE,
            CONSTRAINT fk_release_impact_assessment_previous_release FOREIGN KEY (previous_release_id)
                REFERENCES public.asset_release(release_id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_impact_assessment_release_id "
        "ON public.release_impact_assessment USING btree (release_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_impact_assessment_previous_release_id "
        "ON public.release_impact_assessment USING btree (previous_release_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_impact_assessment_generated_dt "
        "ON public.release_impact_assessment USING btree (generated_dt)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.release_impact_assessment")
    op.execute("ALTER TABLE public.asset_release DROP CONSTRAINT IF EXISTS chk_asset_release_documentation_payload")
    op.execute("ALTER TABLE public.asset_release DROP CONSTRAINT IF EXISTS chk_asset_release_documentation_mode")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS documentation_fetched_at")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS documentation_source_url")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS documentation_text")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS documentation_mode")
