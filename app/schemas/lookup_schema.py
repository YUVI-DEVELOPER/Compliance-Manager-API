from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LookupMasterCreateRequest(BaseModel):
    lookup_key: str = Field(..., min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=250)
    is_active: bool = True
    created_by: str | None = Field(default=None, max_length=150)


class LookupMasterUpdateRequest(BaseModel):
    description: str | None = Field(default=None, max_length=250)
    is_active: bool | None = None
    modified_by: str | None = Field(default=None, max_length=150)


class LookupMasterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lookup_key: str
    description: str | None = None
    is_active: bool
    valueCount: int = 0
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class LookupValueCreateRequest(BaseModel):
    lookup_id: int
    code: str = Field(..., min_length=1, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=150)
    sort_order: int | None = 0
    is_active: bool = True
    metadata: dict[str, Any] | None = None
    created_by: str | None = Field(default=None, max_length=150)


class LookupValueUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    display_name: str | None = Field(default=None, min_length=1, max_length=150)
    sort_order: int | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None
    modified_by: str | None = Field(default=None, max_length=150)


class LookupValueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lookup_id: int
    code: str
    display_name: str
    sort_order: int | None = None
    is_active: bool
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_json")
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
