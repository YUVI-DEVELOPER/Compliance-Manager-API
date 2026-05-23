import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.document_link_schema import (
    ApiResponse,
    DocumentAiAutofillAnalyzeRequest,
    DocumentLinkCreate,
    DocumentLinkUpdate,
)
from app.services.document_vectorization_service import (
    STATUS_QUEUED,
    delete_document_vectors_background,
    get_asset_vectorization_documents,
    get_asset_vectorization_summary,
    get_document_vectorization_chunks,
    get_document_vectorization_detail,
    get_document_vectorization_process,
    get_document_vectorization_report,
    process_document_vectorization_background,
)
from app.services.document_link_service import (
    create_document_for_asset,
    create_document_for_release,
    delete_document_link,
    get_document_link_by_id,
    get_documents_by_asset,
    get_documents_by_release,
    reprocess_document_link_vectorization,
    update_document_link,
)
from app.services.document_ai_autofill_service import analyze_document_link_ai_autofill

router = APIRouter(tags=["document-link"])


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _queue_vectorization_if_needed(background_tasks: BackgroundTasks, data: object) -> None:
    status_value = getattr(data, "vectorization_status", None)
    document_link_id = getattr(data, "document_link_id", None)
    if status_value == STATUS_QUEUED and document_link_id is not None:
        background_tasks.add_task(process_document_vectorization_background, document_link_id)


@router.post("/document-link/ai-autofill", response_model=ApiResponse)
async def document_link_ai_autofill(
    payload: DocumentAiAutofillAnalyzeRequest,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPLOAD")),
) -> dict[str, object]:
    data = await analyze_document_link_ai_autofill(payload)
    return {
        "success": True,
        "message": "Document AI Autofill analysis completed",
        "data": data,
    }


@router.get("/asset/{asset_id}/documents", response_model=ApiResponse)
async def asset_document_list(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_documents_by_asset(db, asset_id)
    return {
        "success": True,
        "message": "Document links fetched successfully",
        "data": data,
    }


@router.get("/asset/{asset_id}/vectorization/summary", response_model=ApiResponse)
async def asset_vectorization_summary(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_vectorization_summary(db, asset_id)
    return {
        "success": True,
        "message": "Asset vectorization summary fetched successfully",
        "data": data,
    }


@router.get("/asset/{asset_id}/vectorization/documents", response_model=ApiResponse)
async def asset_vectorization_documents(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_asset_vectorization_documents(db, asset_id)
    return {
        "success": True,
        "message": "Asset vectorization documents fetched successfully",
        "data": data,
    }


@router.post("/asset/{asset_id}/documents", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def asset_document_create(
    asset_id: uuid.UUID,
    payload: DocumentLinkCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_LINK")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_document_for_asset(
        db,
        asset_id,
        payload,
        base_url=_base_url(request),
        request=request,
        current_user=current_user,
    )
    _queue_vectorization_if_needed(background_tasks, data)
    return {
        "success": True,
        "message": "Document link created successfully",
        "data": data,
    }


@router.get("/release/{release_id}/documents", response_model=ApiResponse)
async def release_document_list(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_documents_by_release(db, release_id)
    return {
        "success": True,
        "message": "Document links fetched successfully",
        "data": data,
    }


@router.post("/release/{release_id}/documents", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def release_document_create(
    release_id: uuid.UUID,
    payload: DocumentLinkCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_LINK")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_document_for_release(
        db,
        release_id,
        payload,
        base_url=_base_url(request),
        request=request,
        current_user=current_user,
    )
    _queue_vectorization_if_needed(background_tasks, data)
    return {
        "success": True,
        "message": "Document link created successfully",
        "data": data,
    }


@router.get("/document-link/{document_link_id}", response_model=ApiResponse)
async def document_link_detail(
    document_link_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_document_link_by_id(db, document_link_id)
    return {
        "success": True,
        "message": "Document link fetched successfully",
        "data": data,
    }


@router.get("/document-link/{document_link_id}/vectorization", response_model=ApiResponse)
async def document_link_vectorization_detail(
    document_link_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_document_vectorization_detail(db, document_link_id)
    return {
        "success": True,
        "message": "Document vectorization detail fetched successfully",
        "data": data,
    }


@router.get("/document-link/{document_link_id}/vectorization/chunks", response_model=ApiResponse)
async def document_link_vectorization_chunks(
    document_link_id: uuid.UUID,
    limit: int = 25,
    offset: int = 0,
    search: str | None = None,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_document_vectorization_chunks(
        db,
        document_link_id,
        limit=limit,
        offset=offset,
        search=search,
    )
    return {
        "success": True,
        "message": "Document vectorization chunks fetched successfully",
        "data": data,
    }


@router.get("/document-link/{document_link_id}/vectorization/report", response_model=ApiResponse)
async def document_link_vectorization_report(
    document_link_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_document_vectorization_report(db, document_link_id)
    return {
        "success": True,
        "message": "Document vectorization report fetched successfully",
        "data": data,
    }


@router.get("/document-link/{document_link_id}/vectorization/process", response_model=ApiResponse)
async def document_link_vectorization_process(
    document_link_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_document_vectorization_process(db, document_link_id)
    return {
        "success": True,
        "message": "Document vectorization process fetched successfully",
        "data": data,
    }


@router.post("/document-link/{document_link_id}/vectorization/refresh", response_model=ApiResponse)
async def document_link_vectorization_refresh(
    document_link_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_document_vectorization_detail(db, document_link_id)
    return {
        "success": True,
        "message": "Document vectorization status refreshed successfully",
        "data": data,
    }


@router.put("/document-link/{document_link_id}", response_model=ApiResponse)
async def document_link_update(
    document_link_id: uuid.UUID,
    payload: DocumentLinkUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_document_link(
        db,
        document_link_id,
        payload,
        base_url=_base_url(request),
        request=request,
        current_user=current_user,
    )
    _queue_vectorization_if_needed(background_tasks, data)
    return {
        "success": True,
        "message": "Document link updated successfully",
        "data": data,
    }


@router.delete("/document-link/{document_link_id}", response_model=ApiResponse)
async def document_link_delete(
    document_link_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_document_link(db, document_link_id, request=request, current_user=current_user)
    background_tasks.add_task(delete_document_vectors_background, document_link_id)
    return {
        "success": True,
        "message": "Document link deleted successfully",
        "data": {"document_link_id": document_link_id},
    }


@router.post("/document-link/{document_link_id}/vectorization/reprocess", response_model=ApiResponse)
async def document_link_vectorization_reprocess(
    document_link_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await reprocess_document_link_vectorization(db, document_link_id, base_url=_base_url(request))
    _queue_vectorization_if_needed(background_tasks, data)
    return {
        "success": True,
        "message": "Document vectorization reprocess requested",
        "data": data,
    }
