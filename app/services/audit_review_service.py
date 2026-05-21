import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.asset import Asset
from app.models.audit_review_finding import AuditReviewFinding
from app.models.audit_review_job import AuditReviewJob
from app.models.audit_review_report import AuditReviewReport
from app.models.audit_review_score import AuditReviewScore
from app.models.audit_trail_record import AuditTrailRecord
from app.schemas.auth_schema import CurrentUser
from app.schemas.audit_review_schema import (
    AUDIT_REVIEW_STATUS_ANALYZED,
    AUDIT_REVIEW_STATUS_ANALYZING,
    AUDIT_REVIEW_STATUS_CREATED,
    AUDIT_REVIEW_STATUS_EXTRACTED,
    AUDIT_REVIEW_STATUS_EXTRACTING,
    AUDIT_REVIEW_STATUS_FAILED,
    AUDIT_REVIEW_STATUS_PARTIAL_EXTRACTION,
    AuditReviewAnalyzeRequest,
    AuditReviewAnalyzeResponse,
    DEFAULT_AUDIT_TRAIL_TYPE,
    AuditReviewExtractResponse,
    AuditReviewFindingResponse,
    AuditReviewJobCreateRequest,
    AuditReviewJobCreateResponse,
    AuditReviewJobDetailResponse,
    AuditReviewJobListItem,
    AuditReviewScoreResponse,
    AuditTrailRecordResponse,
)
from app.services.audit_review_metadata import (
    REVIEW_SCOPE_CUSTOM,
    AuditReviewMetadataError,
    get_metadata_response,
    get_selected_audit_trail_types,
    resolve_review_scope,
    score_label_for_scope,
)
from app.services.audit_review_normalizers import (
    ACTION_KEYS,
    best_action_label,
    infer_action_category_from_payload,
    normalize_audit_record,
)
from app.services.audit_review_checks_service import (
    AuditAnalysisConfig,
    AuditFindingCandidate,
    run_deterministic_audit_checks,
)
from app.services.audit_review_scoring_service import (
    OVERALL_CHECK_CODE,
    build_score_models,
    calculate_audit_review_score,
)
from app.services.veeva_audit_mcp_client import VeevaAuditMcpClient, VeevaAuditMcpClientError


logger = logging.getLogger(__name__)

DELETE_ACTION_TERMS = ("delete", "remove", "purge")
PERMISSION_CHANGE_TERMS = ("role", "permission", "access", "security", "group")
EXTRACTABLE_STATUSES = {
    AUDIT_REVIEW_STATUS_CREATED,
    AUDIT_REVIEW_STATUS_FAILED,
    AUDIT_REVIEW_STATUS_PARTIAL_EXTRACTION,
}
ANALYZABLE_STATUSES = {
    AUDIT_REVIEW_STATUS_EXTRACTED,
    AUDIT_REVIEW_STATUS_PARTIAL_EXTRACTION,
    AUDIT_REVIEW_STATUS_ANALYZED,
}
SYSTEM_AUDIT_REVIEW_ACTOR = "audit-review-scheduler"
DEFAULT_VEEVA_AUDIT_EXTRACTION_CHUNK_DAYS = 14
DEFAULT_VEEVA_AUDIT_LOOKBACK_DAYS = 30
VEEVA_AUDIT_LOOKBACK_CALENDAR_BOUNDARY_GRACE_DAYS = 1


class AuditReviewServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data or {}


class AuditReviewNotFoundError(AuditReviewServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404)


class AuditReviewValidationError(AuditReviewServiceError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=400, data=data)


class AuditReviewExtractionError(AuditReviewServiceError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=502, data=data)


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_metadata_selection(
    review_scope: str | None,
    selected_audit_trail_types: list[str] | None,
    audit_trail_type: str | None,
) -> tuple[str, list[str]]:
    try:
        selected = get_selected_audit_trail_types(review_scope, selected_audit_trail_types, audit_trail_type)
        scope = resolve_review_scope(review_scope, selected, audit_trail_type)
    except AuditReviewMetadataError as exc:
        raise AuditReviewValidationError(exc.message, data=exc.data) from exc
    return scope, selected


def _job_selected_types(job: AuditReviewJob) -> list[str]:
    value = job.selected_audit_trail_types_json
    if isinstance(value, list):
        selected = [str(item) for item in value if str(item).strip()]
    else:
        selected = []
    if selected:
        return selected
    return [job.audit_trail_type or DEFAULT_AUDIT_TRAIL_TYPE]


def _job_review_scope(job: AuditReviewJob) -> str:
    scope = getattr(job, "review_scope", None)
    selected = _job_selected_types(job)
    try:
        return resolve_review_scope(scope, selected, job.audit_trail_type)
    except AuditReviewMetadataError:
        return REVIEW_SCOPE_CUSTOM


def _score_label_for_job(job: AuditReviewJob) -> str:
    return score_label_for_scope(_job_review_scope(job), _job_selected_types(job))


def _coverage_by_audit_type(job: AuditReviewJob) -> dict[str, Any]:
    summary = job.extraction_summary_json or {}
    audit_types = summary.get("audit_types") if isinstance(summary, dict) else None
    if isinstance(audit_types, dict):
        return audit_types
    selected = _job_selected_types(job)
    record_count = int(summary.get("record_count") or 0) if isinstance(summary, dict) else 0
    return {
        audit_trail_type: {
            "status": job.status,
            "record_count": record_count if audit_trail_type == (job.audit_trail_type or selected[0]) else 0,
        }
        for audit_trail_type in selected
    }


