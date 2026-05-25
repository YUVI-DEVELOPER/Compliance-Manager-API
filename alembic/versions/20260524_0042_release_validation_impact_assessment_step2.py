"""Add release validation structured impact assessment step 2.

Revision ID: 20260524_0042
Revises: 20260524_0041
Create Date: 2026-05-24 23:15:00

"""

from __future__ import annotations

from alembic import op


revision = "20260524_0042"
down_revision = "20260524_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.release_validation_impact_assessment (
            assessment_id UUID NOT NULL DEFAULT gen_random_uuid(),
            package_id UUID NOT NULL,
            assessment_no VARCHAR(50) NOT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'DRAFT',
            total_score INTEGER NOT NULL DEFAULT 0,
            risk_level VARCHAR(40) NOT NULL DEFAULT 'NOT_ASSESSED',
            validation_scope VARCHAR(60) NOT NULL DEFAULT 'NOT_ASSESSED',
            summary TEXT,
            created_by VARCHAR,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by VARCHAR,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_by VARCHAR,
            completed_at TIMESTAMPTZ,
            reopened_by VARCHAR,
            reopened_at TIMESTAMPTZ,
            reopen_reason TEXT,
            CONSTRAINT release_validation_impact_assessment_pkey PRIMARY KEY (assessment_id),
            CONSTRAINT uq_release_validation_impact_assessment_package UNIQUE (package_id),
            CONSTRAINT uq_release_validation_impact_assessment_no UNIQUE (assessment_no),
            CONSTRAINT fk_release_validation_impact_assessment_package FOREIGN KEY (package_id)
                REFERENCES public.release_validation_package(package_id) ON DELETE CASCADE,
            CONSTRAINT chk_release_validation_impact_assessment_status CHECK (
                status IN ('DRAFT', 'IN_PROGRESS', 'COMPLETED', 'REOPENED', 'SUPERSEDED')
            ),
            CONSTRAINT chk_release_validation_impact_assessment_risk_level CHECK (
                risk_level IN ('NOT_ASSESSED', 'NO_IMPACT', 'LOW', 'MEDIUM', 'HIGH')
            ),
            CONSTRAINT chk_release_validation_impact_assessment_validation_scope CHECK (
                validation_scope IN ('NOT_ASSESSED', 'NO_VALIDATION_REQUIRED', 'LIMITED_VALIDATION', 'FULL_VALIDATION')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_impact_assessment_package_id "
        "ON public.release_validation_impact_assessment USING btree (package_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_impact_assessment_assessment_no "
        "ON public.release_validation_impact_assessment USING btree (assessment_no)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_impact_assessment_status "
        "ON public.release_validation_impact_assessment USING btree (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_impact_assessment_risk_level "
        "ON public.release_validation_impact_assessment USING btree (risk_level)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_impact_assessment_validation_scope "
        "ON public.release_validation_impact_assessment USING btree (validation_scope)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.release_validation_impact_response (
            response_id UUID NOT NULL DEFAULT gen_random_uuid(),
            assessment_id UUID NOT NULL,
            question_code VARCHAR(80) NOT NULL,
            category VARCHAR(120) NOT NULL,
            question_text TEXT NOT NULL,
            answer VARCHAR(30) NOT NULL,
            weight INTEGER NOT NULL,
            critical BOOLEAN NOT NULL,
            mandatory BOOLEAN NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            rationale TEXT,
            evidence_reference TEXT,
            answered_by VARCHAR,
            answered_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT release_validation_impact_response_pkey PRIMARY KEY (response_id),
            CONSTRAINT uq_release_validation_impact_response_question UNIQUE (assessment_id, question_code),
            CONSTRAINT fk_release_validation_impact_response_assessment FOREIGN KEY (assessment_id)
                REFERENCES public.release_validation_impact_assessment(assessment_id) ON DELETE CASCADE,
            CONSTRAINT chk_release_validation_impact_response_answer CHECK (
                answer IN ('YES', 'NO', 'NOT_APPLICABLE', 'UNKNOWN')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_impact_response_assessment_id "
        "ON public.release_validation_impact_response USING btree (assessment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_impact_response_question_code "
        "ON public.release_validation_impact_response USING btree (question_code)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_impact_response_answer "
        "ON public.release_validation_impact_response USING btree (answer)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.release_validation_ai_suggestion (
            suggestion_id UUID NOT NULL DEFAULT gen_random_uuid(),
            assessment_id UUID,
            release_id UUID NOT NULL,
            package_id UUID NOT NULL,
            question_code VARCHAR(80) NOT NULL,
            suggested_answer VARCHAR(30) NOT NULL,
            suggested_rationale TEXT,
            confidence VARCHAR(20),
            evidence_reference TEXT,
            caveat TEXT,
            source_fields_used JSONB,
            model_name VARCHAR(200),
            provider VARCHAR(100),
            prompt_version VARCHAR(50),
            raw_response JSONB,
            accepted_by_user BOOLEAN NOT NULL DEFAULT false,
            accepted_at TIMESTAMPTZ,
            created_by VARCHAR,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT release_validation_ai_suggestion_pkey PRIMARY KEY (suggestion_id),
            CONSTRAINT fk_release_validation_ai_suggestion_assessment FOREIGN KEY (assessment_id)
                REFERENCES public.release_validation_impact_assessment(assessment_id) ON DELETE SET NULL,
            CONSTRAINT fk_release_validation_ai_suggestion_release FOREIGN KEY (release_id)
                REFERENCES public.asset_release(release_id) ON DELETE CASCADE,
            CONSTRAINT fk_release_validation_ai_suggestion_package FOREIGN KEY (package_id)
                REFERENCES public.release_validation_package(package_id) ON DELETE CASCADE,
            CONSTRAINT chk_release_validation_ai_suggestion_answer CHECK (
                suggested_answer IN ('YES', 'NO', 'NOT_APPLICABLE', 'UNKNOWN')
            ),
            CONSTRAINT chk_release_validation_ai_suggestion_confidence CHECK (
                confidence IS NULL OR confidence IN ('LOW', 'MEDIUM', 'HIGH')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_ai_suggestion_assessment_id "
        "ON public.release_validation_ai_suggestion USING btree (assessment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_ai_suggestion_release_id "
        "ON public.release_validation_ai_suggestion USING btree (release_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_ai_suggestion_package_id "
        "ON public.release_validation_ai_suggestion USING btree (package_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_validation_ai_suggestion_question_code "
        "ON public.release_validation_ai_suggestion USING btree (question_code)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.release_validation_ai_suggestion")
    op.execute("DROP TABLE IF EXISTS public.release_validation_impact_response")
    op.execute("DROP TABLE IF EXISTS public.release_validation_impact_assessment")
