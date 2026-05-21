import re
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lookup_master import LookupMaster
from app.models.lookup_value import LookupValue
from app.schemas.lookup_schema import (
    LookupMasterCreateRequest,
    LookupMasterResponse,
    LookupMasterUpdateRequest,
    LookupValueCreateRequest,
    LookupValueResponse,
    LookupValueUpdateRequest,
)

LOOKUP_KEY_PATTERN = re.compile(r"^[A-Z0-9_]{1,50}$")
LOOKUP_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,50}$")


class ServiceValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class ServiceNotFoundError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ServiceConflictError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _normalize_lookup_key(lookup_key: str) -> str:
    normalized = lookup_key.strip().upper()
    if not normalized:
        raise ServiceValidationError("lookup_key is required")
    if not LOOKUP_KEY_PATTERN.fullmatch(normalized):
        raise ServiceValidationError("lookup_key must be uppercase, no spaces, max 50 chars")
    return normalized


def _normalize_code(code: str) -> str:
    normalized = code.strip().upper()
    if not normalized:
        raise ServiceValidationError("code is required")
    if not LOOKUP_CODE_PATTERN.fullmatch(normalized):
        raise ServiceValidationError("code must be uppercase, no spaces, max 50 chars")
    return normalized


def _normalize_display_name(display_name: str) -> str:
    normalized = display_name.strip()
    if not normalized:
        raise ServiceValidationError("display_name is required")
    if len(normalized) > 150:
        raise ServiceValidationError("display_name must not exceed 150 characters")
    return normalized


def _normalize_description(description: str | None) -> str | None:
    if description is None:
        return None
    normalized = description.strip()
    if not normalized:
        return None
    if len(normalized) > 250:
        raise ServiceValidationError("description must not exceed 250 characters")
    return normalized


def _normalize_metadata(metadata: dict | None) -> dict | None:
    if metadata is None:
        return None
    if not isinstance(metadata, dict):
        raise ServiceValidationError("metadata must be a JSON object")
    return metadata or None


