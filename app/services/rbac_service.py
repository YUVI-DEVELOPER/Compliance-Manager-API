from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_log_service import create_audit_log
from app.models.permission import Permission
from app.models.permission_group import PermissionGroup
from app.models.permission_group_item import PermissionGroupItem
from app.models.role import Role
from app.models.role_permission import RolePermission
from app.models.role_permission_group import RolePermissionGroup
from app.models.user_role import UserRole
from app.schemas.rbac_schema import (
    GroupedPermissionGroupsResponse,
    GroupedPermissionsResponse,
    PermissionCreateRequest,
    PermissionGroupResponse,
    PermissionResponse,
    PermissionUpdateRequest,
    RoleCreateRequest,
    RolePermissionAssignmentRequest,
    RolePermissionGroupAssignmentRequest,
    RoleResponse,
    RoleUpdateRequest,
)


def normalize_code(value: str) -> str:
    return value.strip().upper().replace(" ", "_")


def _actor(actor_id: uuid.UUID | None) -> str | None:
    return str(actor_id) if actor_id is not None else None


def _permission_response(permission: Permission) -> PermissionResponse:
    return PermissionResponse.model_validate(permission)


def _permission_group_response(group: PermissionGroup, permission_codes: list[str] | None = None) -> PermissionGroupResponse:
    data = PermissionGroupResponse.model_validate(group).model_dump()
    data["permission_codes"] = permission_codes or []
    return PermissionGroupResponse(**data)


async def _role_response(db: AsyncSession, role: Role) -> RoleResponse:
    direct_permissions = await get_direct_role_permission_codes(db, role.id)
    permission_groups = await get_role_permission_group_codes(db, role.id)
    permissions = sorted(set(direct_permissions) | set(await get_role_group_permission_codes(db, role.id)))
    return RoleResponse(
        id=role.id,
        role_code=role.role_code,
        role_name=role.role_name,
        description=role.description,
        is_system_role=role.is_system_role,
        is_active=role.is_active,
        created_at=role.created_at,
        updated_at=role.updated_at,
        permissions=permissions,
        direct_permissions=direct_permissions,
        permission_groups=permission_groups,
    )


async def record_audit_event(
    db: AsyncSession,
    *,
    table_name: str,
    operation_type: str,
    record_pk: dict[str, Any] | None = None,
    old_data: dict[str, Any] | None = None,
    new_data: dict[str, Any] | None = None,
    changed_by: uuid.UUID | str | None = None,
    module_name: str | None = None,
    entity_name: str | None = None,
    action: str | None = None,
    event_description: str | None = None,
    reason: str | None = None,
    request: Any | None = None,
    current_user: Any | None = None,
) -> None:
    normalized_table = table_name.replace("_", " ").title()
    normalized_operation = operation_type.strip().upper()
    default_action = {
        "INSERT": f"{table_name.upper()}_CREATED",
        "UPDATE": f"{table_name.upper()}_UPDATED",
        "DELETE": f"{table_name.upper()}_DELETED",
    }.get(normalized_operation, f"{table_name.upper()}_{normalized_operation}")
    record_id = None
    if record_pk:
        record_id = record_pk.get("id") or record_pk.get("user_id") or record_pk.get("role_id")

    await create_audit_log(
        db,
        request=request,
        current_user=current_user or changed_by,
        module_name=module_name or normalized_table,
        entity_name=entity_name or normalized_table,
        table_name=table_name,
        record_id=record_id,
        action=action or default_action,
        event_description=event_description,
        old_data=old_data,
        new_data=new_data,
        reason=reason,
    )


async def get_user_role_permission_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> tuple[list[str], list[str]]:
    role_result = await db.execute(
        select(Role.role_code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, Role.is_active.is_(True))
        .order_by(Role.role_code)
    )
    roles = list(dict.fromkeys(role_result.scalars().all()))

    direct_permission_result = await db.execute(
        select(Permission.permission_code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            Role.is_active.is_(True),
            Permission.is_active.is_(True),
        )
        .order_by(Permission.permission_code)
    )
    group_permission_result = await db.execute(
        select(Permission.permission_code)
        .join(PermissionGroupItem, PermissionGroupItem.permission_id == Permission.id)
        .join(PermissionGroup, PermissionGroup.id == PermissionGroupItem.group_id)
        .join(RolePermissionGroup, RolePermissionGroup.permission_group_id == PermissionGroup.id)
        .join(Role, Role.id == RolePermissionGroup.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            Role.is_active.is_(True),
            PermissionGroup.is_active.is_(True),
            Permission.is_active.is_(True),
        )
        .order_by(Permission.permission_code)
    )
    permissions = list(
        dict.fromkeys(
            [
                *direct_permission_result.scalars().all(),
                *group_permission_result.scalars().all(),
            ]
        )
    )
    return roles, permissions


