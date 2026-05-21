import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.authored_document_schema import (
    ApiResponse,
    AuthoredDocumentAiRegenerateRequest,
    AuthoredDocumentCommentRequest,
    AuthoredDocumentCreateAiDraftRequest,
    AuthoredDocumentCreateFromTemplateRequest,
    AuthoredDocumentPublishRequest,
    AuthoredDocumentUpdate,
    AuthoredDocumentWorkflowActionRequest,
    DocumentTemplateCreate,
    DocumentTemplateUpdate,
)
from app.services.authored_document_service import (
    approve_authored_document,
    comment_on_authored_document,
    create_authored_document_ai_draft,
    create_authored_document_from_template,
    create_document_template,
    delete_authored_document,
    delete_document_template,
    get_authored_document_by_id,
    get_authored_document_history,
    get_authored_documents_by_asset,
    get_authored_documents_by_release,
    get_document_template_by_code,
    get_document_template_by_id,
    get_document_templates,
    regenerate_authored_document_ai_content,
    reject_authored_document,
    request_authored_document_changes,
    submit_authored_document_for_review,
    update_authored_document,
    update_document_template,
)
from app.services.authored_document_pdf_service import build_authored_document_pdf
from app.services.veeva_publish_service import (
    get_authored_document_publish_status,
    publish_authored_document_to_veeva,
    retry_authored_document_publish_to_veeva,
)

router = APIRouter(tags=["authored-document"])


