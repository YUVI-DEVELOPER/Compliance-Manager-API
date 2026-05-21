from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PermissionCreateRequest(BaseModel):
    permission_code: str = Field(..., min_length=2, max_length=100)
    permission_name: str = Field(..., min_length=1, max_length=150)
    module_name: str = Field(..., min_length=1, max_length=80)
    action_name: str = Field(..., min_length=1, max_length=80)
    description: str | None = None
    is_system_permission: bool = False
    is_active: bool = True


class PermissionUpdateRequest(BaseModel):
    permission_name: str | None = Field(default=None, min_length=1, max_length=150)
    module_name: str | None = Field(default=None, min_length=1, max_length=80)
    action_name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    permission_code: str
    permission_name: str
    module_name: str
    action_name: str
    description: str | None = None
    is_system_permission: bool
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RoleCreateRequest(BaseModel):
    role_code: str = Field(..., min_length=2, max_length=80)
    role_name: str = Field(..., min_length=1, max_length=150)
    description: str | None = None
    permission_codes: list[str] = Field(default_factory=list)
    permission_group_codes: list[str] = Field(default_factory=list)
    is_active: bool = True


class RoleUpdateRequest(BaseModel):
    role_name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None


class RolePermissionAssignmentRequest(BaseModel):
    permission_codes: list[str] = Field(default_factory=list)


class RolePermissionGroupAssignmentRequest(BaseModel):
    permission_group_codes: list[str] = Field(default_factory=list)


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role_code: str
    role_name: str
    description: str | None = None
    is_system_role: bool
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    permissions: list[str] = Field(default_factory=list)
    direct_permissions: list[str] = Field(default_factory=list)
    permission_groups: list[str] = Field(default_factory=list)


class PermissionGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    group_code: str
    group_name: str
    module_name: str
    description: str | None = None
    display_order: int
    is_system_group: bool
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    permission_codes: list[str] = Field(default_factory=list)


class GroupedPermissionsResponse(BaseModel):
    module_name: str
    permissions: list[PermissionResponse]


class GroupedPermissionGroupsResponse(BaseModel):
    module_name: str
    permission_groups: list[PermissionGroupResponse]
