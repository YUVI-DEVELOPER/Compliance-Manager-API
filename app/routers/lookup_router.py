from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.lookup_schema import (
    ApiResponse,
    LookupMasterCreateRequest,
    LookupMasterUpdateRequest,
    LookupValueCreateRequest,
    LookupValueUpdateRequest,
)
from app.services.lookup_service import (
    create_lookup_master,
    create_lookup_value,
    delete_lookup_master,
    delete_lookup_value,
    get_active_lookup_values,
    get_lookup_master_by_id,
    get_lookup_masters,
    get_lookup_value_by_id,
    update_lookup_master,
    update_lookup_value,
)

router = APIRouter(prefix="/lookup", tags=["lookup"])


@router.get("/master", response_model=ApiResponse)
async def lookup_master_list(
    active_only: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("LOOKUP_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_lookup_masters(db, active_only=active_only)
    return {
        "success": True,
        "message": "Lookup masters fetched successfully",
        "data": data,
    }


@router.get("/master/{master_id}", response_model=ApiResponse)
async def lookup_master_detail(
    master_id: int,
    current_user: CurrentUser = Depends(require_permission("LOOKUP_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_lookup_master_by_id(db, master_id)
    return {
        "success": True,
        "message": "Lookup master fetched successfully",
        "data": data,
    }


@router.post("/master", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def lookup_master_create(
    payload: LookupMasterCreateRequest,
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_lookup_master(db, payload)
    return {
        "success": True,
        "message": "Lookup master created successfully",
        "data": data,
    }


@router.put("/master/{master_id}", response_model=ApiResponse)
async def lookup_master_update(
    master_id: int,
    payload: LookupMasterUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_lookup_master(db, master_id, payload)
    return {
        "success": True,
        "message": "Lookup master updated successfully",
        "data": data,
    }


@router.delete("/master/{master_id}", response_model=ApiResponse)
async def lookup_master_delete(
    master_id: int,
    modified_by: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_lookup_master(db, master_id, modified_by)
    return {
        "success": True,
        "message": "Lookup master deleted successfully",
        "data": {"id": master_id},
    }


@router.get("/values/{lookup_key}", response_model=ApiResponse)
async def lookup_values(
    lookup_key: str,
    current_user: CurrentUser = Depends(require_permission("LOOKUP_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_active_lookup_values(db, lookup_key)
    return {
        "success": True,
        "message": "Lookup values fetched successfully",
        "data": data,
    }


@router.get("/value/{value_id}", response_model=ApiResponse)
async def lookup_value_detail(
    value_id: int,
    current_user: CurrentUser = Depends(require_permission("LOOKUP_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_lookup_value_by_id(db, value_id)
    return {
        "success": True,
        "message": "Lookup value fetched successfully",
        "data": data,
    }


@router.post("/value", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def lookup_value_create(
    payload: LookupValueCreateRequest,
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_lookup_value(db, payload)
    return {
        "success": True,
        "message": "Lookup value created successfully",
        "data": data,
    }


@router.put("/value/{value_id}", response_model=ApiResponse)
async def lookup_value_update(
    value_id: int,
    payload: LookupValueUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_lookup_value(db, value_id, payload)
    return {
        "success": True,
        "message": "Lookup value updated successfully",
        "data": data,
    }


@router.delete("/value/{value_id}", response_model=ApiResponse)
async def lookup_value_delete(
    value_id: int,
    modified_by: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_lookup_value(db, value_id, modified_by)
    return {
        "success": True,
        "message": "Lookup value deleted successfully",
        "data": {"id": value_id},
    }
