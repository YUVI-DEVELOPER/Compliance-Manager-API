import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lookup_master import LookupMaster
from app.models.lookup_value import LookupValue
from app.models.org_entity_role_assignment import OrgEntityRoleAssignment
from app.models.org_role import OrgRole
from app.models.org_role_action import OrgRoleAction
from app.models.org_structure import OrgStructure
from app.schemas.org_role_schema import (
    OrgEntityRoleAssignmentCreateRequest,
    OrgEntityRoleAssignmentResponse,
    OrgEntityRoleAssignmentUpdateRequest,
    OrgRoleActionCreateRequest,
    OrgRoleActionResponse,
    OrgRoleActionUpdateRequest,
    OrgRoleCreateRequest,
    OrgRoleDetailResponse,
    OrgRoleResponse,
    OrgRoleSummaryResponse,
    OrgRoleUpdateRequest,
)
from app.services.org_service import ServiceConflictError, ServiceNotFoundError, ServiceValidationError

ROLE_RACI_LOOKUP_KEY = "ORG_ROLE_RACI"
ROLE_TYPE_LOOKUP_KEY = "ORG_ROLE_TYPE"
ROLE_ACTION_TYPE_LOOKUP_KEY = "ORG_ROLE_ACTION_TYPE"


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_required_text(value: str, field_name: str, *, max_length: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ServiceValidationError(f"{field_name} is required")
    if len(normalized) > max_length:
        raise ServiceValidationError(f"{field_name} must not exceed {max_length} characters")
    return normalized


def _normalize_optional_text(value: str | None, field_name: str, *, max_length: int) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    if len(normalized) > max_length:
        raise ServiceValidationError(f"{field_name} must not exceed {max_length} characters")
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


def _normalize_person_email(value: str | None) -> str | None:
    normalized = _strip_optional(value)
    return normalized.lower() if normalized is not None else None


def _normalize_employee_code(value: str | None) -> str | None:
    normalized = _strip_optional(value)
    return normalized.upper() if normalized is not None else None


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


async def _get_active_org(db: AsyncSession, org_id: uuid.UUID) -> OrgStructure:
    stmt = select(OrgStructure).where(OrgStructure.id == org_id, OrgStructure.is_deleted.is_(False))
    result = await db.execute(stmt)
    org = result.scalars().first()
    if org is None:
        raise ServiceNotFoundError("Org node not found")
    return org


async def _get_role(db: AsyncSession, role_id: uuid.UUID, *, active_only: bool = False) -> OrgRole:
    stmt = select(OrgRole).where(OrgRole.id == role_id, OrgRole.is_deleted.is_(False))
    if active_only:
        stmt = stmt.where(OrgRole.is_active.is_(True))
    result = await db.execute(stmt)
    role = result.scalars().first()
    if role is None:
        raise ServiceNotFoundError("Org role not found")
    return role


async def _get_role_action(db: AsyncSession, action_id: uuid.UUID) -> OrgRoleAction:
    stmt = select(OrgRoleAction).where(OrgRoleAction.id == action_id)
    result = await db.execute(stmt)
    action = result.scalars().first()
    if action is None:
        raise ServiceNotFoundError("Org role action not found")
    return action


async def _get_assignment(db: AsyncSession, assignment_id: uuid.UUID) -> OrgEntityRoleAssignment:
    stmt = select(OrgEntityRoleAssignment).where(
        OrgEntityRoleAssignment.id == assignment_id,
        OrgEntityRoleAssignment.is_deleted.is_(False),
    )
    result = await db.execute(stmt)
    assignment = result.scalars().first()
    if assignment is None:
        raise ServiceNotFoundError("Org role assignment not found")
    return assignment


async def _ensure_unique_role_name(
    db: AsyncSession,
    role_name: str,
    *,
    exclude_role_id: uuid.UUID | None = None,
) -> None:
    stmt = select(OrgRole.id).where(
        OrgRole.is_deleted.is_(False),
        func.lower(OrgRole.role_name) == role_name.lower(),
    )
    if exclude_role_id is not None:
        stmt = stmt.where(OrgRole.id != exclude_role_id)
    result = await db.execute(stmt.limit(1))
    if result.scalars().first() is not None:
        raise ServiceConflictError("Org role name already exists")


async def _ensure_unique_role_action_seq(
    db: AsyncSession,
    *,
    role_id: uuid.UUID,
    seq: int,
    exclude_action_id: uuid.UUID | None = None,
) -> None:
    stmt = select(OrgRoleAction.id).where(OrgRoleAction.role_id == role_id, OrgRoleAction.seq == seq)
    if exclude_action_id is not None:
        stmt = stmt.where(OrgRoleAction.id != exclude_action_id)
    result = await db.execute(stmt.limit(1))
    if result.scalars().first() is not None:
        raise ServiceConflictError("Action sequence already exists for this role")


async def _ensure_no_duplicate_active_assignment(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    role_id: uuid.UUID,
    person_name: str,
    person_email: str | None,
    employee_code: str | None,
    exclude_assignment_id: uuid.UUID | None = None,
) -> None:
    stmt = select(OrgEntityRoleAssignment).where(
        OrgEntityRoleAssignment.org_id == org_id,
        OrgEntityRoleAssignment.role_id == role_id,
        OrgEntityRoleAssignment.is_deleted.is_(False),
        OrgEntityRoleAssignment.is_active.is_(True),
    )
    if exclude_assignment_id is not None:
        stmt = stmt.where(OrgEntityRoleAssignment.id != exclude_assignment_id)
    result = await db.execute(stmt)
    existing_rows = result.scalars().all()

    target_name = person_name.casefold()
    target_email = (person_email or "").casefold()
    target_employee_code = (employee_code or "").upper()

    for row in existing_rows:
        row_name = row.person_name.strip().casefold()
        row_email = (row.person_email or "").strip().casefold()
        row_employee_code = (row.employee_code or "").strip().upper()
        if row_name == target_name and row_email == target_email and row_employee_code == target_employee_code:
            raise ServiceConflictError("This active role assignment already exists for the org node")


async def _build_role_action_count_map(db: AsyncSession, role_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not role_ids:
        return {}
    stmt = (
        select(OrgRoleAction.role_id, func.count(OrgRoleAction.id))
        .where(OrgRoleAction.role_id.in_(role_ids))
        .group_by(OrgRoleAction.role_id)
    )
    result = await db.execute(stmt)
    return {role_id: count for role_id, count in result.all()}


async def _build_role_assignment_count_map(db: AsyncSession, role_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not role_ids:
        return {}
    stmt = (
        select(OrgEntityRoleAssignment.role_id, func.count(OrgEntityRoleAssignment.id))
        .where(
            OrgEntityRoleAssignment.role_id.in_(role_ids),
            OrgEntityRoleAssignment.is_deleted.is_(False),
            OrgEntityRoleAssignment.is_active.is_(True),
        )
        .group_by(OrgEntityRoleAssignment.role_id)
    )
    result = await db.execute(stmt)
    return {role_id: count for role_id, count in result.all()}


def _build_role_response(
    role: OrgRole,
    *,
    action_count: int = 0,
    active_assignment_count: int = 0,
) -> OrgRoleResponse:
    return OrgRoleResponse(
        id=role.id,
        role_name=role.role_name,
        role_raci=role.role_raci,
        ownership=role.ownership,
        role_type=role.role_type,
        is_active=role.is_active,
        created_by=role.created_by,
        created_dt=role.created_dt,
        modified_by=role.modified_by,
        modified_dt=role.modified_dt,
        is_deleted=role.is_deleted,
        deleted_at=role.deleted_at,
        deleted_by=role.deleted_by,
        action_count=action_count,
        active_assignment_count=active_assignment_count,
    )


def _build_role_summary(role: OrgRole) -> OrgRoleSummaryResponse:
    return OrgRoleSummaryResponse(
        id=role.id,
        role_name=role.role_name,
        role_raci=role.role_raci,
        ownership=role.ownership,
        role_type=role.role_type,
        is_active=role.is_active,
    )


def _build_assignment_response(
    assignment: OrgEntityRoleAssignment,
    role: OrgRole | None,
) -> OrgEntityRoleAssignmentResponse:
    return OrgEntityRoleAssignmentResponse(
        id=assignment.id,
        org_id=assignment.org_id,
        role_id=assignment.role_id,
        person_name=assignment.person_name,
        person_email=assignment.person_email,
        employee_code=assignment.employee_code,
        remarks=assignment.remarks,
        is_active=assignment.is_active,
        created_by=assignment.created_by,
        created_dt=assignment.created_dt,
        modified_by=assignment.modified_by,
        modified_dt=assignment.modified_dt,
        is_deleted=assignment.is_deleted,
        deleted_at=assignment.deleted_at,
        deleted_by=assignment.deleted_by,
        role=_build_role_summary(role) if role is not None else None,
    )


async def get_org_roles(db: AsyncSession, active_only: bool = False) -> list[OrgRoleResponse]:
    stmt = select(OrgRole).where(OrgRole.is_deleted.is_(False))
    if active_only:
        stmt = stmt.where(OrgRole.is_active.is_(True))
    stmt = stmt.order_by(OrgRole.role_name.asc())
    result = await db.execute(stmt)
    roles = result.scalars().all()

    role_ids = [role.id for role in roles]
    action_counts = await _build_role_action_count_map(db, role_ids)
    assignment_counts = await _build_role_assignment_count_map(db, role_ids)

    return [
        _build_role_response(
            role,
            action_count=action_counts.get(role.id, 0),
            active_assignment_count=assignment_counts.get(role.id, 0),
        )
        for role in roles
    ]


async def get_org_role_by_id(db: AsyncSession, role_id: uuid.UUID) -> OrgRoleDetailResponse:
    role = await _get_role(db, role_id)
    action_stmt = select(OrgRoleAction).where(OrgRoleAction.role_id == role_id).order_by(OrgRoleAction.seq.asc())
    action_result = await db.execute(action_stmt)
    actions = action_result.scalars().all()

    action_counts = await _build_role_action_count_map(db, [role.id])
    assignment_counts = await _build_role_assignment_count_map(db, [role.id])
    base_response = _build_role_response(
        role,
        action_count=action_counts.get(role.id, 0),
        active_assignment_count=assignment_counts.get(role.id, 0),
    )
    return OrgRoleDetailResponse(
        **base_response.model_dump(),
        actions=[OrgRoleActionResponse.model_validate(action) for action in actions],
    )


async def create_org_role(db: AsyncSession, payload: OrgRoleCreateRequest) -> OrgRoleResponse:
    normalized_role_name = _normalize_required_text(payload.role_name, "role_name", max_length=150)
    normalized_ownership = _normalize_required_text(payload.ownership, "ownership", max_length=150)
    normalized_role_raci = await _normalize_lookup_code(
        db,
        lookup_key=ROLE_RACI_LOOKUP_KEY,
        value=payload.role_raci,
        field_name="role_raci",
    )
    normalized_role_type = await _normalize_lookup_code(
        db,
        lookup_key=ROLE_TYPE_LOOKUP_KEY,
        value=payload.role_type,
        field_name="role_type",
    )

    await _ensure_unique_role_name(db, normalized_role_name)

    now = datetime.now(UTC)
    role = OrgRole(
        role_name=normalized_role_name,
        role_raci=normalized_role_raci,
        ownership=normalized_ownership,
        role_type=normalized_role_type,
        is_active=payload.is_active,
        created_by=_strip_optional(payload.created_by),
        created_dt=now,
        modified_dt=now,
        is_deleted=False,
    )
    db.add(role)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Org role name already exists") from exc

    await db.refresh(role)
    return _build_role_response(role)


async def update_org_role(db: AsyncSession, role_id: uuid.UUID, payload: OrgRoleUpdateRequest) -> OrgRoleResponse:
    role = await _get_role(db, role_id)
    updates = payload.model_dump(exclude_unset=True)

    if "role_name" in updates and updates["role_name"] is not None:
        role.role_name = _normalize_required_text(updates["role_name"], "role_name", max_length=150)
        await _ensure_unique_role_name(db, role.role_name, exclude_role_id=role.id)

    if "ownership" in updates and updates["ownership"] is not None:
        role.ownership = _normalize_required_text(updates["ownership"], "ownership", max_length=150)

    if "role_raci" in updates and updates["role_raci"] is not None:
        role.role_raci = await _normalize_lookup_code(
            db,
            lookup_key=ROLE_RACI_LOOKUP_KEY,
            value=updates["role_raci"],
            field_name="role_raci",
        )

    if "role_type" in updates and updates["role_type"] is not None:
        role.role_type = await _normalize_lookup_code(
            db,
            lookup_key=ROLE_TYPE_LOOKUP_KEY,
            value=updates["role_type"],
            field_name="role_type",
        )

    if "is_active" in updates and updates["is_active"] is not None:
        role.is_active = updates["is_active"]

    if "modified_by" in updates:
        role.modified_by = _strip_optional(updates["modified_by"])

    role.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to update org role") from exc

    await db.refresh(role)
    action_counts = await _build_role_action_count_map(db, [role.id])
    assignment_counts = await _build_role_assignment_count_map(db, [role.id])
    return _build_role_response(
        role,
        action_count=action_counts.get(role.id, 0),
        active_assignment_count=assignment_counts.get(role.id, 0),
    )


async def delete_org_role(db: AsyncSession, role_id: uuid.UUID, modified_by: str | None = None) -> None:
    role = await _get_role(db, role_id)
    assignment_counts = await _build_role_assignment_count_map(db, [role.id])
    if assignment_counts.get(role.id, 0) > 0:
        raise ServiceConflictError("Cannot delete a role with active org assignments")

    now = datetime.now(UTC)
    role.is_active = False
    role.is_deleted = True
    role.deleted_at = now
    role.deleted_by = _strip_optional(modified_by)
    role.modified_by = _strip_optional(modified_by)
    role.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete org role") from exc


async def get_org_role_actions(db: AsyncSession, role_id: uuid.UUID) -> list[OrgRoleActionResponse]:
    await _get_role(db, role_id)
    stmt = select(OrgRoleAction).where(OrgRoleAction.role_id == role_id).order_by(OrgRoleAction.seq.asc())
    result = await db.execute(stmt)
    actions = result.scalars().all()
    return [OrgRoleActionResponse.model_validate(action) for action in actions]


async def create_org_role_action(
    db: AsyncSession,
    role_id: uuid.UUID,
    payload: OrgRoleActionCreateRequest,
) -> OrgRoleActionResponse:
    await _get_role(db, role_id)
    await _ensure_unique_role_action_seq(db, role_id=role_id, seq=payload.seq)

    normalized_action_type = await _normalize_lookup_code(
        db,
        lookup_key=ROLE_ACTION_TYPE_LOOKUP_KEY,
        value=payload.action_type,
        field_name="action_type",
    )
    normalized_action = _normalize_required_text(payload.action, "action", max_length=250)
    now = datetime.now(UTC)
    action = OrgRoleAction(
        role_id=role_id,
        seq=payload.seq,
        action_type=normalized_action_type,
        action=normalized_action,
        created_by=_strip_optional(payload.created_by),
        created_dt=now,
        modified_dt=now,
    )
    db.add(action)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Action sequence already exists for this role") from exc

    await db.refresh(action)
    return OrgRoleActionResponse.model_validate(action)


async def update_org_role_action(
    db: AsyncSession,
    action_id: uuid.UUID,
    payload: OrgRoleActionUpdateRequest,
) -> OrgRoleActionResponse:
    action = await _get_role_action(db, action_id)
    await _get_role(db, action.role_id)
    updates = payload.model_dump(exclude_unset=True)

    next_seq = updates.get("seq", action.seq)
    if next_seq != action.seq:
        await _ensure_unique_role_action_seq(
            db,
            role_id=action.role_id,
            seq=next_seq,
            exclude_action_id=action.id,
        )
        action.seq = next_seq

    if "action_type" in updates and updates["action_type"] is not None:
        action.action_type = await _normalize_lookup_code(
            db,
            lookup_key=ROLE_ACTION_TYPE_LOOKUP_KEY,
            value=updates["action_type"],
            field_name="action_type",
        )

    if "action" in updates and updates["action"] is not None:
        action.action = _normalize_required_text(updates["action"], "action", max_length=250)

    if "modified_by" in updates:
        action.modified_by = _strip_optional(updates["modified_by"])
    action.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to update org role action") from exc

    await db.refresh(action)
    return OrgRoleActionResponse.model_validate(action)


async def delete_org_role_action(db: AsyncSession, action_id: uuid.UUID) -> None:
    action = await _get_role_action(db, action_id)
    await db.delete(action)
    await db.commit()


async def get_org_role_assignments(
    db: AsyncSession,
    org_id: uuid.UUID,
    active_only: bool = False,
) -> list[OrgEntityRoleAssignmentResponse]:
    await _get_active_org(db, org_id)
    stmt = select(OrgEntityRoleAssignment).where(
        OrgEntityRoleAssignment.org_id == org_id,
        OrgEntityRoleAssignment.is_deleted.is_(False),
    )
    if active_only:
        stmt = stmt.where(OrgEntityRoleAssignment.is_active.is_(True))
    stmt = stmt.order_by(OrgEntityRoleAssignment.is_active.desc(), OrgEntityRoleAssignment.person_name.asc())
    result = await db.execute(stmt)
    assignments = result.scalars().all()

    role_ids = sorted({assignment.role_id for assignment in assignments})
    role_map: dict[uuid.UUID, OrgRole] = {}
    if role_ids:
        role_stmt = select(OrgRole).where(OrgRole.id.in_(role_ids), OrgRole.is_deleted.is_(False))
        role_result = await db.execute(role_stmt)
        role_map = {role.id: role for role in role_result.scalars().all()}

    return [_build_assignment_response(assignment, role_map.get(assignment.role_id)) for assignment in assignments]


async def create_org_role_assignment(
    db: AsyncSession,
    org_id: uuid.UUID,
    payload: OrgEntityRoleAssignmentCreateRequest,
) -> OrgEntityRoleAssignmentResponse:
    await _get_active_org(db, org_id)
    role = await _get_role(db, payload.role_id, active_only=True)

    normalized_person_name = _normalize_required_text(payload.person_name, "person_name", max_length=150)
    normalized_person_email = _normalize_person_email(payload.person_email)
    normalized_employee_code = _normalize_employee_code(payload.employee_code)
    normalized_remarks = _normalize_optional_text(payload.remarks, "remarks", max_length=500)

    if payload.is_active:
        await _ensure_no_duplicate_active_assignment(
            db,
            org_id=org_id,
            role_id=role.id,
            person_name=normalized_person_name,
            person_email=normalized_person_email,
            employee_code=normalized_employee_code,
        )

    now = datetime.now(UTC)
    assignment = OrgEntityRoleAssignment(
        org_id=org_id,
        role_id=role.id,
        person_name=normalized_person_name,
        person_email=normalized_person_email,
        employee_code=normalized_employee_code,
        remarks=normalized_remarks,
        is_active=payload.is_active,
        created_by=_strip_optional(payload.created_by),
        created_dt=now,
        modified_dt=now,
        is_deleted=False,
    )
    db.add(assignment)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to create org role assignment") from exc

    await db.refresh(assignment)
    return _build_assignment_response(assignment, role)


async def update_org_role_assignment(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    payload: OrgEntityRoleAssignmentUpdateRequest,
) -> OrgEntityRoleAssignmentResponse:
    assignment = await _get_assignment(db, assignment_id)
    updates = payload.model_dump(exclude_unset=True)

    next_org_id = updates.get("org_id", assignment.org_id)
    next_role_id = updates.get("role_id", assignment.role_id)
    await _get_active_org(db, next_org_id)
    role = await _get_role(db, next_role_id, active_only=True)

    next_person_name = (
        _normalize_required_text(updates["person_name"], "person_name", max_length=150)
        if "person_name" in updates and updates["person_name"] is not None
        else assignment.person_name
    )
    next_person_email = (
        _normalize_person_email(updates["person_email"])
        if "person_email" in updates
        else assignment.person_email
    )
    next_employee_code = (
        _normalize_employee_code(updates["employee_code"])
        if "employee_code" in updates
        else assignment.employee_code
    )
    next_remarks = (
        _normalize_optional_text(updates["remarks"], "remarks", max_length=500)
        if "remarks" in updates
        else assignment.remarks
    )
    next_is_active = updates.get("is_active", assignment.is_active)

    if next_is_active:
        await _ensure_no_duplicate_active_assignment(
            db,
            org_id=next_org_id,
            role_id=next_role_id,
            person_name=next_person_name,
            person_email=next_person_email,
            employee_code=next_employee_code,
            exclude_assignment_id=assignment.id,
        )

    assignment.org_id = next_org_id
    assignment.role_id = next_role_id
    assignment.person_name = next_person_name
    assignment.person_email = next_person_email
    assignment.employee_code = next_employee_code
    assignment.remarks = next_remarks
    assignment.is_active = next_is_active
    if "modified_by" in updates:
        assignment.modified_by = _strip_optional(updates["modified_by"])
    assignment.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to update org role assignment") from exc

    await db.refresh(assignment)
    return _build_assignment_response(assignment, role)


async def delete_org_role_assignment(
    db: AsyncSession,
    assignment_id: uuid.UUID,
    modified_by: str | None = None,
) -> None:
    assignment = await _get_assignment(db, assignment_id)
    now = datetime.now(UTC)
    assignment.is_active = False
    assignment.is_deleted = True
    assignment.deleted_at = now
    assignment.deleted_by = _strip_optional(modified_by)
    assignment.modified_by = _strip_optional(modified_by)
    assignment.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete org role assignment") from exc