def _build_checklist_applicability_from_summary(summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(summary, dict):
        return []
    checklist = summary.get("checklist_applicability")
    if isinstance(checklist, list):
        return [item for item in checklist if isinstance(item, dict)]
    breakdown = summary.get("score_breakdown")
    if not isinstance(breakdown, list):
        return []
    return [
        {
            "check_code": item.get("check_code"),
            "check_name": item.get("check_name"),
            "applicability": item.get("applicability") or item.get("score_status"),
            "applicable_audit_trail_types": item.get("applicable_audit_trail_types") or [],
            "evaluated_record_count": item.get("evaluated_record_count") or item.get("applicable_record_count") or 0,
            "skipped_record_count": item.get("skipped_record_count") or 0,
        }
        for item in breakdown
        if isinstance(item, dict)
    ]


def _limit(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length]


def _safe_error_message(value: Any) -> str:
    text = str(value or "Veeva MCP audit trail extraction failed.").strip()
    return text[:1000]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mcp_failure_data(mcp_response: dict[str, Any]) -> dict[str, Any]:
    data = mcp_response.get("data")
    return data if isinstance(data, dict) else {}


def _actor_from_current_user(current_user: CurrentUser | None) -> dict[str, Any] | None:
    if current_user is None:
        return None
    email = str(current_user.email or "").strip()
    full_name = str(current_user.full_name or "").strip()
    display_name = full_name or email
    if not display_name:
        return None
    return {
        "actor_type": "USER",
        "user_id": str(current_user.id),
        "full_name": full_name or None,
        "email": email or None,
        "display_name": display_name,
        "roles": list(current_user.roles or []),
        "permissions": list(current_user.permissions or []),
    }


def _system_actor() -> dict[str, Any]:
    return {
        "actor_type": "SYSTEM",
        "user_id": None,
        "full_name": SYSTEM_AUDIT_REVIEW_ACTOR,
        "email": None,
        "display_name": SYSTEM_AUDIT_REVIEW_ACTOR,
        "roles": [],
        "permissions": [],
    }


def _actor_label(actor: dict[str, Any] | None) -> str | None:
    if actor is None:
        return None
    return str(actor.get("display_name") or actor.get("email") or "").strip() or None


def _workflow_actor(
    current_user: CurrentUser | None,
    *,
    period_basis: str | None = None,
    trigger_mode: str | None = None,
) -> dict[str, Any] | None:
    user_actor = _actor_from_current_user(current_user)
    if user_actor is not None:
        return user_actor
    normalized_period = str(period_basis or "").strip().upper()
    normalized_trigger = str(trigger_mode or "").strip().upper()
    if normalized_period == "SCHEDULED" or normalized_trigger.startswith("SCHEDULED"):
        return _system_actor()
    return None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return _to_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _review_window_chunks(start_dt: datetime, end_dt: datetime, chunk_days: int) -> list[tuple[datetime, datetime]]:
    start = _to_utc(start_dt)
    end = _to_utc(end_dt)
    if end <= start:
        return []

    window_days = max(1, _safe_int(chunk_days, DEFAULT_VEEVA_AUDIT_EXTRACTION_CHUNK_DAYS))
    chunk_delta = timedelta(days=window_days)
    chunks: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + chunk_delta, end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end
    return chunks


def _audit_extraction_chunk_days(client: VeevaAuditMcpClient) -> int:
    configured = getattr(client.settings, "VEEVA_AUDIT_EXTRACTION_CHUNK_DAYS", DEFAULT_VEEVA_AUDIT_EXTRACTION_CHUNK_DAYS)
    try:
        return max(1, int(configured))
    except (TypeError, ValueError):
        return DEFAULT_VEEVA_AUDIT_EXTRACTION_CHUNK_DAYS


def _audit_lookback_days(client: VeevaAuditMcpClient) -> int:
    configured = getattr(client.settings, "VEEVA_AUDIT_LOOKBACK_DAYS", DEFAULT_VEEVA_AUDIT_LOOKBACK_DAYS)
    try:
        return max(1, min(int(configured), DEFAULT_VEEVA_AUDIT_LOOKBACK_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_VEEVA_AUDIT_LOOKBACK_DAYS


def _audit_lookback_boundary_grace_days(lookback_days: int) -> int:
    return VEEVA_AUDIT_LOOKBACK_CALENDAR_BOUNDARY_GRACE_DAYS if lookback_days < DEFAULT_VEEVA_AUDIT_LOOKBACK_DAYS else 0


def _oldest_supported_audit_start(reference_dt: datetime, lookback_days: int) -> datetime:
    return _to_utc(reference_dt) - timedelta(days=lookback_days + _audit_lookback_boundary_grace_days(lookback_days))


def _normalized_record_dedupe_key(audit_trail_type: str, normalized: dict[str, Any]) -> str:
    source_key = str(normalized.get("source_record_key") or "").strip()
    if source_key:
        return f"{audit_trail_type}:{source_key}"
    fingerprint = "|".join(
        str(normalized.get(key) or "")
        for key in (
            "event_timestamp",
            "user_id",
            "action_type",
            "object_type",
            "object_name",
            "object_id",
            "field_name",
            "old_value",
            "new_value",
        )
    )
    return f"{audit_trail_type}:fingerprint:{fingerprint}"


def build_audit_review_candidate_key(
    asset_id: uuid.UUID,
    audit_trail_type: str,
    start_dt: datetime,
    end_dt: datetime,
) -> str:
    return f"{asset_id}:{audit_trail_type}:{_iso_utc(start_dt)}:{_iso_utc(end_dt)}"


def _build_review_candidate_key(asset_id: uuid.UUID, audit_trail_type: str, start_dt: datetime, end_dt: datetime) -> str:
    return build_audit_review_candidate_key(asset_id, audit_trail_type, start_dt, end_dt)


def _record_count_subquery():
    return (
        select(
            AuditTrailRecord.job_id.label("job_id"),
            func.count(AuditTrailRecord.record_id).label("record_count"),
        )
        .group_by(AuditTrailRecord.job_id)
        .subquery()
    )


def _finding_count_subquery():
    return (
        select(
            AuditReviewFinding.job_id.label("job_id"),
            func.count(AuditReviewFinding.finding_id).label("finding_count"),
        )
        .group_by(AuditReviewFinding.job_id)
        .subquery()
    )


def _overall_score_subquery():
    return (
        select(
            AuditReviewScore.job_id.label("job_id"),
            AuditReviewScore.overall_score.label("overall_score"),
            AuditReviewScore.rating.label("rating"),
        )
        .where(AuditReviewScore.check_code == OVERALL_CHECK_CODE, AuditReviewScore.score_scope == "OVERALL")
        .subquery()
    )


def _job_with_count_query() -> Select[tuple[AuditReviewJob, int, int, int | None, str | None]]:
    record_counts = _record_count_subquery()
    finding_counts = _finding_count_subquery()
    overall_scores = _overall_score_subquery()
    return select(
        AuditReviewJob,
        func.coalesce(record_counts.c.record_count, 0).label("record_count"),
        func.coalesce(finding_counts.c.finding_count, 0).label("finding_count"),
        overall_scores.c.overall_score,
        overall_scores.c.rating,
    ).outerjoin(
        record_counts,
        AuditReviewJob.job_id == record_counts.c.job_id,
    ).outerjoin(
        finding_counts,
        AuditReviewJob.job_id == finding_counts.c.job_id,
    ).outerjoin(
        overall_scores,
        AuditReviewJob.job_id == overall_scores.c.job_id,
    )


async def _get_asset_by_id(db: AsyncSession, asset_id: uuid.UUID) -> Asset | None:
    result = await db.execute(select(Asset).where(Asset.asset_uuid == asset_id))
    return result.scalars().first()


async def _require_asset(db: AsyncSession, asset_id: uuid.UUID) -> Asset:
    asset = await _get_asset_by_id(db, asset_id)
    if asset is None:
        raise AuditReviewNotFoundError("Asset not found")
    return asset


async def _get_job_model(db: AsyncSession, job_id: uuid.UUID) -> AuditReviewJob | None:
    result = await db.execute(select(AuditReviewJob).where(AuditReviewJob.job_id == job_id))
    return result.scalars().first()


async def _require_job(db: AsyncSession, job_id: uuid.UUID) -> AuditReviewJob:
    job = await _get_job_model(db, job_id)
    if job is None:
        raise AuditReviewNotFoundError("Audit review job not found")
    return job


def _build_job_list_item(job: AuditReviewJob, record_count: int) -> AuditReviewJobListItem:
    return AuditReviewJobListItem(
        job_id=job.job_id,
        asset_id=job.asset_id,
        review_start_dt=job.review_start_dt,
        review_end_dt=job.review_end_dt,
        audit_trail_type=job.audit_trail_type,
        review_scope=_job_review_scope(job),
        selected_audit_trail_types=_job_selected_types(job),
        status=job.status,
        record_count=record_count,
        created_dt=job.created_dt,
        completed_at=job.completed_at,
    )


def _build_job_detail(
    job: AuditReviewJob,
    record_count: int,
    finding_count: int,
    overall_score: int | None,
    rating: str | None,
    latest_report: AuditReviewReport | None = None,
) -> AuditReviewJobDetailResponse:
    return AuditReviewJobDetailResponse(
        job_id=job.job_id,
        asset_id=job.asset_id,
        review_candidate_key=job.review_candidate_key,
        vault_dns=job.vault_dns,
        veeva_instance_name=job.veeva_instance_name,
        veeva_app_name=job.veeva_app_name,
        audit_trail_type=job.audit_trail_type,
        review_scope=_job_review_scope(job),
        selected_audit_trail_types=_job_selected_types(job),
        score_label=_score_label_for_job(job),
        review_start_dt=job.review_start_dt,
        review_end_dt=job.review_end_dt,
        period_basis=job.period_basis,
        trigger_mode=job.trigger_mode,
        status=job.status,
        input_snapshot_json=job.input_snapshot_json or {},
        extraction_summary_json=job.extraction_summary_json or {},
        analysis_summary_json=job.analysis_summary_json,
        report_summary_json=job.report_summary_json,
        error_message=job.error_message,
        requested_by=job.requested_by,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_by=job.created_by,
        created_dt=job.created_dt,
        modified_by=job.modified_by,
        modified_dt=job.modified_dt,
        record_count=record_count,
        finding_count=finding_count,
        overall_score=overall_score,
        rating=rating,
        latest_report_id=latest_report.report_id if latest_report is not None else None,
        latest_report_status=latest_report.report_status if latest_report is not None else None,
        latest_report_approval_status=latest_report.report_status if latest_report is not None else None,
        latest_report_submitted_by=latest_report.submitted_by if latest_report is not None else None,
        latest_report_submitted_dt=latest_report.submitted_dt if latest_report is not None else None,
        latest_report_reviewed_by=latest_report.reviewed_by if latest_report is not None else None,
        latest_report_reviewed_dt=latest_report.reviewed_dt if latest_report is not None else None,
        coverage_by_audit_type=_coverage_by_audit_type(job),
        audit_type_scores=[
            item
            for item in (job.analysis_summary_json or {}).get("audit_type_scores", [])
            if isinstance(item, dict)
        ],
        checkpoint_scores=[
            item
            for item in (job.analysis_summary_json or {}).get("checkpoint_scores", [])
            if isinstance(item, dict)
        ],
        checklist_applicability=_build_checklist_applicability_from_summary(job.analysis_summary_json),
    )


def _parse_event_timestamp(value: Any) -> tuple[datetime | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, datetime):
        parsed = _to_utc(value)
        return parsed, parsed.tzname()

    text = str(value).strip()
    if not text:
        return None, None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, None

    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    return parsed, "UTC" if text.endswith("Z") else parsed.tzname()


def _contains_any(value: str | None, terms: tuple[str, ...]) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return any(term in lowered for term in terms)


def _is_permission_change(action_type: str | None, object_type: str | None, field_name: str | None) -> bool:
    return any(_contains_any(value, PERMISSION_CHANGE_TERMS) for value in (action_type, object_type, field_name))


def _is_known_action_text(value: Any) -> bool:
    return value is not None and best_action_label(value) != "UNKNOWN"


def _first_payload_action(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ACTION_KEYS:
            value = payload.get(key)
            if _is_known_action_text(value):
                return str(value).strip()
        for key, value in payload.items():
            if str(key) in ACTION_KEYS and _is_known_action_text(value):
                return str(value).strip()
            nested = _first_payload_action(value)
            if nested:
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = _first_payload_action(item)
            if nested:
                return nested
    return None


def _record_action_fields(record: AuditTrailRecord) -> dict[str, str | None]:
    extra = record.normalized_extra_json if isinstance(record.normalized_extra_json, dict) else {}
    raw_payload = record.raw_payload_json if isinstance(record.raw_payload_json, dict) else {}
    raw_action = extra.get("raw_action")
    if not _is_known_action_text(raw_action):
        raw_action = _first_payload_action(raw_payload)

    detected_action_category = extra.get("detected_action_category")
    if not _is_known_action_text(detected_action_category):
        detected_action_category = infer_action_category_from_payload(raw_payload, record.audit_trail_type)

    display_action = best_action_label(
        extra.get("display_action"),
        record.action_type,
        detected_action_category,
        raw_action,
    )
    return {
        "raw_action": str(raw_action).strip() if _is_known_action_text(raw_action) else None,
        "detected_action_category": str(detected_action_category).strip() if _is_known_action_text(detected_action_category) else None,
        "display_action": display_action,
    }


def _build_record_model(job: AuditReviewJob, item: dict[str, Any], created_dt: datetime) -> AuditTrailRecord:
    event_timestamp, event_timezone = _parse_event_timestamp(item.get("event_timestamp"))
    source_record_key = _limit(item.get("source_record_key"), 300)
    action_type = _limit(item.get("action_type"), 150)
    object_type = _limit(item.get("object_type"), 150)
    field_name = _limit(item.get("field_name"), 250)

    raw_payload = item.get("raw_payload")
    if not isinstance(raw_payload, dict):
        raw_payload = dict(item)

    return AuditTrailRecord(
        job_id=job.job_id,
        asset_id=job.asset_id,
        source_record_key=source_record_key,
        audit_trail_type=_limit(item.get("audit_trail_type"), 100) or job.audit_trail_type,
        event_timestamp=event_timestamp,
        event_timezone=_limit(item.get("event_timezone") or event_timezone, 50),
        user_id=_limit(item.get("user_id"), 150),
        user_name=_limit(item.get("user_name"), 250),
        action_type=action_type,
        object_type=object_type,
        object_name=_limit(item.get("object_name"), 300),
        object_id=_limit(item.get("object_id"), 150),
        field_name=field_name,
        old_value=None if item.get("old_value") is None else str(item.get("old_value")),
        new_value=None if item.get("new_value") is None else str(item.get("new_value")),
        event_status=_limit(item.get("event_status"), 80),
        reason=None if item.get("reason") is None else str(item.get("reason")),
        change_control_id=_limit(item.get("change_control_id"), 150),
        ip_address=_limit(item.get("ip_address"), 100),
        session_id=_limit(item.get("session_id"), 150),
        auth_method=_limit(item.get("auth_method"), 100),
        failure_reason=None if item.get("failure_reason") is None else str(item.get("failure_reason")),
        is_delete_action=bool(item.get("is_delete_action")) or _contains_any(action_type, DELETE_ACTION_TERMS),
        is_permission_change=bool(item.get("is_permission_change")) or _is_permission_change(action_type, object_type, field_name),
        is_export_action=bool(item.get("is_export_action")),
        is_configuration_change=bool(item.get("is_configuration_change")),
        record_quality_status="VALID" if event_timestamp is not None and source_record_key is not None else "INCOMPLETE",
        raw_payload_json=raw_payload,
        normalized_extra_json=item.get("normalized_extra_json") if isinstance(item.get("normalized_extra_json"), dict) else {},
        created_dt=created_dt,
    )


def _build_record_response(record: AuditTrailRecord, include_raw: bool) -> dict[str, Any]:
    action_fields = _record_action_fields(record)
    payload = AuditTrailRecordResponse(
        record_id=record.record_id,
        job_id=record.job_id,
        asset_id=record.asset_id,
        source_record_key=record.source_record_key,
        audit_trail_type=record.audit_trail_type,
        event_timestamp=record.event_timestamp,
        event_timezone=record.event_timezone,
        user_id=record.user_id,
        user_name=record.user_name,
        raw_action=action_fields["raw_action"],
        action_type=record.action_type,
        detected_action_category=action_fields["detected_action_category"],
        display_action=action_fields["display_action"],
        object_type=record.object_type,
        object_name=record.object_name,
        object_id=record.object_id,
        field_name=record.field_name,
        old_value=record.old_value,
        new_value=record.new_value,
        event_status=record.event_status,
        reason=record.reason,
        change_control_id=record.change_control_id,
        ip_address=record.ip_address,
        session_id=record.session_id,
        auth_method=record.auth_method,
        failure_reason=record.failure_reason,
        is_delete_action=record.is_delete_action,
        is_permission_change=record.is_permission_change,
        is_export_action=record.is_export_action,
        is_configuration_change=record.is_configuration_change,
        record_quality_status=record.record_quality_status,
        created_dt=record.created_dt,
        raw_payload_json=record.raw_payload_json if include_raw else None,
        normalized_extra_json=record.normalized_extra_json if include_raw else None,
    ).model_dump()
    if not include_raw:
        payload.pop("raw_payload_json", None)
        payload.pop("normalized_extra_json", None)
    return payload


def _build_analysis_config(payload: AuditReviewAnalyzeRequest, job: AuditReviewJob) -> AuditAnalysisConfig:
    return AuditAnalysisConfig(
        business_timezone=payload.business_timezone,
        business_start_hour=payload.business_start_hour,
        business_end_hour=payload.business_end_hour,
        audit_trail_type=job.audit_trail_type,
        review_scope=_job_review_scope(job),
        selected_audit_trail_types=tuple(_job_selected_types(job)),
    )


def _build_finding_model(
    job: AuditReviewJob,
    candidate: AuditFindingCandidate,
    created_dt: datetime,
) -> AuditReviewFinding:
    return AuditReviewFinding(
        job_id=job.job_id,
        asset_id=job.asset_id,
        primary_record_id=candidate.record.record_id if candidate.record is not None else None,
        check_code=candidate.check_code,
        check_name=candidate.check_name,
        audit_trail_type=candidate.audit_trail_type,
        parameter_code=candidate.parameter_code,
        checkpoint_code=candidate.checkpoint_code,
        finding_type=candidate.check_code,
        severity=candidate.severity,
        score_impact=candidate.score_impact,
        finding_title=candidate.finding_title,
        finding_summary=candidate.finding_summary,
        title=candidate.finding_title,
        description=candidate.finding_summary,
        evidence_json=candidate.evidence_json,
        source_record_count=candidate.source_record_count,
        status="OPEN",
        created_by=job.requested_by,
        created_dt=created_dt,
        modified_by=job.requested_by,
        modified_dt=created_dt,
    )


def _build_finding_response(finding: AuditReviewFinding) -> dict[str, Any]:
    return AuditReviewFindingResponse(
        finding_id=finding.finding_id,
        job_id=finding.job_id,
        asset_id=finding.asset_id,
        primary_record_id=finding.primary_record_id,
        check_code=finding.check_code,
        check_name=finding.check_name,
        audit_trail_type=finding.audit_trail_type,
        parameter_code=finding.parameter_code,
        checkpoint_code=finding.checkpoint_code,
        finding_type=finding.finding_type,
        severity=finding.severity,
        status=finding.status,
        score_impact=finding.score_impact,
        finding_title=finding.finding_title,
        finding_summary=finding.finding_summary,
        title=finding.title,
        description=finding.description,
        evidence_json=finding.evidence_json or {},
        source_record_count=finding.source_record_count,
        created_dt=finding.created_dt,
    ).model_dump()


def _build_score_response(score: AuditReviewScore) -> dict[str, Any]:
    return AuditReviewScoreResponse(
        score_id=score.score_id,
        job_id=score.job_id,
        asset_id=score.asset_id,
        check_code=score.check_code,
        check_name=score.check_name,
        score_scope=score.score_scope,
        audit_trail_type=score.audit_trail_type,
        score_label=score.score_label,
        applicability=score.applicability,
        evaluated_record_count=score.evaluated_record_count,
        skipped_record_count=score.skipped_record_count,
        no_data_count=score.no_data_count,
        overall_score=score.overall_score,
        rating=score.rating,
        score_status=score.score_status,
        source_record_count=score.source_record_count,
        finding_count=score.finding_count,
        penalty_per_finding=score.penalty_per_finding,
        penalty_cap=score.penalty_cap,
        raw_penalty=score.raw_penalty,
        applied_penalty=score.applied_penalty,
        sort_order=score.sort_order,
        scoring_summary_json=score.scoring_summary_json or {},
        created_dt=score.created_dt,
    ).model_dump()


async def create_audit_review_job(
    db: AsyncSession,
    asset_id: uuid.UUID,
    payload: AuditReviewJobCreateRequest,
    *,
    period_basis: str = "MANUAL",
    trigger_mode: str = "MANUAL",
    input_snapshot_extra: dict[str, Any] | None = None,
    current_user: CurrentUser | None = None,
) -> AuditReviewJobCreateResponse:
    asset = await _require_asset(db, asset_id)
    if payload.review_end_dt < payload.review_start_dt:
        raise AuditReviewValidationError("review_start_dt must be before or equal to review_end_dt")

    review_scope, selected_audit_trail_types = _normalize_metadata_selection(
        payload.review_scope,
        payload.selected_audit_trail_types,
        payload.audit_trail_type,
    )
    audit_trail_type = selected_audit_trail_types[0] if selected_audit_trail_types else DEFAULT_AUDIT_TRAIL_TYPE
    now = _utc_now()
    actor = _workflow_actor(current_user, period_basis=period_basis, trigger_mode=trigger_mode)
    actor_label = _actor_label(actor)
    input_snapshot = {
        "asset_id": str(asset.asset_uuid),
        "asset_code": asset.asset_id,
        "asset_name": asset.asset_name,
        "audit_trail_type": audit_trail_type,
        "review_scope": review_scope,
        "selected_audit_trail_types": selected_audit_trail_types,
        "review_start_dt": _iso_utc(payload.review_start_dt),
        "review_end_dt": _iso_utc(payload.review_end_dt),
        "veeva_instance_name": payload.veeva_instance_name,
        "veeva_app_name": payload.veeva_app_name,
        "vault_dns": payload.vault_dns,
        "requested_by": actor_label,
        "requested_actor": actor,
    }
    if input_snapshot_extra:
        input_snapshot.update(input_snapshot_extra)
    job = AuditReviewJob(
        asset_id=asset.asset_uuid,
        review_candidate_key=_build_review_candidate_key(
            asset.asset_uuid,
            "|".join(selected_audit_trail_types),
            payload.review_start_dt,
            payload.review_end_dt,
        ),
        vault_dns=payload.vault_dns,
        veeva_instance_name=payload.veeva_instance_name,
        veeva_app_name=payload.veeva_app_name,
        audit_trail_type=audit_trail_type,
        review_scope=review_scope,
        selected_audit_trail_types_json=selected_audit_trail_types,
        review_start_dt=payload.review_start_dt,
        review_end_dt=payload.review_end_dt,
        period_basis=period_basis,
        trigger_mode=trigger_mode,
        status=AUDIT_REVIEW_STATUS_CREATED,
        input_snapshot_json=input_snapshot,
        extraction_summary_json={},
        requested_by=actor_label,
        created_by=actor_label,
        created_dt=now,
        modified_by=actor_label,
        modified_dt=now,
    )
    db.add(job)
    await db.commit()

    return AuditReviewJobCreateResponse(
        job_id=job.job_id,
        asset_id=job.asset_id,
        status=job.status,
        review_scope=review_scope,
        selected_audit_trail_types=selected_audit_trail_types,
    )


async def list_audit_review_jobs_for_asset(db: AsyncSession, asset_id: uuid.UUID) -> list[AuditReviewJobListItem]:
    await _require_asset(db, asset_id)
    stmt = (
        _job_with_count_query()
        .where(AuditReviewJob.asset_id == asset_id)
        .order_by(AuditReviewJob.created_dt.desc(), AuditReviewJob.job_id.desc())
    )
    result = await db.execute(stmt)
    return [_build_job_list_item(job, int(record_count or 0)) for job, record_count, _, _, _ in result.all()]


async def get_audit_review_job(db: AsyncSession, job_id: uuid.UUID) -> AuditReviewJobDetailResponse:
    stmt = _job_with_count_query().where(AuditReviewJob.job_id == job_id)
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        raise AuditReviewNotFoundError("Audit review job not found")
    job, record_count, finding_count, overall_score, rating = row
    latest_report_result = await db.execute(
        select(AuditReviewReport)
        .where(AuditReviewReport.job_id == job.job_id)
        .order_by(AuditReviewReport.created_dt.desc(), AuditReviewReport.report_id.desc())
        .limit(1)
    )
    latest_report = latest_report_result.scalars().first()
    return _build_job_detail(
        job,
        int(record_count or 0),
        int(finding_count or 0),
        overall_score,
        rating,
        latest_report,
    )


async def _mark_job_failed(
    db: AsyncSession,
    job: AuditReviewJob,
    message: str,
    *,
    extraction_summary: dict[str, Any] | None = None,
) -> None:
    now = _utc_now()
    job.status = AUDIT_REVIEW_STATUS_FAILED
    job.error_message = _safe_error_message(message)
    job.extraction_summary_json = extraction_summary or job.extraction_summary_json or {}
    job.completed_at = now
    job.modified_dt = now
    await db.commit()


async def extract_audit_review_job(
    db: AsyncSession,
    job_id: uuid.UUID,
    mcp_client: VeevaAuditMcpClient | None = None,
    *,
    current_user: CurrentUser | None = None,
) -> AuditReviewExtractResponse:
    job = await _require_job(db, job_id)
    if job.status not in EXTRACTABLE_STATUSES:
        raise AuditReviewValidationError(
            "Audit review job can only be extracted when status is CREATED, PARTIAL_EXTRACTION, or FAILED.",
            data={"job_id": str(job.job_id), "status": job.status},
        )

    client = mcp_client or VeevaAuditMcpClient()
    now = _utc_now()
    actor = _workflow_actor(current_user, period_basis=job.period_basis, trigger_mode=job.trigger_mode)
    actor_label = _actor_label(actor)
    job.status = AUDIT_REVIEW_STATUS_EXTRACTING
    job.started_at = now
    job.completed_at = None
    job.error_message = None
    job.modified_dt = now
    job.modified_by = actor_label or job.modified_by
    await db.commit()

    extracted_at = _utc_now()
    await db.execute(delete(AuditTrailRecord).where(AuditTrailRecord.job_id == job.job_id))

    selected_audit_trail_types = _job_selected_types(job)
    type_summaries: dict[str, dict[str, Any]] = {}
    successful_types: list[str] = []
    failed_types: list[str] = []
    partial_types: list[str] = []
    record_count = 0
    chunk_days = _audit_extraction_chunk_days(client)
    lookback_days = _audit_lookback_days(client)
    lookback_grace_days = _audit_lookback_boundary_grace_days(lookback_days)
    oldest_supported_start = _oldest_supported_audit_start(now, lookback_days)
    if _to_utc(job.review_start_dt) < oldest_supported_start:
        message = (
            "Veeva audit extraction cannot start because the requested review period begins "
            f"before the Vault audit endpoint lookback window of {lookback_days} day(s). "
            "The review period was not clamped; choose a more recent period or use an audit source with longer retention."
        )
        extraction_summary = {
            "record_count": 0,
            "review_scope": _job_review_scope(job),
            "audit_trail_type": job.audit_trail_type,
            "selected_audit_trail_types": selected_audit_trail_types,
            "successful_audit_trail_types": [],
            "failed_audit_trail_types": selected_audit_trail_types,
            "partial_audit_trail_types": [],
            "audit_types": {
                audit_trail_type: {
                    "status": "FAILED",
                    "record_count": 0,
                    "mcp_record_count": 0,
                    "error_message": message,
                    "failed_at": _iso_utc(_utc_now()),
                    "veeva_lookback_days": lookback_days,
                    "calendar_boundary_grace_days": lookback_grace_days,
                    "oldest_supported_start_dt": _iso_utc(oldest_supported_start),
                    "requested_review_start_dt": _iso_utc(job.review_start_dt),
                    "requested_review_end_dt": _iso_utc(job.review_end_dt),
                    "period_was_clamped": False,
                }
                for audit_trail_type in selected_audit_trail_types
            },
            "mcp_base_url": client.base_url,
            "chunk_days": chunk_days,
            "veeva_lookback_days": lookback_days,
            "calendar_boundary_grace_days": lookback_grace_days,
            "oldest_supported_start_dt": _iso_utc(oldest_supported_start),
            "requested_review_start_dt": _iso_utc(job.review_start_dt),
            "requested_review_end_dt": _iso_utc(job.review_end_dt),
            "period_was_clamped": False,
            "extracted_at": _iso_utc(extracted_at),
            "extracted_by": actor_label,
            "extracted_actor": actor,
        }
        await _mark_job_failed(db, job, message, extraction_summary=extraction_summary)
        raise AuditReviewExtractionError(
            message,
            data={
                "veeva_lookback_days": lookback_days,
                "calendar_boundary_grace_days": lookback_grace_days,
                "oldest_supported_start_dt": _iso_utc(oldest_supported_start),
                "requested_review_start_dt": _iso_utc(job.review_start_dt),
                "requested_review_end_dt": _iso_utc(job.review_end_dt),
                "period_was_clamped": False,
                "failed_audit_trail_types": selected_audit_trail_types,
                "audit_types": extraction_summary["audit_types"],
            },
        )

    for audit_trail_type in selected_audit_trail_types:
        chunks = _review_window_chunks(job.review_start_dt, job.review_end_dt, chunk_days)
        chunk_summaries: list[dict[str, Any]] = []
        stored_count = 0
        normalization_errors = 0
        duplicate_record_count = 0
        mcp_record_count = 0
        successful_chunk_count = 0
        failed_chunk_count = 0
        seen_record_keys: set[str] = set()

        for chunk_start_dt, chunk_end_dt in chunks:
            request_payload = {
                "audit_trail_type": audit_trail_type,
                "review_start_dt": _iso_utc(chunk_start_dt),
                "review_end_dt": _iso_utc(chunk_end_dt),
                "events": [],
                "objects": [],
                "limit": 200,
            }

            try:
                mcp_response = await client.get_audit_trail(request_payload)
            except VeevaAuditMcpClientError as exc:
                failed_chunk_count += 1
                chunk_summaries.append(
                    {
                        "status": "FAILED",
                        "review_start_dt": request_payload["review_start_dt"],
                        "review_end_dt": request_payload["review_end_dt"],
                        "record_count": 0,
                        "error_message": _safe_error_message(exc.message),
                        "mcp_base_url": client.base_url,
                        "failed_at": _iso_utc(_utc_now()),
                        "data": exc.data,
                    }
                )
                continue

            if mcp_response.get("success") is not True:
                failed_chunk_count += 1
                mcp_message = _safe_error_message(mcp_response.get("message"))
                failure_data = _mcp_failure_data(mcp_response)
                logger.warning(
                    "Veeva audit extraction chunk failed.",
                    extra={
                        "event": "audit_review_veeva_chunk_failed",
                        "job_id": str(job.job_id),
                        "audit_trail_type": audit_trail_type,
                        "review_start_dt": request_payload["review_start_dt"],
                        "review_end_dt": request_payload["review_end_dt"],
                        "mcp_status_code": mcp_response.get("_mcp_status_code"),
                        "mcp_message": mcp_message,
                        "veeva_failure": failure_data,
                    },
                )
                chunk_summaries.append(
                    {
                        "status": "FAILED",
                        "review_start_dt": request_payload["review_start_dt"],
                        "review_end_dt": request_payload["review_end_dt"],
                        "record_count": 0,
                        "error_message": mcp_message,
                        "mcp_base_url": client.base_url,
                        "mcp_status_code": mcp_response.get("_mcp_status_code"),
                        "data": failure_data,
                        "failed_at": _iso_utc(_utc_now()),
                    }
                )
                continue

            mcp_data = mcp_response.get("data") or {}
            records = mcp_data.get("records") if isinstance(mcp_data, dict) else None
            if not isinstance(records, list):
                failed_chunk_count += 1
                chunk_summaries.append(
                    {
                        "status": "FAILED",
                        "review_start_dt": request_payload["review_start_dt"],
                        "review_end_dt": request_payload["review_end_dt"],
                        "record_count": 0,
                        "error_message": "Veeva MCP audit trail response did not include a records list.",
                        "mcp_base_url": client.base_url,
                        "mcp_status_code": mcp_response.get("_mcp_status_code"),
                        "failed_at": _iso_utc(_utc_now()),
                    }
                )
                continue

            successful_chunk_count += 1
            chunk_stored_count = 0
            chunk_normalization_errors = 0
            chunk_duplicate_count = 0
            chunk_mcp_record_count = _safe_int(mcp_data.get("record_count"), len(records)) if isinstance(mcp_data, dict) else len(records)
            mcp_record_count += chunk_mcp_record_count

            for item in records:
                if not isinstance(item, dict):
                    continue
                try:
                    normalized = normalize_audit_record(audit_trail_type, item)
                except Exception:
                    normalization_errors += 1
                    chunk_normalization_errors += 1
                    continue
                dedupe_key = _normalized_record_dedupe_key(audit_trail_type, normalized)
                if dedupe_key in seen_record_keys:
                    duplicate_record_count += 1
                    chunk_duplicate_count += 1
                    continue
                seen_record_keys.add(dedupe_key)
                db.add(_build_record_model(job, normalized, extracted_at))
                stored_count += 1
                chunk_stored_count += 1

            chunk_summary = {
                "status": "EXTRACTED",
                "review_start_dt": request_payload["review_start_dt"],
                "review_end_dt": request_payload["review_end_dt"],
                "record_count": chunk_stored_count,
                "mcp_record_count": chunk_mcp_record_count,
                "normalization_error_count": chunk_normalization_errors,
                "duplicate_record_count": chunk_duplicate_count,
                "mcp_base_url": client.base_url,
                "mcp_status_code": mcp_response.get("_mcp_status_code"),
                "extracted_at": _iso_utc(extracted_at),
            }
            chunk_summaries.append(chunk_summary)

        if successful_chunk_count > 0:
            successful_types.append(audit_trail_type)
        if successful_chunk_count == 0:
            failed_types.append(audit_trail_type)
        elif failed_chunk_count > 0:
            partial_types.append(audit_trail_type)
        record_count += stored_count
        type_status = "EXTRACTED"
        if successful_chunk_count == 0:
            type_status = "FAILED"
        elif failed_chunk_count > 0:
            type_status = "PARTIAL_EXTRACTED"
        type_summary = {
            "status": type_status,
            "record_count": stored_count,
            "mcp_record_count": mcp_record_count,
            "mcp_base_url": client.base_url,
            "extracted_at": _iso_utc(extracted_at),
            "normalization_error_count": normalization_errors,
            "duplicate_record_count": duplicate_record_count,
            "chunk_days": chunk_days,
            "chunk_count": len(chunks),
            "successful_chunk_count": successful_chunk_count,
            "failed_chunk_count": failed_chunk_count,
            "chunks": chunk_summaries,
        }
        if successful_chunk_count == 0:
            type_summary["error_message"] = "All extraction chunks failed for this audit trail type."
            type_summary["failed_at"] = _iso_utc(_utc_now())
        type_summaries[audit_trail_type] = type_summary

    extraction_summary = {
        "record_count": record_count,
        "review_scope": _job_review_scope(job),
        "audit_trail_type": job.audit_trail_type,
        "selected_audit_trail_types": selected_audit_trail_types,
        "successful_audit_trail_types": successful_types,
        "failed_audit_trail_types": failed_types,
        "partial_audit_trail_types": partial_types,
        "audit_types": type_summaries,
        "mcp_base_url": client.base_url,
        "chunk_days": chunk_days,
        "extracted_at": _iso_utc(extracted_at),
        "extracted_by": actor_label,
        "extracted_actor": actor,
    }

    if not successful_types:
        message = "All selected audit trail extractions failed."
        await _mark_job_failed(db, job, message, extraction_summary=extraction_summary)
        raise AuditReviewExtractionError(
            message,
            data={"failed_audit_trail_types": failed_types, "audit_types": type_summaries},
        )

    job.status = AUDIT_REVIEW_STATUS_PARTIAL_EXTRACTION if failed_types or partial_types else AUDIT_REVIEW_STATUS_EXTRACTED
    job.extraction_summary_json = extraction_summary
    job.error_message = (
        "One or more selected audit trail extraction chunks failed."
        if partial_types and not failed_types
        else "One or more selected audit trail extractions failed."
        if failed_types
        else None
    )
    job.completed_at = extracted_at
    job.modified_dt = extracted_at
    job.modified_by = actor_label or job.modified_by
    await db.commit()

    return AuditReviewExtractResponse(
        job_id=job.job_id,
        asset_id=job.asset_id,
        status=job.status,
        record_count=record_count,
        extraction_summary_json=extraction_summary,
        coverage_by_audit_type=type_summaries,
    )


async def get_audit_review_job_records(
    db: AsyncSession,
    job_id: uuid.UUID,
    *,
    include_raw: bool = False,
    audit_trail_type: str | None = None,
) -> list[dict[str, Any]]:
    await _require_job(db, job_id)
    stmt = (
        select(AuditTrailRecord)
        .where(AuditTrailRecord.job_id == job_id)
        .order_by(AuditTrailRecord.event_timestamp.asc().nullslast(), AuditTrailRecord.created_dt.asc())
    )
    if audit_trail_type:
        stmt = stmt.where(AuditTrailRecord.audit_trail_type == audit_trail_type.strip().lower())
    result = await db.execute(stmt)
    return [_build_record_response(record, include_raw=include_raw) for record in result.scalars().all()]


async def analyze_audit_review_job(
    db: AsyncSession,
    job_id: uuid.UUID,
    payload: AuditReviewAnalyzeRequest,
    *,
    current_user: CurrentUser | None = None,
) -> AuditReviewAnalyzeResponse:
    job = await _require_job(db, job_id)
    if job.status not in ANALYZABLE_STATUSES:
        raise AuditReviewValidationError(
            "Audit review job can only be analyzed when status is EXTRACTED, PARTIAL_EXTRACTION, or ANALYZED.",
            data={"job_id": str(job.job_id), "status": job.status},
        )

    records_result = await db.execute(
        select(AuditTrailRecord)
        .where(AuditTrailRecord.job_id == job.job_id)
        .order_by(AuditTrailRecord.event_timestamp.asc().nullslast(), AuditTrailRecord.created_dt.asc())
    )
    records = list(records_result.scalars().all())

    analysis_config = _build_analysis_config(payload, job)
    try:
        analysis_config.zone_info()
    except ValueError as exc:
        raise AuditReviewValidationError(str(exc), data={"business_timezone": payload.business_timezone}) from exc

    started_at = _utc_now()
    actor = _workflow_actor(current_user, period_basis=job.period_basis, trigger_mode=job.trigger_mode)
    actor_label = _actor_label(actor)
    job.status = AUDIT_REVIEW_STATUS_ANALYZING
    job.error_message = None
    job.modified_dt = started_at
    job.modified_by = actor_label or job.modified_by
    await db.commit()

    check_results = run_deterministic_audit_checks(records, analysis_config)
    scoring_result = calculate_audit_review_score(
        check_results,
        total_records_analyzed=len(records),
        review_scope=_job_review_scope(job),
        selected_audit_trail_types=_job_selected_types(job),
    )
    analyzed_at = _utc_now()

    await db.execute(delete(AuditReviewFinding).where(AuditReviewFinding.job_id == job.job_id))
    await db.execute(delete(AuditReviewScore).where(AuditReviewScore.job_id == job.job_id))

    for check_result in check_results:
        for candidate in check_result.findings:
            db.add(_build_finding_model(job, candidate, analyzed_at))

    for score_row in build_score_models(job, scoring_result, created_dt=analyzed_at):
        db.add(score_row)

    analysis_summary = {
        **scoring_result.summary_dict(),
        "analyzed_at": _iso_utc(analyzed_at),
        "business_timezone": analysis_config.business_timezone,
        "business_start_hour": analysis_config.business_start_hour,
        "business_end_hour": analysis_config.business_end_hour,
        "check_count": len(check_results),
        "checklist_applicability": [item.to_applicability_dict() for item in check_results],
        "analyzed_by": actor_label,
        "analyzed_actor": actor,
    }
    job.status = AUDIT_REVIEW_STATUS_ANALYZED
    job.analysis_summary_json = analysis_summary
    job.error_message = None
    job.completed_at = analyzed_at
    job.modified_dt = analyzed_at
    job.modified_by = actor_label or job.modified_by
    await db.commit()

    return AuditReviewAnalyzeResponse(
        job_id=job.job_id,
        asset_id=job.asset_id,
        status=job.status,
        overall_score=scoring_result.overall_score,
        rating=scoring_result.rating,
        score_label=scoring_result.score_label,
        total_records_analyzed=scoring_result.total_records_analyzed,
        total_findings=scoring_result.total_findings,
        finding_counts_by_severity=scoring_result.finding_counts_by_severity,
        score_breakdown=[item.to_dict() for item in scoring_result.score_breakdown],
        audit_type_scores=[item.to_dict() for item in scoring_result.audit_type_scores],
        checkpoint_scores=[item.to_dict() for item in scoring_result.checkpoint_scores],
        checklist_applicability=[item.to_applicability_dict() for item in check_results],
    )


async def get_audit_review_job_findings(
    db: AsyncSession,
    job_id: uuid.UUID,
    *,
    severity: str | None = None,
    check_code: str | None = None,
    audit_trail_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    await _require_job(db, job_id)
    stmt = select(AuditReviewFinding).where(AuditReviewFinding.job_id == job_id)
    if severity:
        stmt = stmt.where(func.upper(AuditReviewFinding.severity) == severity.strip().upper())
    if check_code:
        stmt = stmt.where(func.upper(AuditReviewFinding.check_code) == check_code.strip().upper())
    if audit_trail_type:
        stmt = stmt.where(AuditReviewFinding.audit_trail_type == audit_trail_type.strip().lower())
    stmt = stmt.order_by(
        AuditReviewFinding.created_dt.asc(),
        AuditReviewFinding.severity.asc().nullslast(),
        AuditReviewFinding.finding_id.asc(),
    ).limit(limit)
    result = await db.execute(stmt)
    return [_build_finding_response(finding) for finding in result.scalars().all()]


async def get_audit_review_job_scores(
    db: AsyncSession,
    job_id: uuid.UUID,
) -> list[dict[str, Any]]:
    await _require_job(db, job_id)
    stmt = (
        select(AuditReviewScore)
        .where(AuditReviewScore.job_id == job_id)
        .order_by(AuditReviewScore.sort_order.asc(), AuditReviewScore.check_code.asc())
    )
    result = await db.execute(stmt)
    return [_build_score_response(score) for score in result.scalars().all()]


async def get_audit_review_metadata() -> dict[str, Any]:
    settings = get_settings()
    client = VeevaAuditMcpClient(settings)
    lookback_days = _audit_lookback_days(client)
    metadata = get_metadata_response()
    metadata.update(
        {
            "veeva_audit_lookback_days": lookback_days,
            "veeva_audit_calendar_boundary_grace_days": _audit_lookback_boundary_grace_days(lookback_days),
            "veeva_audit_extraction_chunk_days": _audit_extraction_chunk_days(client),
        }
    )
    return metadata
