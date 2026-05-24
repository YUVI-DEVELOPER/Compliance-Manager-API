import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit_actions
from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.org_role_schema import OrgEntityRoleAssignmentCreateRequest
from app.schemas.org_schema import ApiResponse, OrgCreateRequest, OrgUpdateRequest
from app.services.org_role_service import create_org_role_assignment, get_org_role_assignments
from app.services.org_service import (
    create_org,
    delete_org,
    get_org_by_id,
    get_org_tree,
    search_org,
    update_org,
)
from app.services.audit_log_service import create_audit_log

router = APIRouter(prefix="/org", tags=["org"])


@router.get("/health")
async def org_health_check() -> dict[str, object]:
    return {
        "success": True,
        "message": "Org module ready",
        "data": None,
    }


@router.get("/tree", response_model=ApiResponse)
async def org_tree(
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_org_tree(db)
    return {
        "success": True,
        "message": "Org tree fetched successfully",
        "data": data,
    }


@router.get("/search", response_model=ApiResponse)
async def org_search(
    q: str = Query(..., min_length=1),
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await search_org(db, q)
    return {
        "success": True,
        "message": "Org search fetched successfully",
        "data": data,
    }


@router.get("/{org_id}", response_model=ApiResponse)
async def org_detail(
    org_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_org_by_id(db, org_id)
    return {
        "success": True,
        "message": "Org detail fetched successfully",
        "data": data,
    }


@router.get("/{org_id}/roles", response_model=ApiResponse)
async def org_role_assignments(
    org_id: uuid.UUID,
    active_only: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_org_role_assignments(db, org_id, active_only=active_only)
    return {
        "success": True,
        "message": "Org role assignments fetched successfully",
        "data": data,
    }


@router.post("/{org_id}/roles", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def org_role_assignment_create(
    org_id: uuid.UUID,
    payload: OrgEntityRoleAssignmentCreateRequest,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_org_role_assignment(db, org_id, payload)
    return {
        "success": True,
        "message": "Org role assignment created successfully",
        "data": data,
    }


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def org_create(
    payload: OrgCreateRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_org(db, payload)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Organization",
        entity_name="Organization",
        table_name="org_structure",
        record_id=data.id,
        action=audit_actions.ORGANIZATION_CREATED,
        event_description="Organization created",
        new_data=data.model_dump(mode="json"),
    )
    await db.commit()
    return {
        "success": True,
        "message": "Org node created successfully",
        "data": data,
    }


@router.put("/{org_id}", response_model=ApiResponse)
async def org_update(
    org_id: uuid.UUID,
    payload: OrgUpdateRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    old_data = (await get_org_by_id(db, org_id)).model_dump(mode="json")
    data = await update_org(db, org_id, payload)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Organization",
        entity_name="Organization",
        table_name="org_structure",
        record_id=org_id,
        action=audit_actions.ORGANIZATION_UPDATED,
        event_description="Organization updated",
        old_data=old_data,
        new_data=data.model_dump(mode="json"),
    )
    await db.commit()
    return {
        "success": True,
        "message": "Org node updated successfully",
        "data": data,
    }


@router.delete("/{org_id}", response_model=ApiResponse)
async def org_delete(
    org_id: uuid.UUID,
    request: Request,
    deleted_by: uuid.UUID | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    old_data = (await get_org_by_id(db, org_id)).model_dump(mode="json")
    await delete_org(db, org_id, deleted_by)
    await create_audit_log(
        db,
        request=request,
        current_user=current_user,
        module_name="Organization",
        entity_name="Organization",
        table_name="org_structure",
        record_id=org_id,
        action=audit_actions.ORGANIZATION_DEACTIVATED,
        event_description="Organization deleted/deactivated",
        old_data=old_data,
        new_data={"deleted": True, "id": str(org_id)},
    )
    await db.commit()
    return {
        "success": True,
        "message": "Org node deleted successfully",
        "data": {"id": org_id},
    }
