"""Enterprise schema baseline.

Revision ID: 20260402_0001
Revises:
Create Date: 2026-04-02 13:15:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260402_0001"
down_revision = None
branch_labels = None
depends_on = None

LOOKUP_MASTER_SEEDS = (
    ("ORG_TYPE", "Organization types", True),
    ("COUNTRY", "Allowed values for org_structure.country", True),
    ("ORG_STATUS", "Allowed values for org_structure.status", True),
    ("SUPPLIER_TYPE", "Types of suppliers", True),
    ("ASSET_TYPE", "Types of assets", True),
    ("ASSET_STATUS", "Asset lifecycle status", True),
    ("ASSET_CRITICALITY", "Allowed values for asset criticality", True),
    ("CURRENCY", "Supported currencies", True),
)

LOOKUP_VALUE_SEEDS = (
    ("COUNTRY", "IN", "India", 1, True),
    ("COUNTRY", "US", "US", 2, True),
    ("COUNTRY", "UK", "United Kingdom", 3, True),
    ("ORG_STATUS", "ACTIVE", "Active", 1, True),
    ("ORG_STATUS", "INACTIVE", "Inactive", 2, True),
    ("ORG_STATUS", "MERGED", "Merged", 3, True),
    ("ORG_STATUS", "CLOSED", "Closed", 4, True),
    ("ORG_STATUS", "UNDER_CONSTRUCTION", "Under Construction", 5, True),
    ("ORG_TYPE", "GROUP", "Group", 1, True),
    ("ORG_TYPE", "COMPANY", "Company", 2, True),
    ("ORG_TYPE", "DIVISION", "Division", 3, True),
    ("ORG_TYPE", "PLANT", "Plant", 4, True),
    ("ORG_TYPE", "SECTION", "Section", 5, True),
    ("ORG_TYPE", "DEPARTMENT", "Department", 6, True),
    ("ORG_TYPE", "REGION", "Region", 7, False),
    ("SUPPLIER_TYPE", "HARDWARE", "hardware supplier", 1, True),
    ("SUPPLIER_TYPE", "SOFTWARE", "software supplier", 2, True),
    ("ASSET_TYPE", "HARDWARE", "hardware", 2, True),
    ("ASSET_TYPE", "SOFTWARE", "Software", 1, True),
    ("ASSET_STATUS", "ACTIVE", "Active", 0, True),
    ("ASSET_STATUS", "RETIRED", "Retired", 0, True),
    ("ASSET_STATUS", "DECOMMISSIONED", "Decommissioned", 0, True),
    ("ASSET_STATUS", "DISPOSED", "Disposed", 0, True),
    ("ASSET_STATUS", "ARCHIVED", "Archived", 0, True),
    ("CURRENCY", "INR", "Indian Rupee", 0, True),
    ("CURRENCY", "USD", "US Dollar", 0, True),
    ("CURRENCY", "GBP", "British Pound", 0, True),
    ("ASSET_CRITICALITY", "CRITICAL", "Critical", 0, False),
    ("ASSET_CRITICALITY", "HIGH", "High", 1, True),
    ("ASSET_CRITICALITY", "LOW", "Low", 0, False),
    ("ASSET_CRITICALITY", "MEDIUM", "Medium", 0, True),
)


def _constraint_exists(name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM pg_constraint WHERE conname = :name"),
            {"name": name},
        ).scalar()
    )


def _ensure_tables() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.lookup_master (
            id SERIAL NOT NULL,
            lookup_key VARCHAR(50) NOT NULL,
            description VARCHAR(250),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by VARCHAR(150),
            created_dt TIMESTAMPTZ DEFAULT now(),
            modified_by VARCHAR(150),
            modified_dt TIMESTAMPTZ DEFAULT now(),
            CONSTRAINT lookup_master_pkey PRIMARY KEY (id),
            CONSTRAINT lookup_master_lookup_key_key UNIQUE (lookup_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.lookup_value (
            id SERIAL NOT NULL,
            lookup_id INTEGER NOT NULL,
            code VARCHAR(50) NOT NULL,
            display_name VARCHAR(150) NOT NULL,
            sort_order INTEGER DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by VARCHAR(150),
            created_dt TIMESTAMPTZ DEFAULT now(),
            modified_by VARCHAR(150),
            modified_dt TIMESTAMPTZ DEFAULT now(),
            CONSTRAINT lookup_value_pkey PRIMARY KEY (id),
            CONSTRAINT lookup_value_lookup_id_code_key UNIQUE (lookup_id, code),
            CONSTRAINT lookup_value_lookup_id_fkey FOREIGN KEY (lookup_id)
                REFERENCES public.lookup_master(id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.org_structure (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            parent_id UUID,
            name VARCHAR(250) NOT NULL,
            type VARCHAR(50) NOT NULL,
            code VARCHAR(25) NOT NULL,
            status VARCHAR(50) NOT NULL,
            address VARCHAR(250),
            city VARCHAR(50),
            state VARCHAR(50),
            country VARCHAR(10),
            long DOUBLE PRECISION,
            lat DOUBLE PRECISION,
            created_by VARCHAR(150),
            created_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            modified_by VARCHAR(150),
            modified_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at TIMESTAMP WITHOUT TIME ZONE,
            deleted_by UUID,
            CONSTRAINT org_structure_pkey PRIMARY KEY (id),
            CONSTRAINT chk_no_self_parent CHECK ((parent_id IS NULL) OR (parent_id <> id)),
            CONSTRAINT uq_org_code UNIQUE (code),
            CONSTRAINT fk_org_structure_parent FOREIGN KEY (parent_id)
                REFERENCES public.org_structure(id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.supplier (
            supplier_id UUID NOT NULL DEFAULT gen_random_uuid(),
            supplier_name VARCHAR(250) NOT NULL,
            supplier_type VARCHAR(50) NOT NULL,
            supplier_add1 VARCHAR(250),
            supplier_add2 VARCHAR(250),
            supplier_city VARCHAR(150),
            supplier_pincode VARCHAR(10),
            supplier_state VARCHAR(150),
            supplier_country VARCHAR(10),
            contact_name VARCHAR(150),
            contact_email VARCHAR(150),
            contact_phone VARCHAR(50),
            enrolled_dt TIMESTAMPTZ,
            created_by VARCHAR(150),
            created_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            modified_by VARCHAR(150),
            modified_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT supplier_pkey PRIMARY KEY (supplier_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.asset_basic_info (
            asset_id UUID NOT NULL DEFAULT gen_random_uuid(),
            org_node_id UUID NOT NULL,
            asset_type VARCHAR(50) NOT NULL,
            asset_name VARCHAR(250) NOT NULL,
            asset_serial_no VARCHAR(100),
            asset_code VARCHAR(100),
            supplier_id UUID,
            manufacturer VARCHAR(200),
            model VARCHAR(100),
            asset_description VARCHAR(500),
            asset_version VARCHAR(25),
            asset_owner VARCHAR(150),
            asset_commission_dt TIMESTAMPTZ,
            asset_purchase_dt TIMESTAMPTZ,
            asset_purchase_ref VARCHAR(50),
            warranty_period INTEGER,
            asset_value DOUBLE PRECISION,
            asset_currency VARCHAR(10),
            asset_release_url VARCHAR(250),
            asset_criticality VARCHAR(50),
            asset_status VARCHAR(50),
            created_by VARCHAR(150),
            created_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            modified_by VARCHAR(150),
            modified_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT asset_basic_info_pkey PRIMARY KEY (asset_id),
            CONSTRAINT uq_asset_code UNIQUE (asset_code),
            CONSTRAINT uq_asset_serial_no UNIQUE (asset_serial_no),
            CONSTRAINT fk_asset_org FOREIGN KEY (org_node_id)
                REFERENCES public.org_structure(id) ON DELETE RESTRICT,
            CONSTRAINT fk_asset_supplier FOREIGN KEY (supplier_id)
                REFERENCES public.supplier(supplier_id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.audit_log (
            audit_id BIGSERIAL NOT NULL,
            table_name TEXT NOT NULL,
            operation_type VARCHAR(10) NOT NULL,
            record_pk JSONB,
            old_data JSONB,
            new_data JSONB,
            changed_columns JSONB,
            changed_by VARCHAR(150),
            changed_at TIMESTAMPTZ DEFAULT now(),
            application_name TEXT,
            client_ip TEXT,
            CONSTRAINT audit_log_pkey PRIMARY KEY (audit_id)
        )
        """
    )


