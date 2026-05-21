import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.qualification_document_schema import (
    ApiResponse,
    QualificationDocumentCreate,
    QualificationDocumentUpdate,
    QualificationDocumentWorkflowActionRequest,
)
from app.services.qualification_document_service import (
    accept_qualification_document,
    create_qualification_document,
    delete_qualification_document,
    get_qualification_document_by_id,
    get_qualification_document_history,
    get_qualification_documents,
    reject_qualification_document,
    request_qualification_document_clarification,
    submit_qualification_document_for_review,
    update_qualification_document,
)

router = APIRouter(tags=["qualification-document"])


@router.get("/qualification-documents", response_model=ApiResponse)
async def qualification_document_list(
    asset_id: uuid.UUID | None = Query(default=None),
    release_id: uuid.UUID | None = Query(default=None),
    supplier_id: uuid.UUID | None = Query(default=None),
    qualification_type: str | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_qualification_documents(
        db,
        asset_id=asset_id,
        release_id=release_id,
        supplier_id=supplier_id,
        qualification_type=qualification_type,
        status_value=status_value,
    )
    return {
        "success": True,
        "message": "Qualification documents fetched successfully",
        "data": data,
    }


@router.get("/asset/{asset_id}/qualification-documents", response_model=ApiResponse)
async def qualification_document_list_by_asset(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_qualification_documents(db, asset_id=asset_id)
    return {
        "success": True,
        "message": "Qualification documents fetched successfully",
        "data": data,
    }


@router.get("/release/{release_id}/qualification-documents", response_model=ApiResponse)
async def qualification_document_list_by_release(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_qualification_documents(db, release_id=release_id)
    return {
        "success": True,
        "message": "Qualification documents fetched successfully",
        "data": data,
    }


@router.get("/supplier/{supplier_id}/qualification-documents", response_model=ApiResponse)
async def qualification_document_list_by_supplier(
    supplier_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_qualification_documents(db, supplier_id=supplier_id)
    return {
        "success": True,
        "message": "Qualification documents fetched successfully",
        "data": data,
    }


@router.post("/qualification-documents", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def qualification_document_create(
    payload: QualificationDocumentCreate,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPLOAD")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_qualification_document(db, payload)
    return {
        "success": True,
        "message": "Qualification document created successfully",
        "data": data,
    }


@router.get("/qualification-documents/{qualification_document_id}", response_model=ApiResponse)
async def qualification_document_detail(
    qualification_document_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_qualification_document_by_id(db, qualification_document_id)
    return {
        "success": True,
        "message": "Qualification document fetched successfully",
        "data": data,
    }


@router.put("/qualification-documents/{qualification_document_id}", response_model=ApiResponse)
async def qualification_document_update(
    qualification_document_id: uuid.UUID,
    payload: QualificationDocumentUpdate,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_qualification_document(db, qualification_document_id, payload)
    return {
        "success": True,
        "message": "Qualification document updated successfully",
        "data": data,
    }


@router.get("/qualification-documents/{qualification_document_id}/history", response_model=ApiResponse)
async def qualification_document_history(
    qualification_document_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_qualification_document_history(db, qualification_document_id)
    return {
        "success": True,
        "message": "Qualification document history fetched successfully",
        "data": data,
    }


@router.post("/qualification-documents/{qualification_document_id}/submit-for-review", response_model=ApiResponse)
async def qualification_document_submit_for_review(
    qualification_document_id: uuid.UUID,
    payload: QualificationDocumentWorkflowActionRequest,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await submit_qualification_document_for_review(db, qualification_document_id, payload)
    return {
        "success": True,
        "message": "Qualification document submitted for review successfully",
        "data": data,
    }


@router.post("/qualification-documents/{qualification_document_id}/accept", response_model=ApiResponse)
async def qualification_document_accept(
    qualification_document_id: uuid.UUID,
    payload: QualificationDocumentWorkflowActionRequest,
    current_user: CurrentUser = Depends(require_permission("AUDIT_FINDING_REVIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await accept_qualification_document(db, qualification_document_id, payload)
    return {
        "success": True,
        "message": "Qualification document accepted successfully",
        "data": data,
    }


@router.post("/qualification-documents/{qualification_document_id}/reject", response_model=ApiResponse)
async def qualification_document_reject(
    qualification_document_id: uuid.UUID,
    payload: QualificationDocumentWorkflowActionRequest,
    current_user: CurrentUser = Depends(require_permission("AUDIT_FINDING_REVIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await reject_qualification_document(db, qualification_document_id, payload)
    return {
        "success": True,
        "message": "Qualification document rejected successfully",
        "data": data,
    }


@router.post("/qualification-documents/{qualification_document_id}/request-clarification", response_model=ApiResponse)
async def qualification_document_request_clarification(
    qualification_document_id: uuid.UUID,
    payload: QualificationDocumentWorkflowActionRequest,
    current_user: CurrentUser = Depends(require_permission("AUDIT_FINDING_REVIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await request_qualification_document_clarification(db, qualification_document_id, payload)
    return {
        "success": True,
        "message": "Qualification document clarification requested successfully",
        "data": data,
    }


@router.delete("/qualification-documents/{qualification_document_id}", response_model=ApiResponse)
async def qualification_document_delete(
    qualification_document_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_qualification_document(db, qualification_document_id)
    return {
        "success": True,
        "message": "Qualification document deleted successfully",
        "data": {"qualification_document_id": qualification_document_id},
    }
