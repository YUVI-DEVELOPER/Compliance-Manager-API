import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.asset_location import AssetLocation
from app.schemas.asset_location_schema import AssetLocationCreate, AssetLocationResponse, AssetLocationUpdate


class ServiceValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class ServiceNotFoundError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ServiceConflictError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_required(value: str | None, field_name: str, max_len: int) -> str:
    if value is None:
        raise ServiceValidationError(f"{field_name} is required")
    normalized = value.strip()
    if not normalized:
        raise ServiceValidationError(f"{field_name} is required")
    if len(normalized) > max_len:
        raise ServiceValidationError(f"{field_name} must not exceed {max_len} characters")
    return normalized


def _normalize_optional_string(value: str | None, field_name: str, max_len: int) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    if len(normalized) > max_len:
        raise ServiceValidationError(f"{field_name} must not exceed {max_len} characters")
    return normalized


def _asset_location_query() -> Select[tuple[AssetLocation]]:
    return select(AssetLocation).options(
        selectinload(AssetLocation.asset).selectinload(Asset.org_node),
    )


async def _get_asset_by_uuid(db: AsyncSession, asset_uuid: uuid.UUID) -> Asset | None:
    stmt = select(Asset).where(Asset.asset_uuid == asset_uuid)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_asset_location_model(db: AsyncSession, asset_uuid: uuid.UUID) -> AssetLocation | None:
    stmt = _asset_location_query().where(AssetLocation.asset_uuid == asset_uuid)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _validate_asset_reference(db: AsyncSession, asset_uuid: uuid.UUID) -> Asset:
    asset = await _get_asset_by_uuid(db, asset_uuid)
    if asset is None:
        raise ServiceNotFoundError("Asset not found")
    return asset


def _normalize_location_payload(
    *,
    building_reference: str,
    floor_reference: str,
    local_reference: str,
    remarks: str | None,
) -> dict[str, object]:
    return {
        "building_reference": _normalize_required(building_reference, "building_reference", 100),
        "floor_reference": _normalize_required(floor_reference, "floor_reference", 60),
        "local_reference": _normalize_required(local_reference, "local_reference", 150),
        "remarks": _normalize_optional_string(remarks, "remarks", 500),
    }


def _build_asset_location_response(location: AssetLocation) -> AssetLocationResponse:
    asset = location.asset
    org_node = asset.org_node if asset is not None else None
    return AssetLocationResponse(
        location_id=location.location_id,
        asset_uuid=location.asset_uuid,
        asset_id=asset.asset_id if asset is not None else None,
        asset_name=asset.asset_name if asset is not None else None,
        org_node_id=asset.org_node_id if asset is not None else None,
        org_node_name=org_node.name if org_node is not None else None,
        building_reference=location.building_reference,
        floor_reference=location.floor_reference,
        local_reference=location.local_reference,
        remarks=location.remarks,
        created_by=location.created_by,
        created_dt=location.created_dt,
        modified_by=location.modified_by,
        modified_dt=location.modified_dt,
    )


def _conflict_message_from_integrity_error(exc: IntegrityError) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    if "uq_asset_location_asset_uuid" in message or "asset_uuid" in message:
        return "Asset location already exists for this asset"
    return "Operation failed due to a data conflict"


async def get_asset_location_by_asset(db: AsyncSession, asset_uuid: uuid.UUID) -> AssetLocationResponse | None:
    await _validate_asset_reference(db, asset_uuid)
    location = await _get_asset_location_model(db, asset_uuid)
    if location is None:
        return None
    return _build_asset_location_response(location)


async def create_asset_location(
    db: AsyncSession,
    asset_uuid: uuid.UUID,
    payload: AssetLocationCreate,
) -> AssetLocationResponse:
    await _validate_asset_reference(db, asset_uuid)

    duplicate = await _get_asset_location_model(db, asset_uuid)
    if duplicate is not None:
        raise ServiceConflictError("Asset location already exists for this asset")

    normalized = _normalize_location_payload(
        building_reference=payload.building_reference,
        floor_reference=payload.floor_reference,
        local_reference=payload.local_reference,
        remarks=payload.remarks,
    )

    now = datetime.now(UTC)
    created_by = _normalize_required(payload.created_by, "created_by", 150)
    location = AssetLocation(
        asset_uuid=asset_uuid,
        **normalized,
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(location)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_asset_location_by_asset(db, asset_uuid)


async def update_asset_location(
    db: AsyncSession,
    asset_uuid: uuid.UUID,
    payload: AssetLocationUpdate,
) -> AssetLocationResponse:
    location = await _get_asset_location_model(db, asset_uuid)
    if location is None:
        if await _get_asset_by_uuid(db, asset_uuid) is None:
            raise ServiceNotFoundError("Asset not found")
        raise ServiceNotFoundError("Asset location not found")

    updates = payload.model_dump(exclude_unset=True)

    required_fields = (
        "building_reference",
        "floor_reference",
        "local_reference",
    )
    for field_name in required_fields:
        if field_name in updates and updates[field_name] is None:
            raise ServiceValidationError(f"{field_name} cannot be null")

    normalized = _normalize_location_payload(
        building_reference=updates.get("building_reference", location.building_reference),
        floor_reference=updates.get("floor_reference", location.floor_reference),
        local_reference=updates.get("local_reference", location.local_reference),
        remarks=updates.get("remarks", location.remarks),
    )

    for field_name, field_value in normalized.items():
        setattr(location, field_name, field_value)

    if "modified_by" in updates:
        location.modified_by = _normalize_optional_string(updates["modified_by"], "modified_by", 150)
    location.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_asset_location_by_asset(db, asset_uuid)


async def delete_asset_location(db: AsyncSession, asset_uuid: uuid.UUID) -> None:
    location = await _get_asset_location_model(db, asset_uuid)
    if location is None:
        if await _get_asset_by_uuid(db, asset_uuid) is None:
            raise ServiceNotFoundError("Asset not found")
        raise ServiceNotFoundError("Asset location not found")

    try:
        await db.delete(location)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete asset location") from exc
