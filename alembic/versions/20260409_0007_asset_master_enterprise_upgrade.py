"""Enhance asset master for enterprise asset classification.

Revision ID: 20260409_0007
Revises: 20260409_0006
Create Date: 2026-04-09 19:10:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260409_0007"
down_revision = "20260409_0006"
branch_labels = None
depends_on = None

LOOKUP_MASTER_SEEDS = (
    ("ASSET_CLASS", "Enterprise asset class", True),
    ("ASSET_CATEGORY", "Enterprise asset category", True),
    ("ASSET_SUB_CATEGORY", "Enterprise asset sub-category", True),
    ("CRITICALITY_CLASS", "Enterprise criticality classes", True),
    ("ASSET_NATURE", "Enterprise asset nature classification", True),
)

LOOKUP_VALUE_SEEDS = (
    ("ASSET_CLASS", "SOFTWARE", "Software", 1, True, '{"is_upgrade_supported": true}'),
    ("ASSET_CLASS", "HARDWARE", "Hardware", 2, True, '{"is_upgrade_supported": true}'),
    ("ASSET_CLASS", "SERVICE", "Service", 3, True, '{"is_upgrade_supported": false}'),
    ("ASSET_CLASS", "DOCUMENT", "Document", 4, True, '{"is_upgrade_supported": false}'),
    ("ASSET_CLASS", "GENERAL", "General", 5, True, '{"is_upgrade_supported": false}'),
    ("ASSET_CATEGORY", "GENERAL", "General", 1, True, None),
    ("ASSET_CATEGORY", "SOFTWARE", "Software", 2, True, None),
    ("ASSET_CATEGORY", "HARDWARE", "Hardware", 3, True, None),
    ("ASSET_SUB_CATEGORY", "STANDARD", "Standard", 1, True, None),
    ("ASSET_SUB_CATEGORY", "APPLICATION", "Application", 2, True, None),
    ("ASSET_SUB_CATEGORY", "DEVICE", "Device", 3, True, None),
    ("CRITICALITY_CLASS", "A", "Class A", 1, True, None),
    ("CRITICALITY_CLASS", "B", "Class B", 2, True, None),
    ("CRITICALITY_CLASS", "C", "Class C", 3, True, None),
    ("CRITICALITY_CLASS", "D", "Class D", 4, True, None),
    ("ASSET_NATURE", "DIGITAL", "Digital", 1, True, None),
    ("ASSET_NATURE", "PHYSICAL", "Physical", 2, True, None),
    ("ASSET_NATURE", "HYBRID", "Hybrid", 3, True, None),
)


def _seed_lookup_data() -> None:
    bind = op.get_bind()

    for lookup_key, description, is_active in LOOKUP_MASTER_SEEDS:
        bind.execute(
            sa.text(
                """
                INSERT INTO public.lookup_master (lookup_key, description, is_active, created_by)
                VALUES (:lookup_key, :description, :is_active, 'alembic')
                ON CONFLICT (lookup_key) DO UPDATE
                SET description = EXCLUDED.description,
                    is_active = EXCLUDED.is_active,
                    modified_by = 'alembic',
                    modified_dt = now()
                """
            ),
            {
                "lookup_key": lookup_key,
                "description": description,
                "is_active": is_active,
            },
        )

    for lookup_key, code, display_name, sort_order, is_active, metadata_json in LOOKUP_VALUE_SEEDS:
        bind.execute(
            sa.text(
                """
                INSERT INTO public.lookup_value (
                    lookup_id,
                    code,
                    display_name,
                    sort_order,
                    is_active,
                    metadata_json,
                    created_by
                )
                SELECT
                    lm.id,
                    :code,
                    :display_name,
                    :sort_order,
                    :is_active,
                    CAST(:metadata_json AS JSONB),
                    'alembic'
                FROM public.lookup_master lm
                WHERE lm.lookup_key = :lookup_key
                ON CONFLICT (lookup_id, code) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    sort_order = EXCLUDED.sort_order,
                    is_active = EXCLUDED.is_active,
                    metadata_json = EXCLUDED.metadata_json,
                    modified_by = 'alembic',
                    modified_dt = now()
                """
            ),
            {
                "lookup_key": lookup_key,
                "code": code,
                "display_name": display_name,
                "sort_order": sort_order,
                "is_active": is_active,
                "metadata_json": metadata_json,
            },
        )


def _recreate_asset_lookup_trigger() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.validate_asset_lookups() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_ok BOOLEAN;
        BEGIN
            SELECT TRUE INTO v_ok
            FROM lookup_master lm
            JOIN lookup_value lv ON lv.lookup_id = lm.id
            WHERE lm.lookup_key = 'ASSET_CLASS'
              AND lm.is_active = TRUE
              AND lv.is_active = TRUE
              AND lv.code = NEW.asset_class
            LIMIT 1;
            IF v_ok IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'Invalid asset_basic_info.asset_class: "%" (not defined in ASSET_CLASS lookup)', NEW.asset_class;
            END IF;

            SELECT TRUE INTO v_ok
            FROM lookup_master lm
            JOIN lookup_value lv ON lv.lookup_id = lm.id
            WHERE lm.lookup_key = 'ASSET_CATEGORY'
              AND lm.is_active = TRUE
              AND lv.is_active = TRUE
              AND lv.code = NEW.asset_category
            LIMIT 1;
            IF v_ok IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'Invalid asset_basic_info.asset_category: "%" (not defined in ASSET_CATEGORY lookup)', NEW.asset_category;
            END IF;

            SELECT TRUE INTO v_ok
            FROM lookup_master lm
            JOIN lookup_value lv ON lv.lookup_id = lm.id
            WHERE lm.lookup_key = 'ASSET_SUB_CATEGORY'
              AND lm.is_active = TRUE
              AND lv.is_active = TRUE
              AND lv.code = NEW.asset_sub_category
            LIMIT 1;
            IF v_ok IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'Invalid asset_basic_info.asset_sub_category: "%" (not defined in ASSET_SUB_CATEGORY lookup)', NEW.asset_sub_category;
            END IF;

            IF NEW.asset_type IS NOT NULL AND NEW.asset_type <> '' THEN
                SELECT TRUE INTO v_ok
                FROM lookup_master lm
                JOIN lookup_value lv ON lv.lookup_id = lm.id
                WHERE lm.lookup_key = 'ASSET_TYPE'
                  AND lm.is_active = TRUE
                  AND lv.is_active = TRUE
                  AND lv.code = NEW.asset_type
                LIMIT 1;
                IF v_ok IS DISTINCT FROM TRUE THEN
                    RAISE EXCEPTION 'Invalid asset_basic_info.asset_type: "%" (not defined in ASSET_TYPE lookup)', NEW.asset_type;
                END IF;
            END IF;

            SELECT TRUE INTO v_ok
            FROM lookup_master lm
            JOIN lookup_value lv ON lv.lookup_id = lm.id
            WHERE lm.lookup_key = 'CRITICALITY_CLASS'
              AND lm.is_active = TRUE
              AND lv.is_active = TRUE
              AND lv.code = NEW.asset_criticality
            LIMIT 1;
            IF v_ok IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'Invalid asset_basic_info.asset_criticality: "%" (not defined in CRITICALITY_CLASS lookup)', NEW.asset_criticality;
            END IF;

            SELECT TRUE INTO v_ok
            FROM lookup_master lm
            JOIN lookup_value lv ON lv.lookup_id = lm.id
            WHERE lm.lookup_key = 'ASSET_NATURE'
              AND lm.is_active = TRUE
              AND lv.is_active = TRUE
              AND lv.code = NEW.asset_nature
            LIMIT 1;
            IF v_ok IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'Invalid asset_basic_info.asset_nature: "%" (not defined in ASSET_NATURE lookup)', NEW.asset_nature;
            END IF;

            IF NEW.asset_currency IS NOT NULL AND NEW.asset_currency <> '' THEN
                SELECT TRUE INTO v_ok
                FROM lookup_master lm
                JOIN lookup_value lv ON lv.lookup_id = lm.id
                WHERE lm.lookup_key = 'CURRENCY'
                  AND lm.is_active = TRUE
                  AND lv.is_active = TRUE
                  AND lv.code = NEW.asset_currency
                LIMIT 1;
                IF v_ok IS DISTINCT FROM TRUE THEN
                    RAISE EXCEPTION 'Invalid asset_basic_info.asset_currency: "%" (not defined in CURRENCY lookup)', NEW.asset_currency;
                END IF;
            END IF;

            IF NEW.asset_status IS NOT NULL AND NEW.asset_status <> '' THEN
                SELECT TRUE INTO v_ok
                FROM lookup_master lm
                JOIN lookup_value lv ON lv.lookup_id = lm.id
                WHERE lm.lookup_key = 'ASSET_STATUS'
                  AND lm.is_active = TRUE
                  AND lv.is_active = TRUE
                  AND lv.code = NEW.asset_status
                LIMIT 1;
                IF v_ok IS DISTINCT FROM TRUE THEN
                    RAISE EXCEPTION 'Invalid asset_basic_info.asset_status: "%" (not defined in ASSET_STATUS lookup)', NEW.asset_status;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_validate_asset_lookups ON public.asset_basic_info")
    op.execute(
        """
        CREATE TRIGGER trg_validate_asset_lookups
        BEFORE INSERT OR UPDATE
        ON public.asset_basic_info
        FOR EACH ROW
        EXECUTE FUNCTION public.validate_asset_lookups()
        """
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute("ALTER TABLE public.lookup_value ADD COLUMN IF NOT EXISTS metadata_json JSONB")

    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS legacy_id VARCHAR(30)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS qr_barcode VARCHAR(50)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS rfid_tag VARCHAR(30)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_class VARCHAR(50)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_category VARCHAR(50)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_sub_category VARCHAR(50)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_nature VARCHAR(50)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS tags JSONB")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS short_description VARCHAR(40)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS tag_number VARCHAR(20)")

    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_type DROP NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_asset_class ON public.asset_basic_info USING btree (asset_class)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_asset_category ON public.asset_basic_info USING btree (asset_category)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_asset_sub_category ON public.asset_basic_info USING btree (asset_sub_category)")

    # Disable the legacy lookup trigger before remapping existing asset values.
    # The pre-existing trigger still validates against ASSET_CRITICALITY and would
    # reject the new enterprise A/B/C/D values during backfill.
    op.execute("DROP TRIGGER IF EXISTS trg_validate_asset_lookups ON public.asset_basic_info")

    _seed_lookup_data()

    op.execute(
        """
        UPDATE public.asset_basic_info
        SET asset_code = 'AST-' || upper(substr(replace(asset_id::text, '-', ''), 1, 12))
        WHERE asset_code IS NULL OR btrim(asset_code) = ''
        """
    )
    op.execute(
        """
        UPDATE public.asset_basic_info
        SET asset_name = left(
            COALESCE(
                NULLIF(btrim(asset_name), ''),
                NULLIF(btrim(asset_code), ''),
                'Asset ' || upper(substr(replace(asset_id::text, '-', ''), 1, 8))
            ),
            250
        )
        WHERE asset_name IS NULL OR btrim(asset_name) = ''
        """
    )
    op.execute(
        """
        UPDATE public.asset_basic_info
        SET asset_description = left(
            COALESCE(
                NULLIF(btrim(asset_description), ''),
                NULLIF(btrim(asset_name), ''),
                NULLIF(btrim(asset_code), ''),
                'Enterprise asset record'
            ),
            500
        )
        WHERE asset_description IS NULL OR btrim(asset_description) = ''
        """
    )
    op.execute(
        """
        UPDATE public.asset_basic_info
        SET short_description = left(
            COALESCE(
                NULLIF(btrim(short_description), ''),
                NULLIF(btrim(asset_name), ''),
                NULLIF(btrim(asset_code), ''),
                'Asset'
            ),
            40
        )
        WHERE short_description IS NULL OR btrim(short_description) = ''
        """
    )
    op.execute(
        """
        UPDATE public.asset_basic_info
        SET asset_owner = left(
            COALESCE(NULLIF(btrim(asset_owner), ''), 'UNASSIGNED'),
            150
        )
        WHERE asset_owner IS NULL OR btrim(asset_owner) = ''
        """
    )
    op.execute(
        """
        UPDATE public.asset_basic_info
        SET asset_class = CASE
            WHEN upper(COALESCE(asset_type, '')) = 'SOFTWARE' THEN 'SOFTWARE'
            WHEN upper(COALESCE(asset_type, '')) = 'HARDWARE' THEN 'HARDWARE'
            ELSE 'GENERAL'
        END
        WHERE asset_class IS NULL OR btrim(asset_class) = ''
        """
    )
    op.execute(
        """
        UPDATE public.asset_basic_info
        SET asset_category = CASE
            WHEN upper(COALESCE(asset_type, '')) = 'SOFTWARE' THEN 'SOFTWARE'
            WHEN upper(COALESCE(asset_type, '')) = 'HARDWARE' THEN 'HARDWARE'
            ELSE 'GENERAL'
        END
        WHERE asset_category IS NULL OR btrim(asset_category) = ''
        """
    )
    op.execute(
        """
        UPDATE public.asset_basic_info
        SET asset_sub_category = CASE
            WHEN upper(COALESCE(asset_type, '')) = 'SOFTWARE' THEN 'APPLICATION'
            WHEN upper(COALESCE(asset_type, '')) = 'HARDWARE' THEN 'DEVICE'
            ELSE 'STANDARD'
        END
        WHERE asset_sub_category IS NULL OR btrim(asset_sub_category) = ''
        """
    )
    op.execute(
        """
        UPDATE public.asset_basic_info
        SET asset_nature = CASE
            WHEN upper(COALESCE(asset_type, '')) = 'SOFTWARE' THEN 'DIGITAL'
            WHEN upper(COALESCE(asset_type, '')) = 'HARDWARE' THEN 'PHYSICAL'
            ELSE 'HYBRID'
        END
        WHERE asset_nature IS NULL OR btrim(asset_nature) = ''
        """
    )
    op.execute(
        """
        UPDATE public.asset_basic_info
        SET asset_criticality = CASE
            WHEN upper(COALESCE(asset_criticality, '')) IN ('A', 'CLASS A', 'CRITICAL', 'HIGH', 'VERY HIGH') THEN 'A'
            WHEN upper(COALESCE(asset_criticality, '')) IN ('B', 'CLASS B', 'MEDIUM') THEN 'B'
            WHEN upper(COALESCE(asset_criticality, '')) IN ('C', 'CLASS C') THEN 'C'
            WHEN upper(COALESCE(asset_criticality, '')) IN ('D', 'CLASS D', 'LOW') THEN 'D'
            ELSE 'C'
        END
        WHERE asset_criticality IS NULL
           OR btrim(asset_criticality) = ''
           OR upper(asset_criticality) NOT IN ('A', 'B', 'C', 'D')
        """
    )

    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_code SET NOT NULL")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_description SET NOT NULL")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN short_description SET NOT NULL")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_owner SET NOT NULL")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_class SET NOT NULL")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_category SET NOT NULL")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_sub_category SET NOT NULL")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_nature SET NOT NULL")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_criticality SET NOT NULL")

    _recreate_asset_lookup_trigger()


def downgrade() -> None:
    pass
