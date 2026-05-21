import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.asset_group_schema import ApiResponse, AssetGroupCreate, AssetGroupMembershipCreate, AssetGroupUpdate
from app.services.asset_group_service import (
    add_assets_to_group,
    create_asset_group,
    delete_asset_group,
    get_asset_group_assets,
    get_asset_group_by_id,
    get_asset_group_tree,
    get_asset_groups,
    remove_asset_from_group,
    update_asset_group,
)

router = APIRouter(prefix="/asset-groups", tags=["asset-grouping"])


@router.get("", response_model=ApiResponse)
async def asset_group_list(
    q: str | None = Query(default=None, description="Search by group name, code, or description"),
    group_type: str | None = Query(default=None, description="Filter by SYSTEM or SUB_SYSTEM"),
    org_node_id: uuid.UUID | None = Query(default=None, description="Optional organization scope"),
    include_inactive: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_groups(
        db,
        q=q,
        group_type=group_type,
        org_node_id=org_node_id,
        include_inactive=include_inactive,
    )
    return {
        "success": True,
        "message": "Asset groups fetched successfully",
        "data": data,
    }


@router.get("/tree", response_model=ApiResponse)
async def asset_group_tree(
    org_node_id: uuid.UUID | None = Query(default=None, description="Optional organization scope"),
    include_inactive: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_group_tree(db, org_node_id=org_node_id, include_inactive=include_inactive)
    return {
        "success": True,
        "message": "Asset group tree fetched successfully",
        "data": data,
    }


@router.get("/{group_id}", response_model=ApiResponse)
async def asset_group_detail(
    group_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_group_by_id(db, group_id)
    return {
        "success": True,
        "message": "Asset group fetched successfully",
        "data": data,
    }


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def asset_group_create(
    payload: AssetGroupCreate,
    current_user: CurrentUser = Depends(require_permission("ASSET_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_asset_group(db, payload)
    return {
        "success": True,
        "message": "Asset group created successfully",
        "data": data,
    }


@router.put("/{group_id}", response_model=ApiResponse)
async def asset_group_update(
    group_id: uuid.UUID,
    payload: AssetGroupUpdate,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_asset_group(db, group_id, payload)
    return {
        "success": True,
        "message": "Asset group updated successfully",
        "data": data,
    }


@router.delete("/{group_id}", response_model=ApiResponse)
async def asset_group_delete(
    group_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_asset_group(db, group_id)
    return {
        "success": True,
        "message": "Asset group deleted successfully",
        "data": {"group_id": group_id},
    }


@router.get("/{group_id}/assets", response_model=ApiResponse)
async def asset_group_assets(
    group_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_group_assets(db, group_id)
    return {
        "success": True,
        "message": "Asset group memberships fetched successfully",
        "data": data,
    }


@router.post("/{group_id}/assets", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def asset_group_add_assets(
    group_id: uuid.UUID,
    payload: AssetGroupMembershipCreate,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await add_assets_to_group(db, group_id, payload)
    return {
        "success": True,
        "message": "Assets added to group successfully",
        "data": data,
    }


@router.delete("/{group_id}/assets/{asset_uuid}", response_model=ApiResponse)
async def asset_group_remove_asset(
    group_id: uuid.UUID,
    asset_uuid: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await remove_asset_from_group(db, group_id, asset_uuid)
    return {
        "success": True,
        "message": "Asset removed from group successfully",
        "data": {
            "group_id": group_id,
            "asset_uuid": asset_uuid,
        },
    }
