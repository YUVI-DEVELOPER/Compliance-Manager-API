from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _jwt_settings() -> tuple[str, str]:
    settings = get_settings()
    if not settings.JWT_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET_KEY is not configured",
        )
    return settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM


def create_access_token(
    *,
    subject: str,
    email: str,
    roles: list[str],
    permissions: list[str],
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    settings = get_settings()
    secret_key, algorithm = _jwt_settings()
    expires_in_seconds = int((expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)).total_seconds())
    now = datetime.now(UTC)
    expire = now + timedelta(seconds=expires_in_seconds)
    payload: dict[str, Any] = {
        "sub": subject,
        "email": email,
        "roles": roles,
        "permissions": permissions,
        "iat": int(now.timestamp()),
        "exp": expire,
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm), expires_in_seconds


def decode_access_token(token: str) -> dict[str, Any]:
    secret_key, algorithm = _jwt_settings()
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return payload
