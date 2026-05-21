from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.app_user import AppUser
from app.schemas.auth_schema import CurrentUser
from app.services.auth_service import build_auth_profile


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    subject = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = uuid.UUID(str(subject))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await db.get(AppUser, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")
    if user.is_locked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is locked")

    profile = await build_auth_profile(db, user)
    return CurrentUser(
        id=profile.id,
        full_name=profile.full_name,
        email=profile.email,
        roles=profile.roles,
        permissions=profile.permissions,
    )


def _missing_permission_detail(permission_codes: Sequence[str], mode: str) -> str:
    return "Access denied."


def require_permission(permission_code: str) -> Callable[..., CurrentUser]:
    async def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if permission_code not in current_user.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_missing_permission_detail([permission_code], "permission"),
            )
        return current_user

    return dependency


def require_any_permission(permission_codes: Sequence[str]) -> Callable[..., CurrentUser]:
    codes = list(permission_codes)

    async def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(code in current_user.permissions for code in codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_missing_permission_detail(codes, "any of"),
            )
        return current_user

    return dependency


def require_all_permissions(permission_codes: Sequence[str]) -> Callable[..., CurrentUser]:
    codes = list(permission_codes)

    async def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not all(code in current_user.permissions for code in codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_missing_permission_detail(codes, "all of"),
            )
        return current_user

    return dependency
