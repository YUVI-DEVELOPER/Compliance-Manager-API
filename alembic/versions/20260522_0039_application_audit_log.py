"""Extend audit_log for application audit trail.

Revision ID: 20260522_0039
Revises: 20260520_0038
Create Date: 2026-05-22 00:00:00

"""

from __future__ import annotations

from alembic import op


revision = "20260522_0039"
down_revision = "20260520_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS event_time TIMESTAMPTZ DEFAULT now()")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS module_name VARCHAR(120)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS entity_name VARCHAR(120)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS record_id VARCHAR(150)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS action VARCHAR(120)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS event_description TEXT")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS changed_fields JSONB")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS performed_by_user_id VARCHAR(150)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS performed_by_name VARCHAR(150)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS performed_by_email VARCHAR(150)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS performed_by_role VARCHAR(150)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS reason TEXT")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS ip_address VARCHAR(100)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS user_agent TEXT")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'SUCCESS'")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS request_id VARCHAR(150)")
    op.execute("ALTER TABLE public.audit_log ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()")

    op.execute("UPDATE public.audit_log SET event_time = COALESCE(event_time, changed_at, now())")
    op.execute("UPDATE public.audit_log SET module_name = COALESCE(module_name, table_name, 'System')")
    op.execute("UPDATE public.audit_log SET entity_name = COALESCE(entity_name, table_name, 'Record')")
    op.execute("UPDATE public.audit_log SET action = COALESCE(action, operation_type, 'SYSTEM_EVENT')")
    op.execute("UPDATE public.audit_log SET status = COALESCE(status, 'SUCCESS')")
    op.execute("UPDATE public.audit_log SET created_at = COALESCE(created_at, changed_at, now())")
    op.execute("UPDATE public.audit_log SET ip_address = COALESCE(ip_address, client_ip)")
    op.execute("UPDATE public.audit_log SET performed_by_user_id = COALESCE(performed_by_user_id, changed_by)")
    op.execute(
        """
        UPDATE public.audit_log
        SET record_id = COALESCE(record_id, record_pk->>'id', record_pk->>'user_id', record_pk->>'role_id')
        WHERE record_id IS NULL AND record_pk IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE public.audit_log
        SET changed_fields = COALESCE(
            changed_fields,
            CASE
                WHEN changed_columns IS NULL THEN NULL
                WHEN jsonb_typeof(changed_columns) = 'array' THEN changed_columns
                WHEN jsonb_typeof(changed_columns) = 'object' THEN (
                    SELECT jsonb_agg(key)
                    FROM jsonb_object_keys(changed_columns) AS key
                )
                ELSE NULL
            END
        )
        """
    )

    op.execute("ALTER TABLE public.audit_log ALTER COLUMN event_time SET NOT NULL")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN event_time SET DEFAULT now()")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN module_name SET NOT NULL")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN module_name SET DEFAULT 'System'")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN entity_name SET NOT NULL")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN entity_name SET DEFAULT 'Record'")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN action SET NOT NULL")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN action SET DEFAULT 'SYSTEM_EVENT'")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN status SET NOT NULL")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN status SET DEFAULT 'SUCCESS'")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN created_at SET NOT NULL")
    op.execute("ALTER TABLE public.audit_log ALTER COLUMN created_at SET DEFAULT now()")

    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_event_time ON public.audit_log USING btree (event_time)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_module_name ON public.audit_log USING btree (module_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_entity_name ON public.audit_log USING btree (entity_name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON public.audit_log USING btree (action)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_record_id ON public.audit_log USING btree (record_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_performed_by_user_id "
        "ON public.audit_log USING btree (performed_by_user_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_status ON public.audit_log USING btree (status)")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.prevent_audit_log_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only and cannot be updated or deleted';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'trg_prevent_audit_log_update_delete'
            ) THEN
                CREATE TRIGGER trg_prevent_audit_log_update_delete
                BEFORE UPDATE OR DELETE ON public.audit_log
                FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_log_mutation();
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_audit_log_update_delete ON public.audit_log")
    op.execute("DROP FUNCTION IF EXISTS public.prevent_audit_log_mutation()")
    op.execute("DROP INDEX IF EXISTS public.idx_audit_status")
    op.execute("DROP INDEX IF EXISTS public.idx_audit_performed_by_user_id")
    op.execute("DROP INDEX IF EXISTS public.idx_audit_record_id")
    op.execute("DROP INDEX IF EXISTS public.idx_audit_action")
    op.execute("DROP INDEX IF EXISTS public.idx_audit_entity_name")
    op.execute("DROP INDEX IF EXISTS public.idx_audit_module_name")
    op.execute("DROP INDEX IF EXISTS public.idx_audit_event_time")