def _ensure_columns_and_defaults() -> None:
    op.execute("ALTER TABLE public.lookup_master ADD COLUMN IF NOT EXISTS description VARCHAR(250)")
    op.execute("ALTER TABLE public.lookup_master ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("ALTER TABLE public.lookup_master ADD COLUMN IF NOT EXISTS created_by VARCHAR(150)")
    op.execute("ALTER TABLE public.lookup_master ADD COLUMN IF NOT EXISTS created_dt TIMESTAMPTZ DEFAULT now()")
    op.execute("ALTER TABLE public.lookup_master ADD COLUMN IF NOT EXISTS modified_by VARCHAR(150)")
    op.execute("ALTER TABLE public.lookup_master ADD COLUMN IF NOT EXISTS modified_dt TIMESTAMPTZ DEFAULT now()")
    op.execute("ALTER TABLE public.lookup_master ALTER COLUMN lookup_key TYPE VARCHAR(50)")
    op.execute("ALTER TABLE public.lookup_master ALTER COLUMN lookup_key SET NOT NULL")
    op.execute("ALTER TABLE public.lookup_master ALTER COLUMN is_active SET DEFAULT TRUE")
    op.execute("ALTER TABLE public.lookup_master ALTER COLUMN created_dt SET DEFAULT now()")
    op.execute("ALTER TABLE public.lookup_master ALTER COLUMN modified_dt SET DEFAULT now()")

    op.execute("ALTER TABLE public.lookup_value ADD COLUMN IF NOT EXISTS lookup_id INTEGER")
    op.execute("ALTER TABLE public.lookup_value ADD COLUMN IF NOT EXISTS code VARCHAR(50)")
    op.execute("ALTER TABLE public.lookup_value ADD COLUMN IF NOT EXISTS display_name VARCHAR(150)")
    op.execute("ALTER TABLE public.lookup_value ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0")
    op.execute("ALTER TABLE public.lookup_value ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("ALTER TABLE public.lookup_value ADD COLUMN IF NOT EXISTS created_by VARCHAR(150)")
    op.execute("ALTER TABLE public.lookup_value ADD COLUMN IF NOT EXISTS created_dt TIMESTAMPTZ DEFAULT now()")
    op.execute("ALTER TABLE public.lookup_value ADD COLUMN IF NOT EXISTS modified_by VARCHAR(150)")
    op.execute("ALTER TABLE public.lookup_value ADD COLUMN IF NOT EXISTS modified_dt TIMESTAMPTZ DEFAULT now()")
    op.execute("ALTER TABLE public.lookup_value ALTER COLUMN lookup_id SET NOT NULL")
    op.execute("ALTER TABLE public.lookup_value ALTER COLUMN code TYPE VARCHAR(50)")
    op.execute("ALTER TABLE public.lookup_value ALTER COLUMN code SET NOT NULL")
    op.execute("ALTER TABLE public.lookup_value ALTER COLUMN display_name TYPE VARCHAR(150)")
    op.execute("ALTER TABLE public.lookup_value ALTER COLUMN display_name SET NOT NULL")
    op.execute("ALTER TABLE public.lookup_value ALTER COLUMN sort_order SET DEFAULT 0")
    op.execute("ALTER TABLE public.lookup_value ALTER COLUMN is_active SET DEFAULT TRUE")
    op.execute("ALTER TABLE public.lookup_value ALTER COLUMN created_dt SET DEFAULT now()")
    op.execute("ALTER TABLE public.lookup_value ALTER COLUMN modified_dt SET DEFAULT now()")

    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS parent_id UUID")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS name VARCHAR(250)")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS type VARCHAR(50)")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS code VARCHAR(25)")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS status VARCHAR(50)")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS address VARCHAR(250)")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS city VARCHAR(50)")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS state VARCHAR(50)")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS country VARCHAR(10)")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS long DOUBLE PRECISION")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS created_by VARCHAR(150)")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS created_dt TIMESTAMPTZ NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS modified_by VARCHAR(150)")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS modified_dt TIMESTAMPTZ NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITHOUT TIME ZONE")
    op.execute("ALTER TABLE public.org_structure ADD COLUMN IF NOT EXISTS deleted_by UUID")

    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS supplier_name VARCHAR(250)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS supplier_type VARCHAR(50)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS supplier_add1 VARCHAR(250)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS supplier_add2 VARCHAR(250)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS supplier_city VARCHAR(150)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS supplier_pincode VARCHAR(10)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS supplier_state VARCHAR(150)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS supplier_country VARCHAR(10)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS contact_name VARCHAR(150)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS contact_email VARCHAR(150)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(50)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS enrolled_dt TIMESTAMPTZ")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS created_by VARCHAR(150)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS created_dt TIMESTAMPTZ NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS modified_by VARCHAR(150)")
    op.execute("ALTER TABLE public.supplier ADD COLUMN IF NOT EXISTS modified_dt TIMESTAMPTZ NOT NULL DEFAULT now()")

    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS org_node_id UUID")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_type VARCHAR(50)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_name VARCHAR(250)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_serial_no VARCHAR(100)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_code VARCHAR(100)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS supplier_id UUID")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS manufacturer VARCHAR(200)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS model VARCHAR(100)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_description VARCHAR(500)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_version VARCHAR(25)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_owner VARCHAR(150)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_commission_dt TIMESTAMPTZ")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_purchase_dt TIMESTAMPTZ")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_purchase_ref VARCHAR(50)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS warranty_period INTEGER")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_value DOUBLE PRECISION")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_currency VARCHAR(10)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_release_url VARCHAR(250)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_criticality VARCHAR(50)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS asset_status VARCHAR(50)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS created_by VARCHAR(150)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS created_dt TIMESTAMPTZ NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS modified_by VARCHAR(150)")
    op.execute("ALTER TABLE public.asset_basic_info ADD COLUMN IF NOT EXISTS modified_dt TIMESTAMPTZ NOT NULL DEFAULT now()")

    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS table_name TEXT")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS operation_type VARCHAR(10)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS record_pk JSONB")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS old_data JSONB")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS new_data JSONB")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS changed_columns JSONB")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS changed_by VARCHAR(150)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS changed_at TIMESTAMPTZ DEFAULT now()")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS application_name TEXT")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS client_ip TEXT")

    op.execute("ALTER TABLE public.org_structure ALTER COLUMN id SET DEFAULT gen_random_uuid()")
    op.execute("ALTER TABLE public.supplier ALTER COLUMN supplier_id SET DEFAULT gen_random_uuid()")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_id SET DEFAULT gen_random_uuid()")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM public.org_structure
                WHERE code IS NULL OR btrim(code) = ''
            ) THEN
                RAISE EXCEPTION 'Cannot enforce org_structure.code NOT NULL because existing rows contain NULL or blank codes';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM public.org_structure
                WHERE char_length(code) > 25
            ) THEN
                RAISE EXCEPTION 'Cannot enforce org_structure.code VARCHAR(25) because existing rows exceed 25 characters';
            END IF;
        END
        $$;
        """
    )
    op.execute("ALTER TABLE public.org_structure ALTER COLUMN code TYPE VARCHAR(25)")
    op.execute("ALTER TABLE public.org_structure ALTER COLUMN code SET NOT NULL")
    op.execute("ALTER TABLE public.org_structure ALTER COLUMN name SET NOT NULL")
    op.execute("ALTER TABLE public.org_structure ALTER COLUMN type SET NOT NULL")
    op.execute("ALTER TABLE public.org_structure ALTER COLUMN status SET NOT NULL")
    op.execute("ALTER TABLE public.org_structure ALTER COLUMN created_dt SET DEFAULT now()")
    op.execute("ALTER TABLE public.org_structure ALTER COLUMN modified_dt SET DEFAULT now()")
    op.execute("ALTER TABLE public.org_structure ALTER COLUMN is_deleted SET DEFAULT FALSE")
    op.execute("ALTER TABLE public.supplier ALTER COLUMN supplier_name SET NOT NULL")
    op.execute("ALTER TABLE public.supplier ALTER COLUMN supplier_type SET NOT NULL")
    op.execute("ALTER TABLE public.supplier ALTER COLUMN created_dt SET DEFAULT now()")
    op.execute("ALTER TABLE public.supplier ALTER COLUMN modified_dt SET DEFAULT now()")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN org_node_id SET NOT NULL")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_type SET NOT NULL")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN asset_name SET NOT NULL")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN created_dt SET DEFAULT now()")
    op.execute("ALTER TABLE public.asset_basic_info ALTER COLUMN modified_dt SET DEFAULT now()")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN table_name SET NOT NULL")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN operation_type SET NOT NULL")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN changed_at SET DEFAULT now()")


def _ensure_constraints_and_indexes() -> None:
    if not _constraint_exists("lookup_master_lookup_key_key"):
        op.execute("ALTER TABLE public.lookup_master ADD CONSTRAINT lookup_master_lookup_key_key UNIQUE (lookup_key)")
    if not _constraint_exists("lookup_value_lookup_id_code_key"):
        op.execute(
            "ALTER TABLE public.lookup_value ADD CONSTRAINT lookup_value_lookup_id_code_key UNIQUE (lookup_id, code)"
        )
    if not _constraint_exists("lookup_value_lookup_id_fkey"):
        op.execute(
            "ALTER TABLE public.lookup_value ADD CONSTRAINT lookup_value_lookup_id_fkey "
            "FOREIGN KEY (lookup_id) REFERENCES public.lookup_master(id) ON DELETE RESTRICT"
        )
    if not _constraint_exists("chk_no_self_parent"):
        op.execute(
            "ALTER TABLE public.org_structure ADD CONSTRAINT chk_no_self_parent "
            "CHECK ((parent_id IS NULL) OR (parent_id <> id))"
        )
    if not _constraint_exists("uq_org_code"):
        op.execute("ALTER TABLE public.org_structure ADD CONSTRAINT uq_org_code UNIQUE (code)")
    if not _constraint_exists("fk_org_structure_parent"):
        op.execute(
            "ALTER TABLE public.org_structure ADD CONSTRAINT fk_org_structure_parent "
            "FOREIGN KEY (parent_id) REFERENCES public.org_structure(id) ON DELETE RESTRICT"
        )
    if not _constraint_exists("uq_asset_code"):
        op.execute("ALTER TABLE public.asset_basic_info ADD CONSTRAINT uq_asset_code UNIQUE (asset_code)")
    if not _constraint_exists("uq_asset_serial_no"):
        op.execute("ALTER TABLE public.asset_basic_info ADD CONSTRAINT uq_asset_serial_no UNIQUE (asset_serial_no)")
    if not _constraint_exists("fk_asset_org"):
        op.execute(
            "ALTER TABLE public.asset_basic_info ADD CONSTRAINT fk_asset_org "
            "FOREIGN KEY (org_node_id) REFERENCES public.org_structure(id) ON DELETE RESTRICT"
        )
    if not _constraint_exists("fk_asset_supplier"):
        op.execute(
            "ALTER TABLE public.asset_basic_info ADD CONSTRAINT fk_asset_supplier "
            "FOREIGN KEY (supplier_id) REFERENCES public.supplier(supplier_id) ON DELETE SET NULL"
        )

    op.execute("CREATE INDEX IF NOT EXISTS idx_asset_code ON public.asset_basic_info USING btree (asset_code)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_asset_org_node ON public.asset_basic_info USING btree (org_node_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_asset_status ON public.asset_basic_info USING btree (asset_status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_asset_supplier ON public.asset_basic_info USING btree (supplier_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_asset_type ON public.asset_basic_info USING btree (asset_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_changed_at ON public.audit_log USING btree (changed_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_operation ON public.audit_log USING btree (operation_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_record_pk ON public.audit_log USING gin (record_pk)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_table ON public.audit_log USING btree (table_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_org_structure_code ON public.org_structure USING btree (code)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_org_structure_parent_id ON public.org_structure USING btree (parent_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_org_structure_status ON public.org_structure USING btree (status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_org_structure_type ON public.org_structure USING btree (type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_supplier_country ON public.supplier USING btree (supplier_country)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_supplier_name ON public.supplier USING btree (supplier_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_supplier_type ON public.supplier USING btree (supplier_type)")


def _create_functions_and_triggers() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_org_cycle() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
          v_id UUID;
        BEGIN
          IF NEW.parent_id IS NULL THEN
            RETURN NEW;
          END IF;
          v_id := NEW.parent_id;
          WHILE v_id IS NOT NULL LOOP
            IF v_id = NEW.id THEN
              RAISE EXCEPTION 'Invalid hierarchy: circular parenting detected';
            END IF;
            SELECT parent_id INTO v_id FROM org_structure WHERE id = v_id;
          END LOOP;
          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.set_modified_dt() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          NEW.modified_dt := now();
          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.set_supplier_modified_dt() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          NEW.modified_dt := now();
          RETURN NEW;
        END;
        $$;
        """
    )
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
            WHERE lm.lookup_key = 'ASSET_TYPE'
              AND lm.is_active = TRUE
              AND lv.is_active = TRUE
              AND lv.code = NEW.asset_type
            LIMIT 1;
            IF v_ok IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'Invalid asset_basic_info.asset_type: "%" (not defined in ASSET_TYPE lookup)', NEW.asset_type;
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

            IF NEW.asset_criticality IS NOT NULL AND NEW.asset_criticality <> '' THEN
                SELECT TRUE INTO v_ok
                FROM lookup_master lm
                JOIN lookup_value lv ON lv.lookup_id = lm.id
                WHERE lm.lookup_key = 'ASSET_CRITICALITY'
                  AND lm.is_active = TRUE
                  AND lv.is_active = TRUE
                  AND lv.code = NEW.asset_criticality
                LIMIT 1;
                IF v_ok IS DISTINCT FROM TRUE THEN
                    RAISE EXCEPTION 'Invalid asset_basic_info.asset_criticality: "%" (not defined in ASSET_CRITICALITY lookup)', NEW.asset_criticality;
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
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.validate_org_structure_lookups() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
          v_ok BOOLEAN;
        BEGIN
          SELECT TRUE INTO v_ok
          FROM lookup_master lm
          JOIN lookup_value lv ON lv.lookup_id = lm.id
          WHERE lm.lookup_key = 'ORG_TYPE'
            AND lm.is_active = TRUE
            AND lv.is_active = TRUE
            AND lv.code = NEW.type
          LIMIT 1;
          IF v_ok IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Invalid org_structure.type: "%" (not defined in ORG_TYPE lookup)', NEW.type;
          END IF;

          SELECT TRUE INTO v_ok
          FROM lookup_master lm
          JOIN lookup_value lv ON lv.lookup_id = lm.id
          WHERE lm.lookup_key = 'ORG_STATUS'
            AND lm.is_active = TRUE
            AND lv.is_active = TRUE
            AND lv.code = NEW.status
          LIMIT 1;
          IF v_ok IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Invalid org_structure.status: "%" (not defined in ORG_STATUS lookup)', NEW.status;
          END IF;

          IF NEW.country IS NOT NULL AND NEW.country <> '' THEN
            SELECT TRUE INTO v_ok
            FROM lookup_master lm
            JOIN lookup_value lv ON lv.lookup_id = lm.id
            WHERE lm.lookup_key = 'COUNTRY'
              AND lm.is_active = TRUE
              AND lv.is_active = TRUE
              AND lv.code = NEW.country
            LIMIT 1;
            IF v_ok IS DISTINCT FROM TRUE THEN
              RAISE EXCEPTION 'Invalid org_structure.country: "%" (not defined in COUNTRY lookup)', NEW.country;
            END IF;
          END IF;

          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.validate_supplier_lookups() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
          v_ok BOOLEAN;
        BEGIN
          SELECT TRUE INTO v_ok
          FROM lookup_master lm
          JOIN lookup_value lv ON lv.lookup_id = lm.id
          WHERE lm.lookup_key = 'SUPPLIER_TYPE'
            AND lm.is_active = TRUE
            AND lv.is_active = TRUE
            AND lv.code = NEW.supplier_type
          LIMIT 1;
          IF v_ok IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Invalid supplier.supplier_type: "%" (not defined in SUPPLIER_TYPE lookup)', NEW.supplier_type;
          END IF;

          IF NEW.supplier_country IS NOT NULL AND NEW.supplier_country <> '' THEN
            SELECT TRUE INTO v_ok
            FROM lookup_master lm
            JOIN lookup_value lv ON lv.lookup_id = lm.id
            WHERE lm.lookup_key = 'COUNTRY'
              AND lm.is_active = TRUE
              AND lv.is_active = TRUE
              AND lv.code = NEW.supplier_country
            LIMIT 1;
            IF v_ok IS DISTINCT FROM TRUE THEN
              RAISE EXCEPTION 'Invalid supplier.supplier_country: "%" (not defined in COUNTRY lookup)', NEW.supplier_country;
            END IF;
          END IF;

          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_org_cycle ON public.org_structure")
    op.execute("DROP TRIGGER IF EXISTS trg_set_asset_modified_dt ON public.asset_basic_info")
    op.execute("DROP TRIGGER IF EXISTS trg_set_modified_dt ON public.org_structure")
    op.execute("DROP TRIGGER IF EXISTS trg_set_supplier_modified_dt ON public.supplier")
    op.execute("DROP TRIGGER IF EXISTS trg_validate_asset_lookups ON public.asset_basic_info")
    op.execute("DROP TRIGGER IF EXISTS trg_validate_org_structure_lookups ON public.org_structure")
    op.execute("DROP TRIGGER IF EXISTS trg_validate_supplier_lookups ON public.supplier")
    op.execute(
        "CREATE TRIGGER trg_prevent_org_cycle BEFORE INSERT OR UPDATE OF parent_id ON public.org_structure "
        "FOR EACH ROW EXECUTE FUNCTION public.prevent_org_cycle()"
    )
    op.execute(
        "CREATE TRIGGER trg_set_asset_modified_dt BEFORE UPDATE ON public.asset_basic_info "
        "FOR EACH ROW EXECUTE FUNCTION public.set_modified_dt()"
    )
    op.execute(
        "CREATE TRIGGER trg_set_modified_dt BEFORE UPDATE ON public.org_structure "
        "FOR EACH ROW EXECUTE FUNCTION public.set_modified_dt()"
    )
    op.execute(
        "CREATE TRIGGER trg_set_supplier_modified_dt BEFORE UPDATE ON public.supplier "
        "FOR EACH ROW EXECUTE FUNCTION public.set_supplier_modified_dt()"
    )
    op.execute(
        "CREATE TRIGGER trg_validate_asset_lookups "
        "BEFORE INSERT OR UPDATE OF asset_type, asset_currency, asset_criticality, asset_status "
        "ON public.asset_basic_info FOR EACH ROW EXECUTE FUNCTION public.validate_asset_lookups()"
    )
    op.execute(
        "CREATE TRIGGER trg_validate_org_structure_lookups "
        "BEFORE INSERT OR UPDATE OF type, status, country "
        "ON public.org_structure FOR EACH ROW EXECUTE FUNCTION public.validate_org_structure_lookups()"
    )
    op.execute(
        "CREATE TRIGGER trg_validate_supplier_lookups "
        "BEFORE INSERT OR UPDATE OF supplier_type, supplier_country "
        "ON public.supplier FOR EACH ROW EXECUTE FUNCTION public.validate_supplier_lookups()"
    )


