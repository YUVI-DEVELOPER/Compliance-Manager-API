from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, time
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect as sa_inspect

from app.models.app_user import AppUser
from app.models.audit_log import AuditLog
from app.schemas.audit_log_schema import AuditActorRead, AuditLogFilterParams, AuditLogRead
from app.schemas.auth_schema import CurrentUser

logger = logging.getLogger("app.audit_log")

SENSITIVE_FIELD_NAMES = {
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "api_key",
    "private_key",
}
MASK_VALUE = "***MASKED***"


def _normalize_key(value: str) -> str:
    return value.lower().replace("-", "_").replace(" ", "_")


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def mask_sensitive_fields(data: Any) -> Any:
    if data is None:
        return None
    if isinstance(data, dict):
        masked: dict[str, Any] = {}
        for key, value in data.items():
            if _normalize_key(str(key)) in SENSITIVE_FIELD_NAMES:
                masked[str(key)] = MASK_VALUE
            else:
                masked[str(key)] = mask_sensitive_fields(value)
        return masked
    if isinstance(data, list):
        return [mask_sensitive_fields(item) for item in data]
    return _json_safe(data)


def serialize_model_to_dict(model: Any) -> dict[str, Any] | None:
    if model is None:
        return None
    if isinstance(model, dict):
        return mask_sensitive_fields(model)
    if hasattr(model, "model_dump"):
        return mask_sensitive_fields(model.model_dump(mode="json"))

    try:
        mapper = sa_inspect(model).mapper
    except Exception:
        return mask_sensitive_fields(dict(model)) if hasattr(model, "items") else None

    data: dict[str, Any] = {}
    for column in mapper.column_attrs:
        data[column.key] = getattr(model, column.key)
    return mask_sensitive_fields(data)


