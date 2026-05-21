from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260418_0020"
down_revision = "20260416_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=150), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
    )

    op.create_index("idx_app_user_email", "app_user", ["email"], unique=False)
    op.create_index("idx_app_user_active", "app_user", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_app_user_active", table_name="app_user")
    op.drop_index("idx_app_user_email", table_name="app_user")
    op.drop_table("app_user")