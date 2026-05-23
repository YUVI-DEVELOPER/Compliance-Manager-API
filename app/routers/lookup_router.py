from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit_actions
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
from app.services.audit_log_service import create_audit_log

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
    request: Request,
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_lookup_master(db, payload)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Lookup/Master Data",
        entity_name="Lookup Master",
        table_name="lookup_master",
        record_id=data.id,
        action=audit_actions.LOOKUP_CREATED,
        event_description="Lookup master created",
        new_data=data.model_dump(mode="json"),
    )
    await db.commit()
    return {
        "success": True,
        "message": "Lookup master created successfully",
        "data": data,
    }


@router.put("/master/{master_id}", response_model=ApiResponse)
async def lookup_master_update(
    master_id: int,
    payload: LookupMasterUpdateRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    old_data = (await get_lookup_master_by_id(db, master_id)).model_dump(mode="json")
    data = await update_lookup_master(db, master_id, payload)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Lookup/Master Data",
        entity_name="Lookup Master",
        table_name="lookup_master",
        record_id=master_id,
        action=audit_actions.LOOKUP_UPDATED,
        event_description="Lookup master updated",
        old_data=old_data,
        new_data=data.model_dump(mode="json"),
    )
    await db.commit()
    return {
        "success": True,
        "message": "Lookup master updated successfully",
        "data": data,
    }


@router.delete("/master/{master_id}", response_model=ApiResponse)
async def lookup_master_delete(
    master_id: int,
    request: Request,
    modified_by: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    old_data = (await get_lookup_master_by_id(db, master_id)).model_dump(mode="json")
    await delete_lookup_master(db, master_id, modified_by)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Lookup/Master Data",
        entity_name="Lookup Master",
        table_name="lookup_master",
        record_id=master_id,
        action=audit_actions.LOOKUP_DEACTIVATED,
        event_description="Lookup master deactivated",
        old_data=old_data,
        new_data={"is_active": False, "id": master_id},
    )
    await db.commit()
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
    request: Request,
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_lookup_value(db, payload)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Lookup/Master Data",
        entity_name="Lookup Value",
        table_name="lookup_value",
        record_id=data.id,
        action=audit_actions.LOOKUP_CREATED,
        event_description="Lookup value created",
        new_data=data.model_dump(mode="json"),
    )
    await db.commit()
    return {
        "success": True,
        "message": "Lookup value created successfully",
        "data": data,
    }


@router.put("/value/{value_id}", response_model=ApiResponse)
async def lookup_value_update(
    value_id: int,
    payload: LookupValueUpdateRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    old_data = (await get_lookup_value_by_id(db, value_id)).model_dump(mode="json")
    data = await update_lookup_value(db, value_id, payload)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Lookup/Master Data",
        entity_name="Lookup Value",
        table_name="lookup_value",
        record_id=value_id,
        action=audit_actions.LOOKUP_UPDATED,
        event_description="Lookup value updated",
        old_data=old_data,
        new_data=data.model_dump(mode="json"),
    )
    await db.commit()
    return {
        "success": True,
        "message": "Lookup value updated successfully",
        "data": data,
    }


@router.delete("/value/{value_id}", response_model=ApiResponse)
async def lookup_value_delete(
    value_id: int,
    request: Request,
    modified_by: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("LOOKUP_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    old_data = (await get_lookup_value_by_id(db, value_id)).model_dump(mode="json")
    await delete_lookup_value(db, value_id, modified_by)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Lookup/Master Data",
        entity_name="Lookup Value",
        table_name="lookup_value",
        record_id=value_id,
        action=audit_actions.LOOKUP_DEACTIVATED,
        event_description="Lookup value deactivated",
        old_data=old_data,
        new_data={"is_active": False, "id": value_id},
    )
    await db.commit()
    return {
        "success": True,
        "message": "Lookup value deleted successfully",
        "data": {"id": value_id},
    }
