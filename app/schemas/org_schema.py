import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrgCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=250)
    code: str = Field(..., min_length=1, max_length=25)
    type: str = Field(..., min_length=1, max_length=50)
    status: str = Field(..., min_length=1, max_length=50)
    parent_id: uuid.UUID | None = None
    address: str | None = Field(default=None, max_length=250)
    city: str | None = Field(default=None, max_length=50)
    state: str | None = Field(default=None, max_length=50)
    country: str | None = Field(default=None, max_length=10)
    lat: float | None = None
    long: float | None = None
    created_by: str | None = Field(default=None, max_length=150)


class OrgUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=250)
    code: str | None = Field(default=None, min_length=1, max_length=25)
    type: str | None = Field(default=None, min_length=1, max_length=50)
    status: str | None = Field(default=None, min_length=1, max_length=50)
    parent_id: uuid.UUID | None = None
    address: str | None = Field(default=None, max_length=250)
    city: str | None = Field(default=None, max_length=50)
    state: str | None = Field(default=None, max_length=50)
    country: str | None = Field(default=None, max_length=10)
    lat: float | None = None
    long: float | None = None
    modified_by: str | None = Field(default=None, max_length=150)


class OrgResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parent_id: uuid.UUID | None = None
    name: str
    code: str
    type: str
    status: str
    address: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    lat: float | None = None
    long: float | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None
    is_deleted: bool
    deleted_at: datetime | None = None
    deleted_by: uuid.UUID | None = None


class OrgTreeResponse(OrgResponse):
    children: list["OrgTreeResponse"] = Field(default_factory=list)


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None


OrgTreeResponse.model_rebuild()
