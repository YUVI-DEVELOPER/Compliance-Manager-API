from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreateRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=150)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    designation: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    role_codes: list[str] = Field(default_factory=list, max_length=1)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=100)


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    email: EmailStr | None = None
    designation: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    is_locked: bool | None = None


class UserResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=100)


class UserRoleAssignmentRequest(BaseModel):
    role_codes: list[str] = Field(default_factory=list, max_length=1)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    email: EmailStr
    designation: str | None = None
    department: str | None = None
    phone: str | None = None
    is_active: bool
    is_locked: bool = False
    failed_login_count: int = 0
    last_login_at: datetime | None = None
    password_changed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class LoginResponse(BaseModel):
    success: bool
    message: str
    data: dict | None = None
