import uuid

from fastapi import APIRouter, Depends, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.release_document_requirement_schema import (
    DocumentRequirementLinkRequest,
    DocumentRequirementStatusUpdateRequest,
    DocumentRequirementWaiverRequest,
)
from app.schemas.release_impact_assessment_schema import (
    ImpactAssessmentAISuggestRequest,
    ImpactAssessmentReopenRequest,
    ImpactResponsesSaveRequest,
)
from app.schemas.release_schema import ApiResponse, ReleaseCreate, ReleaseUpdate
from app.services.release_document_requirement_service import (
    DocumentRequirementServiceError,
    complete_checklist,
    generate_checklist,
    get_checklist,
    get_summary,
    link_requirement,
    request_or_approve_waiver,
    update_requirement_status,
)
from app.services.release_impact_assessment_service import (
    ImpactAssessmentServiceError,
    complete_assessment,
    get_assessment_by_release,
    get_questions,
    initialize_assessment,
    reopen_assessment,
    save_responses,
    suggest_impact_assessment_answers,
)
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
    get_validation_package_by_release,
    update_release,
)

router = APIRouter(tags=["release"])


def _service_error_response(exc: ImpactAssessmentServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(
            {
                "success": False,
                "message": exc.message,
                "data": exc.data,
            }
        ),
    )


def _document_requirement_error_response(exc: DocumentRequirementServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(
            {
                "success": False,
                "message": exc.message,
                "data": exc.data,
            }
        ),
    )


def _actor_name(current_user: CurrentUser) -> str:
    return str(current_user.email or current_user.full_name or current_user.id)


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
        "message": "Release created and validation package initialized successfully",
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


