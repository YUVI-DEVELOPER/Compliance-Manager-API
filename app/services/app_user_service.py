from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit_actions
from app.core.security import hash_password
from app.models.app_user import AppUser
from app.models.role import Role
from app.models.user_role import UserRole
from app.schemas.app_user_schema import (
    UserCreateRequest,
    UserResetPasswordRequest,
    UserResponse,
    UserRoleAssignmentRequest,
    UserUpdateRequest,
)
from app.services.rbac_service import (
    get_roles_by_codes,
    get_user_role_permission_profile,
    normalize_code,
    record_audit_event,
)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


async def _user_response(db: AsyncSession, user: AppUser) -> UserResponse:
    roles, permissions = await get_user_role_permission_profile(db, user.id)
    data = UserResponse.model_validate(user).model_dump()
    data["roles"] = roles
    data["permissions"] = permissions
    return UserResponse(**data)


async def get_user_response(db: AsyncSession, user: AppUser) -> UserResponse:
    return await _user_response(db, user)


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> AppUser:
    user = await db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def get_user_by_email(db: AsyncSession, email: str) -> AppUser | None:
    result = await db.execute(select(AppUser).where(AppUser.email == email.lower().strip()))
    return result.scalars().first()


async def list_users(db: AsyncSession, *, include_inactive: bool = False) -> list[UserResponse]:
    stmt = select(AppUser).order_by(AppUser.full_name, AppUser.email)
    if not include_inactive:
        stmt = stmt.where(AppUser.is_active.is_(True))
    result = await db.execute(stmt)
    users = result.scalars().all()
    return [await _user_response(db, user) for user in users]


