import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependencies import require_any_permission, require_permission
from app.core.database import get_db
from app.schemas.auth_schema import CurrentUser
from app.schemas.audit_review_schema import (
    ApiResponse,
    AuditReviewAiSummaryGenerateRequest,
    AuditReviewAnalyzeRequest,
    AuditReviewJobCreateRequest,
    DismissNotificationRequest,
    PrepareNotificationsRequest,
    AuditReviewReportReviewDecisionRequest,
    AuditReviewReportSubmitReviewRequest,
    AuditReviewSchedulePatchRequest,
    AuditReviewScheduleUpsertRequest,
    SendNotificationRequest,
)
from app.services.audit_review_ai_summary_service import (
    clear_audit_review_ai_summary,
    generate_audit_review_ai_summary,
    get_audit_review_ai_summary,
)
from app.services.audit_review_notification_service import (
    dismiss_audit_review_notification,
    list_asset_audit_review_notifications,
    list_audit_review_report_notifications,
    prepare_audit_review_notifications,
    send_audit_review_notification,
    send_audit_review_report_notifications,
)
from app.services.audit_review_report_service import (
    approve_audit_review_report,
    generate_audit_review_report,
    get_audit_review_report,
    list_audit_review_reports_for_asset,
    reject_audit_review_report,
    request_changes_audit_review_report,
    submit_audit_review_report_for_review,
)
from app.services.audit_review_pdf_service import (
    build_audit_review_report_html_preview,
    build_audit_review_report_pdf,
)
from app.services.audit_review_service import (
    AuditReviewServiceError,
    analyze_audit_review_job,
    create_audit_review_job,
    extract_audit_review_job,
    get_audit_review_job,
    get_audit_review_job_findings,
    get_audit_review_metadata,
    get_audit_review_job_records,
    get_audit_review_job_scores,
    list_audit_review_jobs_for_asset,
)
from app.services.audit_review_scheduler_service import (
    list_audit_review_schedule_runs,
    list_audit_review_schedules_for_asset,
    run_audit_review_schedule_now,
    run_due_audit_review_schedules,
    update_audit_review_schedule,
    upsert_audit_review_schedule,
)
from app.services.asset_service import get_assets


router = APIRouter(tags=["audit-review"])


def _service_error_response(exc: AuditReviewServiceError) -> JSONResponse:
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


def _current_user_actor_name(current_user: CurrentUser) -> str:
    return current_user.full_name.strip() or str(current_user.email).strip()


@router.get("/api/audit-reviews/metadata", response_model=ApiResponse)
async def audit_review_metadata(
    current_user: CurrentUser = Depends(require_permission("AUDIT_REVIEW_VIEW")),
) -> dict[str, object]:
    data = await get_audit_review_metadata()
    return {
        "success": True,
        "message": "Audit review metadata fetched successfully.",
        "data": data,
    }