def _seed_and_align_data() -> None:
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

    for lookup_key, code, display_name, sort_order, is_active in LOOKUP_VALUE_SEEDS:
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
                "lookup_key": lookup_key,
                "code": code,
                "display_name": display_name,
                "sort_order": sort_order,
                "is_active": is_active,
            },
        )

    op.execute(
        """
        UPDATE public.org_structure AS child
        SET type = 'PLANT',
            modified_by = COALESCE(child.modified_by, 'alembic'),
            modified_dt = now()
        FROM public.org_structure AS parent
        WHERE child.parent_id = parent.id
          AND child.type = 'DIVISION'
          AND parent.type = 'REGION'
        """
    )
    op.execute(
        """
        UPDATE public.org_structure
        SET type = 'DIVISION',
            modified_by = COALESCE(modified_by, 'alembic'),
            modified_dt = now()
        WHERE type = 'REGION'
        """
    )
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('public.lookup_master', 'id'),
            GREATEST(COALESCE((SELECT MAX(id) FROM public.lookup_master), 1), 1),
            TRUE
        )
        """
    )
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('public.lookup_value', 'id'),
            GREATEST(COALESCE((SELECT MAX(id) FROM public.lookup_value), 1), 1),
            TRUE
        )
        """
    )
    op.execute(
        """
        SELECT setval(
            pg_get_serial_sequence('public.audit_log', 'audit_id'),
            GREATEST(COALESCE((SELECT MAX(audit_id) FROM public.audit_log), 1), 1),
            TRUE
        )
        """
    )

def upgrade() -> None:
    _ensure_tables()
    _ensure_columns_and_defaults()
    _ensure_constraints_and_indexes()
    _create_functions_and_triggers()
    _seed_and_align_data()


def downgrade() -> None:
    raise RuntimeError(
        "The baseline migration is intentionally not downgradeable because reversing it would require destructive schema changes."
    )
