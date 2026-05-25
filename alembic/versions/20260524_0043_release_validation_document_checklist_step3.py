"""Add release validation document checklist step 3.

Revision ID: 20260524_0043_step3
Revises: 20260524_0043
Create Date: 2026-05-24 23:58:00

"""

from __future__ import annotations

from alembic import op


revision = "20260524_0043_step3"
down_revision = "20260524_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.release_validation_document_requirement (
            requirement_id UUID NOT NULL DEFAULT gen_random_uuid(),
            package_id UUID NOT NULL,
            release_id UUID NOT NULL,
            document_code VARCHAR(100) NOT NULL,
            document_name VARCHAR(250) NOT NULL,
            document_category VARCHAR(100) NOT NULL,
            document_description TEXT,
            requirement_level VARCHAR(40) NOT NULL,
            required_flag BOOLEAN NOT NULL DEFAULT false,
            waivable_flag BOOLEAN NOT NULL DEFAULT true,
            waiver_requires_qa_flag BOOLEAN NOT NULL DEFAULT true,
            status VARCHAR(40) NOT NULL,
            owner_role VARCHAR(100),
            owner_user_id UUID,
            source_type VARCHAR(60),
            linked_document_link_id UUID,
            linked_authored_document_id UUID,
            linked_qualification_document_id UUID,
            file_name VARCHAR(255),
            file_path TEXT,
            external_url TEXT,
            waiver_reason TEXT,
            waiver_requested_by VARCHAR(150),
            waiver_requested_at TIMESTAMPTZ,
            waiver_approved_by VARCHAR(150),
            waiver_approved_at TIMESTAMPTZ,
            trigger_scope VARCHAR(80),
            trigger_risk_level VARCHAR(40),
            trigger_question_codes_json JSONB,
            trigger_reason TEXT,
            generated_version INTEGER NOT NULL DEFAULT 1,
            is_active BOOLEAN NOT NULL DEFAULT true,
            display_order INTEGER NOT NULL DEFAULT 0,
            created_by VARCHAR(150),
            created_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by VARCHAR(150),
            updated_dt TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT release_validation_document_requirement_pkey PRIMARY KEY (requirement_id),
            CONSTRAINT fk_release_validation_document_requirement_package FOREIGN KEY (package_id)
                REFERENCES public.release_validation_package(package_id) ON DELETE CASCADE,
            CONSTRAINT fk_release_validation_document_requirement_release FOREIGN KEY (release_id)
                REFERENCES public.asset_release(release_id) ON DELETE CASCADE,
            CONSTRAINT chk_release_validation_document_requirement_level CHECK (
                requirement_level IN ('REQUIRED', 'CONDITIONAL', 'OPTIONAL', 'NOT_REQUIRED')
            ),
            CONSTRAINT chk_release_validation_document_requirement_status CHECK (
                status IN (
                    'MISSING',
                    'DRAFT',
                    'UPLOADED',
                    'LINKED',
                    'IN_REVIEW',
                    'APPROVED',
                    'REJECTED',
                    'WAIVED',
                    'NOT_REQUIRED',
                    'OBSOLETE'
                )
            ),
            CONSTRAINT chk_release_validation_document_requirement_source_type CHECK (
                source_type IS NULL OR source_type IN (
                    'NONE',
                    'UPLOAD',
                    'EXTERNAL_URL',
                    'DOCUMENT_PORTAL',
                    'AUTHORED_DOCUMENT',
                    'QUALIFICATION_DOCUMENT'
                )
            ),
            CONSTRAINT chk_release_validation_document_requirement_generated_version CHECK (
                generated_version >= 1
            )
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_release_validation_document_requirement_active_code "
        "ON public.release_validation_document_requirement USING btree (package_id, document_code) "
        "WHERE is_active = true"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_document_requirement_package_id "
        "ON public.release_validation_document_requirement USING btree (package_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_document_requirement_release_id "
        "ON public.release_validation_document_requirement USING btree (release_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_document_requirement_status "
        "ON public.release_validation_document_requirement USING btree (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_document_requirement_document_code "
        "ON public.release_validation_document_requirement USING btree (document_code)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_document_requirement_level "
        "ON public.release_validation_document_requirement USING btree (requirement_level)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_document_requirement_active "
        "ON public.release_validation_document_requirement USING btree (is_active)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.release_validation_document_requirement")
