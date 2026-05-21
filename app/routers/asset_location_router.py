import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.asset_location_schema import ApiResponse, AssetLocationCreate, AssetLocationUpdate
from app.services.asset_location_service import (
    create_asset_location,
    delete_asset_location,
    get_asset_location_by_asset,
    update_asset_location,
)

router = APIRouter(tags=["asset-location"])


@router.get("/asset/{asset_id}/location", response_model=ApiResponse)
async def asset_location_detail(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_location_by_asset(db, asset_id)
    return {
        "success": True,
        "message": "Asset location fetched successfully" if data is not None else "Asset location not configured for this asset",
        "data": data,
    }


@router.post("/asset/{asset_id}/location", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def asset_location_create(
    asset_id: uuid.UUID,
    payload: AssetLocationCreate,
    current_user: CurrentUser = Depends(require_permission("ASSET_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_asset_location(db, asset_id, payload)
    return {
        "success": True,
        "message": "Asset location created successfully",
        "data": data,
    }


@router.put("/asset/{asset_id}/location", response_model=ApiResponse)
async def asset_location_update(
    asset_id: uuid.UUID,
    payload: AssetLocationUpdate,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_asset_location(db, asset_id, payload)
    return {
        "success": True,
        "message": "Asset location updated successfully",
        "data": data,
    }


@router.delete("/asset/{asset_id}/location", response_model=ApiResponse)
async def asset_location_delete(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_asset_location(db, asset_id)
    return {
        "success": True,
        "message": "Asset location deleted successfully",
        "data": {"asset_id": asset_id},
    }
