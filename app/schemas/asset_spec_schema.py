import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AssetSpecCreateRequest(BaseModel):
    asset_sub_category_id: int
    parameter_grouping: str = Field(..., min_length=1, max_length=50)
    parameter_name: str = Field(..., min_length=1, max_length=50)
    parameter_value: str = Field(..., min_length=1, max_length=150)
    guidelines: str | None = Field(default=None, max_length=150)
    is_active: bool = True
    created_by: str = Field(..., min_length=1, max_length=150)


class AssetSpecUpdateRequest(BaseModel):
    asset_sub_category_id: int | None = None
    parameter_grouping: str | None = Field(default=None, min_length=1, max_length=50)
    parameter_name: str | None = Field(default=None, min_length=1, max_length=50)
    parameter_value: str | None = Field(default=None, min_length=1, max_length=150)
    guidelines: str | None = Field(default=None, max_length=150)
    is_active: bool | None = None
    modified_by: str | None = Field(default=None, max_length=150)


class AssetSpecResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_spec_id: uuid.UUID
    asset_sub_category_id: int
    asset_sub_category_code: str | None = None
    asset_sub_category_name: str | None = None
    parameter_seq: int
    parameter_grouping: str
    parameter_name: str
    parameter_value: str
    guidelines: str | None = None
    is_active: bool
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class AssetSpecGroupResponse(BaseModel):
    parameter_grouping: str
    specs: list[AssetSpecResponse]


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
