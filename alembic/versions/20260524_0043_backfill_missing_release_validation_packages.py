"""Backfill validation packages for existing release records.

Revision ID: 20260524_0043
Revises: 20260524_0042
Create Date: 2026-05-24 23:45:00

"""

from __future__ import annotations

from alembic import op


revision = "20260524_0043"
down_revision = "20260524_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH missing_release AS (
            SELECT
                ar.release_id,
                EXTRACT(YEAR FROM COALESCE(ar.created_dt, now()))::int AS package_year,
                COALESCE(NULLIF(btrim(ar.created_by), ''), 'migration-backfill') AS actor,
                ROW_NUMBER() OVER (
                    PARTITION BY EXTRACT(YEAR FROM COALESCE(ar.created_dt, now()))::int
                    ORDER BY ar.created_dt ASC NULLS LAST, ar.release_id ASC
                ) AS missing_sequence
            FROM public.asset_release ar
            LEFT JOIN public.release_validation_package rvp
                ON rvp.release_id = ar.release_id
            WHERE rvp.package_id IS NULL
        ),
        existing_sequence AS (
            SELECT
                CAST(SUBSTRING(package_no FROM '^VAL-PKG-([0-9]{4})-[0-9]+$') AS int) AS package_year,
                MAX(CAST(SUBSTRING(package_no FROM '^VAL-PKG-[0-9]{4}-([0-9]+)$') AS int)) AS max_sequence
            FROM public.release_validation_package
            WHERE package_no ~ '^VAL-PKG-[0-9]{4}-[0-9]+$'
            GROUP BY CAST(SUBSTRING(package_no FROM '^VAL-PKG-([0-9]{4})-[0-9]+$') AS int)
        )
        INSERT INTO public.release_validation_package (
            release_id,
            package_no,
            package_status,
            validation_scope,
            risk_level,
            impact_assessment_status,
            document_checklist_status,
            testing_status,
            approval_status,
            created_by,
            created_dt,
            modified_by,
            modified_dt
        )
        SELECT
            mr.release_id,
            'VAL-PKG-' || mr.package_year::text || '-' ||
                LPAD((COALESCE(es.max_sequence, 0) + mr.missing_sequence)::text, 4, '0') AS package_no,
            'DRAFT',
            'NOT_ASSESSED',
            'NOT_ASSESSED',
            'PENDING',
            'NOT_GENERATED',
            'NOT_STARTED',
            'NOT_STARTED',
            mr.actor,
            now(),
            mr.actor,
            now()
        FROM missing_release mr
        LEFT JOIN existing_sequence es
            ON es.package_year = mr.package_year
        ON CONFLICT (release_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM public.release_validation_package
        WHERE created_by = 'migration-backfill'
          AND package_status = 'DRAFT'
          AND validation_scope = 'NOT_ASSESSED'
          AND risk_level = 'NOT_ASSESSED'
          AND impact_assessment_status = 'PENDING'
          AND NOT EXISTS (
              SELECT 1
              FROM public.release_validation_impact_assessment ia
              WHERE ia.package_id = public.release_validation_package.package_id
          )
        """
    )
