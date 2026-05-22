import uuid

from fastapi import APIRouter, Depends, Request, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.app_user_schema import (
    UserCreateRequest,
    UserLoginRequest,
    UserResetPasswordRequest,
    UserResponse,
    UserRoleAssignmentRequest,
    UserUpdateRequest,
)
from app.schemas.auth_schema import CurrentUser
from app.services.app_user_service import (
    create_user,
    get_user_by_id,
    get_user_response,
    get_user_roles,
    list_users,
    reset_user_password,
    set_user_active,
    set_user_roles,
    update_user,
)
from app.services.auth_service import login

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/login")
async def login_user_api(
    payload: UserLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    data = await login(db, payload, request=request)
    return {
        "success": True,
        "message": "Login successful",
        "data": data.model_dump(mode="json"),
    }


@router.get("", response_model=list[UserResponse])
async def list_users_api(
    include_inactive: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("USER_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> list[UserResponse]:
    return await list_users(db, include_inactive=include_inactive)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user_api(
    payload: UserCreateRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("USER_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await create_user(db, payload, actor_id=current_user.id, request=request, current_user=current_user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_api(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("USER_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    user = await get_user_by_id(db, user_id)
    return await get_user_response(db, user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user_api(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("USER_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await update_user(db, user_id, payload, actor_id=current_user.id, request=request, current_user=current_user)


@router.patch("/{user_id}/activate", response_model=UserResponse)
async def activate_user_api(
    user_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("USER_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await set_user_active(db, user_id, True, actor_id=current_user.id, request=request, current_user=current_user)


@router.patch("/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user_api(
    user_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("USER_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await set_user_active(db, user_id, False, actor_id=current_user.id, request=request, current_user=current_user)


@router.patch("/{user_id}/reset-password", response_model=UserResponse)
async def reset_user_password_api(
    user_id: uuid.UUID,
    payload: UserResetPasswordRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("USER_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await reset_user_password(db, user_id, payload, actor_id=current_user.id, request=request, current_user=current_user)


@router.get("/{user_id}/roles", response_model=list[str])
async def get_user_roles_api(
    user_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("USER_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    return await get_user_roles(db, user_id)


@router.patch("/{user_id}/roles", response_model=UserResponse)
async def set_user_roles_api(
    user_id: uuid.UUID,
    payload: UserRoleAssignmentRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("USER_ASSIGN_ROLE")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await set_user_roles(db, user_id, payload, actor_id=current_user.id, request=request, current_user=current_user)