async def create_user(
    db: AsyncSession,
    payload: UserCreateRequest,
    *,
    actor_id: uuid.UUID | None = None,
    request=None,
    current_user=None,
) -> UserResponse:
    email = payload.email.lower().strip()
    existing = await get_user_by_email(db, email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    user = AppUser(
        full_name=payload.full_name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
        designation=_clean_optional(payload.designation),
        department=_clean_optional(payload.department),
        phone=_clean_optional(payload.phone),
        is_active=True,
        is_locked=False,
        failed_login_count=0,
        password_changed_at=datetime.now(UTC),
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(user)
    await db.flush()
    if payload.role_codes:
        await _replace_user_roles(db, user, payload.role_codes, actor_id=actor_id)
    await record_audit_event(
        db,
        table_name="app_user",
        operation_type="INSERT",
        record_pk={"id": str(user.id)},
        new_data={"email": user.email, "role_codes": [normalize_code(code) for code in payload.role_codes]},
        changed_by=actor_id,
        module_name="User Management",
        entity_name="User",
        action=audit_actions.USER_CREATED,
        event_description="User created",
        request=request,
        current_user=current_user,
    )
    await db.commit()
    await db.refresh(user)
    return await _user_response(db, user)


async def update_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    *,
    actor_id: uuid.UUID | None = None,
    request=None,
    current_user=None,
) -> UserResponse:
    user = await get_user_by_id(db, user_id)
    old_data = {
        "full_name": user.full_name,
        "email": user.email,
        "designation": user.designation,
        "department": user.department,
        "phone": user.phone,
        "is_locked": user.is_locked,
    }
    updates = payload.model_dump(exclude_unset=True)
    if "email" in updates and updates["email"] is not None:
        email = str(updates["email"]).lower().strip()
        existing = await get_user_by_email(db, email)
        if existing is not None and existing.id != user.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
        user.email = email
    if "full_name" in updates and updates["full_name"] is not None:
        user.full_name = updates["full_name"].strip()
    if "designation" in updates:
        user.designation = _clean_optional(updates["designation"])
    if "department" in updates:
        user.department = _clean_optional(updates["department"])
    if "phone" in updates:
        user.phone = _clean_optional(updates["phone"])
    if "is_locked" in updates and updates["is_locked"] is not None:
        user.is_locked = bool(updates["is_locked"])
        if not user.is_locked:
            user.failed_login_count = 0
    user.updated_by = actor_id
    await record_audit_event(
        db,
        table_name="app_user",
        operation_type="UPDATE",
        record_pk={"id": str(user.id)},
        old_data=old_data,
        new_data=updates,
        changed_by=actor_id,
        module_name="User Management",
        entity_name="User",
        action=audit_actions.USER_UPDATED,
        event_description="User updated",
        request=request,
        current_user=current_user,
    )
    await db.commit()
    await db.refresh(user)
    return await _user_response(db, user)


async def set_user_active(
    db: AsyncSession,
    user_id: uuid.UUID,
    is_active: bool,
    *,
    actor_id: uuid.UUID | None = None,
    request=None,
    current_user=None,
) -> UserResponse:
    user = await get_user_by_id(db, user_id)
    old_active = user.is_active
    user.is_active = is_active
    user.updated_by = actor_id
    await record_audit_event(
        db,
        table_name="app_user",
        operation_type="UPDATE",
        record_pk={"id": str(user.id)},
        old_data={"is_active": old_active},
        new_data={"is_active": is_active},
        changed_by=actor_id,
        module_name="User Management",
        entity_name="User",
        action=audit_actions.USER_ACTIVATED if is_active else audit_actions.USER_DEACTIVATED,
        event_description="User activated" if is_active else "User deactivated",
        request=request,
        current_user=current_user,
    )
    await db.commit()
    await db.refresh(user)
    return await _user_response(db, user)


async def reset_user_password(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: UserResetPasswordRequest,
    *,
    actor_id: uuid.UUID | None = None,
    request=None,
    current_user=None,
) -> UserResponse:
    user = await get_user_by_id(db, user_id)
    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = datetime.now(UTC)
    user.failed_login_count = 0
    user.is_locked = False
    user.updated_by = actor_id
    await record_audit_event(
        db,
        table_name="app_user",
        operation_type="UPDATE",
        record_pk={"id": str(user.id)},
        old_data=None,
        new_data={"password_reset": True},
        changed_by=actor_id,
        module_name="User Management",
        entity_name="User",
        action=audit_actions.USER_UPDATED,
        event_description="User password reset",
        request=request,
        current_user=current_user,
    )
    await db.commit()
    await db.refresh(user)
    return await _user_response(db, user)


async def _replace_user_roles(
    db: AsyncSession,
    user: AppUser,
    role_codes: list[str],
    *,
    actor_id: uuid.UUID | None,
) -> None:
    roles: list[Role] = await get_roles_by_codes(db, role_codes)
    await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for role in roles:
        db.add(UserRole(user_id=user.id, role_id=role.id, created_by=actor_id))


async def get_user_roles(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    await get_user_by_id(db, user_id)
    roles, _ = await get_user_role_permission_profile(db, user_id)
    return roles


async def set_user_roles(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: UserRoleAssignmentRequest,
    *,
    actor_id: uuid.UUID | None = None,
    request=None,
    current_user=None,
) -> UserResponse:
    user = await get_user_by_id(db, user_id)
    old_roles, _ = await get_user_role_permission_profile(db, user.id)
    new_roles = [normalize_code(code) for code in payload.role_codes]
    await _replace_user_roles(db, user, payload.role_codes, actor_id=actor_id)
    user.updated_by = actor_id
    action = audit_actions.USER_ROLE_ASSIGNED
    if set(new_roles) < set(old_roles) or (set(old_roles) - set(new_roles) and not (set(new_roles) - set(old_roles))):
        action = audit_actions.USER_ROLE_REMOVED
    await record_audit_event(
        db,
        table_name="user_role",
        operation_type="UPDATE",
        record_pk={"user_id": str(user.id)},
        old_data={"role_codes": old_roles},
        new_data={"role_codes": new_roles},
        changed_by=actor_id,
        module_name="User Management",
        entity_name="User Role",
        action=action,
        event_description="User role assignment changed",
        request=request,
        current_user=current_user,
    )
    await db.commit()
    await db.refresh(user)
    return await _user_response(db, user)
