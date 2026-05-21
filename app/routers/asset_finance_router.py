import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.asset_finance_schema import ApiResponse, AssetFinanceCreate, AssetFinanceUpdate
from app.services.asset_finance_service import (
    create_asset_finance,
    delete_asset_finance,
    get_asset_finance_by_asset,
    update_asset_finance,
)

router = APIRouter(tags=["asset-finance"])


@router.get("/asset/{asset_id}/finance", response_model=ApiResponse)
async def asset_finance_detail(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_finance_by_asset(db, asset_id)
    return {
        "success": True,
        "message": "Asset finance fetched successfully" if data is not None else "Asset finance not configured for this asset",
        "data": data,
    }


@router.post("/asset/{asset_id}/finance", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def asset_finance_create(
    asset_id: uuid.UUID,
    payload: AssetFinanceCreate,
    current_user: CurrentUser = Depends(require_permission("ASSET_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_asset_finance(db, asset_id, payload)
    return {
        "success": True,
        "message": "Asset finance created successfully",
        "data": data,
    }


@router.put("/asset/{asset_id}/finance", response_model=ApiResponse)
async def asset_finance_update(
    asset_id: uuid.UUID,
    payload: AssetFinanceUpdate,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_asset_finance(db, asset_id, payload)
    return {
        "success": True,
        "message": "Asset finance updated successfully",
        "data": data,
    }


@router.delete("/asset/{asset_id}/finance", response_model=ApiResponse)
async def asset_finance_delete(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_asset_finance(db, asset_id)
    return {
        "success": True,
        "message": "Asset finance deleted successfully",
        "data": {"asset_id": asset_id},
    }
