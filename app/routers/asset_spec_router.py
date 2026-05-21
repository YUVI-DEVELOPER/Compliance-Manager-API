import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.asset_spec_schema import ApiResponse, AssetSpecCreateRequest, AssetSpecUpdateRequest
from app.services.asset_spec_service import (
    create_asset_spec,
    delete_asset_spec,
    get_asset_spec_by_id,
    get_asset_specs,
    update_asset_spec,
)

router = APIRouter(prefix="/asset-specs", tags=["asset-specs"])


@router.get("", response_model=ApiResponse)
async def asset_spec_list(
    asset_sub_category_id: int | None = Query(default=None, description="Filter by asset sub-category ID"),
    include_inactive: bool = Query(default=False, description="Include inactive spec rows"),
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_specs(db, asset_sub_category_id=asset_sub_category_id, include_inactive=include_inactive)
    return {
        "success": True,
        "message": "Asset specs fetched successfully",
        "data": data,
    }


@router.get("/asset-sub-categories/{asset_sub_category_id}/specs", response_model=ApiResponse)
async def asset_spec_list_by_sub_category(
    asset_sub_category_id: int,
    include_inactive: bool = Query(default=False, description="Include inactive spec rows"),
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_specs(db, asset_sub_category_id=asset_sub_category_id, include_inactive=include_inactive)
    return {
        "success": True,
        "message": "Asset specs fetched successfully",
        "data": data,
    }


@router.get("/{asset_spec_id}", response_model=ApiResponse)
async def asset_spec_detail(
    asset_spec_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_spec_by_id(db, asset_spec_id)
    return {
        "success": True,
        "message": "Asset spec fetched successfully",
        "data": data,
    }


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def asset_spec_create(
    payload: AssetSpecCreateRequest,
    current_user: CurrentUser = Depends(require_permission("ASSET_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_asset_spec(db, payload)
    return {
        "success": True,
        "message": "Asset spec created successfully",
        "data": data,
    }


@router.put("/{asset_spec_id}", response_model=ApiResponse)
async def asset_spec_update(
    asset_spec_id: uuid.UUID,
    payload: AssetSpecUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_asset_spec(db, asset_spec_id, payload)
    return {
        "success": True,
        "message": "Asset spec updated successfully",
        "data": data,
    }


@router.delete("/{asset_spec_id}", response_model=ApiResponse)
async def asset_spec_delete(
    asset_spec_id: uuid.UUID,
    modified_by: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("ASSET_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await delete_asset_spec(db, asset_spec_id, modified_by)
    return {
        "success": True,
        "message": "Asset spec deleted successfully",
        "data": data,
    }
