from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.routers.audit_review_router import router as audit_review_router
from app.routers.auth_router import router as auth_router
from app.routers.authored_document_router import router as authored_document_router
from app.routers.asset_group_router import router as asset_group_router
from app.routers.asset_finance_router import router as asset_finance_router
from app.routers.asset_location_router import router as asset_location_router
from app.routers.asset_router import router as asset_router
from app.routers.asset_spec_router import router as asset_spec_router
from app.routers.document_link_router import router as document_link_router
from app.routers.document_viewer_router import router as document_viewer_router
from app.routers.file_upload_router import router as file_upload_router
from app.routers.lookup_router import router as lookup_router
from app.routers.org_role_router import router as org_role_router
from app.routers.org_router import router as org_router
from app.routers.permission_group_router import router as permission_group_router
from app.routers.permission_router import router as permission_router
from app.routers.qualification_document_router import router as qualification_document_router
from app.routers.release_router import router as release_router
from app.routers.role_router import router as role_router
from app.routers.supplier_router import router as supplier_router
from app.routers.supplier_evaluation_router import router as supplier_evaluation_router
from app.schemas.lookup_schema import ApiResponse
from app.schemas.auth_schema import CurrentUser
from app.services.asset_spec_service import get_asset_specs
from app.services.lookup_service import get_active_lookup_values
from app.routers.app_user_router import router as app_user_router

api_router = APIRouter()


@api_router.get("/asset-sub-categories/{asset_sub_category_id}/specs", response_model=ApiResponse)
async def asset_specs_by_sub_category(
    asset_sub_category_id: int,
    include_inactive: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    data = await get_asset_specs(db, asset_sub_category_id=asset_sub_category_id, include_inactive=include_inactive)
    return ApiResponse(
        success=True,
        message="Asset specs fetched successfully",
        data=data,
    )


@api_router.get("/lookup-value", response_model=ApiResponse)
async def lookup_value_by_master_code(
    master_code: str = Query(..., description="Lookup master code/key"),
    current_user: CurrentUser = Depends(require_permission("LOOKUP_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    lookup_values = await get_active_lookup_values(db, master_code)
    data = [
        {
            "code": lv.code,
            "value": lv.display_name,
        }
        for lv in lookup_values
    ]
    return ApiResponse(
        success=True,
        message="Lookup values fetched successfully",
        data=data,
    )


api_router.include_router(auth_router)
api_router.include_router(org_router)
api_router.include_router(org_role_router)
api_router.include_router(supplier_router)
api_router.include_router(supplier_evaluation_router)
api_router.include_router(asset_group_router)
api_router.include_router(asset_finance_router)
api_router.include_router(asset_location_router)
api_router.include_router(asset_router)
api_router.include_router(audit_review_router)
api_router.include_router(asset_spec_router)
api_router.include_router(authored_document_router)
api_router.include_router(release_router)
api_router.include_router(document_link_router)
api_router.include_router(document_viewer_router)
api_router.include_router(file_upload_router)
api_router.include_router(qualification_document_router)
api_router.include_router(lookup_router)
api_router.include_router(app_user_router)
api_router.include_router(role_router)
api_router.include_router(permission_router)
api_router.include_router(permission_group_router)
