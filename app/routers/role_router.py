import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.rbac_schema import (
    RoleCreateRequest,
    RolePermissionAssignmentRequest,
    RolePermissionGroupAssignmentRequest,
    RoleResponse,
    RoleUpdateRequest,
)
from app.services.rbac_service import (
    create_role,
    get_role_by_id,
    get_role_permission_codes,
    get_role_permission_group_codes,
    get_role_response,
    list_roles,
    set_role_active,
    set_role_permission_groups,
    set_role_permissions,
    update_role,
)

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("", response_model=list[RoleResponse])
async def list_roles_api(
    include_inactive: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("ROLE_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> list[RoleResponse]:
    return await list_roles(db, include_inactive=include_inactive)


@router.post("", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role_api(
    payload: RoleCreateRequest,
    current_user: CurrentUser = Depends(require_permission("ROLE_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    return await create_role(db, payload, actor_id=current_user.id)


@router.get("/{role_id}", response_model=RoleResponse)
async def get_role_api(
    role_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ROLE_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    return await get_role_response(db, role_id)


@router.patch("/{role_id}", response_model=RoleResponse)
async def update_role_api(
    role_id: uuid.UUID,
    payload: RoleUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("ROLE_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    return await update_role(db, role_id, payload, actor_id=current_user.id)


@router.patch("/{role_id}/activate", response_model=RoleResponse)
async def activate_role_api(
    role_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ROLE_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    return await set_role_active(db, role_id, True, actor_id=current_user.id)


@router.patch("/{role_id}/deactivate", response_model=RoleResponse)
async def deactivate_role_api(
    role_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ROLE_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    return await set_role_active(db, role_id, False, actor_id=current_user.id)


@router.get("/{role_id}/permissions", response_model=list[str])
async def get_role_permissions_api(
    role_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ROLE_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    await get_role_by_id(db, role_id)
    return await get_role_permission_codes(db, role_id)


@router.get("/{role_id}/permission-groups", response_model=list[str])
async def get_role_permission_groups_api(
    role_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ROLE_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    await get_role_by_id(db, role_id)
    return await get_role_permission_group_codes(db, role_id)


@router.patch("/{role_id}/permissions", response_model=RoleResponse)
async def set_role_permissions_api(
    role_id: uuid.UUID,
    payload: RolePermissionAssignmentRequest,
    current_user: CurrentUser = Depends(require_permission("ROLE_ASSIGN_PERMISSION")),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    return await set_role_permissions(db, role_id, payload, actor_id=current_user.id)


@router.patch("/{role_id}/permission-groups", response_model=RoleResponse)
async def set_role_permission_groups_api(
    role_id: uuid.UUID,
    payload: RolePermissionGroupAssignmentRequest,
    current_user: CurrentUser = Depends(require_permission("ROLE_ASSIGN_PERMISSION")),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    return await set_role_permission_groups(db, role_id, payload, actor_id=current_user.id)
