import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AssetFinanceCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    acquisition_dt: date
    purchase_order_no: str | None = Field(
        default=None,
        max_length=20,
        validation_alias=AliasChoices("purchase_order_no", "purchaseOrderNo"),
    )
    invoice_ref: str | None = Field(default=None, max_length=20, validation_alias=AliasChoices("invoice_ref", "invoiceRef"))
    supplier_id: uuid.UUID = Field(validation_alias=AliasChoices("supplier_id", "supplierId"))
    make: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=50)
    manufacturer: str | None = Field(default=None, max_length=100)
    oem_release_url: str | None = Field(
        default=None,
        max_length=500,
        validation_alias=AliasChoices("oem_release_url", "oemReleaseUrl"),
    )
    capitalization_date: date = Field(validation_alias=AliasChoices("capitalization_date", "capitalizationDate"))
    acquisition_cost: Decimal = Field(
        ...,
        gt=0,
        max_digits=18,
        decimal_places=2,
        validation_alias=AliasChoices("acquisition_cost", "acquisitionCost"),
    )
    currency_code: str = Field(
        ...,
        min_length=1,
        max_length=10,
        validation_alias=AliasChoices("currency_code", "currencyCode"),
    )
    replacement_value: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
        validation_alias=AliasChoices("replacement_value", "replacementValue"),
    )
    insured_value: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
        validation_alias=AliasChoices("insured_value", "insuredValue"),
    )
    salvage_value: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
        validation_alias=AliasChoices("salvage_value", "salvageValue"),
    )
    depreciation_method: str = Field(
        ...,
        min_length=1,
        max_length=50,
        validation_alias=AliasChoices("depreciation_method", "depreciationMethod"),
    )
    useful_life_years: int = Field(
        ...,
        ge=1,
        le=99,
        validation_alias=AliasChoices("useful_life_years", "usefulLifeYears"),
    )
    depreciation_rate_pct: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=5,
        decimal_places=2,
        validation_alias=AliasChoices("depreciation_rate_pct", "depreciationRatePct"),
    )
    accumulated_depreciation: Decimal = Field(
        ...,
        ge=0,
        max_digits=18,
        decimal_places=2,
        validation_alias=AliasChoices("accumulated_depreciation", "accumulatedDepreciation"),
    )
    cost_center: str | None = Field(default=None, max_length=15, validation_alias=AliasChoices("cost_center", "costCenter"))
    gl_account_capex: str | None = Field(
        default=None,
        max_length=15,
        validation_alias=AliasChoices("gl_account_capex", "glAccountCapex"),
    )
    asset_class_gl: str | None = Field(
        default=None,
        max_length=50,
        validation_alias=AliasChoices("asset_class_gl", "assetClassGl"),
    )
    wbs_element: str | None = Field(default=None, max_length=20, validation_alias=AliasChoices("wbs_element", "wbsElement"))
    created_by: str = Field(..., min_length=1, max_length=150, validation_alias=AliasChoices("created_by", "createdBy"))


class AssetFinanceUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    acquisition_dt: date | None = None
    purchase_order_no: str | None = Field(
        default=None,
        max_length=20,
        validation_alias=AliasChoices("purchase_order_no", "purchaseOrderNo"),
    )
    invoice_ref: str | None = Field(default=None, max_length=20, validation_alias=AliasChoices("invoice_ref", "invoiceRef"))
    supplier_id: uuid.UUID | None = Field(default=None, validation_alias=AliasChoices("supplier_id", "supplierId"))
    make: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=50)
    manufacturer: str | None = Field(default=None, max_length=100)
    oem_release_url: str | None = Field(
        default=None,
        max_length=500,
        validation_alias=AliasChoices("oem_release_url", "oemReleaseUrl"),
    )
    capitalization_date: date | None = Field(default=None, validation_alias=AliasChoices("capitalization_date", "capitalizationDate"))
    acquisition_cost: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=18,
        decimal_places=2,
        validation_alias=AliasChoices("acquisition_cost", "acquisitionCost"),
    )
    currency_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=10,
        validation_alias=AliasChoices("currency_code", "currencyCode"),
    )
    replacement_value: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
        validation_alias=AliasChoices("replacement_value", "replacementValue"),
    )
    insured_value: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
        validation_alias=AliasChoices("insured_value", "insuredValue"),
    )
    salvage_value: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
        validation_alias=AliasChoices("salvage_value", "salvageValue"),
    )
    depreciation_method: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        validation_alias=AliasChoices("depreciation_method", "depreciationMethod"),
    )
    useful_life_years: int | None = Field(
        default=None,
        ge=1,
        le=99,
        validation_alias=AliasChoices("useful_life_years", "usefulLifeYears"),
    )
    depreciation_rate_pct: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=5,
        decimal_places=2,
        validation_alias=AliasChoices("depreciation_rate_pct", "depreciationRatePct"),
    )
    accumulated_depreciation: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
        validation_alias=AliasChoices("accumulated_depreciation", "accumulatedDepreciation"),
    )
    cost_center: str | None = Field(default=None, max_length=15, validation_alias=AliasChoices("cost_center", "costCenter"))
    gl_account_capex: str | None = Field(
        default=None,
        max_length=15,
        validation_alias=AliasChoices("gl_account_capex", "glAccountCapex"),
    )
    asset_class_gl: str | None = Field(
        default=None,
        max_length=50,
        validation_alias=AliasChoices("asset_class_gl", "assetClassGl"),
    )
    wbs_element: str | None = Field(default=None, max_length=20, validation_alias=AliasChoices("wbs_element", "wbsElement"))
    modified_by: str | None = Field(
        default=None,
        max_length=150,
        validation_alias=AliasChoices("modified_by", "modifiedBy"),
    )


class AssetFinanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    finance_id: uuid.UUID
    asset_uuid: uuid.UUID
    asset_id: str | None = None
    asset_name: str | None = None
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    acquisition_dt: date
    purchase_order_no: str | None = None
    invoice_ref: str | None = None
    make: str | None = None
    model: str | None = None
    manufacturer: str | None = None
    oem_release_url: str | None = None
    capitalization_date: date
    acquisition_cost: Decimal
    currency_code: str
    book_value: Decimal
    replacement_value: Decimal | None = None
    insured_value: Decimal | None = None
    salvage_value: Decimal | None = None
    depreciation_method: str
    useful_life_years: int
    depreciation_rate_pct: Decimal | None = None
    accumulated_depreciation: Decimal
    cost_center: str | None = None
    gl_account_capex: str | None = None
    asset_class_gl: str | None = None
    wbs_element: str | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
