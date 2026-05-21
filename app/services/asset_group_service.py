import re
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.asset_group import AssetGroup
from app.models.asset_group_membership import AssetGroupMembership
from app.models.org_structure import OrgStructure
from app.schemas.asset_group_schema import (
    AssetGroupCreate,
    AssetGroupMembershipCreate,
    AssetGroupMembershipResponse,
    AssetGroupResponse,
    AssetGroupTreeResponse,
    AssetGroupType,
    AssetGroupUpdate,
)

GROUP_TYPE_VALUES: set[str] = {"SYSTEM", "SUB_SYSTEM"}
GROUP_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,49}$")


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


def _normalize_group_type(value: str | None, field_name: str = "group_type") -> AssetGroupType:
    normalized = _normalize_required(value, field_name, 20).upper()
    if normalized not in GROUP_TYPE_VALUES:
        raise ServiceValidationError(f"{field_name} must be one of: {', '.join(sorted(GROUP_TYPE_VALUES))}")
    return normalized  # type: ignore[return-value]


def _normalize_group_code(value: str | None) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    normalized = normalized.upper()
    if len(normalized) > 50:
        raise ServiceValidationError("group_code must not exceed 50 characters")
    if not GROUP_CODE_PATTERN.fullmatch(normalized):
        raise ServiceValidationError(
            "group_code must start with a letter or number and contain only uppercase letters, numbers, hyphen, or underscore",
        )
    return normalized


def _normalize_asset_uuid_list(asset_uuids: list[uuid.UUID]) -> list[uuid.UUID]:
    normalized: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for asset_uuid in asset_uuids:
        if asset_uuid in seen:
            continue
        seen.add(asset_uuid)
        normalized.append(asset_uuid)
    if not normalized:
        raise ServiceValidationError("asset_uuids must include at least one asset")
    return normalized


def _group_ordering():
    return (
        case((AssetGroup.group_type == "SYSTEM", 0), else_=1),
        AssetGroup.group_name.asc(),
        AssetGroup.group_code.asc().nulls_last(),
    )


def _group_query() -> Select[tuple[AssetGroup]]:
    return select(AssetGroup).options(
        selectinload(AssetGroup.parent),
        selectinload(AssetGroup.org_node),
    )


def _membership_query() -> Select[tuple[AssetGroupMembership]]:
    return select(AssetGroupMembership).options(
        selectinload(AssetGroupMembership.asset).selectinload(Asset.org_node),
    )


