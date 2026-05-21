import logging
import re
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lookup_master import LookupMaster
from app.models.lookup_value import LookupValue
from app.models.org_structure import OrgStructure
from app.schemas.org_schema import OrgCreateRequest, OrgResponse, OrgTreeResponse, OrgUpdateRequest
from app.utils.tree_builder import build_org_tree

logger = logging.getLogger(__name__)

CODE_PATTERN = re.compile(r"^[A-Z0-9-]{3,25}$")
ORG_TYPE_LOOKUP_KEY = "ORG_TYPE"
ORG_STATUS_LOOKUP_KEY = "ORG_STATUS"
COUNTRY_LOOKUP_KEY = "COUNTRY"
CLOSED_STATUS = "CLOSED"


class ServiceValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class ServiceNotFoundError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ServiceConflictError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _active_org_query() -> Select[tuple[OrgStructure]]:
    return select(OrgStructure).where(OrgStructure.is_deleted.is_(False))


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise ServiceValidationError("name is required")
    if len(normalized) > 250:
        raise ServiceValidationError("name must not exceed 250 characters")
    return normalized


def _normalize_code(code: str) -> str:
    normalized = code.strip().upper()
    if not CODE_PATTERN.fullmatch(normalized):
        raise ServiceValidationError(
            "code must be 3-25 characters and contain only uppercase letters, numbers, and hyphen",
        )
    return normalized


