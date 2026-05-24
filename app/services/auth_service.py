from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit_actions
from app.core.security import create_access_token, hash_password, verify_password
from app.models.app_user import AppUser
from app.models.login_audit_log import LoginAuditLog
from app.schemas.auth_schema import AuthUserProfile, ChangePasswordRequest, CurrentUser, LoginRequest, LoginSuccessResponse
from app.schemas.app_user_schema import UserLoginRequest
from app.services.app_user_service import get_user_by_email, get_user_by_id
from app.services.audit_log_service import create_audit_log
from app.services.rbac_service import get_user_role_permission_profile, record_audit_event


def _request_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    forwarded_for = request.headers.get("x-forwarded-for") if request is not None else None
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host


def _request_user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    return request.headers.get("user-agent")


def _verify_password_with_legacy_support(user: AppUser, plain_password: str) -> tuple[bool, bool]:
    if user.password_hash.startswith("hashed::"):
        return user.password_hash == f"hashed::{plain_password}", True
    try:
        return verify_password(plain_password, user.password_hash), False
    except ValueError:
        return False, False


async def _write_login_audit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    email: str,
    login_status: str,
    request: Request | None = None,
    failure_reason: str | None = None,
    logout_time: datetime | None = None,
) -> None:
    now = datetime.now(UTC)
    db.add(
        LoginAuditLog(
            user_id=user_id,
            email=email.lower().strip(),
            login_time=now,
            logout_time=logout_time,
            ip_address=_request_ip(request),
            user_agent=_request_user_agent(request),
            login_status=login_status,
            failure_reason=failure_reason,
            created_at=now,
        )
    )


async def build_auth_profile(db: AsyncSession, user: AppUser) -> AuthUserProfile:
    roles, permissions = await get_user_role_permission_profile(db, user.id)
    return AuthUserProfile(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        roles=roles,
        permissions=permissions,
    )


async def login(
    db: AsyncSession,
    payload: LoginRequest | UserLoginRequest,
    *,
    request: Request | None = None,
) -> LoginSuccessResponse:
    email = payload.email.lower().strip()
    user = await get_user_by_email(db, email)
    invalid_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if user is None:
        await _write_login_audit(db, user_id=None, email=email, login_status="FAILED", request=request, failure_reason="INVALID_CREDENTIALS")
        await create_audit_log(
            db,
            request=request,
            module_name="Authentication",
            entity_name="User Session",
            table_name="login_audit_log",
            action=audit_actions.LOGIN_FAILED,
            event_description="Login failed",
            new_data={"email": email, "failure_reason": "INVALID_CREDENTIALS"},
            status="FAILED",
            reason="INVALID_CREDENTIALS",
        )
        await db.commit()
        raise invalid_error

    password_ok, used_legacy_hash = _verify_password_with_legacy_support(user, payload.password)
    if not password_ok:
        user.failed_login_count += 1
        await _write_login_audit(
            db,
            user_id=user.id,
            email=email,
            login_status="FAILED",
            request=request,
            failure_reason="INVALID_CREDENTIALS",
        )
        await create_audit_log(
            db,
            request=request,
            current_user=user.id,
            module_name="Authentication",
            entity_name="User Session",
            table_name="login_audit_log",
            record_id=user.id,
            action=audit_actions.LOGIN_FAILED,
            event_description="Login failed",
            new_data={"email": email, "failure_reason": "INVALID_CREDENTIALS"},
            status="FAILED",
            reason="INVALID_CREDENTIALS",
        )
        await db.commit()
        raise invalid_error

    if not user.is_active:
        await _write_login_audit(db, user_id=user.id, email=email, login_status="FAILED", request=request, failure_reason="INACTIVE_ACCOUNT")
        await create_audit_log(
            db,
            request=request,
            current_user=user.id,
            module_name="Authentication",
            entity_name="User Session",
            table_name="login_audit_log",
            record_id=user.id,
            action=audit_actions.LOGIN_FAILED,
            event_description="Login failed for inactive account",
            new_data={"email": email, "failure_reason": "INACTIVE_ACCOUNT"},
            status="FAILED",
            reason="INACTIVE_ACCOUNT",
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

    if user.is_locked:
        await _write_login_audit(db, user_id=user.id, email=email, login_status="FAILED", request=request, failure_reason="LOCKED_ACCOUNT")
        await create_audit_log(
            db,
            request=request,
            current_user=user.id,
            module_name="Authentication",
            entity_name="User Session",
            table_name="login_audit_log",
            record_id=user.id,
            action=audit_actions.LOGIN_FAILED,
            event_description="Login failed for locked account",
            new_data={"email": email, "failure_reason": "LOCKED_ACCOUNT"},
            status="FAILED",
            reason="LOCKED_ACCOUNT",
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is locked")

    if used_legacy_hash:
        user.password_hash = hash_password(payload.password)
        user.password_changed_at = datetime.now(UTC)
    user.failed_login_count = 0
    user.last_login_at = datetime.now(UTC)
    profile = await build_auth_profile(db, user)
    token, expires_in = create_access_token(
        subject=str(user.id),
        email=user.email,
        roles=profile.roles,
        permissions=profile.permissions,
    )
    await _write_login_audit(db, user_id=user.id, email=email, login_status="SUCCESS", request=request)
    await create_audit_log(
        db,
        request=request,
        current_user=CurrentUser(
            id=profile.id,
            full_name=profile.full_name,
            email=profile.email,
            roles=profile.roles,
            permissions=profile.permissions,
        ),
        module_name="Authentication",
        entity_name="User Session",
        table_name="login_audit_log",
        record_id=user.id,
        action=audit_actions.LOGIN_SUCCESS,
        event_description="Login successful",
        new_data={"email": user.email},
    )
    await db.commit()
    return LoginSuccessResponse(access_token=token, expires_in=expires_in, user=profile)


async def logout(
    db: AsyncSession,
    current_user: CurrentUser,
    *,
    request: Request | None = None,
) -> None:
    now = datetime.now(UTC)
    await _write_login_audit(
        db,
        user_id=current_user.id,
        email=current_user.email,
        login_status="LOGOUT",
        request=request,
        logout_time=now,
    )
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Authentication",
        entity_name="User Session",
        table_name="login_audit_log",
        record_id=current_user.id,
        action=audit_actions.LOGOUT,
        event_description="Logout successful",
        new_data={"email": str(current_user.email), "logout_time": now.isoformat()},
    )
    await db.commit()


async def change_password(
    db: AsyncSession,
    current_user: CurrentUser,
    payload: ChangePasswordRequest,
) -> None:
    user = await get_user_by_id(db, current_user.id)
    password_ok, _ = _verify_password_with_legacy_support(user, payload.current_password)
    if not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid current password")
    user.password_hash = hash_password(payload.new_password)
    user.password_changed_at = datetime.now(UTC)
    user.updated_by = current_user.id
    await record_audit_event(
        db,
        table_name="app_user",
        operation_type="UPDATE",
        record_pk={"id": str(user.id)},
        new_data={"password_changed": True},
        changed_by=current_user.id,
    )
    await db.commit()