async def _get_master_by_id(db: AsyncSession, master_id: int) -> LookupMaster | None:
    stmt = select(LookupMaster).where(LookupMaster.id == master_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_master_by_key(db: AsyncSession, lookup_key: str) -> LookupMaster | None:
    stmt = select(LookupMaster).where(LookupMaster.lookup_key == lookup_key)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_active_master_by_key(db: AsyncSession, lookup_key: str) -> LookupMaster | None:
    stmt = select(LookupMaster).where(
        LookupMaster.lookup_key == lookup_key,
        LookupMaster.is_active.is_(True),
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_value_by_id(db: AsyncSession, value_id: int) -> LookupValue | None:
    stmt = select(LookupValue).where(LookupValue.id == value_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_value_by_lookup_and_code(db: AsyncSession, lookup_id: int, code: str) -> LookupValue | None:
    stmt = select(LookupValue).where(
        LookupValue.lookup_id == lookup_id,
        LookupValue.code == code,
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _has_active_values(db: AsyncSession, lookup_id: int) -> bool:
    stmt = (
        select(LookupValue.id)
        .where(LookupValue.lookup_id == lookup_id, LookupValue.is_active.is_(True))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first() is not None


def _master_query(active_only: bool) -> Select[tuple[LookupMaster]]:
    active_value_counts = (
        select(
            LookupValue.lookup_id,
            func.count(LookupValue.id).label("valueCount"),
        )
        .where(LookupValue.is_active.is_(True))
        .group_by(LookupValue.lookup_id)
        .subquery()
    )

    stmt = (
        select(
            LookupMaster,
            func.coalesce(active_value_counts.c.valueCount, 0).label("valueCount"),
        )
        .outerjoin(active_value_counts, active_value_counts.c.lookup_id == LookupMaster.id)
    )
    if active_only:
        stmt = stmt.where(LookupMaster.is_active.is_(True))
    return stmt.order_by(LookupMaster.lookup_key.asc())


def _build_master_response(master: LookupMaster, value_count: int) -> LookupMasterResponse:
    return LookupMasterResponse(
        id=master.id,
        lookup_key=master.lookup_key,
        description=master.description,
        is_active=master.is_active,
        valueCount=value_count,
        created_by=master.created_by,
        created_dt=master.created_dt,
        modified_by=master.modified_by,
        modified_dt=master.modified_dt,
    )


async def get_lookup_masters(db: AsyncSession, active_only: bool = False) -> list[LookupMasterResponse]:
    result = await db.execute(_master_query(active_only=active_only))
    rows = result.all()
    return [
        _build_master_response(master, value_count)
        for master, value_count in rows
    ]


async def get_lookup_master_by_id(db: AsyncSession, master_id: int) -> LookupMasterResponse:
    stmt = _master_query(active_only=False).where(LookupMaster.id == master_id)
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        raise ServiceNotFoundError("Lookup master not found")
    master, value_count = row
    return _build_master_response(master, value_count)


async def create_lookup_master(
    db: AsyncSession,
    payload: LookupMasterCreateRequest,
) -> LookupMasterResponse:
    lookup_key = _normalize_lookup_key(payload.lookup_key)
    description = _normalize_description(payload.description)

    existing = await _get_master_by_key(db, lookup_key)
    if existing is not None:
        raise ServiceConflictError("lookup_key already exists")

    master = LookupMaster(
        lookup_key=lookup_key,
        description=description,
        is_active=payload.is_active,
        created_by=payload.created_by,
        created_dt=datetime.now(UTC),
    )
    db.add(master)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("lookup_key already exists") from exc

    await db.refresh(master)
    return LookupMasterResponse.model_validate(master)


async def update_lookup_master(
    db: AsyncSession,
    master_id: int,
    payload: LookupMasterUpdateRequest,
) -> LookupMasterResponse:
    master = await _get_master_by_id(db, master_id)
    if master is None:
        raise ServiceNotFoundError("Lookup master not found")

    updates = payload.model_dump(exclude_unset=True)

    if "is_active" in updates and updates["is_active"] is False and master.is_active:
        if await _has_active_values(db, master.id):
            raise ServiceConflictError("Cannot deactivate master with active values")

    if "description" in updates:
        master.description = _normalize_description(updates["description"])

    if "is_active" in updates and updates["is_active"] is not None:
        master.is_active = updates["is_active"]

    if "modified_by" in updates:
        master.modified_by = updates["modified_by"]

    master.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to update lookup master") from exc

    await db.refresh(master)
    return LookupMasterResponse.model_validate(master)


async def delete_lookup_master(db: AsyncSession, master_id: int, modified_by: str | None = None) -> None:
    master = await _get_master_by_id(db, master_id)
    if master is None:
        raise ServiceNotFoundError("Lookup master not found")

    if await _has_active_values(db, master.id):
        raise ServiceConflictError("Cannot delete master with active values")

    master.is_active = False
    master.modified_by = modified_by
    master.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete lookup master") from exc


async def get_active_lookup_values(db: AsyncSession, lookup_key: str) -> list[LookupValueResponse]:
    normalized_key = _normalize_lookup_key(lookup_key)
    master = await _get_active_master_by_key(db, normalized_key)
    if master is None:
        raise ServiceNotFoundError("Active lookup key not found")

    stmt = (
        select(LookupValue)
        .where(
            LookupValue.lookup_id == master.id,
            LookupValue.is_active.is_(True),
        )
        .order_by(LookupValue.sort_order.asc().nulls_last(), LookupValue.code.asc())
    )
    result = await db.execute(stmt)
    values = result.scalars().all()
    return [LookupValueResponse.model_validate(value) for value in values]


async def get_lookup_value_by_id(db: AsyncSession, value_id: int) -> LookupValueResponse:
    value = await _get_value_by_id(db, value_id)
    if value is None:
        raise ServiceNotFoundError("Lookup value not found")
    return LookupValueResponse.model_validate(value)


async def create_lookup_value(
    db: AsyncSession,
    payload: LookupValueCreateRequest,
) -> LookupValueResponse:
    master = await _get_master_by_id(db, payload.lookup_id)
    if master is None:
        raise ServiceNotFoundError("Lookup master not found")
    if not master.is_active:
        raise ServiceValidationError("Lookup master is inactive")

    normalized_code = _normalize_code(payload.code)
    normalized_display_name = _normalize_display_name(payload.display_name)

    duplicate = await _get_value_by_lookup_and_code(db, payload.lookup_id, normalized_code)
    if duplicate is not None:
        raise ServiceConflictError("Lookup value code already exists for this lookup")

    value = LookupValue(
        lookup_id=payload.lookup_id,
        code=normalized_code,
        display_name=normalized_display_name,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
        metadata_json=_normalize_metadata(payload.metadata),
        created_by=payload.created_by,
        created_dt=datetime.now(UTC),
    )
    db.add(value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Lookup value code already exists for this lookup") from exc

    await db.refresh(value)
    return LookupValueResponse.model_validate(value)


async def update_lookup_value(
    db: AsyncSession,
    value_id: int,
    payload: LookupValueUpdateRequest,
) -> LookupValueResponse:
    value = await _get_value_by_id(db, value_id)
    if value is None:
        raise ServiceNotFoundError("Lookup value not found")

    updates = payload.model_dump(exclude_unset=True)

    if "code" in updates and updates["code"] is not None:
        normalized_code = _normalize_code(updates["code"])
        if normalized_code != value.code:
            duplicate = await _get_value_by_lookup_and_code(db, value.lookup_id, normalized_code)
            if duplicate is not None and duplicate.id != value.id:
                raise ServiceConflictError("Lookup value code already exists for this lookup")
            value.code = normalized_code

    if "display_name" in updates and updates["display_name"] is not None:
        value.display_name = _normalize_display_name(updates["display_name"])

    if "sort_order" in updates:
        value.sort_order = updates["sort_order"]

    if "is_active" in updates and updates["is_active"] is not None:
        value.is_active = updates["is_active"]

    if "metadata" in updates:
        value.metadata_json = _normalize_metadata(updates["metadata"])

    if "modified_by" in updates:
        value.modified_by = updates["modified_by"]

    value.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Lookup value code already exists for this lookup") from exc

    await db.refresh(value)
    return LookupValueResponse.model_validate(value)


async def delete_lookup_value(db: AsyncSession, value_id: int, modified_by: str | None = None) -> None:
    value = await _get_value_by_id(db, value_id)
    if value is None:
        raise ServiceNotFoundError("Lookup value not found")

    value.is_active = False
    value.modified_by = modified_by
    value.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete lookup value") from exc
