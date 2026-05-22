from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit_actions
from app.core.auth_dependencies import get_current_user
from app.core.database import get_db
from app.schemas.audit_log_schema import (
    AuditLogDetailResponse,
    AuditLogFilterParams,
    AuditLogListResponse,
    AuditLogPagination,
    AuditLogSummaryResponse,
)
from app.schemas.auth_schema import CurrentUser
from app.services.audit_log_service import (
    create_audit_log,
    export_audit_logs,
    get_audit_log_by_id,
    get_audit_log_summary,
    list_audit_logs,
)

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


def _is_admin(current_user: CurrentUser) -> bool:
    return "ADMIN" in {role.upper() for role in current_user.roles}


def _require_audit_access(current_user: CurrentUser, permission: str) -> None:
    if _is_admin(current_user) or permission in current_user.permissions:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")


def _filters_from_query(
    page: int,
    limit: int,
    from_date: datetime | None,
    to_date: datetime | None,
    module_name: str | None,
    entity_name: str | None,
    action: str | None,
    performed_by_user_id: str | None,
    performed_by_email: str | None,
    performed_by_role: str | None,
    record_id: str | None,
    status_value: str | None,
    search: str | None,
) -> AuditLogFilterParams:
    return AuditLogFilterParams(
        page=page,
        limit=limit,
        from_date=from_date,
        to_date=to_date,
        module_name=module_name,
        entity_name=entity_name,
        action=action,
        performed_by_user_id=performed_by_user_id,
        performed_by_email=performed_by_email,
        performed_by_role=performed_by_role,
        record_id=record_id,
        status=status_value,
        search=search,
    )


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs_api(
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    module_name: str | None = Query(default=None),
    entity_name: str | None = Query(default=None),
    action: str | None = Query(default=None),
    performed_by_user_id: str | None = Query(default=None),
    performed_by_email: str | None = Query(default=None),
    performed_by_role: str | None = Query(default=None),
    record_id: str | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    _require_audit_access(current_user, "AUDIT_LOG_VIEW")
    filters = _filters_from_query(
        page,
        limit,
        from_date,
        to_date,
        module_name,
        entity_name,
        action,
        performed_by_user_id,
        performed_by_email,
        performed_by_role,
        record_id,
        status_value,
        search,
    )
    rows, total = await list_audit_logs(db, filters)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Audit Log",
        entity_name="Audit Log",
        table_name="audit_log",
        action=audit_actions.AUDIT_LOG_VIEWED,
        event_description="Audit log list viewed",
        new_data={"filters": filters.model_dump(mode="json")},
    )
    await db.commit()
    return AuditLogListResponse(
        success=True,
        message="Audit logs retrieved successfully",
        data=rows,
        pagination=AuditLogPagination(page=page, limit=limit, total=total),
    )


@router.get("/summary", response_model=AuditLogSummaryResponse)
async def audit_log_summary_api(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuditLogSummaryResponse:
    _require_audit_access(current_user, "AUDIT_LOG_VIEW")
    return AuditLogSummaryResponse(
        success=True,
        message="Audit log summary retrieved successfully",
        data=await get_audit_log_summary(db),
    )


@router.get("/export")
async def export_audit_logs_api(
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10000, ge=1, le=10000),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    module_name: str | None = Query(default=None),
    entity_name: str | None = Query(default=None),
    action: str | None = Query(default=None),
    performed_by_user_id: str | None = Query(default=None),
    performed_by_email: str | None = Query(default=None),
    performed_by_role: str | None = Query(default=None),
    record_id: str | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    _require_audit_access(current_user, "AUDIT_LOG_EXPORT")
    filters = _filters_from_query(
        page,
        limit,
        from_date,
        to_date,
        module_name,
        entity_name,
        action,
        performed_by_user_id,
        performed_by_email,
        performed_by_role,
        record_id,
        status_value,
        search,
    )
    rows = await export_audit_logs(db, filters)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Audit Log",
        entity_name="Audit Log",
        table_name="audit_log",
        action=audit_actions.AUDIT_LOG_EXPORTED,
        event_description="Audit log exported",
        new_data={"filters": filters.model_dump(mode="json"), "row_count": len(rows)},
    )
    await db.commit()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Event Time", "User", "Email", "Role", "Module", "Entity", "Action", "Record ID", "Status"])
    for row in rows:
        writer.writerow(
            [
                row.event_time.isoformat(),
                row.performed_by.name or "",
                row.performed_by.email or "",
                row.performed_by.role or "",
                row.module_name,
                row.entity_name,
                row.action,
                row.record_id or "",
                row.status,
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-log-export.csv"'},
    )


@router.get("/{audit_id}", response_model=AuditLogDetailResponse)
async def get_audit_log_api(
    audit_id: int,
    request: Request,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuditLogDetailResponse:
    _require_audit_access(current_user, "AUDIT_LOG_VIEW")
    row = await get_audit_log_by_id(db, audit_id)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Audit Log",
        entity_name="Audit Log",
        table_name="audit_log",
        record_id=audit_id,
        action=audit_actions.AUDIT_LOG_VIEWED,
        event_description="Audit log detail viewed",
        new_data={"audit_id": audit_id},
    )
    await db.commit()
    return AuditLogDetailResponse(success=True, message="Audit log retrieved successfully", data=row)