async def user_has_permission(db: AsyncSession, user_id: uuid.UUID, permission_code: str) -> bool:
    normalized = normalize_code(permission_code)
    direct_result = await db.execute(
        select(func.count(Permission.id))
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            Permission.permission_code == normalized,
            Permission.is_active.is_(True),
            Role.is_active.is_(True),
        )
    )
    if int(direct_result.scalar_one() or 0) > 0:
        return True

    group_result = await db.execute(
        select(func.count(Permission.id))
        .join(PermissionGroupItem, PermissionGroupItem.permission_id == Permission.id)
        .join(PermissionGroup, PermissionGroup.id == PermissionGroupItem.group_id)
        .join(RolePermissionGroup, RolePermissionGroup.permission_group_id == PermissionGroup.id)
        .join(Role, Role.id == RolePermissionGroup.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            Permission.permission_code == normalized,
            Permission.is_active.is_(True),
            PermissionGroup.is_active.is_(True),
            Role.is_active.is_(True),
        )
    )
    return int(group_result.scalar_one() or 0) > 0


async def list_permissions(
    db: AsyncSession,
    *,
    include_inactive: bool = False,
    module_name: str | None = None,
) -> list[PermissionResponse]:
    stmt = select(Permission).order_by(Permission.module_name, Permission.permission_code)
    if not include_inactive:
        stmt = stmt.where(Permission.is_active.is_(True))
    if module_name:
        stmt = stmt.where(Permission.module_name == normalize_code(module_name))
    result = await db.execute(stmt)
    return [_permission_response(permission) for permission in result.scalars().all()]


async def list_permissions_grouped_by_module(
    db: AsyncSession,
    *,
    include_inactive: bool = False,
) -> list[GroupedPermissionsResponse]:
    permissions = await list_permissions(db, include_inactive=include_inactive)
    grouped: dict[str, list[PermissionResponse]] = defaultdict(list)
    for permission in permissions:
        grouped[permission.module_name].append(permission)
    return [
        GroupedPermissionsResponse(module_name=module_name, permissions=items)
        for module_name, items in sorted(grouped.items())
    ]


async def get_permission_group_permission_codes(db: AsyncSession, group_id: uuid.UUID) -> list[str]:
    result = await db.execute(
        select(Permission.permission_code)
        .join(PermissionGroupItem, PermissionGroupItem.permission_id == Permission.id)
        .where(PermissionGroupItem.group_id == group_id)
        .order_by(Permission.permission_code)
    )
    return list(result.scalars().all())


async def list_permission_groups(
    db: AsyncSession,
    *,
    include_inactive: bool = False,
    module_name: str | None = None,
) -> list[PermissionGroupResponse]:
    stmt = select(PermissionGroup).order_by(PermissionGroup.display_order, PermissionGroup.group_code)
    if not include_inactive:
        stmt = stmt.where(PermissionGroup.is_active.is_(True))
    if module_name:
        stmt = stmt.where(PermissionGroup.module_name == normalize_code(module_name))
    result = await db.execute(stmt)
    groups = result.scalars().all()
    return [
        _permission_group_response(group, await get_permission_group_permission_codes(db, group.id))
        for group in groups
    ]


async def list_permission_groups_grouped_by_module(
    db: AsyncSession,
    *,
    include_inactive: bool = False,
) -> list[GroupedPermissionGroupsResponse]:
    groups = await list_permission_groups(db, include_inactive=include_inactive)
    grouped: dict[str, list[PermissionGroupResponse]] = defaultdict(list)
    for group in groups:
        grouped[group.module_name].append(group)
    return [
        GroupedPermissionGroupsResponse(module_name=module_name, permission_groups=items)
        for module_name, items in sorted(grouped.items())
    ]


async def get_permission_by_id(db: AsyncSession, permission_id: uuid.UUID) -> Permission:
    permission = await db.get(Permission, permission_id)
    if permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found")
    return permission


async def get_permissions_by_codes(db: AsyncSession, permission_codes: list[str]) -> list[Permission]:
    codes = [normalize_code(code) for code in permission_codes]
    if not codes:
        return []
    result = await db.execute(select(Permission).where(Permission.permission_code.in_(codes)))
    permissions = result.scalars().all()
    found_codes = {permission.permission_code for permission in permissions}
    missing = sorted(set(codes) - found_codes)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown permission code(s): {', '.join(missing)}",
        )
    return list(permissions)