@router.get("/document-templates", response_model=ApiResponse)
async def document_template_list(
    document_type: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_document_templates(db, document_type=document_type, active_only=active_only)
    return {
        "success": True,
        "message": "Document templates fetched successfully",
        "data": data,
    }


@router.get("/document-templates/by-code/{template_code}", response_model=ApiResponse)
async def document_template_detail_by_code(
    template_code: str,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_document_template_by_code(db, template_code)
    return {
        "success": True,
        "message": "Document template fetched successfully",
        "data": data,
    }


@router.get("/document-templates/{template_id}", response_model=ApiResponse)
async def document_template_detail(
    template_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_document_template_by_id(db, template_id)
    return {
        "success": True,
        "message": "Document template fetched successfully",
        "data": data,
    }


@router.post("/document-templates", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def document_template_create(
    payload: DocumentTemplateCreate,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPLOAD")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_document_template(db, payload)
    return {
        "success": True,
        "message": "Document template created successfully",
        "data": data,
    }


@router.put("/document-templates/{template_id}", response_model=ApiResponse)
async def document_template_update(
    template_id: uuid.UUID,
    payload: DocumentTemplateUpdate,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_document_template(db, template_id, payload)
    return {
        "success": True,
        "message": "Document template updated successfully",
        "data": data,
    }


@router.delete("/document-templates/{template_id}", response_model=ApiResponse)
async def document_template_delete(
    template_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_document_template(db, template_id)
    return {
        "success": True,
        "message": "Document template deleted successfully",
        "data": {"template_id": template_id},
    }


@router.get("/asset/{asset_id}/authored-documents", response_model=ApiResponse)
async def authored_document_list_by_asset(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_authored_documents_by_asset(db, asset_id)
    return {
        "success": True,
        "message": "Authored documents fetched successfully",
        "data": data,
    }


@router.get("/release/{release_id}/authored-documents", response_model=ApiResponse)
async def authored_document_list_by_release(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_authored_documents_by_release(db, release_id)
    return {
        "success": True,
        "message": "Authored documents fetched successfully",
        "data": data,
    }


@router.post("/authored-documents/create-from-template", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def authored_document_create_from_template(
    payload: AuthoredDocumentCreateFromTemplateRequest,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPLOAD")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_authored_document_from_template(db, payload)
    return {
        "success": True,
        "message": "Authored document draft created successfully",
        "data": data,
    }


@router.post("/authored-documents/create-ai-draft", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def authored_document_create_ai_draft(
    payload: AuthoredDocumentCreateAiDraftRequest,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPLOAD")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await create_authored_document_ai_draft(db, payload)
    return {
        "success": True,
        "message": "AI-authored document draft created successfully",
        "data": data,
    }


@router.get("/authored-documents/{authored_document_id}", response_model=ApiResponse)
async def authored_document_detail(
    authored_document_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_authored_document_by_id(db, authored_document_id)
    return {
        "success": True,
        "message": "Authored document fetched successfully",
        "data": data,
    }


@router.get("/authored-documents/{authored_document_id}/preview-pdf")
async def authored_document_preview_pdf(
    authored_document_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    pdf = await build_authored_document_pdf(db, authored_document_id)
    return StreamingResponse(
        BytesIO(pdf.content),
        media_type=pdf.media_type,
        headers={
            "Content-Disposition": f'inline; filename="{pdf.file_name}"',
            "Cache-Control": "no-store",
        },
    )


@router.put("/authored-documents/{authored_document_id}", response_model=ApiResponse)
async def authored_document_update(
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentUpdate,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await update_authored_document(db, authored_document_id, payload)
    return {
        "success": True,
        "message": "Authored document updated successfully",
        "data": data,
    }


@router.post("/authored-documents/{authored_document_id}/regenerate-ai-content", response_model=ApiResponse)
async def authored_document_regenerate_ai_content(
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentAiRegenerateRequest,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await regenerate_authored_document_ai_content(db, authored_document_id, payload)
    return {
        "success": True,
        "message": "AI-authored document content generated successfully",
        "data": data,
    }


@router.post("/authored-documents/{authored_document_id}/submit-for-review", response_model=ApiResponse)
async def authored_document_submit_for_review(
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentWorkflowActionRequest,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await submit_authored_document_for_review(db, authored_document_id, payload)
    return {
        "success": True,
        "message": "Authored document submitted for review successfully",
        "data": data,
    }


@router.post("/authored-documents/{authored_document_id}/request-changes", response_model=ApiResponse)
async def authored_document_request_changes(
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentWorkflowActionRequest,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await request_authored_document_changes(db, authored_document_id, payload)
    return {
        "success": True,
        "message": "Changes requested successfully",
        "data": data,
    }


@router.post("/authored-documents/{authored_document_id}/approve", response_model=ApiResponse)
async def authored_document_approve(
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentWorkflowActionRequest,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await approve_authored_document(db, authored_document_id, payload)
    return {
        "success": True,
        "message": "Authored document approved successfully",
        "data": data,
    }


@router.post("/authored-documents/{authored_document_id}/reject", response_model=ApiResponse)
async def authored_document_reject(
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentWorkflowActionRequest,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await reject_authored_document(db, authored_document_id, payload)
    return {
        "success": True,
        "message": "Authored document rejected successfully",
        "data": data,
    }


@router.post("/authored-documents/{authored_document_id}/comment", response_model=ApiResponse)
async def authored_document_comment(
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentCommentRequest,
    current_user: CurrentUser = Depends(require_permission("AUDIT_COMMENT_ADD")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await comment_on_authored_document(db, authored_document_id, payload)
    return {
        "success": True,
        "message": "Comment added successfully",
        "data": data,
    }


@router.get("/authored-documents/{authored_document_id}/history", response_model=ApiResponse)
async def authored_document_history(
    authored_document_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_authored_document_history(db, authored_document_id)
    return {
        "success": True,
        "message": "Authored document history fetched successfully",
        "data": data,
    }


@router.get("/authored-documents/{authored_document_id}/publish-status", response_model=ApiResponse)
async def authored_document_publish_status(
    authored_document_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_authored_document_publish_status(db, authored_document_id)
    return {
        "success": True,
        "message": "Authored document publish status fetched successfully",
        "data": data,
    }


@router.post("/authored-documents/{authored_document_id}/publish-to-veeva", response_model=ApiResponse)
async def authored_document_publish_to_veeva(
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentPublishRequest,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await publish_authored_document_to_veeva(db, authored_document_id, payload)
    return {
        "success": True,
        "message": "Authored document published to Veeva successfully",
        "data": data,
    }


@router.post("/authored-documents/{authored_document_id}/retry-publish", response_model=ApiResponse)
async def authored_document_retry_publish(
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentPublishRequest,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await retry_authored_document_publish_to_veeva(db, authored_document_id, payload)
    return {
        "success": True,
        "message": "Authored document Veeva publish retried successfully",
        "data": data,
    }


@router.delete("/authored-documents/{authored_document_id}", response_model=ApiResponse)
async def authored_document_delete(
    authored_document_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("DOCUMENT_DELETE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await delete_authored_document(db, authored_document_id)
    return {
        "success": True,
        "message": "Authored document deleted successfully",
        "data": {"authored_document_id": authored_document_id},
    }
