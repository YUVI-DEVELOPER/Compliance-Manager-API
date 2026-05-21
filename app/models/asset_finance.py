import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.supplier import Supplier


class AssetFinance(Base):
    __tablename__ = "asset_finance"
    __table_args__ = (
        UniqueConstraint("asset_uuid", name="uq_asset_finance_asset_uuid"),
        CheckConstraint("acquisition_cost > 0", name="chk_asset_finance_acquisition_cost_positive"),
        CheckConstraint("accumulated_depreciation >= 0", name="chk_asset_finance_accumulated_non_negative"),
        CheckConstraint("accumulated_depreciation <= acquisition_cost", name="chk_asset_finance_accumulated_not_gt_cost"),
        CheckConstraint("book_value = acquisition_cost - accumulated_depreciation", name="chk_asset_finance_book_value_formula"),
        CheckConstraint("book_value >= 0", name="chk_asset_finance_book_value_non_negative"),
        CheckConstraint("capitalization_date >= acquisition_dt", name="chk_asset_finance_capitalization_not_before_acquisition"),
        CheckConstraint("useful_life_years >= 1 AND useful_life_years <= 99", name="chk_asset_finance_useful_life_range"),
        CheckConstraint(
            "replacement_value IS NULL OR replacement_value >= 0",
            name="chk_asset_finance_replacement_non_negative",
        ),
        CheckConstraint("insured_value IS NULL OR insured_value >= 0", name="chk_asset_finance_insured_non_negative"),
        CheckConstraint("salvage_value IS NULL OR salvage_value >= 0", name="chk_asset_finance_salvage_non_negative"),
        CheckConstraint(
            "depreciation_rate_pct IS NULL OR depreciation_rate_pct >= 0",
            name="chk_asset_finance_depreciation_rate_non_negative",
        ),
        Index("idx_asset_finance_asset_uuid", "asset_uuid"),
        Index("idx_asset_finance_supplier_id", "supplier_id"),
        Index("idx_asset_finance_currency_code", "currency_code"),
        Index("idx_asset_finance_depreciation_method", "depreciation_method"),
    )

    finance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    asset_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_asset_finance_asset", ondelete="CASCADE"),
        nullable=False,
    )
    acquisition_dt: Mapped[date] = mapped_column(Date, nullable=False)
    purchase_order_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    invoice_ref: Mapped[str | None] = mapped_column(String(20), nullable=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.supplier_id", name="fk_asset_finance_supplier", ondelete="RESTRICT"),
        nullable=False,
    )
    make: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    oem_release_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    capitalization_date: Mapped[date] = mapped_column(Date, nullable=False)
    acquisition_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False)
    book_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    replacement_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    insured_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    salvage_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    depreciation_method: Mapped[str] = mapped_column(String(50), nullable=False)
    useful_life_years: Mapped[int] = mapped_column(nullable=False)
    depreciation_rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    accumulated_depreciation: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cost_center: Mapped[str | None] = mapped_column(String(15), nullable=True)
    gl_account_capex: Mapped[str | None] = mapped_column(String(15), nullable=True)
    asset_class_gl: Mapped[str | None] = mapped_column(String(50), nullable=True)
    wbs_element: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    asset: Mapped["Asset"] = relationship("Asset", back_populates="finance")
    supplier: Mapped["Supplier"] = relationship("Supplier")
