"""Add authored document foundation.

Revision ID: 20260415_0012
Revises: 20260413_0011
Create Date: 2026-04-15 00:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260415_0012"
down_revision = "20260413_0011"
branch_labels = None
depends_on = None

SEED_TEMPLATE_CODE = "URS_BASELINE_V1"
SEED_TEMPLATE_NAME = "URS Baseline Template"
SEED_DOCUMENT_TYPE = "URS"
SEED_TEMPLATE_CONTENT = """# {{document_title}}

Document Type: {{document_type}}
Status: {{status}}
Template: {{template_name}} ({{template_code}})
Generated On: {{generated_on}}

## Purpose
{{purpose}}

## Scope
{{scope}}

## Asset Summary
- Asset Name: {{asset_name}}
- Asset ID: {{asset_id}}
- Asset Description: {{asset_description}}
- Short Description: {{short_description}}
- Asset Owner: {{asset_owner}}
- Organization: {{organization_name}}
- Supplier: {{supplier_name}}
- Manufacturer: {{manufacturer}}
- Model: {{model}}
- Asset Version: {{asset_version}}

## Asset Classification
- Asset Class: {{asset_class}}
- Asset Category: {{asset_category}}
- Asset Sub-Category: {{asset_sub_category}}
- Asset Type: {{asset_type}}
- Criticality: {{criticality_class}}
- Asset Nature: {{asset_nature}}
- Asset Status: {{asset_status}}

## Release Context
{{release_context}}

## Asset Specifications Summary
{{asset_specs_summary}}

## Authoring Notes
- This draft was prefilled deterministically from Asset Master, Asset Specs, release context, and user-provided notes.
- Review and refine the content before routing the document into later review or approval phases.
"""


def _seed_default_template() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO public.document_template (
                template_code,
                template_name,
                document_type,
                template_content,
                is_active,
                created_by,
                modified_by
            )
            VALUES (
                :template_code,
                :template_name,
                :document_type,
                :template_content,
                TRUE,
                'alembic',
                'alembic'
            )
            ON CONFLICT (template_code) DO UPDATE
            SET template_name = EXCLUDED.template_name,
                document_type = EXCLUDED.document_type,
                template_content = EXCLUDED.template_content,
                is_active = EXCLUDED.is_active,
                modified_by = 'alembic',
                modified_dt = now()
            """
        ),
        {
            "template_code": SEED_TEMPLATE_CODE,
            "template_name": SEED_TEMPLATE_NAME,
            "document_type": SEED_DOCUMENT_TYPE,
            "template_content": SEED_TEMPLATE_CONTENT,
        },
    )


def upgrade() -> None:
    op.create_table(
        "document_template",
        sa.Column("template_id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("template_code", sa.String(length=100), nullable=False),
        sa.Column("template_name", sa.String(length=150), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("template_content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("template_id"),
        sa.UniqueConstraint("template_code", name="uq_document_template_code"),
    )
    op.create_index("idx_document_template_document_type", "document_template", ["document_type"], unique=False)
    op.create_index("idx_document_template_is_active", "document_template", ["is_active"], unique=False)

    op.create_table(
        "authored_document",
        sa.Column(
            "authored_document_id",
            sa.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=250), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column(
            "asset_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("asset_basic_info.asset_id", name="fk_authored_document_asset", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "release_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("asset_release.release_id", name="fk_authored_document_release", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "template_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("document_template.template_id", name="fk_authored_document_template", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_context_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "(asset_id IS NOT NULL AND release_id IS NULL) OR (asset_id IS NULL AND release_id IS NOT NULL)",
            name="chk_authored_document_exactly_one_target",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'READY_FOR_REVIEW')",
            name="chk_authored_document_status",
        ),
        sa.PrimaryKeyConstraint("authored_document_id"),
    )
    op.create_index("idx_authored_document_asset_id", "authored_document", ["asset_id"], unique=False)
    op.create_index("idx_authored_document_release_id", "authored_document", ["release_id"], unique=False)
    op.create_index("idx_authored_document_template_id", "authored_document", ["template_id"], unique=False)
    op.create_index("idx_authored_document_document_type", "authored_document", ["document_type"], unique=False)
    op.create_index("idx_authored_document_status", "authored_document", ["status"], unique=False)

    _seed_default_template()


def downgrade() -> None:
    op.drop_index("idx_authored_document_status", table_name="authored_document")
    op.drop_index("idx_authored_document_document_type", table_name="authored_document")
    op.drop_index("idx_authored_document_template_id", table_name="authored_document")
    op.drop_index("idx_authored_document_release_id", table_name="authored_document")
    op.drop_index("idx_authored_document_asset_id", table_name="authored_document")
    op.drop_table("authored_document")
    op.drop_index("idx_document_template_is_active", table_name="document_template")
    op.drop_index("idx_document_template_document_type", table_name="document_template")
    op.drop_table("document_template")
