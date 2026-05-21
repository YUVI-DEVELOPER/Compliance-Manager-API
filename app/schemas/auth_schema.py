from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class AuthUserProfile(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=100)


class LoginSuccessResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUserProfile


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=100)
    new_password: str = Field(..., min_length=8, max_length=100)


class CurrentUser(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
