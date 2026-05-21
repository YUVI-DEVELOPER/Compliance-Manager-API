"""Remove authored document additional notes section.

Revision ID: 20260514_0033
Revises: 20260512_0032
Create Date: 2026-05-14 00:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260514_0033"
down_revision = "20260512_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE public.document_template
               SET template_content = replace(
                       replace(
                           template_content,
                           :old_crlf_section,
                           :crlf_separator
                       ),
                       :old_lf_section,
                       :lf_separator
                   ),
                   modified_by = COALESCE(modified_by, 'alembic'),
                   modified_dt = now()
             WHERE template_content LIKE '%## Additional Notes%'
               AND template_content LIKE '%{{additional_notes}}%'
            """
        ),
        {
            "old_crlf_section": "\r\n## Additional Notes\r\n{{additional_notes}}\r\n",
            "old_lf_section": "\n## Additional Notes\n{{additional_notes}}\n",
            "crlf_separator": "\r\n",
            "lf_separator": "\n",
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE public.document_template
               SET template_content = replace(
                       template_content,
                       :authoring_header,
                       :restored_section
                   ),
                   modified_by = COALESCE(modified_by, 'alembic'),
                   modified_dt = now()
             WHERE template_code = 'URS_BASELINE_V1'
               AND template_content NOT LIKE '%## Additional Notes%'
               AND template_content LIKE :authoring_header_like
            """
        ),
        {
            "authoring_header": "\n## Authoring Notes",
            "authoring_header_like": "%\n## Authoring Notes%",
            "restored_section": "\n## Additional Notes\n{{additional_notes}}\n\n## Authoring Notes",
        },
    )
