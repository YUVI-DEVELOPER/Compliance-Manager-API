import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AssetLocationCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    building_reference: str = Field(
        ...,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("building_reference", "buildingReference"),
    )
    floor_reference: str = Field(
        ...,
        min_length=1,
        max_length=60,
        validation_alias=AliasChoices("floor_reference", "floorReference"),
    )
    local_reference: str = Field(
        ...,
        min_length=1,
        max_length=150,
        validation_alias=AliasChoices("local_reference", "localReference"),
    )
    remarks: str | None = Field(default=None, max_length=500)
    created_by: str = Field(..., min_length=1, max_length=150, validation_alias=AliasChoices("created_by", "createdBy"))


class AssetLocationUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    building_reference: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        validation_alias=AliasChoices("building_reference", "buildingReference"),
    )
    floor_reference: str | None = Field(
        default=None,
        min_length=1,
        max_length=60,
        validation_alias=AliasChoices("floor_reference", "floorReference"),
    )
    local_reference: str | None = Field(
        default=None,
        min_length=1,
        max_length=150,
        validation_alias=AliasChoices("local_reference", "localReference"),
    )
    remarks: str | None = Field(default=None, max_length=500)
    modified_by: str | None = Field(
        default=None,
        max_length=150,
        validation_alias=AliasChoices("modified_by", "modifiedBy"),
    )


class AssetLocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    location_id: uuid.UUID
    asset_uuid: uuid.UUID
    asset_id: str | None = None
    asset_name: str | None = None
    org_node_id: uuid.UUID | None = None
    org_node_name: str | None = None
    building_reference: str
    floor_reference: str
    local_reference: str
    remarks: str | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