async def get_permission_groups_by_codes(db: AsyncSession, permission_group_codes: list[str]) -> list[PermissionGroup]:
    codes = [normalize_code(code) for code in permission_group_codes]
    if not codes:
        return []
    result = await db.execute(select(PermissionGroup).where(PermissionGroup.group_code.in_(codes)))
    groups = result.scalars().all()
    found_codes = {group.group_code for group in groups}
    missing = sorted(set(codes) - found_codes)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown permission group code(s): {', '.join(missing)}",
        )
    return list(groups)


async def create_permission(
    db: AsyncSession,
    payload: PermissionCreateRequest,
    *,
    actor_id: uuid.UUID | None = None,
) -> PermissionResponse:
    permission_code = normalize_code(payload.permission_code)
    existing = await db.execute(select(Permission.id).where(Permission.permission_code == permission_code))
    if existing.scalars().first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Permission code already exists")

    permission = Permission(
        permission_code=permission_code,
        permission_name=payload.permission_name.strip(),
        module_name=normalize_code(payload.module_name),
        action_name=normalize_code(payload.action_name),
        description=payload.description,
        is_system_permission=payload.is_system_permission,
        is_active=payload.is_active,
    )
    db.add(permission)
    await db.flush()
    await record_audit_event(
        db,
        table_name="permission",
        operation_type="INSERT",
        record_pk={"id": str(permission.id)},
        new_data={"permission_code": permission.permission_code},
        changed_by=actor_id,
    )
    await db.commit()
    await db.refresh(permission)
    return _permission_response(permission)


async def update_permission(
    db: AsyncSession,
    permission_id: uuid.UUID,
    payload: PermissionUpdateRequest,
    *,
    actor_id: uuid.UUID | None = None,
) -> PermissionResponse:
    permission = await get_permission_by_id(db, permission_id)
    old_data = {
        "permission_name": permission.permission_name,
        "module_name": permission.module_name,
        "action_name": permission.action_name,
        "description": permission.description,
    }
    updates = payload.model_dump(exclude_unset=True)
    if "permission_name" in updates and updates["permission_name"] is not None:
        permission.permission_name = updates["permission_name"].strip()
    if "module_name" in updates and updates["module_name"] is not None:
        permission.module_name = normalize_code(updates["module_name"])
    if "action_name" in updates and updates["action_name"] is not None:
        permission.action_name = normalize_code(updates["action_name"])
    if "description" in updates:
        permission.description = updates["description"]

    await record_audit_event(
        db,
        table_name="permission",
        operation_type="UPDATE",
        record_pk={"id": str(permission.id)},
        old_data=old_data,
        new_data=updates,
        changed_by=actor_id,
    )
    await db.commit()
    await db.refresh(permission)
    return _permission_response(permission)


async def set_permission_active(
    db: AsyncSession,
    permission_id: uuid.UUID,
    is_active: bool,
    *,
    actor_id: uuid.UUID | None = None,
) -> PermissionResponse:
    permission = await get_permission_by_id(db, permission_id)
    old_active = permission.is_active
    permission.is_active = is_active
    await record_audit_event(
        db,
        table_name="permission",
        operation_type="UPDATE",
        record_pk={"id": str(permission.id)},
        old_data={"is_active": old_active},
        new_data={"is_active": is_active},
        changed_by=actor_id,
    )
    await db.commit()
    await db.refresh(permission)
    return _permission_response(permission)


async def get_role_by_id(db: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


async def get_role_response(db: AsyncSession, role_id: uuid.UUID) -> RoleResponse:
    role = await get_role_by_id(db, role_id)
    return await _role_response(db, role)


async def get_roles_by_codes(db: AsyncSession, role_codes: list[str]) -> list[Role]:
    codes = [normalize_code(code) for code in role_codes]
    if not codes:
        return []
    result = await db.execute(select(Role).where(Role.role_code.in_(codes)))
    roles = result.scalars().all()
    found_codes = {role.role_code for role in roles}
    missing = sorted(set(codes) - found_codes)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown role code(s): {', '.join(missing)}",
        )
    return list(roles)


async def get_direct_role_permission_codes(db: AsyncSession, role_id: uuid.UUID) -> list[str]:
    result = await db.execute(
        select(Permission.permission_code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.permission_code)
    )
    return list(result.scalars().all())


