from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AuditActorRead(BaseModel):
    user_id: str | None = None
    name: str | None = None
    email: EmailStr | str | None = None
    role: str | None = None


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_id: int
    event_time: datetime
    module_name: str
    entity_name: str
    table_name: str | None = None
    record_id: str | None = None
    action: str
    event_description: str | None = None
    old_data: dict[str, Any] | list[Any] | None = None
    new_data: dict[str, Any] | list[Any] | None = None
    changed_fields: list[str] = Field(default_factory=list)
    performed_by: AuditActorRead
    reason: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    status: str
    request_id: str | None = None
    created_at: datetime | None = None


class AuditLogPagination(BaseModel):
    page: int
    limit: int
    total: int


class AuditLogListResponse(BaseModel):
    success: bool
    message: str
    data: list[AuditLogRead]
    pagination: AuditLogPagination


class AuditLogDetailResponse(BaseModel):
    success: bool
    message: str
    data: AuditLogRead


class AuditLogFilterParams(BaseModel):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=20, ge=1, le=200)
    from_date: datetime | None = None
    to_date: datetime | None = None
    module_name: str | None = None
    entity_name: str | None = None
    action: str | None = None
    performed_by_user_id: str | None = None
    performed_by_email: str | None = None
    performed_by_role: str | None = None
    record_id: str | None = None
    status: str | None = None
    search: str | None = None


class AuditLogSummaryResponse(BaseModel):
    success: bool
    message: str
    data: dict[str, int]


class AuditLogExportResponse(BaseModel):
    success: bool
    message: str
    data: dict[str, Any]
