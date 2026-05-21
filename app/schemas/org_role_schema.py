import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class OrgRoleCreateRequest(BaseModel):
    role_name: str = Field(..., min_length=1, max_length=150)
    role_raci: str = Field(..., min_length=1, max_length=50)
    ownership: str = Field(..., min_length=1, max_length=150)
    role_type: str = Field(..., min_length=1, max_length=50)
    is_active: bool = True
    created_by: str | None = Field(default=None, max_length=150)


class OrgRoleUpdateRequest(BaseModel):
    role_name: str | None = Field(default=None, min_length=1, max_length=150)
    role_raci: str | None = Field(default=None, min_length=1, max_length=50)
    ownership: str | None = Field(default=None, min_length=1, max_length=150)
    role_type: str | None = Field(default=None, min_length=1, max_length=50)
    is_active: bool | None = None
    modified_by: str | None = Field(default=None, max_length=150)


class OrgRoleActionCreateRequest(BaseModel):
    seq: int = Field(..., ge=1)
    action_type: str = Field(..., min_length=1, max_length=50)
    action: str = Field(..., min_length=1, max_length=250)
    created_by: str | None = Field(default=None, max_length=150)


class OrgRoleActionUpdateRequest(BaseModel):
    seq: int | None = Field(default=None, ge=1)
    action_type: str | None = Field(default=None, min_length=1, max_length=50)
    action: str | None = Field(default=None, min_length=1, max_length=250)
    modified_by: str | None = Field(default=None, max_length=150)


class OrgEntityRoleAssignmentCreateRequest(BaseModel):
    role_id: uuid.UUID
    person_name: str = Field(..., min_length=1, max_length=150)
    person_email: EmailStr | None = None
    employee_code: str | None = Field(default=None, max_length=50)
    remarks: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    created_by: str | None = Field(default=None, max_length=150)


class OrgEntityRoleAssignmentUpdateRequest(BaseModel):
    org_id: uuid.UUID | None = None
    role_id: uuid.UUID | None = None
    person_name: str | None = Field(default=None, min_length=1, max_length=150)
    person_email: EmailStr | None = None
    employee_code: str | None = Field(default=None, max_length=50)
    remarks: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    modified_by: str | None = Field(default=None, max_length=150)


class OrgRoleActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role_id: uuid.UUID
    seq: int
    action_type: str
    action: str
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class OrgRoleSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role_name: str
    role_raci: str
    ownership: str
    role_type: str
    is_active: bool


class OrgRoleResponse(OrgRoleSummaryResponse):
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None
    is_deleted: bool
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    action_count: int = 0
    active_assignment_count: int = 0


class OrgRoleDetailResponse(OrgRoleResponse):
    actions: list[OrgRoleActionResponse] = Field(default_factory=list)


class OrgEntityRoleAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    role_id: uuid.UUID
    person_name: str
    person_email: str | None = None
    employee_code: str | None = None
    remarks: str | None = None
    is_active: bool
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None
    is_deleted: bool
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    role: OrgRoleSummaryResponse | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
