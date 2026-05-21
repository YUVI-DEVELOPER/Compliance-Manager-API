"""Add asset finance extension table.

Revision ID: 20260413_0009
Revises: 20260410_0008
Create Date: 2026-04-13 00:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_0009"
down_revision = "20260410_0008"
branch_labels = None
depends_on = None

LOOKUP_MASTER_SEEDS = (
    ("DEPRECIATION_METHOD", "Supported asset depreciation methods", True),
    ("ASSET_CLASS_GL", "General ledger asset class mapping", True),
)

LOOKUP_VALUE_SEEDS = (
    ("DEPRECIATION_METHOD", "STRAIGHT_LINE", "Straight Line", 1, True),
    ("DEPRECIATION_METHOD", "DECLINING_BALANCE", "Declining Balance", 2, True),
    ("DEPRECIATION_METHOD", "UNITS_OF_PRODUCTION", "Units Of Production", 3, True),
    ("ASSET_CLASS_GL", "CAPEX_HARDWARE", "Capex Hardware", 1, True),
    ("ASSET_CLASS_GL", "CAPEX_SOFTWARE", "Capex Software", 2, True),
    ("ASSET_CLASS_GL", "CAPEX_INFRASTRUCTURE", "Capex Infrastructure", 3, True),
    ("ASSET_CLASS_GL", "CAPEX_LAB", "Capex Lab Equipment", 4, True),
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
                SELECT
                    lm.id,
                    :code,
                    :display_name,
                    :sort_order,
                    :is_active,
                    'alembic'
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


def _create_lookup_trigger() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.validate_asset_finance_lookups() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_ok BOOLEAN;
        BEGIN
            SELECT TRUE INTO v_ok
            FROM lookup_master lm
            JOIN lookup_value lv ON lv.lookup_id = lm.id
            WHERE lm.lookup_key = 'CURRENCY'
              AND lm.is_active = TRUE
              AND lv.is_active = TRUE
              AND lv.code = NEW.currency_code
            LIMIT 1;
            IF v_ok IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'Invalid asset_finance.currency_code: "%" (not defined in CURRENCY lookup)', NEW.currency_code;
            END IF;

            SELECT TRUE INTO v_ok
            FROM lookup_master lm
            JOIN lookup_value lv ON lv.lookup_id = lm.id
            WHERE lm.lookup_key = 'DEPRECIATION_METHOD'
              AND lm.is_active = TRUE
              AND lv.is_active = TRUE
              AND lv.code = NEW.depreciation_method
            LIMIT 1;
            IF v_ok IS DISTINCT FROM TRUE THEN
                RAISE EXCEPTION 'Invalid asset_finance.depreciation_method: "%" (not defined in DEPRECIATION_METHOD lookup)', NEW.depreciation_method;
            END IF;

            IF NEW.asset_class_gl IS NOT NULL AND NEW.asset_class_gl <> '' THEN
                SELECT TRUE INTO v_ok
                FROM lookup_master lm
                JOIN lookup_value lv ON lv.lookup_id = lm.id
                WHERE lm.lookup_key = 'ASSET_CLASS_GL'
                  AND lm.is_active = TRUE
                  AND lv.is_active = TRUE
                  AND lv.code = NEW.asset_class_gl
                LIMIT 1;
                IF v_ok IS DISTINCT FROM TRUE THEN
                    RAISE EXCEPTION 'Invalid asset_finance.asset_class_gl: "%" (not defined in ASSET_CLASS_GL lookup)', NEW.asset_class_gl;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_validate_asset_finance_lookups ON public.asset_finance")
    op.execute(
        """
        CREATE TRIGGER trg_validate_asset_finance_lookups
        BEFORE INSERT OR UPDATE
        ON public.asset_finance
        FOR EACH ROW
        EXECUTE FUNCTION public.validate_asset_finance_lookups()
        """
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    _seed_lookup_data()

    op.create_table(
        "asset_finance",
        sa.Column("finance_id", sa.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "asset_uuid",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("asset_basic_info.asset_id", name="fk_asset_finance_asset", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("acquisition_dt", sa.Date(), nullable=False),
        sa.Column("purchase_order_no", sa.String(length=20), nullable=True),
        sa.Column("invoice_ref", sa.String(length=20), nullable=True),
        sa.Column(
            "supplier_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("supplier.supplier_id", name="fk_asset_finance_supplier", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("make", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=50), nullable=True),
        sa.Column("manufacturer", sa.String(length=100), nullable=True),
        sa.Column("oem_release_url", sa.String(length=500), nullable=True),
        sa.Column("capitalization_date", sa.Date(), nullable=False),
        sa.Column("acquisition_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency_code", sa.String(length=10), nullable=False),
        sa.Column("book_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("replacement_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("insured_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("salvage_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("depreciation_method", sa.String(length=50), nullable=False),
        sa.Column("useful_life_years", sa.Integer(), nullable=False),
        sa.Column("depreciation_rate_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("accumulated_depreciation", sa.Numeric(18, 2), nullable=False),
        sa.Column("cost_center", sa.String(length=15), nullable=True),
        sa.Column("gl_account_capex", sa.String(length=15), nullable=True),
        sa.Column("asset_class_gl", sa.String(length=50), nullable=True),
        sa.Column("wbs_element", sa.String(length=20), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("created_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("modified_by", sa.String(length=150), nullable=True),
        sa.Column("modified_dt", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("acquisition_cost > 0", name="chk_asset_finance_acquisition_cost_positive"),
        sa.CheckConstraint("accumulated_depreciation >= 0", name="chk_asset_finance_accumulated_non_negative"),
        sa.CheckConstraint(
            "accumulated_depreciation <= acquisition_cost",
            name="chk_asset_finance_accumulated_not_gt_cost",
        ),
        sa.CheckConstraint("book_value = acquisition_cost - accumulated_depreciation", name="chk_asset_finance_book_value_formula"),
        sa.CheckConstraint("book_value >= 0", name="chk_asset_finance_book_value_non_negative"),
        sa.CheckConstraint(
            "capitalization_date >= acquisition_dt",
            name="chk_asset_finance_capitalization_not_before_acquisition",
        ),
        sa.CheckConstraint("useful_life_years >= 1 AND useful_life_years <= 99", name="chk_asset_finance_useful_life_range"),
        sa.CheckConstraint(
            "replacement_value IS NULL OR replacement_value >= 0",
            name="chk_asset_finance_replacement_non_negative",
        ),
        sa.CheckConstraint(
            "insured_value IS NULL OR insured_value >= 0",
            name="chk_asset_finance_insured_non_negative",
        ),
        sa.CheckConstraint(
            "salvage_value IS NULL OR salvage_value >= 0",
            name="chk_asset_finance_salvage_non_negative",
        ),
        sa.CheckConstraint(
            "depreciation_rate_pct IS NULL OR depreciation_rate_pct >= 0",
            name="chk_asset_finance_depreciation_rate_non_negative",
        ),
        sa.PrimaryKeyConstraint("finance_id"),
        sa.UniqueConstraint("asset_uuid", name="uq_asset_finance_asset_uuid"),
    )

    op.create_index("idx_asset_finance_asset_uuid", "asset_finance", ["asset_uuid"], unique=False)
    op.create_index("idx_asset_finance_supplier_id", "asset_finance", ["supplier_id"], unique=False)
    op.create_index("idx_asset_finance_currency_code", "asset_finance", ["currency_code"], unique=False)
    op.create_index("idx_asset_finance_depreciation_method", "asset_finance", ["depreciation_method"], unique=False)

    _create_lookup_trigger()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_validate_asset_finance_lookups ON public.asset_finance")
    op.execute("DROP FUNCTION IF EXISTS public.validate_asset_finance_lookups()")
    op.drop_index("idx_asset_finance_depreciation_method", table_name="asset_finance")
    op.drop_index("idx_asset_finance_currency_code", table_name="asset_finance")
    op.drop_index("idx_asset_finance_supplier_id", table_name="asset_finance")
    op.drop_index("idx_asset_finance_asset_uuid", table_name="asset_finance")
    op.drop_table("asset_finance")
