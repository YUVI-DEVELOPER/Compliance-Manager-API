import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


def _normalize_tags_input(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, str):
        return [item.strip() for item in value.split(",")]
    if isinstance(value, list):
        return value
    return value


class AssetSpecValue(BaseModel):
    asset_spec_id: str
    parameter_grouping: str
    parameter_name: str
    parameter_description: str | None = None
    parameter_value: str


class AssetCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    org_node_id: uuid.UUID
    asset_id: str = Field(..., min_length=1, max_length=20, validation_alias=AliasChoices("asset_id", "asset_code"))
    asset_name: str = Field(..., min_length=1, max_length=100)
    asset_description: str = Field(..., min_length=1, max_length=500)
    short_description: str = Field(..., min_length=1, max_length=40)
    asset_owner: str = Field(..., min_length=1, max_length=150)
    asset_class: str = Field(..., min_length=1, max_length=50)
    asset_category: str = Field(..., min_length=1, max_length=50)
    asset_sub_category: str = Field(..., min_length=1, max_length=50)
    criticality_class: str = Field(
        ...,
        min_length=1,
        max_length=50,
        validation_alias=AliasChoices("criticality_class", "asset_criticality"),
    )
    asset_nature: str = Field(..., min_length=1, max_length=50)
    created_by: str = Field(..., min_length=1, max_length=150)

    asset_type: str | None = Field(default=None, max_length=50)
    legacy_id: str | None = Field(default=None, max_length=30)
    qr_barcode: str | None = Field(default=None, max_length=50)
    rfid_tag: str | None = Field(default=None, max_length=30)
    serial_number: str | None = Field(
        default=None,
        max_length=50,
        validation_alias=AliasChoices("serial_number", "asset_serial_no"),
    )
    tags: list[str] | None = None
    tag_number: str | None = Field(default=None, max_length=20)

    supplier_id: uuid.UUID | None = None

    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=100)
    asset_version: str | None = Field(default=None, max_length=25)

    asset_commission_dt: datetime | None = None
    asset_purchase_dt: datetime | None = None
    asset_purchase_ref: str | None = Field(default=None, max_length=50)
    warranty_period: int | None = None
    asset_value: float | None = None
    asset_currency: str | None = Field(default=None, max_length=10)
    asset_release_url: str | None = Field(default=None, max_length=250)
    asset_status: str | None = Field(default=None, max_length=50)
    asset_spec_values: list[AssetSpecValue] | None = None

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> object:
        return _normalize_tags_input(value)


class AssetUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    org_node_id: uuid.UUID | None = None
    asset_id: str | None = Field(default=None, min_length=1, max_length=20, validation_alias=AliasChoices("asset_id", "asset_code"))
    asset_name: str | None = Field(default=None, min_length=1, max_length=100)
    asset_description: str | None = Field(default=None, min_length=1, max_length=500)
    short_description: str | None = Field(default=None, min_length=1, max_length=40)
    asset_owner: str | None = Field(default=None, min_length=1, max_length=150)
    asset_class: str | None = Field(default=None, min_length=1, max_length=50)
    asset_category: str | None = Field(default=None, min_length=1, max_length=50)
    asset_sub_category: str | None = Field(default=None, min_length=1, max_length=50)
    criticality_class: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        validation_alias=AliasChoices("criticality_class", "asset_criticality"),
    )
    asset_nature: str | None = Field(default=None, min_length=1, max_length=50)

    asset_type: str | None = Field(default=None, max_length=50)
    legacy_id: str | None = Field(default=None, max_length=30)
    qr_barcode: str | None = Field(default=None, max_length=50)
    rfid_tag: str | None = Field(default=None, max_length=30)
    serial_number: str | None = Field(
        default=None,
        max_length=50,
        validation_alias=AliasChoices("serial_number", "asset_serial_no"),
    )
    tags: list[str] | None = None
    tag_number: str | None = Field(default=None, max_length=20)

    supplier_id: uuid.UUID | None = None

    manufacturer: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=100)
    asset_version: str | None = Field(default=None, max_length=25)

    asset_commission_dt: datetime | None = None
    asset_purchase_dt: datetime | None = None
    asset_purchase_ref: str | None = Field(default=None, max_length=50)
    warranty_period: int | None = None
    asset_value: float | None = None
    asset_currency: str | None = Field(default=None, max_length=10)
    asset_release_url: str | None = Field(default=None, max_length=250)
    asset_status: str | None = Field(default=None, max_length=50)
    asset_spec_values: list[AssetSpecValue] | None = None

    modified_by: str | None = Field(default=None, max_length=150)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> object:
        return _normalize_tags_input(value)


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_uuid: uuid.UUID
    asset_id: str
    org_node_id: uuid.UUID
    org_node_name: str | None = None
    supplier_id: uuid.UUID | None = None
    supplier_name: str | None = None

    legacy_id: str | None = None
    qr_barcode: str | None = None
    rfid_tag: str | None = None
    serial_number: str | None = None

    asset_class: str
    asset_category: str
    asset_sub_category: str
    asset_type: str | None = None
    criticality_class: str
    asset_nature: str
    tags: list[str] | None = None

    asset_name: str
    asset_description: str
    short_description: str
    tag_number: str | None = None
    asset_owner: str

    manufacturer: str | None = None
    model: str | None = None
    asset_version: str | None = None
    asset_commission_dt: datetime | None = None
    asset_purchase_dt: datetime | None = None
    asset_purchase_ref: str | None = None
    warranty_period: int | None = None
    asset_value: float | None = None
    asset_currency: str | None = None
    asset_release_url: str | None = None
    asset_status: str | None = None
    asset_spec_values: list[AssetSpecValue] | None = None

    can_create_release: bool
    asset_class_upgrade_supported: bool

    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None

    asset_code: str | None = None
    asset_serial_no: str | None = None
    asset_criticality: str | None = None


class AssetInventoryReportRow(BaseModel):
    asset_uuid: uuid.UUID
    asset_id: str
    asset_name: str
    asset_class: str | None = None
    asset_category: str | None = None
    asset_sub_category: str | None = None
    asset_type: str | None = None
    org_node_id: uuid.UUID
    org_node_name: str | None = None
    org_node_code: str | None = None
    supplier_id: uuid.UUID | None = None
    supplier_name: str | None = None
    asset_owner: str | None = None
    criticality_class: str | None = None
    lifecycle_state: str | None = None
    asset_status: str | None = None
    serial_number: str | None = None
    tag_number: str | None = None
    legacy_id: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    asset_commission_dt: datetime | None = None
    asset_purchase_dt: datetime | None = None


class AssetInventoryReportResponse(BaseModel):
    scope: Literal["enterprise", "unit"]
    org_id: uuid.UUID | None = None
    org_name: str | None = None
    includes_descendants: bool
    total: int
    items: list[AssetInventoryReportRow]


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
