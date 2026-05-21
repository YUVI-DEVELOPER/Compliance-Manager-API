import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset_spec import AssetSpec
from app.models.lookup_master import LookupMaster
from app.models.lookup_value import LookupValue
from app.schemas.asset_spec_schema import AssetSpecCreateRequest, AssetSpecResponse, AssetSpecUpdateRequest

ASSET_SUB_CATEGORY_LOOKUP_KEY = "ASSET_SUB_CATEGORY"


class ServiceValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class ServiceNotFoundError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ServiceConflictError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _normalize_required_string(value: str | None, field_name: str, max_len: int) -> str:
    if value is None:
        raise ServiceValidationError(f"{field_name} is required")
    normalized = value.strip()
    if not normalized:
        raise ServiceValidationError(f"{field_name} is required")
    if len(normalized) > max_len:
        raise ServiceValidationError(f"{field_name} must not exceed {max_len} characters")
    return normalized


def _normalize_optional_string(value: str | None, field_name: str, max_len: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_len:
        raise ServiceValidationError(f"{field_name} must not exceed {max_len} characters")
    return normalized


def _asset_spec_query(*, include_inactive: bool = False) -> Select[tuple[AssetSpec]]:
    stmt = select(AssetSpec).options(selectinload(AssetSpec.asset_sub_category))
    if not include_inactive:
        stmt = stmt.where(AssetSpec.is_active.is_(True))
    return stmt.order_by(
        AssetSpec.asset_sub_category_id.asc(),
        AssetSpec.parameter_grouping.asc(),
        AssetSpec.parameter_seq.asc(),
    )


async def _get_spec_by_id(db: AsyncSession, asset_spec_id: uuid.UUID) -> AssetSpec | None:
    stmt = select(AssetSpec).options(selectinload(AssetSpec.asset_sub_category)).where(AssetSpec.asset_spec_id == asset_spec_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_active_sub_category(
    db: AsyncSession,
    asset_sub_category_id: int,
) -> LookupValue | None:
    stmt = (
        select(LookupValue)
        .join(LookupMaster, LookupValue.lookup_id == LookupMaster.id)
        .where(
            LookupValue.id == asset_sub_category_id,
            LookupMaster.lookup_key == ASSET_SUB_CATEGORY_LOOKUP_KEY,
            LookupMaster.is_active.is_(True),
            LookupValue.is_active.is_(True),
        )
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _validate_asset_sub_category(db: AsyncSession, asset_sub_category_id: int) -> LookupValue:
    if asset_sub_category_id <= 0:
        raise ServiceValidationError("asset_sub_category_id must be a positive integer")
    sub_category = await _get_active_sub_category(db, asset_sub_category_id)
    if sub_category is None:
        raise ServiceValidationError("asset_sub_category_id references an unknown or inactive asset sub-category")
    return sub_category


async def _has_active_duplicate(
    db: AsyncSession,
    *,
    asset_sub_category_id: int,
    parameter_grouping: str,
    parameter_name: str,
    exclude_spec_id: uuid.UUID | None = None,
) -> bool:
    stmt = select(AssetSpec.asset_spec_id).where(
        AssetSpec.asset_sub_category_id == asset_sub_category_id,
        func.lower(AssetSpec.parameter_grouping) == parameter_grouping.lower(),
        func.lower(AssetSpec.parameter_name) == parameter_name.lower(),
        AssetSpec.is_active.is_(True),
    )
    if exclude_spec_id is not None:
        stmt = stmt.where(AssetSpec.asset_spec_id != exclude_spec_id)
    result = await db.execute(stmt.limit(1))
    return result.first() is not None


def _build_response(spec: AssetSpec) -> AssetSpecResponse:
    sub_category = spec.asset_sub_category
    return AssetSpecResponse(
        asset_spec_id=spec.asset_spec_id,
        asset_sub_category_id=spec.asset_sub_category_id,
        asset_sub_category_code=sub_category.code if sub_category is not None else None,
        asset_sub_category_name=sub_category.display_name if sub_category is not None else None,
        parameter_seq=spec.parameter_seq,
        parameter_grouping=spec.parameter_grouping,
        parameter_name=spec.parameter_name,
        parameter_value=spec.parameter_value,
        guidelines=spec.guidelines,
        is_active=spec.is_active,
        created_by=spec.created_by,
        created_dt=spec.created_dt,
        modified_by=spec.modified_by,
        modified_dt=spec.modified_dt,
    )


async def get_asset_specs(
    db: AsyncSession,
    asset_sub_category_id: int | None = None,
    *,
    include_inactive: bool = False,
) -> list[AssetSpecResponse]:
    stmt = _asset_spec_query(include_inactive=include_inactive)
    if asset_sub_category_id is not None:
        stmt = stmt.where(AssetSpec.asset_sub_category_id == asset_sub_category_id)

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_build_response(row) for row in rows]


async def get_asset_spec_by_id(db: AsyncSession, asset_spec_id: uuid.UUID) -> AssetSpecResponse:
    spec = await _get_spec_by_id(db, asset_spec_id)
    if spec is None:
        raise ServiceNotFoundError("Asset spec not found")
    return _build_response(spec)


async def create_asset_spec(db: AsyncSession, payload: AssetSpecCreateRequest) -> AssetSpecResponse:
    sub_category = await _validate_asset_sub_category(db, payload.asset_sub_category_id)

    parameter_grouping = _normalize_required_string(payload.parameter_grouping, "parameter_grouping", 50)
    parameter_name = _normalize_required_string(payload.parameter_name, "parameter_name", 50)
    parameter_value = _normalize_required_string(payload.parameter_value, "parameter_value", 150)
    guidelines = _normalize_optional_string(payload.guidelines, "guidelines", 150)
    created_by = _normalize_required_string(payload.created_by, "created_by", 150)

    if await _has_active_duplicate(
        db,
        asset_sub_category_id=sub_category.id,
        parameter_grouping=parameter_grouping,
        parameter_name=parameter_name,
    ):
        raise ServiceConflictError("An active spec row with the same sub-category, grouping, and parameter name already exists")

    spec = AssetSpec(
        asset_sub_category_id=sub_category.id,
        parameter_grouping=parameter_grouping,
        parameter_name=parameter_name,
        parameter_value=parameter_value,
        guidelines=guidelines,
        is_active=payload.is_active,
        created_by=created_by,
        created_dt=datetime.now(UTC),
        modified_by=created_by,
        modified_dt=datetime.now(UTC),
    )
    db.add(spec)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to create asset spec") from exc

    await db.refresh(spec)
    return await get_asset_spec_by_id(db, spec.asset_spec_id)


async def update_asset_spec(
    db: AsyncSession,
    asset_spec_id: uuid.UUID,
    payload: AssetSpecUpdateRequest,
) -> AssetSpecResponse:
    spec = await _get_spec_by_id(db, asset_spec_id)
    if spec is None:
        raise ServiceNotFoundError("Asset spec not found")

    updates = payload.model_dump(exclude_unset=True)

    next_sub_category_id = spec.asset_sub_category_id
    if "asset_sub_category_id" in updates and updates["asset_sub_category_id"] is not None:
        sub_category = await _validate_asset_sub_category(db, updates["asset_sub_category_id"])
        next_sub_category_id = sub_category.id

    next_grouping = spec.parameter_grouping
    if "parameter_grouping" in updates and updates["parameter_grouping"] is not None:
        next_grouping = _normalize_required_string(updates["parameter_grouping"], "parameter_grouping", 50)

    next_name = spec.parameter_name
    if "parameter_name" in updates and updates["parameter_name"] is not None:
        next_name = _normalize_required_string(updates["parameter_name"], "parameter_name", 50)

    next_value = spec.parameter_value
    if "parameter_value" in updates and updates["parameter_value"] is not None:
        next_value = _normalize_required_string(updates["parameter_value"], "parameter_value", 150)

    next_guidelines = spec.guidelines
    if "guidelines" in updates:
        next_guidelines = _normalize_optional_string(updates["guidelines"], "guidelines", 150)

    next_is_active = spec.is_active
    if "is_active" in updates and updates["is_active"] is not None:
        next_is_active = updates["is_active"]

    if next_is_active and await _has_active_duplicate(
        db,
        asset_sub_category_id=next_sub_category_id,
        parameter_grouping=next_grouping,
        parameter_name=next_name,
        exclude_spec_id=spec.asset_spec_id,
    ):
        raise ServiceConflictError("An active spec row with the same sub-category, grouping, and parameter name already exists")

    spec.asset_sub_category_id = next_sub_category_id
    spec.parameter_grouping = next_grouping
    spec.parameter_name = next_name
    spec.parameter_value = next_value
    spec.guidelines = next_guidelines
    spec.is_active = next_is_active

    if "modified_by" in updates:
        spec.modified_by = _normalize_optional_string(updates["modified_by"], "modified_by", 150)

    spec.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to update asset spec") from exc

    await db.refresh(spec)
    return await get_asset_spec_by_id(db, spec.asset_spec_id)


async def delete_asset_spec(db: AsyncSession, asset_spec_id: uuid.UUID, modified_by: str | None = None) -> dict[str, object]:
    spec = await _get_spec_by_id(db, asset_spec_id)
    if spec is None:
        raise ServiceNotFoundError("Asset spec not found")

    spec.is_active = False
    spec.modified_by = _normalize_optional_string(modified_by, "modified_by", 150)
    spec.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete asset spec") from exc

    return {"asset_spec_id": asset_spec_id, "is_active": False}
