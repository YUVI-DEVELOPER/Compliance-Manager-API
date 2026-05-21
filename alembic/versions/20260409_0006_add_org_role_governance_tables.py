"""Add org governance role catalog, actions, and assignments.

Revision ID: 20260409_0006
Revises: 20260409_0005
Create Date: 2026-04-09 15:10:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260409_0006"
down_revision = "20260409_0005"
branch_labels = None
depends_on = None

LOOKUP_MASTER_SEEDS = (
    ("ORG_ROLE_RACI", "RACI classifications for org governance roles", True),
    ("ORG_ROLE_TYPE", "Role types for org governance roles", True),
    ("ORG_ROLE_ACTION_TYPE", "Action types available for org governance roles", True),
)

LOOKUP_VALUE_SEEDS = (
    ("ORG_ROLE_RACI", "RESPONSIBLE", "Responsible", 1, True),
    ("ORG_ROLE_RACI", "ACCOUNTABLE", "Accountable", 2, True),
    ("ORG_ROLE_RACI", "CONSULTED", "Consulted", 3, True),
    ("ORG_ROLE_RACI", "INFORMED", "Informed", 4, True),
    ("ORG_ROLE_TYPE", "BUSINESS", "Business", 1, True),
    ("ORG_ROLE_TYPE", "COMPLIANCE", "Compliance", 2, True),
    ("ORG_ROLE_TYPE", "OPERATIONS", "Operations", 3, True),
    ("ORG_ROLE_TYPE", "SECURITY", "Security", 4, True),
    ("ORG_ROLE_TYPE", "TECHNOLOGY", "Technology", 5, True),
    ("ORG_ROLE_ACTION_TYPE", "APPROVE", "Approve", 1, True),
    ("ORG_ROLE_ACTION_TYPE", "ESCALATE", "Escalate", 2, True),
    ("ORG_ROLE_ACTION_TYPE", "EXECUTE", "Execute", 3, True),
    ("ORG_ROLE_ACTION_TYPE", "NOTIFY", "Notify", 4, True),
    ("ORG_ROLE_ACTION_TYPE", "REVIEW", "Review", 5, True),
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


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.org_role (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            role_name VARCHAR(150) NOT NULL,
            role_raci VARCHAR(50) NOT NULL,
            ownership VARCHAR(150) NOT NULL,
            role_type VARCHAR(50) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by VARCHAR(150),
            created_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            modified_by VARCHAR(150),
            modified_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at TIMESTAMPTZ,
            deleted_by VARCHAR(150),
            CONSTRAINT org_role_pkey PRIMARY KEY (id),
            CONSTRAINT uq_org_role_role_name UNIQUE (role_name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.org_role_action (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            role_id UUID NOT NULL,
            seq INTEGER NOT NULL,
            action_type VARCHAR(50) NOT NULL,
            action VARCHAR(250) NOT NULL,
            created_by VARCHAR(150),
            created_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            modified_by VARCHAR(150),
            modified_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT org_role_action_pkey PRIMARY KEY (id),
            CONSTRAINT uq_org_role_action_role_seq UNIQUE (role_id, seq),
            CONSTRAINT fk_org_role_action_role FOREIGN KEY (role_id)
                REFERENCES public.org_role(id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.org_entity_role_assignment (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL,
            role_id UUID NOT NULL,
            person_name VARCHAR(150) NOT NULL,
            person_email VARCHAR(254),
            employee_code VARCHAR(50),
            remarks VARCHAR(500),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by VARCHAR(150),
            created_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            modified_by VARCHAR(150),
            modified_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at TIMESTAMPTZ,
            deleted_by VARCHAR(150),
            CONSTRAINT org_entity_role_assignment_pkey PRIMARY KEY (id),
            CONSTRAINT fk_org_entity_role_assignment_org FOREIGN KEY (org_id)
                REFERENCES public.org_structure(id) ON DELETE RESTRICT,
            CONSTRAINT fk_org_entity_role_assignment_role FOREIGN KEY (role_id)
                REFERENCES public.org_role(id) ON DELETE RESTRICT
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_org_role_is_active ON public.org_role USING btree (is_active)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_org_role_role_raci ON public.org_role USING btree (role_raci)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_org_role_role_type ON public.org_role USING btree (role_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_org_role_action_role_id ON public.org_role_action USING btree (role_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_org_role_action_action_type ON public.org_role_action USING btree (action_type)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_org_entity_role_assignment_is_active "
        "ON public.org_entity_role_assignment USING btree (is_active)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_org_entity_role_assignment_org_id "
        "ON public.org_entity_role_assignment USING btree (org_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_org_entity_role_assignment_role_id "
        "ON public.org_entity_role_assignment USING btree (role_id)"
    )

    _seed_lookup_data()


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.org_entity_role_assignment")
    op.execute("DROP TABLE IF EXISTS public.org_role_action")
    op.execute("DROP TABLE IF EXISTS public.org_role")