def _normalize_lookup_input(value: str, field_name: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ServiceValidationError(f"{field_name} is required")
    if len(normalized) > 50:
        raise ServiceValidationError(f"{field_name} must not exceed 50 characters")
    return normalized


def _format_allowed_codes(codes: set[str]) -> str:
    return ", ".join(sorted(codes))


def _validate_required_location_fields(
    *,
    address: str | None,
    city: str | None,
    state: str | None,
    country: str | None,
) -> None:
    missing_fields = [
        field_name
        for field_name, value in (
            ("address", address),
            ("city", city),
            ("state", state),
            ("country", country),
        )
        if value is None
    ]
    if missing_fields:
        raise ServiceValidationError(
            f"Structured address is required. Missing: {', '.join(missing_fields)}",
        )


async def _get_active_lookup_codes(db: AsyncSession, lookup_key: str) -> set[str]:
    stmt = (
        select(LookupValue.code)
        .join(LookupMaster, LookupValue.lookup_id == LookupMaster.id)
        .where(
            LookupMaster.lookup_key == lookup_key,
            LookupMaster.is_active.is_(True),
            LookupValue.is_active.is_(True),
        )
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())


async def _normalize_lookup_code(
    db: AsyncSession,
    *,
    lookup_key: str,
    value: str,
    field_name: str,
) -> str:
    normalized = _normalize_lookup_input(value, field_name)
    active_codes = await _get_active_lookup_codes(db, lookup_key)
    if not active_codes:
        raise ServiceValidationError(f"{field_name} lookup is not configured")
    if normalized not in active_codes:
        raise ServiceValidationError(f"{field_name} must be one of: {_format_allowed_codes(active_codes)}")
    return normalized


async def _normalize_optional_lookup_code(
    db: AsyncSession,
    *,
    lookup_key: str,
    value: str | None,
    field_name: str,
) -> str | None:
    stripped = _strip_optional(value)
    if stripped is None:
        return None
    return await _normalize_lookup_code(
        db,
        lookup_key=lookup_key,
        value=stripped,
        field_name=field_name,
    )


async def _normalize_org_type(db: AsyncSession, node_type: str) -> str:
    return await _normalize_lookup_code(
        db,
        lookup_key=ORG_TYPE_LOOKUP_KEY,
        value=node_type,
        field_name="type",
    )


async def _normalize_org_status(db: AsyncSession, node_status: str) -> str:
    return await _normalize_lookup_code(
        db,
        lookup_key=ORG_STATUS_LOOKUP_KEY,
        value=node_status,
        field_name="status",
    )


async def _normalize_country(db: AsyncSession, country: str | None) -> str | None:
    return await _normalize_optional_lookup_code(
        db,
        lookup_key=COUNTRY_LOOKUP_KEY,
        value=country,
        field_name="country",
    )


async def _get_active_org_by_id(db: AsyncSession, org_id: uuid.UUID) -> OrgStructure | None:
    stmt = _active_org_query().where(OrgStructure.id == org_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_active_root_id(db: AsyncSession) -> uuid.UUID | None:
    stmt = (
        select(OrgStructure.id)
        .where(OrgStructure.is_deleted.is_(False), OrgStructure.parent_id.is_(None))
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _has_non_deleted_children(db: AsyncSession, org_id: uuid.UUID) -> bool:
    stmt = (
        select(OrgStructure.id)
        .where(OrgStructure.is_deleted.is_(False), OrgStructure.parent_id == org_id)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first() is not None


async def _get_active_parent_map(db: AsyncSession) -> dict[uuid.UUID, uuid.UUID | None]:
    stmt = select(OrgStructure.id, OrgStructure.parent_id).where(OrgStructure.is_deleted.is_(False))
    result = await db.execute(stmt)
    return {row[0]: row[1] for row in result.all()}


async def _get_active_org_by_code(db: AsyncSession, code: str) -> OrgStructure | None:
    stmt = _active_org_query().where(OrgStructure.code == code)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _validate_parent_reference(
    db: AsyncSession,
    org_id: uuid.UUID | None,
    parent_id: uuid.UUID | None,
) -> None:
    if parent_id is None:
        return

    if org_id is not None and parent_id == org_id:
        raise ServiceValidationError("Node cannot be its own parent")

    parent = await _get_active_org_by_id(db, parent_id)
    if parent is None:
        raise ServiceValidationError("Parent node not found")

    if parent.status == CLOSED_STATUS:
        raise ServiceValidationError("Cannot assign a CLOSED node as parent")

    if org_id is None:
        return

    parent_map = await _get_active_parent_map(db)
    cursor = parent_id
    while cursor is not None:
        if cursor == org_id:
            raise ServiceValidationError("Circular parent reference detected")
        cursor = parent_map.get(cursor)


async def get_org_tree(db: AsyncSession) -> list[OrgTreeResponse]:
    stmt = _active_org_query().order_by(OrgStructure.name.asc())
    result = await db.execute(stmt)
    org_rows = result.scalars().all()

    if not org_rows:
        return []

    return build_org_tree(org_rows)


async def get_org_by_id(db: AsyncSession, org_id: uuid.UUID) -> OrgResponse:
    org = await _get_active_org_by_id(db, org_id)
    if org is None:
        raise ServiceNotFoundError("Org node not found")

    return OrgResponse.model_validate(org)


async def create_org(db: AsyncSession, payload: OrgCreateRequest) -> OrgResponse:
    normalized_name = _normalize_name(payload.name)
    normalized_code = _normalize_code(payload.code)
    normalized_type = await _normalize_org_type(db, payload.type)
    normalized_status = await _normalize_org_status(db, payload.status)
    normalized_address = _strip_optional(payload.address)
    normalized_city = _strip_optional(payload.city)
    normalized_state = _strip_optional(payload.state)
    normalized_country = await _normalize_country(db, payload.country)

    _validate_required_location_fields(
        address=normalized_address,
        city=normalized_city,
        state=normalized_state,
        country=normalized_country,
    )

    if payload.parent_id is None:
        existing_root_id = await _get_active_root_id(db)
        if existing_root_id is not None:
            raise ServiceConflictError("Only one active root node is allowed")
    else:
        await _validate_parent_reference(db=db, org_id=None, parent_id=payload.parent_id)

    existing = await _get_active_org_by_code(db, normalized_code)
    if existing is not None:
        raise ServiceConflictError("Org code already exists")

    now = datetime.now(UTC)
    org = OrgStructure(
        parent_id=payload.parent_id,
        name=normalized_name,
        code=normalized_code,
        type=normalized_type,
        status=normalized_status,
        address=normalized_address,
        city=normalized_city,
        state=normalized_state,
        country=normalized_country,
        lat=payload.lat,
        long=payload.long,
        created_by=_strip_optional(payload.created_by),
        created_dt=now,
        modified_dt=now,
        is_deleted=False,
    )

    db.add(org)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "code" in str(exc.orig).lower() and "unique" in str(exc.orig).lower():
            raise ServiceConflictError("Org code already exists") from exc
        raise

    await db.refresh(org)
    logger.info("org_created id=%s code=%s", org.id, org.code)
    return OrgResponse.model_validate(org)


async def update_org(db: AsyncSession, org_id: uuid.UUID, payload: OrgUpdateRequest) -> OrgResponse:
    org = await _get_active_org_by_id(db, org_id)
    if org is None:
        raise ServiceNotFoundError("Org node not found")

    updates = payload.model_dump(exclude_unset=True)

    for required_field in ("name", "code", "type", "status"):
        if required_field in updates and updates[required_field] is None:
            raise ServiceValidationError(f"{required_field} cannot be null")

    next_parent_id = updates.get("parent_id", org.parent_id)
    next_type = await _normalize_org_type(db, updates["type"]) if "type" in updates else org.type
    next_status = await _normalize_org_status(db, updates["status"]) if "status" in updates else org.status

    if "name" in updates:
        updates["name"] = _normalize_name(updates["name"])

    if "code" in updates:
        updates["code"] = _normalize_code(updates["code"])
        if updates["code"] != org.code:
            duplicate = await _get_active_org_by_code(db, updates["code"])
            if duplicate is not None and duplicate.id != org.id:
                raise ServiceConflictError("Org code already exists")

    if "country" in updates:
        updates["country"] = await _normalize_country(db, updates["country"])

    for field_name in ("address", "city", "state", "created_by", "modified_by"):
        if field_name in updates:
            updates[field_name] = _strip_optional(updates[field_name])

    next_address = updates["address"] if "address" in updates else org.address
    next_city = updates["city"] if "city" in updates else org.city
    next_state = updates["state"] if "state" in updates else org.state
    next_country = updates["country"] if "country" in updates else org.country
    _validate_required_location_fields(
        address=next_address,
        city=next_city,
        state=next_state,
        country=next_country,
    )

    if "parent_id" in updates and updates["parent_id"] != org.parent_id and org.status == CLOSED_STATUS:
        raise ServiceValidationError("Structural changes are not allowed for CLOSED nodes")

    if "type" in updates and next_type != org.type and await _has_non_deleted_children(db, org_id):
        raise ServiceValidationError("Cannot change type for a node that has existing child nodes")

    if next_parent_id is None:
        stmt = (
            select(OrgStructure.id)
            .where(
                OrgStructure.is_deleted.is_(False),
                OrgStructure.parent_id.is_(None),
                OrgStructure.id != org_id,
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        other_root_id = result.scalars().first()
        if other_root_id is not None:
            raise ServiceConflictError("Only one active root node is allowed")
    else:
        await _validate_parent_reference(db=db, org_id=org_id, parent_id=next_parent_id)

    if "type" in updates:
        updates["type"] = next_type
    if "status" in updates:
        updates["status"] = next_status

    for field, value in updates.items():
        setattr(org, field, value)

    org.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "code" in str(exc.orig).lower() and "unique" in str(exc.orig).lower():
            raise ServiceConflictError("Org code already exists") from exc
        raise

    await db.refresh(org)
    logger.info("org_updated id=%s", org.id)
    return OrgResponse.model_validate(org)


async def delete_org(db: AsyncSession, org_id: uuid.UUID, deleted_by: uuid.UUID | None = None) -> None:
    org = await _get_active_org_by_id(db, org_id)
    if org is None:
        raise ServiceNotFoundError("Org node not found")

    child_stmt = _active_org_query().where(OrgStructure.parent_id == org_id)
    child_result = await db.execute(child_stmt)
    existing_child = child_result.scalars().first()

    if existing_child is not None:
        raise ServiceConflictError("Cannot delete node with existing child nodes")

    now = datetime.now(UTC)
    org.is_deleted = True
    org.deleted_at = now
    org.deleted_by = deleted_by
    org.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Delete operation failed") from exc

    logger.info("org_soft_deleted id=%s", org.id)


async def search_org(db: AsyncSession, query: str, limit: int = 100) -> list[OrgResponse]:
    cleaned = query.strip()
    if not cleaned:
        raise ServiceValidationError("Search query must not be empty")

    safe_limit = min(max(limit, 1), 100)
    pattern = f"%{cleaned}%"
    stmt = (
        _active_org_query()
        .where(or_(OrgStructure.name.ilike(pattern), OrgStructure.code.ilike(pattern), OrgStructure.type.ilike(pattern)))
        .order_by(OrgStructure.name.asc())
        .limit(safe_limit)
    )
    result = await db.execute(stmt)
    org_rows = result.scalars().all()
    return [OrgResponse.model_validate(row) for row in org_rows]