def compare_old_new_values(
    old_data: dict[str, Any] | None,
    new_data: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    old = mask_sensitive_fields(old_data) or {}
    new = mask_sensitive_fields(new_data) or {}
    changed_fields = sorted(
        key
        for key in set(old.keys()) | set(new.keys())
        if old.get(key) != new.get(key)
    )
    changed_old = {key: old.get(key) for key in changed_fields if key in old}
    changed_new = {key: new.get(key) for key in changed_fields if key in new}
    return changed_old or None, changed_new or None, changed_fields


def get_request_context(request: Request | None) -> dict[str, str | None]:
    if request is None:
        return {"ip_address": None, "user_agent": None, "request_id": None}
    forwarded_for = request.headers.get("x-forwarded-for")
    ip_address = forwarded_for.split(",")[0].strip() if forwarded_for else None
    if ip_address is None and request.client is not None:
        ip_address = request.client.host
    return {
        "ip_address": ip_address,
        "user_agent": request.headers.get("user-agent"),
        "request_id": request.headers.get("x-request-id"),
    }


async def get_actor_context(
    db: AsyncSession,
    current_user: CurrentUser | uuid.UUID | str | None,
) -> dict[str, str | None]:
    if current_user is None:
        return {
            "performed_by_user_id": None,
            "performed_by_name": None,
            "performed_by_email": None,
            "performed_by_role": None,
        }
    if isinstance(current_user, CurrentUser):
        return {
            "performed_by_user_id": str(current_user.id),
            "performed_by_name": current_user.full_name,
            "performed_by_email": str(current_user.email),
            "performed_by_role": current_user.roles[0] if current_user.roles else None,
        }

    actor_id = str(current_user)
    user: AppUser | None = None
    try:
        user = await db.get(AppUser, uuid.UUID(actor_id))
    except (ValueError, TypeError):
        user = None
    return {
        "performed_by_user_id": actor_id,
        "performed_by_name": user.full_name if user is not None else None,
        "performed_by_email": user.email if user is not None else None,
        "performed_by_role": None,
    }


async def create_audit_log(
    db: AsyncSession,
    *,
    request: Request | None = None,
    current_user: CurrentUser | uuid.UUID | str | None = None,
    module_name: str,
    entity_name: str,
    table_name: str | None = None,
    record_id: str | uuid.UUID | int | None = None,
    action: str,
    event_description: str | None = None,
    old_data: dict[str, Any] | None = None,
    new_data: dict[str, Any] | None = None,
    reason: str | None = None,
    status: str = "SUCCESS",
) -> AuditLog | None:
    try:
        operation_type = "UPDATE"
        if action.endswith("_CREATED") or action in {"LOGIN_SUCCESS", "LOGIN_FAILED"}:
            operation_type = "INSERT"
        elif action.endswith("_DEACTIVATED"):
            operation_type = "UPDATE"
        elif action.endswith("_EXPORTED") or action.endswith("_DOWNLOADED") or action.endswith("_VIEWED"):
            operation_type = "SELECT"

        masked_old = mask_sensitive_fields(old_data)
        masked_new = mask_sensitive_fields(new_data)
        if masked_old is not None and masked_new is not None:
            changed_old, changed_new, changed_fields = compare_old_new_values(masked_old, masked_new)
        else:
            changed_old = masked_old
            changed_new = masked_new
            changed_fields = sorted((masked_new or masked_old or {}).keys()) if isinstance(masked_new or masked_old, dict) else []

        request_context = get_request_context(request)
        actor_context = await get_actor_context(db, current_user)
        audit_log = AuditLog(
            module_name=module_name,
            entity_name=entity_name,
            table_name=table_name or entity_name,
            record_id=str(record_id) if record_id is not None else None,
            action=action,
            event_description=event_description,
            operation_type=operation_type[:10],
            record_pk={"id": str(record_id)} if record_id is not None else None,
            old_data=changed_old,
            new_data=changed_new,
            changed_columns=changed_fields,
            changed_fields=changed_fields,
            changed_by=actor_context["performed_by_user_id"],
            performed_by_user_id=actor_context["performed_by_user_id"],
            performed_by_name=actor_context["performed_by_name"],
            performed_by_email=actor_context["performed_by_email"],
            performed_by_role=actor_context["performed_by_role"],
            application_name="Compliance Manager",
            client_ip=request_context["ip_address"],
            reason=reason,
            ip_address=request_context["ip_address"],
            user_agent=request_context["user_agent"],
            status=status,
            request_id=request_context["request_id"],
        )
        db.add(audit_log)
        return audit_log
    except Exception:
        logger.exception("audit_log_create_failed action=%s module=%s entity=%s", action, module_name, entity_name)
        return None


def _audit_log_read(log: AuditLog) -> AuditLogRead:
    changed_fields = log.changed_fields
    if changed_fields is None and isinstance(log.changed_columns, list):
        changed_fields = log.changed_columns
    if changed_fields is None and isinstance(log.changed_columns, dict):
        changed_fields = list(log.changed_columns.keys())
    return AuditLogRead(
        audit_id=log.audit_id,
        event_time=log.event_time or log.changed_at,
        module_name=log.module_name,
        entity_name=log.entity_name,
        table_name=log.table_name,
        record_id=log.record_id,
        action=log.action,
        event_description=log.event_description,
        old_data=log.old_data,
        new_data=log.new_data,
        changed_fields=changed_fields or [],
        performed_by=AuditActorRead(
            user_id=log.performed_by_user_id or log.changed_by,
            name=log.performed_by_name,
            email=log.performed_by_email,
            role=log.performed_by_role,
        ),
        reason=log.reason,
        ip_address=log.ip_address or log.client_ip,
        user_agent=log.user_agent,
        status=log.status,
        request_id=log.request_id,
        created_at=log.created_at,
    )


def _apply_filters(stmt, filters: AuditLogFilterParams):
    if filters.from_date is not None:
        stmt = stmt.where(AuditLog.event_time >= filters.from_date)
    if filters.to_date is not None:
        to_date = filters.to_date
        if isinstance(to_date, datetime) and to_date.time() == time.min:
            to_date = datetime.combine(to_date.date(), time.max, tzinfo=to_date.tzinfo)
        stmt = stmt.where(AuditLog.event_time <= to_date)
    if filters.module_name:
        stmt = stmt.where(AuditLog.module_name.ilike(f"%{filters.module_name.strip()}%"))
    if filters.entity_name:
        stmt = stmt.where(AuditLog.entity_name.ilike(f"%{filters.entity_name.strip()}%"))
    if filters.action:
        stmt = stmt.where(AuditLog.action == filters.action.strip())
    if filters.performed_by_user_id:
        stmt = stmt.where(AuditLog.performed_by_user_id == filters.performed_by_user_id.strip())
    if filters.performed_by_email:
        stmt = stmt.where(AuditLog.performed_by_email.ilike(f"%{filters.performed_by_email.strip()}%"))
    if filters.performed_by_role:
        stmt = stmt.where(AuditLog.performed_by_role.ilike(f"%{filters.performed_by_role.strip()}%"))
    if filters.record_id:
        stmt = stmt.where(AuditLog.record_id.ilike(f"%{filters.record_id.strip()}%"))
    if filters.status:
        stmt = stmt.where(AuditLog.status == filters.status.strip().upper())
    if filters.search:
        pattern = f"%{filters.search.strip()}%"
        stmt = stmt.where(
            or_(
                AuditLog.module_name.ilike(pattern),
                AuditLog.entity_name.ilike(pattern),
                AuditLog.action.ilike(pattern),
                AuditLog.event_description.ilike(pattern),
                AuditLog.record_id.ilike(pattern),
                AuditLog.performed_by_name.ilike(pattern),
                AuditLog.performed_by_email.ilike(pattern),
                cast(AuditLog.old_data, String).ilike(pattern),
                cast(AuditLog.new_data, String).ilike(pattern),
            )
        )
    return stmt


async def list_audit_logs(
    db: AsyncSession,
    filters: AuditLogFilterParams,
) -> tuple[list[AuditLogRead], int]:
    base_stmt = _apply_filters(select(AuditLog), filters)
    total_result = await db.execute(select(func.count()).select_from(base_stmt.subquery()))
    total = int(total_result.scalar_one() or 0)
    stmt = (
        base_stmt.order_by(AuditLog.event_time.desc(), AuditLog.audit_id.desc())
        .offset((filters.page - 1) * filters.limit)
        .limit(filters.limit)
    )
    result = await db.execute(stmt)
    return [_audit_log_read(log) for log in result.scalars().all()], total


async def get_audit_log_by_id(db: AsyncSession, audit_id: int) -> AuditLogRead:
    log = await db.get(AuditLog, audit_id)
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    return _audit_log_read(log)


async def export_audit_logs(db: AsyncSession, filters: AuditLogFilterParams) -> list[AuditLogRead]:
    export_filters = filters.model_copy(update={"page": 1, "limit": 10000})
    rows, _ = await list_audit_logs(db, export_filters)
    return rows


async def get_audit_log_summary(db: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    today_start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    total_result = await db.execute(select(func.count(AuditLog.audit_id)))
    today_result = await db.execute(select(func.count(AuditLog.audit_id)).where(AuditLog.event_time >= today_start))
    failed_result = await db.execute(select(func.count(AuditLog.audit_id)).where(AuditLog.status != "SUCCESS"))
    critical_actions = [
        "USER_ROLE_ASSIGNED",
        "USER_ROLE_REMOVED",
        "PERMISSION_ASSIGNED",
        "PERMISSION_REMOVED",
        "ASSET_CRITICALITY_CHANGED",
        "ASSET_DEACTIVATED",
        "ROLE_DEACTIVATED",
    ]
    critical_result = await db.execute(
        select(func.count(AuditLog.audit_id)).where(AuditLog.action.in_(critical_actions))
    )
    return {
        "total_logs": int(total_result.scalar_one() or 0),
        "today_logs": int(today_result.scalar_one() or 0),
        "failed_actions": int(failed_result.scalar_one() or 0),
        "critical_changes": int(critical_result.scalar_one() or 0),
    }
