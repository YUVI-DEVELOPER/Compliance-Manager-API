from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.rbac_schema import GroupedPermissionGroupsResponse, PermissionGroupResponse
from app.services.rbac_service import list_permission_groups, list_permission_groups_grouped_by_module

router = APIRouter(prefix="/permission-groups", tags=["permission-groups"])


@router.get("", response_model=list[PermissionGroupResponse])
async def list_permission_groups_api(
    include_inactive: bool = Query(default=False),
    module_name: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("ROLE_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> list[PermissionGroupResponse]:
    return await list_permission_groups(db, include_inactive=include_inactive, module_name=module_name)


@router.get("/grouped-by-module", response_model=list[GroupedPermissionGroupsResponse])
async def list_permission_groups_grouped_api(
    include_inactive: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("ROLE_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> list[GroupedPermissionGroupsResponse]:
    return await list_permission_groups_grouped_by_module(db, include_inactive=include_inactive)
