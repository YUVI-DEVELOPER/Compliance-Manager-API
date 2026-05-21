import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.asset_schema import ApiResponse, AssetCreate, AssetUpdate
from app.services.asset_report_service import get_asset_inventory_report
from app.services.asset_service import (
    create_asset,
    delete_asset,
    get_asset_by_id,
    get_assets,
    search_asset,
    update_asset,
)

router = APIRouter(prefix="/asset", tags=["asset"])


@router.get("", response_model=ApiResponse)
async def asset_list(
    org_node_id: uuid.UUID | None = Query(default=None, description="Filter by organization node ID"),
    supplier_id: uuid.UUID | None = Query(default=None, description="Filter by supplier ID"),
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_assets(db, org_node_id=org_node_id, supplier_id=supplier_id)
    return {
        "success": True,
        "message": "Assets fetched unsuccessfully",
        "data": data,
    }


@router.get("/search", response_model=ApiResponse)
async def asset_search(
    q: str = Query(..., min_length=1),
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await search_asset(db, q)
    return {
        "success": True,
        "message": "Assets fetched successfully",
        "data": data,
    }


@router.get("/report/inventory", response_model=ApiResponse)
async def asset_inventory_report(
    scope: Literal["enterprise", "unit"] = Query(default="enterprise"),
    org_id: uuid.UUID | None = Query(default=None, description="Organization scope identifier for unit reporting"),
    q: str | None = Query(default=None, description="Search across identifiers, names, owners, organization, or supplier"),
    lifecycle_state: str | None = Query(default=None, description="Lifecycle or asset status filter"),
    asset_class: str | None = Query(default=None, description="Asset class filter"),
    asset_category: str | None = Query(default=None, description="Asset category filter"),
    current_user: CurrentUser = Depends(require_permission("REPORT_EXPORT")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_inventory_report(
        db,
        scope=scope,
        org_id=org_id,
        q=q,
        lifecycle_state=lifecycle_state,
        asset_class=asset_class,
        asset_category=asset_category,
    )
    return {
        "success": True,
        "message": "Asset inventory report fetched successfully",
        "data": data,
    }


@router.get("/{asset_id}", response_model=ApiResponse)
async def asset_detail(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_by_id(db, asset_id)
    return {
        "success": True,
        "message": "Asset fetched successfully",
        "data": data,
    }


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def asset_create(
    payload: AssetCreate,
    current_user: CurrentUser = Depends(require_permission("ASSET_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_asset(db, payload)
    return {
        "success": True,
        "message": "Asset created successfully",
        "data": data,
    }


@router.put("/{asset_id}", response_model=ApiResponse)
async def asset_update(
    asset_id: uuid.UUID,
    payload: AssetUpdate,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_asset(db, asset_id, payload)
    return {
        "success": True,
        "message": "Asset updated successfully",
        "data": data,
    }


@router.delete("/{asset_id}", response_model=ApiResponse)
async def asset_delete(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_asset(db, asset_id)
    return {
        "success": True,
        "message": "Asset deleted successfully",
        "data": {"asset_id": asset_id},
    }