@router.get("/release/{release_id}/validation-package", response_model=ApiResponse)
async def release_validation_package_detail(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_validation_package_by_release(db, release_id)
    return {
        "success": True,
        "message": "Validation package fetched successfully",
        "data": data,
    }


@router.post("/release/{release_id}/document-requirements/generate", response_model=ApiResponse)
async def release_validation_document_requirement_generate(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await generate_checklist(db, release_id, _actor_name(current_user))
    except DocumentRequirementServiceError as exc:
        return _document_requirement_error_response(exc)
    return {
        "success": True,
        "message": "Document checklist generated successfully",
        "data": data,
    }


@router.get("/release/{release_id}/document-requirements", response_model=ApiResponse)
async def release_validation_document_requirement_list(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await get_checklist(db, release_id)
    except DocumentRequirementServiceError as exc:
        return _document_requirement_error_response(exc)
    return {
        "success": True,
        "message": "Document checklist fetched successfully",
        "data": data,
    }


@router.get("/release/{release_id}/document-requirements/summary", response_model=ApiResponse)
async def release_validation_document_requirement_summary(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await get_summary(db, release_id)
    except DocumentRequirementServiceError as exc:
        return _document_requirement_error_response(exc)
    return {
        "success": True,
        "message": "Document checklist summary fetched successfully",
        "data": data,
    }


@router.patch("/release/{release_id}/document-requirements/{requirement_id}/link", response_model=ApiResponse)
async def release_validation_document_requirement_link(
    release_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: DocumentRequirementLinkRequest,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await link_requirement(db, release_id, requirement_id, payload, _actor_name(current_user))
    except DocumentRequirementServiceError as exc:
        return _document_requirement_error_response(exc)
    return {
        "success": True,
        "message": "Document requirement linked successfully",
        "data": data,
    }


@router.patch("/release/{release_id}/document-requirements/{requirement_id}/status", response_model=ApiResponse)
async def release_validation_document_requirement_status_update(
    release_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: DocumentRequirementStatusUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await update_requirement_status(db, release_id, requirement_id, payload, _actor_name(current_user))
    except DocumentRequirementServiceError as exc:
        return _document_requirement_error_response(exc)
    return {
        "success": True,
        "message": "Document requirement status updated successfully",
        "data": data,
    }


@router.post("/release/{release_id}/document-requirements/{requirement_id}/waiver", response_model=ApiResponse)
async def release_validation_document_requirement_waiver(
    release_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: DocumentRequirementWaiverRequest,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await request_or_approve_waiver(db, release_id, requirement_id, payload, _actor_name(current_user))
    except DocumentRequirementServiceError as exc:
        return _document_requirement_error_response(exc)
    return {
        "success": True,
        "message": "Document requirement waiver processed successfully",
        "data": data,
    }


@router.post("/release/{release_id}/document-requirements/complete", response_model=ApiResponse)
async def release_validation_document_requirement_complete(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await complete_checklist(db, release_id, _actor_name(current_user))
    except DocumentRequirementServiceError as exc:
        return _document_requirement_error_response(exc)
    return {
        "success": True,
        "message": "Document checklist completed successfully",
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


@router.get("/release/{release_id}/impact-assessment/questions", response_model=ApiResponse)
async def release_validation_impact_questions(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        await get_assessment_by_release(db, release_id)
        data = get_questions()
    except ImpactAssessmentServiceError as exc:
        return _service_error_response(exc)
    return {
        "success": True,
        "message": "Impact assessment questions fetched successfully",
        "data": data,
    }


@router.get("/release/{release_id}/impact-assessment", response_model=ApiResponse)
async def release_validation_impact_assessment_detail(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await get_assessment_by_release(db, release_id)
    except ImpactAssessmentServiceError as exc:
        return _service_error_response(exc)
    return {
        "success": True,
        "message": (
            "Impact assessment fetched successfully"
            if data is not None
            else "Impact assessment has not been initialized"
        ),
        "data": data,
    }


@router.post("/release/{release_id}/impact-assessment", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def release_validation_impact_assessment_initialize(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await initialize_assessment(db, release_id, _actor_name(current_user))
    except ImpactAssessmentServiceError as exc:
        return _service_error_response(exc)
    return {
        "success": True,
        "message": "Impact assessment initialized successfully",
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


@router.get("/release/{release_id}/impact-assessment/report", response_model=ApiResponse)
async def release_impact_assessment_report_detail(
    release_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_latest_assessment_for_release(db, release_id)
    return {
        "success": True,
        "message": "Impact assessment report fetched successfully",
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


@router.put("/impact-assessments/{assessment_id}/responses", response_model=ApiResponse)
async def release_validation_impact_assessment_response_save(
    assessment_id: uuid.UUID,
    payload: ImpactResponsesSaveRequest,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await save_responses(db, assessment_id, payload.responses, _actor_name(current_user))
    except ImpactAssessmentServiceError as exc:
        return _service_error_response(exc)
    return {
        "success": True,
        "message": "Impact assessment responses saved successfully",
        "data": data,
    }


@router.post("/impact-assessments/{assessment_id}/complete", response_model=ApiResponse)
async def release_validation_impact_assessment_complete(
    assessment_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await complete_assessment(db, assessment_id, _actor_name(current_user))
    except ImpactAssessmentServiceError as exc:
        return _service_error_response(exc)
    return {
        "success": True,
        "message": "Impact assessment completed and validation scope defined successfully",
        "data": data,
    }


@router.post("/impact-assessments/{assessment_id}/reopen", response_model=ApiResponse)
async def release_validation_impact_assessment_reopen(
    assessment_id: uuid.UUID,
    payload: ImpactAssessmentReopenRequest,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await reopen_assessment(db, assessment_id, payload.reason, _actor_name(current_user))
    except ImpactAssessmentServiceError as exc:
        return _service_error_response(exc)
    return {
        "success": True,
        "message": "Impact assessment reopened successfully",
        "data": data,
    }


@router.post("/release/{release_id}/impact-assessment/ai-suggest", response_model=ApiResponse)
async def release_validation_impact_assessment_ai_suggest(
    release_id: uuid.UUID,
    payload: ImpactAssessmentAISuggestRequest | None = None,
    current_user: CurrentUser = Depends(require_permission("ASSET_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await suggest_impact_assessment_answers(
            db,
            release_id,
            payload or ImpactAssessmentAISuggestRequest(),
            _actor_name(current_user),
        )
    except ImpactAssessmentServiceError as exc:
        return _service_error_response(exc)
    return {
        "success": True,
        "message": "AI impact assessment suggestions generated successfully",
        "data": data,
    }