@router.get("/api/audit-reviews/assets", response_model=ApiResponse)
async def audit_review_assets(
    current_user: CurrentUser = Depends(require_any_permission(["AUDIT_REVIEW_VIEW", "SCHEDULE_VIEW"])),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    data = await get_assets(db)
    return {
        "success": True,
        "message": "Audit review asset candidates fetched successfully.",
        "data": data,
    }


@router.post("/asset/{asset_id}/audit-review-jobs", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def audit_review_job_create(
    asset_id: uuid.UUID,
    payload: AuditReviewJobCreateRequest,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REVIEW_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await create_audit_review_job(db, asset_id, payload, current_user=current_user)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review job created successfully.",
        "data": data,
    }


@router.get("/asset/{asset_id}/audit-review-jobs", response_model=ApiResponse)
async def audit_review_job_list(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REVIEW_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await list_audit_review_jobs_for_asset(db, asset_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review jobs fetched successfully.",
        "data": data,
    }


@router.get("/asset/{asset_id}/audit-review-reports", response_model=ApiResponse)
async def audit_review_report_list_for_asset(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REPORT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await list_audit_review_reports_for_asset(db, asset_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review reports fetched successfully.",
        "data": data,
    }


@router.get("/asset/{asset_id}/audit-review-notifications", response_model=ApiResponse)
async def asset_audit_review_notifications(
    asset_id: uuid.UUID,
    notification_status: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: CurrentUser = Depends(require_permission("NOTIFICATION_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await list_asset_audit_review_notifications(
            db,
            asset_id,
            status=notification_status,
            priority=priority,
            limit=limit,
        )
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Asset audit review notifications fetched successfully.",
        "data": data,
    }


@router.post("/asset/{asset_id}/audit-review-schedules", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def audit_review_schedule_create_or_update(
    asset_id: uuid.UUID,
    payload: AuditReviewScheduleUpsertRequest,
    current_user: CurrentUser = Depends(require_permission("SCHEDULE_CREATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await upsert_audit_review_schedule(db, asset_id, payload, current_user=current_user)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review schedule saved successfully.",
        "data": data,
    }


@router.get("/asset/{asset_id}/audit-review-schedules", response_model=ApiResponse)
async def audit_review_schedule_list_for_asset(
    asset_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("SCHEDULE_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await list_audit_review_schedules_for_asset(db, asset_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review schedules fetched successfully.",
        "data": data,
    }


@router.patch("/audit-review-schedules/{schedule_id}", response_model=ApiResponse)
async def audit_review_schedule_update(
    schedule_id: uuid.UUID,
    payload: AuditReviewSchedulePatchRequest,
    current_user: CurrentUser = Depends(require_permission("SCHEDULE_UPDATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await update_audit_review_schedule(db, schedule_id, payload, current_user=current_user)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review schedule updated successfully.",
        "data": data,
    }


@router.post("/audit-review-schedules/{schedule_id}/run-now", response_model=ApiResponse)
async def audit_review_schedule_run_now(
    schedule_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("SCHEDULE_RUN")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await run_audit_review_schedule_now(db, schedule_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review schedule run processed.",
        "data": data,
    }


@router.post("/audit-review-scheduler/run-due", response_model=ApiResponse)
async def audit_review_scheduler_run_due(
    current_user: CurrentUser = Depends(require_permission("SCHEDULE_RUN")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await run_due_audit_review_schedules(db)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Due audit review schedules processed.",
        "data": data,
    }


@router.get("/audit-review-schedules/{schedule_id}/runs", response_model=ApiResponse)
async def audit_review_schedule_runs(
    schedule_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("SCHEDULE_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await list_audit_review_schedule_runs(db, schedule_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review schedule runs fetched successfully.",
        "data": data,
    }


@router.get("/audit-review-jobs/{job_id}", response_model=ApiResponse)
async def audit_review_job_detail(
    job_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REVIEW_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await get_audit_review_job(db, job_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review job fetched successfully.",
        "data": data,
    }


@router.post("/audit-review-jobs/{job_id}/extract", response_model=ApiResponse)
async def audit_review_job_extract(
    job_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REVIEW_EXTRACT")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await extract_audit_review_job(db, job_id, current_user=current_user)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit trail records extracted successfully.",
        "data": data,
    }


@router.post("/audit-review-jobs/{job_id}/analyze", response_model=ApiResponse)
async def audit_review_job_analyze(
    job_id: uuid.UUID,
    payload: AuditReviewAnalyzeRequest | None = None,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REVIEW_ANALYZE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await analyze_audit_review_job(db, job_id, payload or AuditReviewAnalyzeRequest(), current_user=current_user)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review analysis completed successfully.",
        "data": data,
    }


@router.post("/audit-review-jobs/{job_id}/generate-report", response_model=ApiResponse)
async def audit_review_job_generate_report(
    job_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REPORT_GENERATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await generate_audit_review_report(db, job_id, current_user=current_user)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Draft audit review report generated successfully.",
        "data": data,
    }


@router.get("/audit-review-jobs/{job_id}/records", response_model=ApiResponse)
async def audit_review_job_records(
    job_id: uuid.UUID,
    include_raw: bool = Query(default=False),
    audit_trail_type: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_permission("AUDIT_RECORD_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await get_audit_review_job_records(db, job_id, include_raw=include_raw, audit_trail_type=audit_trail_type)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit trail records fetched successfully.",
        "data": data,
    }


@router.get("/audit-review-jobs/{job_id}/findings", response_model=ApiResponse)
async def audit_review_job_findings(
    job_id: uuid.UUID,
    severity: str | None = Query(default=None),
    check_code: str | None = Query(default=None),
    audit_trail_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: CurrentUser = Depends(require_permission("AUDIT_FINDING_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await get_audit_review_job_findings(
            db,
            job_id,
            severity=severity,
            check_code=check_code,
            audit_trail_type=audit_trail_type,
            limit=limit,
        )
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review findings fetched successfully.",
        "data": data,
    }


@router.get("/audit-review-jobs/{job_id}/scores", response_model=ApiResponse)
async def audit_review_job_scores(
    job_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REVIEW_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await get_audit_review_job_scores(db, job_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review scores fetched successfully.",
        "data": data,
    }


@router.get("/audit-review-reports/{report_id}", response_model=ApiResponse)
async def audit_review_report_detail(
    report_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REPORT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await get_audit_review_report(db, report_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review report fetched successfully.",
        "data": data,
    }


@router.post("/audit-review-reports/{report_id}/generate-ai-summary", response_model=ApiResponse)
async def audit_review_report_generate_ai_summary(
    report_id: uuid.UUID,
    payload: AuditReviewAiSummaryGenerateRequest,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REPORT_GENERATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await generate_audit_review_ai_summary(db, report_id, payload, current_user=current_user)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review AI summary generated successfully.",
        "data": data,
    }


@router.get("/audit-review-reports/{report_id}/ai-summary", response_model=ApiResponse)
async def audit_review_report_ai_summary(
    report_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REPORT_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await get_audit_review_ai_summary(db, report_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review AI summary fetched successfully.",
        "data": data,
    }


@router.delete("/audit-review-reports/{report_id}/ai-summary", response_model=ApiResponse)
async def audit_review_report_clear_ai_summary(
    report_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REPORT_GENERATE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await clear_audit_review_ai_summary(db, report_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review AI summary cleared successfully.",
        "data": data,
    }


@router.post("/audit-review-reports/{report_id}/prepare-notifications", response_model=ApiResponse)
async def audit_review_report_prepare_notifications(
    report_id: uuid.UUID,
    payload: PrepareNotificationsRequest,
    current_user: CurrentUser = Depends(require_permission("NOTIFICATION_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await prepare_audit_review_notifications(
            db,
            report_id,
            payload.model_copy(update={"requested_by": _current_user_actor_name(current_user)}),
        )
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review notifications prepared successfully.",
        "data": data,
    }


@router.get("/audit-review-reports/{report_id}/notifications", response_model=ApiResponse)
async def audit_review_report_notifications(
    report_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("NOTIFICATION_VIEW")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await list_audit_review_report_notifications(db, report_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review report notifications fetched successfully.",
        "data": data,
    }


@router.post("/audit-review-reports/{report_id}/send-notifications", response_model=ApiResponse)
async def audit_review_report_send_notifications(
    report_id: uuid.UUID,
    payload: SendNotificationRequest,
    current_user: CurrentUser = Depends(require_permission("NOTIFICATION_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await send_audit_review_report_notifications(
            db,
            report_id,
            payload.model_copy(update={"sent_by": _current_user_actor_name(current_user)}),
        )
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review report notifications processed.",
        "data": data,
    }


@router.get("/audit-review-reports/{report_id}/download-pdf")
async def audit_review_report_download_pdf(
    report_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("REPORT_EXPORT")),
    db: AsyncSession = Depends(get_db),
):
    try:
        download = await build_audit_review_report_pdf(db, report_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return StreamingResponse(
        BytesIO(download.content),
        media_type=download.media_type,
        headers={"Content-Disposition": f'attachment; filename="{download.file_name}"'},
    )


@router.get("/audit-review-reports/{report_id}/preview-html", response_class=HTMLResponse)
async def audit_review_report_preview_html(
    report_id: uuid.UUID,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REPORT_VIEW")),
    db: AsyncSession = Depends(get_db),
):
    try:
        html = await build_audit_review_report_html_preview(db, report_id)
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return HTMLResponse(content=html)


@router.post("/audit-review-reports/{report_id}/submit-review", response_model=ApiResponse)
async def audit_review_report_submit_review(
    report_id: uuid.UUID,
    payload: AuditReviewReportSubmitReviewRequest,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REPORT_SUBMIT")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await submit_audit_review_report_for_review(
            db,
            report_id,
            payload,
            current_user=current_user,
        )
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review report submitted for QA review successfully.",
        "data": data,
    }


@router.post("/audit-review-reports/{report_id}/approve", response_model=ApiResponse)
async def audit_review_report_approve(
    report_id: uuid.UUID,
    payload: AuditReviewReportReviewDecisionRequest,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REPORT_APPROVE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await approve_audit_review_report(
            db,
            report_id,
            payload,
            current_user=current_user,
        )
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review report approved successfully.",
        "data": data,
    }


@router.post("/audit-review-reports/{report_id}/reject", response_model=ApiResponse)
async def audit_review_report_reject(
    report_id: uuid.UUID,
    payload: AuditReviewReportReviewDecisionRequest,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REPORT_REJECT")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await reject_audit_review_report(
            db,
            report_id,
            payload,
            current_user=current_user,
        )
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review report rejected successfully.",
        "data": data,
    }


@router.post("/audit-review-reports/{report_id}/request-changes", response_model=ApiResponse)
async def audit_review_report_request_changes(
    report_id: uuid.UUID,
    payload: AuditReviewReportReviewDecisionRequest,
    current_user: CurrentUser = Depends(require_permission("AUDIT_REPORT_REQUEST_CHANGES")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await request_changes_audit_review_report(
            db,
            report_id,
            payload,
            current_user=current_user,
        )
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review report changes requested successfully.",
        "data": data,
    }


@router.post("/audit-review-notifications/{notification_id}/send", response_model=ApiResponse)
async def audit_review_notification_send(
    notification_id: uuid.UUID,
    payload: SendNotificationRequest,
    current_user: CurrentUser = Depends(require_permission("NOTIFICATION_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await send_audit_review_notification(
            db,
            notification_id,
            payload.model_copy(update={"sent_by": _current_user_actor_name(current_user)}),
        )
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": data.message,
        "data": data,
    }


@router.post("/audit-review-notifications/{notification_id}/dismiss", response_model=ApiResponse)
async def audit_review_notification_dismiss(
    notification_id: uuid.UUID,
    payload: DismissNotificationRequest,
    current_user: CurrentUser = Depends(require_permission("NOTIFICATION_MANAGE")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object] | JSONResponse:
    try:
        data = await dismiss_audit_review_notification(
            db,
            notification_id,
            payload.model_copy(update={"dismissed_by": _current_user_actor_name(current_user)}),
        )
    except AuditReviewServiceError as exc:
        return _service_error_response(exc)

    return {
        "success": True,
        "message": "Audit review notification dismissed successfully.",
        "data": data,
    }
