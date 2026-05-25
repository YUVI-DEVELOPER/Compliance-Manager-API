"""Add release validation package lifecycle step 1.

Revision ID: 20260524_0041
Revises: 20260522_0040
Create Date: 2026-05-24 22:10:00

"""

from __future__ import annotations

from alembic import op


revision = "20260524_0041"
down_revision = "20260522_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS release_name VARCHAR(200)")
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS previous_version VARCHAR(50)")
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS release_type VARCHAR(40)")
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS vendor_name VARCHAR(150)")
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS planned_implementation_date TIMESTAMPTZ")
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS environment VARCHAR(30)")
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS release_description TEXT")
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS business_reason TEXT")
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS change_control_no VARCHAR(100)")
    op.execute(
        "ALTER TABLE public.asset_release "
        "ADD COLUMN IF NOT EXISTS expected_validated_functionality_impact VARCHAR(20)"
    )
    op.execute("ALTER TABLE public.asset_release ADD COLUMN IF NOT EXISTS release_status VARCHAR(50)")

    op.execute(
        """
        UPDATE public.asset_release ar
        SET release_name = LEFT(
            COALESCE(
                NULLIF(btrim(ar.release_name), ''),
                NULLIF(btrim(CONCAT(a.asset_name, ' ', ar.version)), ''),
                ar.version
            ),
            200
        )
        FROM public.asset_basic_info a
        WHERE ar.asset_id = a.asset_id
          AND (ar.release_name IS NULL OR btrim(ar.release_name) = '')
        """
    )
    op.execute(
        """
        UPDATE public.asset_release
        SET release_name = LEFT(COALESCE(NULLIF(btrim(release_name), ''), version), 200)
        WHERE release_name IS NULL OR btrim(release_name) = ''
        """
    )
    op.execute(
        """
        UPDATE public.asset_release
        SET release_type = COALESCE(NULLIF(btrim(release_type), ''), 'PATCH'),
            environment = COALESCE(NULLIF(btrim(environment), ''), 'MULTI_ENV'),
            release_status = COALESCE(NULLIF(btrim(release_status), ''), 'IMPACT_ASSESSMENT_PENDING')
        WHERE release_type IS NULL
           OR btrim(release_type) = ''
           OR environment IS NULL
           OR btrim(environment) = ''
           OR release_status IS NULL
           OR btrim(release_status) = ''
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public'
                  AND t.relname = 'asset_release'
                  AND c.contype = 'p'
            ) THEN
                ALTER TABLE public.asset_release
                ADD CONSTRAINT asset_release_pkey PRIMARY KEY (release_id);
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.release_validation_package (
            package_id UUID NOT NULL DEFAULT gen_random_uuid(),
            release_id UUID NOT NULL,
            package_no VARCHAR(50) NOT NULL,
            package_status VARCHAR(50) NOT NULL DEFAULT 'DRAFT',
            validation_scope VARCHAR(50) NOT NULL DEFAULT 'NOT_ASSESSED',
            risk_level VARCHAR(30) NOT NULL DEFAULT 'NOT_ASSESSED',
            impact_assessment_status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
            document_checklist_status VARCHAR(50) NOT NULL DEFAULT 'NOT_GENERATED',
            testing_status VARCHAR(50) NOT NULL DEFAULT 'NOT_STARTED',
            approval_status VARCHAR(50) NOT NULL DEFAULT 'NOT_STARTED',
            final_decision VARCHAR(50),
            created_by VARCHAR,
            created_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            modified_by VARCHAR,
            modified_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT release_validation_package_pkey PRIMARY KEY (package_id),
            CONSTRAINT uq_release_validation_package_release UNIQUE (release_id),
            CONSTRAINT uq_release_validation_package_no UNIQUE (package_no),
            CONSTRAINT fk_release_validation_package_release FOREIGN KEY (release_id)
                REFERENCES public.asset_release(release_id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_package_release_id "
        "ON public.release_validation_package USING btree (release_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_package_package_no "
        "ON public.release_validation_package USING btree (package_no)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_package_package_status "
        "ON public.release_validation_package USING btree (package_status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_package_validation_scope "
        "ON public.release_validation_package USING btree (validation_scope)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_package_impact_assessment_status "
        "ON public.release_validation_package USING btree (impact_assessment_status)"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_set_release_validation_package_modified_dt ON public.release_validation_package")
    op.execute(
        "CREATE TRIGGER trg_set_release_validation_package_modified_dt "
        "BEFORE UPDATE ON public.release_validation_package "
        "FOR EACH ROW EXECUTE FUNCTION public.set_modified_dt()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_set_release_validation_package_modified_dt ON public.release_validation_package")
    op.execute("DROP TABLE IF EXISTS public.release_validation_package")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS release_status")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS expected_validated_functionality_impact")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS change_control_no")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS business_reason")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS release_description")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS environment")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS planned_implementation_date")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS vendor_name")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS release_type")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS previous_version")
    op.execute("ALTER TABLE public.asset_release DROP COLUMN IF EXISTS release_name")
