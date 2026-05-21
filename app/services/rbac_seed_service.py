from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.rbac import PERMISSION_CATALOG, PERMISSION_GROUP_CATALOG, ROLE_CATALOG
from app.core.security import hash_password, verify_password
from app.models.app_user import AppUser
from app.models.permission import Permission
from app.models.permission_group import PermissionGroup
from app.models.permission_group_item import PermissionGroupItem
from app.models.role import Role
from app.models.role_permission import RolePermission
from app.models.role_permission_group import RolePermissionGroup
from app.models.user_role import UserRole

logger = logging.getLogger("app.rbac.seed")


def _password_matches(password_hash: str, plain_password: str) -> bool:
    if password_hash.startswith("hashed::"):
        return password_hash == f"hashed::{plain_password}"
    try:
        return verify_password(plain_password, password_hash)
    except ValueError:
        return False


async def _ensure_default_admin(
    db,
    *,
    admin_role: Role | None,
    existing_user_count: int,
) -> None:
    settings = get_settings()
    admin_email = settings.DEFAULT_ADMIN_EMAIL.lower().strip()
    admin_password = settings.DEFAULT_ADMIN_PASSWORD
    admin_name = settings.DEFAULT_ADMIN_NAME.strip() or "System Admin"

    if not admin_email or not admin_password:
        if existing_user_count == 0:
            message = (
                "DEFAULT_ADMIN_EMAIL and DEFAULT_ADMIN_PASSWORD are required to seed the first admin user "
                "when app_user is empty"
            )
            if settings.APP_ENV != "production":
                raise RuntimeError(message)
            logger.warning(message)
        return

    result = await db.execute(select(AppUser).where(AppUser.email == admin_email))
    admin = result.scalars().first()
    now = datetime.now(UTC)

    if admin is None:
        admin = AppUser(
            full_name=admin_name,
            email=admin_email,
            password_hash=hash_password(admin_password),
            is_active=True,
            is_locked=False,
            failed_login_count=0,
            password_changed_at=now,
        )
        db.add(admin)
        await db.flush()
        logger.info("seeded_default_admin email=%s", admin.email)
    else:
        admin.full_name = admin_name
        admin.is_active = True
        admin.is_locked = False
        admin.failed_login_count = 0
        if not _password_matches(admin.password_hash, admin_password) or admin.password_hash.startswith("hashed::"):
            admin.password_hash = hash_password(admin_password)
            admin.password_changed_at = now
        logger.info("synced_default_admin email=%s", admin.email)

    if admin_role is not None:
        existing_role = await db.execute(
            select(UserRole.id).where(UserRole.user_id == admin.id, UserRole.role_id == admin_role.id)
        )
        if existing_role.scalars().first() is None:
            db.add(UserRole(user_id=admin.id, role_id=admin_role.id))


async def seed_rbac_defaults() -> None:
    async with SessionLocal() as db:
        permission_map: dict[str, Permission] = {}
        for seed in PERMISSION_CATALOG:
            result = await db.execute(
                select(Permission).where(Permission.permission_code == seed.permission_code)
            )
            permission = result.scalars().first()
            if permission is None:
                permission = Permission(
                    permission_code=seed.permission_code,
                    permission_name=seed.permission_name,
                    module_name=seed.module_name,
                    action_name=seed.action_name,
                    description=seed.description,
                    is_system_permission=True,
                    is_active=True,
                )
                db.add(permission)
                await db.flush()
            else:
                permission.permission_name = seed.permission_name
                permission.module_name = seed.module_name
                permission.action_name = seed.action_name
                permission.description = seed.description
                permission.is_system_permission = True
            permission_map[permission.permission_code] = permission

        group_map: dict[str, PermissionGroup] = {}
        for seed in PERMISSION_GROUP_CATALOG:
            result = await db.execute(select(PermissionGroup).where(PermissionGroup.group_code == seed.group_code))
            group = result.scalars().first()
            if group is None:
                group = PermissionGroup(
                    group_code=seed.group_code,
                    group_name=seed.group_name,
                    module_name=seed.module_name,
                    description=seed.description,
                    display_order=seed.display_order,
                    is_system_group=True,
                    is_active=True,
                )
                db.add(group)
                await db.flush()
            else:
                group.group_name = seed.group_name
                group.module_name = seed.module_name
                group.description = seed.description
                group.display_order = seed.display_order
                group.is_system_group = True
                group.is_active = True
            group_map[group.group_code] = group

            await db.execute(delete(PermissionGroupItem).where(PermissionGroupItem.group_id == group.id))
            for permission_code in seed.permission_codes:
                permission = permission_map.get(permission_code)
                if permission is not None:
                    db.add(PermissionGroupItem(group_id=group.id, permission_id=permission.id))

        role_map: dict[str, Role] = {}
        for seed in ROLE_CATALOG:
            result = await db.execute(select(Role).where(Role.role_code == seed.role_code))
            role = result.scalars().first()
            if role is None:
                role = Role(
                    role_code=seed.role_code,
                    role_name=seed.role_name,
                    description=seed.description,
                    is_system_role=True,
                    is_active=True,
                )
                db.add(role)
                await db.flush()
            else:
                role.role_name = seed.role_name
                role.description = seed.description
                role.is_system_role = True
            role_map[role.role_code] = role

            await db.execute(delete(RolePermissionGroup).where(RolePermissionGroup.role_id == role.id))
            for group_code in seed.permission_group_codes:
                group = group_map.get(group_code)
                if group is not None:
                    db.add(RolePermissionGroup(role_id=role.id, permission_group_id=group.id))

            await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
            for permission_code in seed.permission_codes:
                permission = permission_map.get(permission_code)
                if permission is not None:
                    db.add(RolePermission(role_id=role.id, permission_id=permission.id))

        user_count_result = await db.execute(select(func.count(AppUser.id)))
        user_count = int(user_count_result.scalar_one() or 0)
        await _ensure_default_admin(db, admin_role=role_map.get("ADMIN"), existing_user_count=user_count)

        await db.commit()
