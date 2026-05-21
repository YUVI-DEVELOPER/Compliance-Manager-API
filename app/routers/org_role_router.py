import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.org_role_schema import (
    ApiResponse,
    OrgEntityRoleAssignmentUpdateRequest,
    OrgRoleActionCreateRequest,
    OrgRoleActionUpdateRequest,
    OrgRoleCreateRequest,
    OrgRoleUpdateRequest,
)
from app.services.org_role_service import (
    create_org_role,
    create_org_role_action,
    delete_org_role,
    delete_org_role_action,
    delete_org_role_assignment,
    get_org_role_actions,
    get_org_role_by_id,
    get_org_roles,
    update_org_role,
    update_org_role_action,
    update_org_role_assignment,
)

router = APIRouter(tags=["org_roles"])


@router.get("/org-roles", response_model=ApiResponse)
async def org_role_list(
    active_only: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_org_roles(db, active_only=active_only)
    return {
        "success": True,
        "message": "Org roles fetched successfully",
        "data": data,
    }


@router.get("/org-roles/{role_id}", response_model=ApiResponse)
async def org_role_detail(
    role_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_org_role_by_id(db, role_id)
    return {
        "success": True,
        "message": "Org role fetched successfully",
        "data": data,
    }


@router.post("/org-roles", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def org_role_create(
    payload: OrgRoleCreateRequest,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_org_role(db, payload)
    return {
        "success": True,
        "message": "Org role created successfully",
        "data": data,
    }


@router.put("/org-roles/{role_id}", response_model=ApiResponse)
async def org_role_update(
    role_id: uuid.UUID,
    payload: OrgRoleUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_org_role(db, role_id, payload)
    return {
        "success": True,
        "message": "Org role updated successfully",
        "data": data,
    }


@router.delete("/org-roles/{role_id}", response_model=ApiResponse)
async def org_role_delete(
    role_id: uuid.UUID,
    modified_by: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_org_role(db, role_id, modified_by)
    return {
        "success": True,
        "message": "Org role deleted successfully",
        "data": {"id": role_id},
    }


@router.get("/org-roles/{role_id}/actions", response_model=ApiResponse)
async def org_role_action_list(
    role_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_org_role_actions(db, role_id)
    return {
        "success": True,
        "message": "Org role actions fetched successfully",
        "data": data,
    }


@router.post("/org-roles/{role_id}/actions", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def org_role_action_create(
    role_id: uuid.UUID,
    payload: OrgRoleActionCreateRequest,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_org_role_action(db, role_id, payload)
    return {
        "success": True,
        "message": "Org role action created successfully",
        "data": data,
    }


@router.put("/org-role-actions/{action_id}", response_model=ApiResponse)
async def org_role_action_update(
    action_id: uuid.UUID,
    payload: OrgRoleActionUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_org_role_action(db, action_id, payload)
    return {
        "success": True,
        "message": "Org role action updated successfully",
        "data": data,
    }


@router.delete("/org-role-actions/{action_id}", response_model=ApiResponse)
async def org_role_action_delete(
    action_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_org_role_action(db, action_id)
    return {
        "success": True,
        "message": "Org role action deleted successfully",
        "data": {"id": action_id},
    }


@router.put("/org-entity-roles/{assignment_id}", response_model=ApiResponse)
async def org_entity_role_assignment_update(
    assignment_id: uuid.UUID,
    payload: OrgEntityRoleAssignmentUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_org_role_assignment(db, assignment_id, payload)
    return {
        "success": True,
        "message": "Org role assignment updated successfully",
        "data": data,
    }


@router.delete("/org-entity-roles/{assignment_id}", response_model=ApiResponse)
async def org_entity_role_assignment_delete(
    assignment_id: uuid.UUID,
    modified_by: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("ORGANIZATION_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_org_role_assignment(db, assignment_id, modified_by)
    return {
        "success": True,
        "message": "Org role assignment deleted successfully",
        "data": {"id": assignment_id},
    }
