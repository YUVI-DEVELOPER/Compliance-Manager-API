import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.supplier_schema import ApiResponse, SupplierCreate, SupplierUpdate
from app.services.supplier_service import (
    create_supplier,
    delete_supplier,
    get_supplier_by_id,
    get_suppliers,
    search_supplier,
    update_supplier,
)

router = APIRouter(prefix="/supplier", tags=["supplier"])


@router.get("", response_model=ApiResponse)
async def supplier_list(
    current_user: CurrentUser = Depends(require_permission("SUPPLIER_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_suppliers(db)
    return {
        "success": True,
        "message": "Suppliers fetched successfully",
        "data": data,
    }


@router.get("/search", response_model=ApiResponse)
async def supplier_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=100, ge=1, le=100),
    current_user: CurrentUser = Depends(require_permission("SUPPLIER_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await search_supplier(db, q, limit=limit)
    return {
        "success": True,
        "message": "Suppliers fetched successfully",
        "data": data,
    }


@router.get("/{supplier_id}", response_model=ApiResponse)
async def supplier_detail(
    supplier_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("SUPPLIER_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_supplier_by_id(db, supplier_id)
    return {
        "success": True,
        "message": "Supplier fetched successfully",
        "data": data,
    }


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def supplier_create(
    payload: SupplierCreate,
    current_user: CurrentUser = Depends(require_permission("SUPPLIER_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_supplier(db, payload)
    return {
        "success": True,
        "message": "Supplier created successfully",
        "data": data,
    }


@router.put("/{supplier_id}", response_model=ApiResponse)
async def supplier_update(
    supplier_id: uuid.UUID,
    payload: SupplierUpdate,
    current_user: CurrentUser = Depends(require_permission("SUPPLIER_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_supplier(db, supplier_id, payload)
    return {
        "success": True,
        "message": "Supplier updated successfully",
        "data": data,
    }


@router.delete("/{supplier_id}", response_model=ApiResponse)
async def supplier_delete(
    supplier_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("SUPPLIER_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_supplier(db, supplier_id)
    return {
        "success": True,
        "message": "Supplier deleted successfully",
        "data": {"supplier_id": supplier_id},
    }