async def get_role_permission_group_codes(db: AsyncSession, role_id: uuid.UUID) -> list[str]:
    result = await db.execute(
        select(PermissionGroup.group_code)
        .join(RolePermissionGroup, RolePermissionGroup.permission_group_id == PermissionGroup.id)
        .where(RolePermissionGroup.role_id == role_id)
        .order_by(PermissionGroup.display_order, PermissionGroup.group_code)
    )
    return list(result.scalars().all())


async def get_role_group_permission_codes(db: AsyncSession, role_id: uuid.UUID) -> list[str]:
    result = await db.execute(
        select(Permission.permission_code)
        .join(PermissionGroupItem, PermissionGroupItem.permission_id == Permission.id)
        .join(PermissionGroup, PermissionGroup.id == PermissionGroupItem.group_id)
        .join(RolePermissionGroup, RolePermissionGroup.permission_group_id == PermissionGroup.id)
        .where(
            RolePermissionGroup.role_id == role_id,
            PermissionGroup.is_active.is_(True),
            Permission.is_active.is_(True),
        )
        .order_by(Permission.permission_code)
    )
    return list(result.scalars().all())


async def get_role_effective_permission_codes(db: AsyncSession, role_id: uuid.UUID) -> list[str]:
    return sorted(
        set(await get_direct_role_permission_codes(db, role_id))
        | set(await get_role_group_permission_codes(db, role_id))
    )


async def get_role_permission_codes(db: AsyncSession, role_id: uuid.UUID) -> list[str]:
    return await get_role_effective_permission_codes(db, role_id)


async def list_roles(db: AsyncSession, *, include_inactive: bool = False) -> list[RoleResponse]:
    stmt = select(Role).order_by(Role.role_code)
    if not include_inactive:
        stmt = stmt.where(Role.is_active.is_(True))
    result = await db.execute(stmt)
    roles = result.scalars().all()
    responses: list[RoleResponse] = []
    for role in roles:
        responses.append(await _role_response(db, role))
    return responses


