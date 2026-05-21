import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.release_schema import ApiResponse, ReleaseCreate, ReleaseUpdate
from app.services.release_assessment_service import (
    download_assessment_for_release,
    generate_impact_assessment_for_release,
    get_latest_assessment_for_release,
)
from app.services.release_service import (
    create_release,
    delete_release,
    get_release_by_id,
    get_releases_by_asset,
    update_release,
)

router = APIRouter(tags=["release"])


@router.get("/asset/{asset_id}/releases", response_model=ApiResponse)
async def release_list(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_releases_by_asset(db, asset_id)
    return {
        "success": True,
        "message": "Releases fetched successfully",
        "data": data,
    }


@router.post("/asset/{asset_id}/releases", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def release_create(
    asset_id: uuid.UUID,
    payload: ReleaseCreate,
    current_user: CurrentUser = Depends(require_permission("ASSET_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_release(db, asset_id, payload)
    return {
        "success": True,
        "message": "Release created successfully",
        "data": data,
    }


@router.get("/release/{release_id}", response_model=ApiResponse)
async def release_detail(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_release_by_id(db, release_id)
    return {
        "success": True,
        "message": "Release fetched successfully",
        "data": data,
    }


@router.put("/release/{release_id}", response_model=ApiResponse)
async def release_update(
    release_id: uuid.UUID,
    payload: ReleaseUpdate,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_release(db, release_id, payload)
    return {
        "success": True,
        "message": "Release updated successfully",
        "data": data,
    }


@router.delete("/release/{release_id}", response_model=ApiResponse)
async def release_delete(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_release(db, release_id)
    return {
        "success": True,
        "message": "Release deleted successfully",
        "data": {"release_id": release_id},
    }


@router.get("/release/{release_id}/impact-assessment", response_model=ApiResponse)
async def release_impact_assessment_detail(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_latest_assessment_for_release(db, release_id)
    return {
        "success": True,
        "message": "Impact assessment fetched successfully",
        "data": data,
    }


@router.post("/release/{release_id}/impact-assessment/regenerate", response_model=ApiResponse)
async def release_impact_assessment_regenerate(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await generate_impact_assessment_for_release(db, release_id)
    return {
        "success": True,
        "message": "Impact assessment regenerated successfully",
        "data": data,
    }


@router.get("/release/{release_id}/impact-assessment/download")
async def release_impact_assessment_download(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("REPORT_EXPORT")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    download = await download_assessment_for_release(db, release_id)
    return Response(
        content=download.report_content,
        media_type=download.media_type,
        headers={"Content-Disposition": f'attachment; filename="{download.file_name}"'},
    )
