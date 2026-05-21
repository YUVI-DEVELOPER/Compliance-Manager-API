import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.rbac_schema import (
    GroupedPermissionsResponse,
    PermissionCreateRequest,
    PermissionResponse,
    PermissionUpdateRequest,
)
from app.services.rbac_service import (
    create_permission,
    get_permission_by_id,
    list_permissions,
    list_permissions_grouped_by_module,
    set_permission_active,
    update_permission,
)

router = APIRouter(prefix="/permissions", tags=["permissions"])


@router.get("", response_model=list[PermissionResponse])
async def list_permissions_api(
    include_inactive: bool = Query(default=False),
    module_name: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("ROLE_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> list[PermissionResponse]:
    return await list_permissions(db, include_inactive=include_inactive, module_name=module_name)


@router.get("/grouped-by-module", response_model=list[GroupedPermissionsResponse])
async def list_permissions_grouped_api(
    include_inactive: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("ROLE_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> list[GroupedPermissionsResponse]:
    return await list_permissions_grouped_by_module(db, include_inactive=include_inactive)


@router.post("", response_model=PermissionResponse, status_code=status.HTTP_201_CREATED)
async def create_permission_api(
    payload: PermissionCreateRequest,
    current_user: CurrentUser = Depends(require_permission("ROLE_ASSIGN_PERMISSION")),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse:
    return await create_permission(db, payload, actor_id=current_user.id)


@router.patch("/{permission_id}", response_model=PermissionResponse)
async def update_permission_api(
    permission_id: uuid.UUID,
    payload: PermissionUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("ROLE_ASSIGN_PERMISSION")),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse:
    return await update_permission(db, permission_id, payload, actor_id=current_user.id)


@router.patch("/{permission_id}/activate", response_model=PermissionResponse)
async def activate_permission_api(
    permission_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ROLE_ASSIGN_PERMISSION")),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse:
    return await set_permission_active(db, permission_id, True, actor_id=current_user.id)


@router.patch("/{permission_id}/deactivate", response_model=PermissionResponse)
async def deactivate_permission_api(
    permission_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ROLE_ASSIGN_PERMISSION")),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse:
    return await set_permission_active(db, permission_id, False, actor_id=current_user.id)


@router.get("/{permission_id}", response_model=PermissionResponse)
async def get_permission_api(
    permission_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ROLE_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> PermissionResponse:
    return PermissionResponse.model_validate(await get_permission_by_id(db, permission_id))