async def create_role(
    db: AsyncSession,
    payload: RoleCreateRequest,
    *,
    actor_id: uuid.UUID | None = None,
    request: Any | None = None,
    current_user: Any | None = None,
) -> RoleResponse:
    role_code = normalize_code(payload.role_code)
    existing = await db.execute(select(Role.id).where(Role.role_code == role_code))
    if existing.scalars().first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role code already exists")

    role = Role(
        role_code=role_code,
        role_name=payload.role_name.strip(),
        description=payload.description,
        is_system_role=False,
        is_active=payload.is_active,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(role)
    await db.flush()
    await _replace_role_permissions(db, role, payload.permission_codes, actor_id=actor_id)
    await _replace_role_permission_groups(db, role, payload.permission_group_codes, actor_id=actor_id)
    await record_audit_event(
        db,
        table_name="role",
        operation_type="INSERT",
        record_pk={"id": str(role.id)},
        new_data={"role_code": role.role_code},
        changed_by=actor_id,
        module_name="Role and Permission",
        entity_name="Role",
        action=audit_actions.ROLE_CREATED,
        event_description="Role created",
        request=request,
        current_user=current_user,
    )
    await db.commit()
    await db.refresh(role)
    return await _role_response(db, role)


async def update_role(
    db: AsyncSession,
    role_id: uuid.UUID,
    payload: RoleUpdateRequest,
    *,
    actor_id: uuid.UUID | None = None,
    request: Any | None = None,
    current_user: Any | None = None,
) -> RoleResponse:
    role = await get_role_by_id(db, role_id)
    old_data = {"role_name": role.role_name, "description": role.description}
    updates = payload.model_dump(exclude_unset=True)
    if "role_name" in updates and updates["role_name"] is not None:
        role.role_name = updates["role_name"].strip()
    if "description" in updates:
        role.description = updates["description"]
    role.updated_by = actor_id
    await record_audit_event(
        db,
        table_name="role",
        operation_type="UPDATE",
        record_pk={"id": str(role.id)},
        old_data=old_data,
        new_data=updates,
        changed_by=actor_id,
        module_name="Role and Permission",
        entity_name="Role",
        action=audit_actions.ROLE_UPDATED,
        event_description="Role updated",
        request=request,
        current_user=current_user,
    )
    await db.commit()
    await db.refresh(role)
    return await _role_response(db, role)


async def set_role_active(
    db: AsyncSession,
    role_id: uuid.UUID,
    is_active: bool,
    *,
    actor_id: uuid.UUID | None = None,
    request: Any | None = None,
    current_user: Any | None = None,
) -> RoleResponse:
    role = await get_role_by_id(db, role_id)
    old_active = role.is_active
    role.is_active = is_active
    role.updated_by = actor_id
    await record_audit_event(
        db,
        table_name="role",
        operation_type="UPDATE",
        record_pk={"id": str(role.id)},
        old_data={"is_active": old_active},
        new_data={"is_active": is_active},
        changed_by=actor_id,
        module_name="Role and Permission",
        entity_name="Role",
        action=audit_actions.ROLE_UPDATED if is_active else audit_actions.ROLE_DEACTIVATED,
        event_description="Role activated" if is_active else "Role deactivated",
        request=request,
        current_user=current_user,
    )
    await db.commit()
    await db.refresh(role)
    return await _role_response(db, role)


async def _replace_role_permissions(
    db: AsyncSession,
    role: Role,
    permission_codes: list[str],
    *,
    actor_id: uuid.UUID | None,
) -> None:
    normalized_codes = [normalize_code(code) for code in permission_codes]
    permissions = await get_permissions_by_codes(db, normalized_codes)
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for permission in permissions:
        db.add(RolePermission(role_id=role.id, permission_id=permission.id, created_by=actor_id))


async def _replace_role_permission_groups(
    db: AsyncSession,
    role: Role,
    permission_group_codes: list[str],
    *,
    actor_id: uuid.UUID | None,
) -> None:
    normalized_codes = [normalize_code(code) for code in permission_group_codes]
    groups = await get_permission_groups_by_codes(db, normalized_codes)
    await db.execute(delete(RolePermissionGroup).where(RolePermissionGroup.role_id == role.id))
    for group in groups:
        db.add(RolePermissionGroup(role_id=role.id, permission_group_id=group.id, created_by=actor_id))


async def set_role_permissions(
    db: AsyncSession,
    role_id: uuid.UUID,
    payload: RolePermissionAssignmentRequest,
    *,
    actor_id: uuid.UUID | None = None,
    request: Any | None = None,
    current_user: Any | None = None,
) -> RoleResponse:
    role = await get_role_by_id(db, role_id)
    old_permissions = await get_direct_role_permission_codes(db, role.id)
    new_permissions = [normalize_code(code) for code in payload.permission_codes]
    await _replace_role_permissions(db, role, payload.permission_codes, actor_id=actor_id)
    role.updated_by = actor_id
    action = audit_actions.PERMISSION_ASSIGNED
    if set(new_permissions) < set(old_permissions) or (set(old_permissions) - set(new_permissions) and not (set(new_permissions) - set(old_permissions))):
        action = audit_actions.PERMISSION_REMOVED
    await record_audit_event(
        db,
        table_name="role_permission",
        operation_type="UPDATE",
        record_pk={"role_id": str(role.id)},
        old_data={"permission_codes": old_permissions},
        new_data={"permission_codes": new_permissions},
        changed_by=actor_id,
        module_name="Role and Permission",
        entity_name="Role Permission",
        action=action,
        event_description="Role direct permissions changed",
        request=request,
        current_user=current_user,
    )
    await db.commit()
    await db.refresh(role)
    return await _role_response(db, role)


async def set_role_permission_groups(
    db: AsyncSession,
    role_id: uuid.UUID,
    payload: RolePermissionGroupAssignmentRequest,
    *,
    actor_id: uuid.UUID | None = None,
    request: Any | None = None,
    current_user: Any | None = None,
) -> RoleResponse:
    role = await get_role_by_id(db, role_id)
    old_groups = await get_role_permission_group_codes(db, role.id)
    new_groups = [normalize_code(code) for code in payload.permission_group_codes]
    await _replace_role_permission_groups(db, role, payload.permission_group_codes, actor_id=actor_id)
    role.updated_by = actor_id
    action = audit_actions.PERMISSION_ASSIGNED
    if set(new_groups) < set(old_groups) or (set(old_groups) - set(new_groups) and not (set(new_groups) - set(old_groups))):
        action = audit_actions.PERMISSION_REMOVED
    await record_audit_event(
        db,
        table_name="role_permission_group",
        operation_type="UPDATE",
        record_pk={"role_id": str(role.id)},
        old_data={"permission_group_codes": old_groups},
        new_data={"permission_group_codes": new_groups},
        changed_by=actor_id,
        module_name="Role and Permission",
        entity_name="Role Permission Group",
        action=action,
        event_description="Role permission groups changed",
        request=request,
        current_user=current_user,
    )
    await db.commit()
    await db.refresh(role)
    return await _role_response(db, role)
from app.core import audit_actions