async def _get_group_model(db: AsyncSession, group_id: uuid.UUID) -> AssetGroup | None:
    stmt = _group_query().where(AssetGroup.id == group_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_group_by_code(db: AsyncSession, group_code: str) -> AssetGroup | None:
    stmt = _group_query().where(AssetGroup.group_code == group_code)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_active_org_node(db: AsyncSession, org_node_id: uuid.UUID) -> OrgStructure | None:
    stmt = select(OrgStructure).where(
        OrgStructure.id == org_node_id,
        OrgStructure.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _validate_org_node_reference(db: AsyncSession, org_node_id: uuid.UUID | None) -> None:
    if org_node_id is None:
        return
    if await _get_active_org_node(db, org_node_id) is None:
        raise ServiceValidationError("org_node_id references an unknown or deleted org node")


async def _get_parent_map(db: AsyncSession) -> dict[uuid.UUID, uuid.UUID | None]:
    stmt = select(AssetGroup.id, AssetGroup.parent_group_id)
    result = await db.execute(stmt)
    return {row[0]: row[1] for row in result.all()}


async def _has_child_groups(db: AsyncSession, group_id: uuid.UUID) -> bool:
    stmt = select(AssetGroup.id).where(AssetGroup.parent_group_id == group_id).limit(1)
    result = await db.execute(stmt)
    return result.scalars().first() is not None


async def _has_asset_memberships(db: AsyncSession, group_id: uuid.UUID) -> bool:
    stmt = select(AssetGroupMembership.id).where(AssetGroupMembership.group_id == group_id).limit(1)
    result = await db.execute(stmt)
    return result.scalars().first() is not None


async def _validate_parent_reference(
    db: AsyncSession,
    *,
    group_id: uuid.UUID | None,
    parent_group_id: uuid.UUID | None,
    group_type: AssetGroupType,
) -> None:
    if parent_group_id is None:
        return

    if group_type != "SUB_SYSTEM":
        raise ServiceValidationError("Only SUB_SYSTEM groups can be assigned to a parent group")

    if group_id is not None and parent_group_id == group_id:
        raise ServiceValidationError("Group cannot be its own parent")

    parent_group = await _get_group_model(db, parent_group_id)
    if parent_group is None:
        raise ServiceValidationError("parent_group_id references an unknown asset group")

    if not parent_group.is_active:
        raise ServiceValidationError("Inactive groups cannot be assigned as parent groups")

    if parent_group.group_type != "SYSTEM":
        raise ServiceValidationError("Parent group must be a SYSTEM")

    if parent_group.parent_group_id is not None:
        raise ServiceValidationError("Only top-level SYSTEM groups can contain sub-systems")

    if group_id is None:
        return

    parent_map = await _get_parent_map(db)
    cursor = parent_group_id
    while cursor is not None:
        if cursor == group_id:
            raise ServiceValidationError("Circular group hierarchy detected")
        cursor = parent_map.get(cursor)


async def _validate_group_transition(
    db: AsyncSession,
    *,
    group_id: uuid.UUID,
    next_group_type: AssetGroupType,
) -> None:
    if next_group_type == "SUB_SYSTEM" and await _has_child_groups(db, group_id):
        raise ServiceValidationError("SUB_SYSTEM groups cannot contain child groups")


async def _get_asset_models(db: AsyncSession, asset_uuids: list[uuid.UUID]) -> list[Asset]:
    if not asset_uuids:
        return []
    stmt = (
        select(Asset)
        .options(selectinload(Asset.org_node))
        .where(Asset.asset_uuid.in_(asset_uuids))
        .order_by(Asset.asset_name.asc(), Asset.asset_id.asc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def _get_membership_models_by_ids(
    db: AsyncSession,
    membership_ids: list[uuid.UUID],
) -> list[AssetGroupMembership]:
    if not membership_ids:
        return []
    stmt = _membership_query().where(AssetGroupMembership.id.in_(membership_ids))
    result = await db.execute(stmt)
    membership_map = {membership.id: membership for membership in result.scalars().all()}
    return [membership_map[membership_id] for membership_id in membership_ids if membership_id in membership_map]


async def _get_group_count_maps(
    db: AsyncSession,
    group_ids: list[uuid.UUID],
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    if not group_ids:
        return {}, {}

    child_stmt = (
        select(AssetGroup.parent_group_id, func.count(AssetGroup.id))
        .where(AssetGroup.parent_group_id.in_(group_ids))
        .group_by(AssetGroup.parent_group_id)
    )
    asset_stmt = (
        select(AssetGroupMembership.group_id, func.count(AssetGroupMembership.id))
        .where(AssetGroupMembership.group_id.in_(group_ids))
        .group_by(AssetGroupMembership.group_id)
    )

    child_result = await db.execute(child_stmt)
    asset_result = await db.execute(asset_stmt)

    child_counts = {
        row[0]: int(row[1])
        for row in child_result.all()
        if row[0] is not None
    }
    asset_counts = {row[0]: int(row[1]) for row in asset_result.all()}
    return child_counts, asset_counts


def _build_group_response(
    group: AssetGroup,
    *,
    child_count: int = 0,
    asset_count: int = 0,
) -> AssetGroupResponse:
    parent_group = group.parent
    org_node = group.org_node
    return AssetGroupResponse(
        id=group.id,
        parent_group_id=group.parent_group_id,
        parent_group_name=parent_group.group_name if parent_group is not None else None,
        group_name=group.group_name,
        group_code=group.group_code,
        group_type=group.group_type,
        description=group.description,
        org_node_id=group.org_node_id,
        org_node_name=org_node.name if org_node is not None else None,
        is_active=group.is_active,
        child_group_count=child_count,
        direct_asset_count=asset_count,
        created_by=group.created_by,
        created_dt=group.created_dt,
        modified_by=group.modified_by,
        modified_dt=group.modified_dt,
    )


def _build_membership_response(membership: AssetGroupMembership) -> AssetGroupMembershipResponse:
    asset = membership.asset
    org_node = asset.org_node if asset is not None else None
    return AssetGroupMembershipResponse(
        id=membership.id,
        group_id=membership.group_id,
        asset_uuid=membership.asset_uuid,
        asset_id=asset.asset_id if asset is not None else None,
        asset_name=asset.asset_name if asset is not None else None,
        asset_class=asset.asset_class if asset is not None else None,
        asset_type=asset.asset_type if asset is not None else None,
        asset_status=asset.asset_status if asset is not None else None,
        org_node_id=asset.org_node_id if asset is not None else None,
        org_node_name=org_node.name if org_node is not None else None,
        created_by=membership.created_by,
        created_dt=membership.created_dt,
        modified_by=membership.modified_by,
        modified_dt=membership.modified_dt,
    )


def _conflict_message_from_integrity_error(exc: IntegrityError) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    if "uq_asset_group_code" in message or ("group_code" in message and "unique" in message):
        return "group_code already exists"
    if "uq_asset_group_membership_group_asset" in message:
        return "One or more assets are already assigned to this group"
    if "chk_asset_group_system_parent" in message:
        return "SYSTEM groups cannot have a parent group"
    if "chk_asset_group_no_self_parent" in message:
        return "Group cannot be its own parent"
    if "chk_asset_group_type" in message:
        return "group_type must be SYSTEM or SUB_SYSTEM"
    return "Operation failed due to a data conflict"


async def get_asset_groups(
    db: AsyncSession,
    *,
    q: str | None = None,
    group_type: str | None = None,
    org_node_id: uuid.UUID | None = None,
    include_inactive: bool = False,
) -> list[AssetGroupResponse]:
    stmt = _group_query()

    if not include_inactive:
        stmt = stmt.where(AssetGroup.is_active.is_(True))

    if group_type is not None:
        stmt = stmt.where(AssetGroup.group_type == _normalize_group_type(group_type))

    if org_node_id is not None:
        stmt = stmt.where(AssetGroup.org_node_id == org_node_id)

    cleaned_query = q.strip() if q is not None else ""
    if cleaned_query:
        pattern = f"%{cleaned_query}%"
        stmt = stmt.where(
            or_(
                AssetGroup.group_name.ilike(pattern),
                AssetGroup.group_code.ilike(pattern),
                AssetGroup.description.ilike(pattern),
            )
        )

    stmt = stmt.order_by(*_group_ordering())
    result = await db.execute(stmt)
    groups = result.scalars().all()
    child_counts, asset_counts = await _get_group_count_maps(db, [group.id for group in groups])
    return [
        _build_group_response(
            group,
            child_count=child_counts.get(group.id, 0),
            asset_count=asset_counts.get(group.id, 0),
        )
        for group in groups
    ]


async def get_asset_group_by_id(db: AsyncSession, group_id: uuid.UUID) -> AssetGroupResponse:
    group = await _get_group_model(db, group_id)
    if group is None:
        raise ServiceNotFoundError("Asset group not found")

    child_counts, asset_counts = await _get_group_count_maps(db, [group.id])
    return _build_group_response(
        group,
        child_count=child_counts.get(group.id, 0),
        asset_count=asset_counts.get(group.id, 0),
    )


async def get_asset_group_tree(
    db: AsyncSession,
    *,
    org_node_id: uuid.UUID | None = None,
    include_inactive: bool = False,
) -> list[AssetGroupTreeResponse]:
    groups = await get_asset_groups(
        db,
        org_node_id=org_node_id,
        include_inactive=include_inactive,
    )
    node_map: dict[uuid.UUID, AssetGroupTreeResponse] = {}
    root_nodes: list[AssetGroupTreeResponse] = []

    for group in groups:
        payload = group.model_dump()
        node_map[group.id] = AssetGroupTreeResponse(**payload, children=[])

    for group in groups:
        node = node_map[group.id]
        if group.parent_group_id is not None and group.parent_group_id in node_map:
            node_map[group.parent_group_id].children.append(node)
        else:
            root_nodes.append(node)

    return root_nodes


async def create_asset_group(db: AsyncSession, payload: AssetGroupCreate) -> AssetGroupResponse:
    group_name = _normalize_required(payload.group_name, "group_name", 150)
    group_type = _normalize_group_type(payload.group_type)
    group_code = _normalize_group_code(payload.group_code)
    description = _normalize_optional_string(payload.description, "description", 500)

    await _validate_org_node_reference(db, payload.org_node_id)
    await _validate_parent_reference(
        db,
        group_id=None,
        parent_group_id=payload.parent_group_id,
        group_type=group_type,
    )

    if group_code is not None:
        duplicate = await _get_group_by_code(db, group_code)
        if duplicate is not None:
            raise ServiceConflictError("group_code already exists")

    now = datetime.now(UTC)
    created_by = _normalize_required(payload.created_by, "created_by", 150)
    group = AssetGroup(
        group_name=group_name,
        group_code=group_code,
        group_type=group_type,
        description=description,
        parent_group_id=payload.parent_group_id,
        org_node_id=payload.org_node_id,
        is_active=payload.is_active,
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(group)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_asset_group_by_id(db, group.id)


async def update_asset_group(
    db: AsyncSession,
    group_id: uuid.UUID,
    payload: AssetGroupUpdate,
) -> AssetGroupResponse:
    group = await _get_group_model(db, group_id)
    if group is None:
        raise ServiceNotFoundError("Asset group not found")

    updates = payload.model_dump(exclude_unset=True)

    if "group_name" in updates:
        updates["group_name"] = _normalize_required(updates["group_name"], "group_name", 150)

    if "group_code" in updates:
        updates["group_code"] = _normalize_group_code(updates["group_code"])
        next_group_code = updates["group_code"]
        if next_group_code != group.group_code and next_group_code is not None:
            duplicate = await _get_group_by_code(db, next_group_code)
            if duplicate is not None and duplicate.id != group.id:
                raise ServiceConflictError("group_code already exists")

    if "description" in updates:
        updates["description"] = _normalize_optional_string(updates["description"], "description", 500)

    next_group_type = _normalize_group_type(updates["group_type"]) if "group_type" in updates else group.group_type
    next_parent_group_id = updates["parent_group_id"] if "parent_group_id" in updates else group.parent_group_id
    next_org_node_id = updates["org_node_id"] if "org_node_id" in updates else group.org_node_id

    await _validate_org_node_reference(db, next_org_node_id)
    await _validate_parent_reference(
        db,
        group_id=group_id,
        parent_group_id=next_parent_group_id,
        group_type=next_group_type,
    )
    await _validate_group_transition(db, group_id=group_id, next_group_type=next_group_type)
    if "is_active" in updates and updates["is_active"] is False and await _has_child_groups(db, group_id):
        raise ServiceValidationError("Cannot deactivate group with existing child groups")

    if "group_type" in updates:
        updates["group_type"] = next_group_type

    if "modified_by" in updates:
        updates["modified_by"] = _normalize_optional_string(updates["modified_by"], "modified_by", 150)

    for field_name, field_value in updates.items():
        setattr(group, field_name, field_value)

    group.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_asset_group_by_id(db, group_id)


async def delete_asset_group(db: AsyncSession, group_id: uuid.UUID) -> None:
    group = await _get_group_model(db, group_id)
    if group is None:
        raise ServiceNotFoundError("Asset group not found")

    if await _has_child_groups(db, group_id):
        raise ServiceConflictError("Cannot delete group with existing child groups")

    if await _has_asset_memberships(db, group_id):
        raise ServiceConflictError("Cannot delete group with assigned assets")

    try:
        await db.delete(group)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete asset group") from exc


async def get_asset_group_assets(
    db: AsyncSession,
    group_id: uuid.UUID,
) -> list[AssetGroupMembershipResponse]:
    if await _get_group_model(db, group_id) is None:
        raise ServiceNotFoundError("Asset group not found")

    stmt = (
        _membership_query()
        .join(Asset, AssetGroupMembership.asset_uuid == Asset.asset_uuid)
        .where(AssetGroupMembership.group_id == group_id)
        .order_by(Asset.asset_name.asc(), Asset.asset_id.asc())
    )
    result = await db.execute(stmt)
    memberships = result.scalars().all()
    return [_build_membership_response(membership) for membership in memberships]


async def add_assets_to_group(
    db: AsyncSession,
    group_id: uuid.UUID,
    payload: AssetGroupMembershipCreate,
) -> list[AssetGroupMembershipResponse]:
    group = await _get_group_model(db, group_id)
    if group is None:
        raise ServiceNotFoundError("Asset group not found")

    if not group.is_active:
        raise ServiceValidationError("Cannot assign assets to an inactive group")

    asset_uuids = _normalize_asset_uuid_list(payload.asset_uuids)
    assets = await _get_asset_models(db, asset_uuids)
    asset_map = {asset.asset_uuid: asset for asset in assets}

    missing_asset_ids = [str(asset_uuid) for asset_uuid in asset_uuids if asset_uuid not in asset_map]
    if missing_asset_ids:
        raise ServiceValidationError(f"Unknown asset_uuid value(s): {', '.join(missing_asset_ids)}")

    duplicate_stmt = select(AssetGroupMembership.asset_uuid).where(
        AssetGroupMembership.group_id == group_id,
        AssetGroupMembership.asset_uuid.in_(asset_uuids),
    )
    duplicate_result = await db.execute(duplicate_stmt)
    duplicate_asset_ids = set(duplicate_result.scalars().all())
    if duplicate_asset_ids:
        raise ServiceConflictError("One or more assets are already assigned to this group")

    now = datetime.now(UTC)
    created_by = _normalize_required(payload.created_by, "created_by", 150)
    memberships: list[AssetGroupMembership] = []
    for asset_uuid in asset_uuids:
        membership = AssetGroupMembership(
            group_id=group_id,
            asset_uuid=asset_uuid,
            created_by=created_by,
            created_dt=now,
            modified_by=created_by,
            modified_dt=now,
        )
        db.add(membership)
        memberships.append(membership)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    created_memberships = await _get_membership_models_by_ids(db, [membership.id for membership in memberships])
    return [_build_membership_response(membership) for membership in created_memberships]


async def remove_asset_from_group(
    db: AsyncSession,
    group_id: uuid.UUID,
    asset_uuid: uuid.UUID,
) -> None:
    if await _get_group_model(db, group_id) is None:
        raise ServiceNotFoundError("Asset group not found")

    stmt = select(AssetGroupMembership).where(
        AssetGroupMembership.group_id == group_id,
        AssetGroupMembership.asset_uuid == asset_uuid,
    )
    result = await db.execute(stmt)
    membership = result.scalars().first()
    if membership is None:
        raise ServiceNotFoundError("Asset membership not found for this group")

    try:
        await db.delete(membership)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to remove asset from group") from exc
