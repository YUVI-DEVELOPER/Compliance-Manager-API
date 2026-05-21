import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.app_user import AppUser
from app.models.audit_review_finding import AuditReviewFinding
from app.models.audit_review_job import AuditReviewJob
from app.models.audit_review_report import AuditReviewReport
from app.models.audit_review_score import AuditReviewScore
from app.models.audit_trail_record import AuditTrailRecord
from app.core.security import verify_password
from app.schemas.auth_schema import CurrentUser
from app.schemas.audit_review_schema import (
    AUDIT_REVIEW_REPORT_STATUS_APPROVED,
    AUDIT_REVIEW_REPORT_STATUS_CHANGES_REQUESTED,
    AUDIT_REVIEW_REPORT_STATUS_DRAFT,
    AUDIT_REVIEW_REPORT_STATUS_REJECTED,
    AUDIT_REVIEW_REPORT_STATUS_SUPERSEDED,
    AUDIT_REVIEW_REPORT_STATUS_UNDER_REVIEW,
    AUDIT_REVIEW_STATUS_ANALYZED,
    AUDIT_REVIEW_STATUS_REPORT_DRAFTED,
    AUDIT_REVIEW_STATUS_REPORT_GENERATING,
    AuditReviewReportDetailResponse,
    AuditReviewReportGenerateResponse,
    AuditReviewReportListItem,
    AuditReviewReportReviewDecisionRequest,
    AuditReviewReportSubmitReviewRequest,
)
from app.services.audit_review_metadata import (
    PARAMETER_CARD_METADATA,
    REVIEW_SCOPE_FULL_GXP,
    resolve_review_scope,
    score_label_for_scope,
)
from app.services.audit_review_scoring_service import OVERALL_CHECK_CODE
from app.services.audit_review_service import AuditReviewNotFoundError, AuditReviewValidationError
from app.services.audit_review_workflow_metadata import (
    actor_user_uuid,
    build_initial_workflow_metadata,
    build_report_workflow_metadata,
    get_audit_review_workflow_config,
    report_origin_from_job,
    update_decision_metadata,
    update_submission_metadata,
    uuid_or_none,
)
from app.services.rbac_service import record_audit_event


REPORTABLE_STATUSES = {AUDIT_REVIEW_STATUS_ANALYZED, AUDIT_REVIEW_STATUS_REPORT_DRAFTED}
REPORT_TITLE = "Veeva Audit Trail Periodic Review Report"
FINDING_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
KEY_FINDINGS_LIMIT = 20
SYSTEM_AUDIT_REVIEW_ACTOR = "audit-review-scheduler"

RECOMMENDATIONS = [
    "Review HIGH severity findings before approval.",
    "Verify off-hours activity with business justification.",
    "Confirm permission/access changes were authorized.",
]
SYSTEM_NOTES = [
    "This is a system-generated draft report.",
    "Deterministic checks were used for scoring.",
    "Human QA/Compliance review is required before final approval.",
]
SCOPE_DISCLAIMER = (
    "This report covers only the selected audit trail scope. It should not be interpreted as a full GxP audit "
    "trail review unless all supported audit trail types were selected."
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _to_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_str(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _actor_from_current_user(current_user: CurrentUser, action_label: str) -> dict[str, Any]:
    email = _safe_str(current_user.email)
    full_name = _safe_str(current_user.full_name)
    display_name = full_name or email
    if not display_name:
        raise AuditReviewValidationError(f"Unable to resolve authenticated actor for {action_label}.")
    return {
        "actor_type": "USER",
        "user_id": str(current_user.id),
        "full_name": full_name or None,
        "email": email or None,
        "display_name": display_name,
        "roles": list(current_user.roles or []),
        "permissions": list(current_user.permissions or []),
    }


def _system_actor(display_name: str = SYSTEM_AUDIT_REVIEW_ACTOR) -> dict[str, Any]:
    return {
        "actor_type": "SYSTEM",
        "user_id": None,
        "full_name": display_name,
        "email": None,
        "display_name": display_name,
        "roles": [],
        "permissions": [],
    }


def _actor_label(actor: dict[str, Any]) -> str:
    return _safe_str(actor.get("display_name")) or _safe_str(actor.get("email")) or SYSTEM_AUDIT_REVIEW_ACTOR


def _actor_audit_id(actor: dict[str, Any]) -> str:
    return _safe_str(actor.get("user_id")) or _actor_label(actor)


def _actor_decision_fields(actor: dict[str, Any]) -> dict[str, Any]:
    return {
        "actor": actor,
        "actor_user_id": actor.get("user_id"),
        "actor_full_name": actor.get("full_name"),
        "actor_email": actor.get("email"),
        "actor_roles": actor.get("roles") or [],
        "actor_permissions": actor.get("permissions") or [],
    }


def _password_matches(password_hash: str | None, plain_password: str) -> bool:
    if not password_hash:
        return False
    if password_hash.startswith("hashed::"):
        return password_hash == f"hashed::{plain_password}"
    try:
        return verify_password(plain_password, password_hash)
    except ValueError:
        return False


async def _verify_e_signature_credentials(
    db: AsyncSession,
    current_user: CurrentUser | None,
    user_email: str,
    plain_password: str,
) -> None:
    if current_user is None:
        raise AuditReviewValidationError("Authenticated user is required for electronic signature.")

    user = await db.get(AppUser, current_user.id)
    if user is None:
        raise AuditReviewValidationError("Unable to verify electronic signature user.")
    if user.email.strip().lower() != user_email.strip().lower():
        raise AuditReviewValidationError(
            "Electronic signature email confirmation failed.",
            data={"field": "e_signature.user_email"},
        )
    if not _password_matches(user.password_hash, plain_password):
        raise AuditReviewValidationError(
            "Electronic signature password confirmation failed.",
            data={"field": "e_signature.current_password"},
        )


def _actor_role_label(actor: dict[str, Any]) -> str | None:
    roles = actor.get("roles") or []
    if not isinstance(roles, list):
        return None
    labels = [str(role).strip() for role in roles if str(role).strip()]
    return ", ".join(labels) if labels else None


def _build_e_signature_record(
    *,
    actor: dict[str, Any],
    signed_at: datetime,
    signature_meaning: str,
    reviewer_comments: str,
    report: AuditReviewReport,
) -> dict[str, Any]:
    signer_name = _actor_label(actor)
    signed_at_text = _iso_datetime(signed_at)
    return {
        "signature_type": "FINAL_QA_APPROVAL",
        "signature_name": signer_name,
        "signature_title": _actor_role_label(actor),
        "user_id": actor.get("user_id"),
        "user_email": actor.get("email"),
        "signature_time": signed_at_text,
        "signature_meaning": signature_meaning,
        "signature_verdict": "Approved",
        "task_name": "Final QA Approval",
        "workflow_name": "Audit Review Report Approval",
        "workflow_step": "Approve Report",
        "authentication_method": "Password re-entry during authenticated application session",
        "reviewer_comments": reviewer_comments,
        "report_id": str(report.report_id),
        "report_version": report.report_version or get_audit_review_workflow_config().report_version,
        "manifest_on_signature_page": True,
        "signature_page_location": "END",
    }


def _authenticated_actor(current_user: CurrentUser | None, action_label: str) -> dict[str, Any]:
    if current_user is None:
        raise AuditReviewValidationError(f"Authenticated user is required for {action_label}.")
    return _actor_from_current_user(current_user, action_label)


def _report_generation_actor(job: AuditReviewJob, current_user: CurrentUser | None) -> dict[str, Any]:
    if current_user is not None:
        return _actor_from_current_user(current_user, "report generation")
    period_basis = _safe_str(job.period_basis).upper()
    trigger_mode = _safe_str(job.trigger_mode).upper()
    if period_basis == "SCHEDULED" or trigger_mode.startswith("SCHEDULED"):
        return _system_actor()
    raise AuditReviewValidationError("Authenticated user is required for report generation.")


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _markdown_cell(value: Any) -> str:
    text = _safe_str(value, "N/A")
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _job_run_actor(job: AuditReviewJob) -> dict[str, Any]:
    actor_sources = [
        (job.analysis_summary_json or {}).get("analyzed_actor"),
        (job.extraction_summary_json or {}).get("extracted_actor"),
        (job.input_snapshot_json or {}).get("requested_actor"),
    ]
    for actor in actor_sources:
        if isinstance(actor, dict) and actor:
            return actor
    return {}


def _actor_display_name_for_report(actor: dict[str, Any], fallback: str | None = None) -> str:
    actor_type = _safe_str(actor.get("actor_type")).upper()
    name = (
        _safe_str(actor.get("display_name"))
        or _safe_str(actor.get("full_name"))
        or _safe_str(actor.get("name"))
        or _safe_str(actor.get("email"))
        or _safe_str(fallback)
    )
    if actor_type == "SYSTEM" or name == SYSTEM_AUDIT_REVIEW_ACTOR:
        return "System Scheduler"
    return name or "N/A"


def _actor_roles_for_report(actor: dict[str, Any]) -> str:
    actor_type = _safe_str(actor.get("actor_type")).upper()
    if actor_type == "SYSTEM":
        return "SYSTEM"
    roles = actor.get("roles")
    if not isinstance(roles, list):
        roles = actor.get("actor_roles")
    if not isinstance(roles, list):
        return ""
    return ", ".join(_safe_str(role) for role in roles if _safe_str(role))


def _actor_role_name_for_report(actor: dict[str, Any], fallback: str | None = None) -> str:
    name = _actor_display_name_for_report(actor, fallback)
    roles = _actor_roles_for_report(actor)
    if roles and name:
        return f"{roles} - {name}"
    return name or roles or "N/A"


def _actor_user_id_for_report(actor: dict[str, Any]) -> str:
    actor_type = _safe_str(actor.get("actor_type")).upper()
    if actor_type == "SYSTEM":
        return "SYSTEM"
    return _safe_str(actor.get("user_id") or actor.get("actor_user_id"), "N/A")


def _job_selected_types(job: AuditReviewJob) -> list[str]:
    value = job.selected_audit_trail_types_json
    if isinstance(value, list) and value:
        return [str(item) for item in value if str(item).strip()]
    return [job.audit_trail_type or "login_audit_trail"]


def _job_scope(job: AuditReviewJob) -> str:
    try:
        return resolve_review_scope(job.review_scope, _job_selected_types(job), job.audit_trail_type)
    except Exception:
        return "CUSTOM"


def _coverage_by_type(job: AuditReviewJob) -> dict[str, Any]:
    summary = job.extraction_summary_json or {}
    audit_types = summary.get("audit_types") if isinstance(summary, dict) else None
    if isinstance(audit_types, dict):
        return audit_types
    return {
        audit_trail_type: {"status": job.status, "record_count": 0}
        for audit_trail_type in _job_selected_types(job)
    }


async def _require_asset(db: AsyncSession, asset_id: uuid.UUID) -> Asset:
    result = await db.execute(select(Asset).where(Asset.asset_uuid == asset_id))
    asset = result.scalars().first()
    if asset is None:
        raise AuditReviewNotFoundError("Asset not found")
    return asset


async def _require_job(db: AsyncSession, job_id: uuid.UUID) -> AuditReviewJob:
    result = await db.execute(
        select(AuditReviewJob)
        .options(selectinload(AuditReviewJob.asset))
        .where(AuditReviewJob.job_id == job_id)
    )
    job = result.scalars().first()
    if job is None:
        raise AuditReviewNotFoundError("Audit review job not found")
    return job


async def _require_report(db: AsyncSession, report_id: uuid.UUID) -> AuditReviewReport:
    result = await db.execute(select(AuditReviewReport).where(AuditReviewReport.report_id == report_id))
    report = result.scalars().first()
    if report is None:
        raise AuditReviewNotFoundError("Audit review report not found")
    return report


async def _latest_report_for_job(db: AsyncSession, job_id: uuid.UUID) -> AuditReviewReport | None:
    result = await db.execute(
        select(AuditReviewReport)
        .where(AuditReviewReport.job_id == job_id)
        .order_by(AuditReviewReport.created_dt.desc(), AuditReviewReport.report_id.desc())
        .limit(1)
    )
    return result.scalars().first()


def _append_approval_history(
    existing: dict[str, Any] | None,
    entry: dict[str, Any],
) -> dict[str, Any]:
    decision = dict(existing or {})
    history = decision.get("history")
    if not isinstance(history, list):
        history = []
    decision["history"] = [*history, entry]
    return decision


def _set_report_summary_status(report: AuditReviewReport, status_value: str, changed_at: datetime) -> None:
    summary = dict(report.report_summary_json or {})
    workflow_metadata = build_report_workflow_metadata(report)
    summary["status"] = status_value
    summary["approval_status"] = status_value
    summary["status_changed_at"] = _iso_datetime(changed_at)
    summary["submitted_by"] = report.submitted_by
    summary["submitted_dt"] = _iso_datetime(report.submitted_dt)
    summary["reviewed_by"] = report.reviewed_by
    summary["reviewed_dt"] = _iso_datetime(report.reviewed_dt)
    summary["reviewer_comments"] = report.reviewer_comments
    summary["decision_status"] = workflow_metadata.get("decision_status")
    summary["decision_by"] = workflow_metadata.get("decision_by_name")
    summary["decision_at"] = workflow_metadata.get("decision_at")
    summary["is_e_signed"] = bool(report.is_e_signed)
    summary["e_signed_at"] = _iso_datetime(report.e_signed_at)
    summary["is_locked"] = bool(report.is_locked)
    summary["locked_at"] = _iso_datetime(report.locked_at)
    summary["final_pdf_path"] = report.final_pdf_path
    summary["final_pdf_hash"] = report.final_pdf_hash
    summary["report_version"] = report.report_version
    report.report_summary_json = summary


async def _sync_job_report_summary_if_latest(
    db: AsyncSession,
    job: AuditReviewJob,
    report: AuditReviewReport,
) -> None:
    latest_report = await _latest_report_for_job(db, job.job_id)
    if latest_report is None or latest_report.report_id != report.report_id:
        return

    job.report_summary_json = dict(report.report_summary_json or {})
    job.modified_by = report.modified_by
    job.modified_dt = report.modified_dt


async def _count_records(db: AsyncSession, job_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(AuditTrailRecord.record_id)).where(AuditTrailRecord.job_id == job_id)
    )
    return int(result.scalar_one() or 0)


async def _load_findings_with_traceability(
    db: AsyncSession,
    job_id: uuid.UUID,
) -> list[tuple[AuditReviewFinding, str | None, str | None]]:
    result = await db.execute(
        select(AuditReviewFinding, AuditTrailRecord.source_record_key, AuditTrailRecord.audit_trail_type)
        .outerjoin(AuditTrailRecord, AuditReviewFinding.primary_record_id == AuditTrailRecord.record_id)
        .where(AuditReviewFinding.job_id == job_id)
        .order_by(AuditReviewFinding.created_dt.asc(), AuditReviewFinding.finding_id.asc())
    )
    rows = list(result.all())
    return sorted(
        rows,
        key=lambda row: (
            FINDING_SEVERITY_ORDER.get(_safe_str(row[0].severity, "LOW").upper(), 99),
            row[0].created_dt,
            str(row[0].finding_id),
        ),
    )


async def _load_scores(db: AsyncSession, job_id: uuid.UUID) -> list[AuditReviewScore]:
    result = await db.execute(
        select(AuditReviewScore)
        .where(AuditReviewScore.job_id == job_id)
        .order_by(AuditReviewScore.sort_order.asc(), AuditReviewScore.check_code.asc())
    )
    return list(result.scalars().all())


def _overall_score_and_rating(
    job: AuditReviewJob,
    scores: list[AuditReviewScore],
) -> tuple[int, str]:
    overall_row = next(
        (score for score in scores if score.check_code == OVERALL_CHECK_CODE and score.score_scope == "OVERALL"),
        None,
    )
    analysis_summary = job.analysis_summary_json or {}
    overall_score = (
        overall_row.overall_score
        if overall_row is not None and overall_row.overall_score is not None
        else _safe_int(analysis_summary.get("overall_score"), 0)
    )
    rating = (
        overall_row.rating
        if overall_row is not None and overall_row.rating
        else _safe_str(analysis_summary.get("rating"), "CRITICAL_RISK")
    )
    return int(overall_score), rating


def _severity_counts(findings: list[tuple[AuditReviewFinding, str | None, str | None]]) -> dict[str, int]:
    counter = Counter(_safe_str(row[0].severity, "LOW").upper() for row in findings)
    return {
        "critical": int(counter.get("CRITICAL", 0)),
        "high": int(counter.get("HIGH", 0)),
        "medium": int(counter.get("MEDIUM", 0)),
        "low": int(counter.get("LOW", 0)),
    }


def _check_summary(scores: list[AuditReviewScore]) -> list[dict[str, Any]]:
    return [
        {
            "check_code": score.check_code,
            "check_name": score.check_name,
            "score_scope": score.score_scope,
            "audit_trail_type": score.audit_trail_type,
            "applicability": score.applicability,
            "evaluated_record_count": score.evaluated_record_count,
            "skipped_record_count": score.skipped_record_count,
            "finding_count": score.finding_count,
            "penalty_points": score.applied_penalty,
            "status": score.score_status,
        }
        for score in scores
        if score.score_scope == "CHECKPOINT"
    ]


def _findings_by_audit_type(findings: list[tuple[AuditReviewFinding, str | None, str | None]]) -> dict[str, int]:
    counter = Counter((finding.audit_trail_type or record_type or "unspecified") for finding, _, record_type in findings)
    return {key: int(value) for key, value in sorted(counter.items())}


def _key_findings(findings: list[tuple[AuditReviewFinding, str | None, str | None]]) -> list[dict[str, Any]]:
    key_findings: list[dict[str, Any]] = []
    for finding, source_record_key, audit_trail_type in findings[:KEY_FINDINGS_LIMIT]:
        traceability = {
            "record_id": str(finding.primary_record_id) if finding.primary_record_id else None,
            "source_record_key": source_record_key,
            "audit_trail_type": finding.audit_trail_type or audit_trail_type,
        }
        key_findings.append(
            {
                "check_code": finding.check_code,
                "audit_trail_type": finding.audit_trail_type or audit_trail_type,
                "parameter_code": finding.parameter_code,
                "checkpoint_code": finding.checkpoint_code,
                "severity": _safe_str(finding.severity, "LOW").upper(),
                "finding_title": finding.finding_title or finding.title or finding.check_name,
                "finding_summary": finding.finding_summary or finding.description or "",
                "source_record_count": finding.source_record_count,
                "traceability": traceability,
            }
        )
    return key_findings


def _report_summary(
    report_json: dict[str, Any],
    *,
    generated_at: datetime,
) -> dict[str, Any]:
    execution_summary = report_json["execution_summary"]
    return {
        "title": report_json["title"],
        "generated_at": _iso_datetime(generated_at),
        "status": AUDIT_REVIEW_REPORT_STATUS_DRAFT,
        "total_records_reviewed": execution_summary["total_records_reviewed"],
        "total_findings": execution_summary["total_findings"],
        "overall_score": execution_summary["overall_score"],
        "score_label": execution_summary.get("score_label"),
        "rating": execution_summary["rating"],
        "finding_summary": report_json["finding_summary"],
        "approval_status": AUDIT_REVIEW_REPORT_STATUS_DRAFT,
        "submitted_by": None,
        "submitted_dt": None,
        "reviewed_by": None,
        "reviewed_dt": None,
        "reviewer_comments": None,
    }


def _report_metadata_response_fields(report: AuditReviewReport, job: AuditReviewJob | None = None) -> dict[str, Any]:
    workflow_metadata = build_report_workflow_metadata(report, job)
    return {
        "review_type": report.review_type or workflow_metadata.get("review_type"),
        "trigger_source": report.trigger_source or workflow_metadata.get("trigger_source"),
        "schedule_id": report.schedule_id or uuid_or_none(workflow_metadata.get("schedule_id")),
        "schedule_run_id": report.schedule_run_id or uuid_or_none(workflow_metadata.get("schedule_run_id")),
        "workflow_metadata_json": report.workflow_metadata_json,
        "workflow_metadata": workflow_metadata,
        "is_e_signed": bool(report.is_e_signed),
        "e_signed_at": report.e_signed_at,
        "e_signed_by_user_id": report.e_signed_by_user_id,
        "is_locked": bool(report.is_locked),
        "locked_at": report.locked_at,
        "locked_by_user_id": report.locked_by_user_id,
        "final_pdf_path": report.final_pdf_path,
        "final_pdf_hash": report.final_pdf_hash,
        "report_version": report.report_version or workflow_metadata.get("report_version"),
    }


def _existing_generation_actor(report: AuditReviewReport, fallback_actor: dict[str, Any]) -> dict[str, Any]:
    summary = report.report_summary_json or {}
    if isinstance(summary.get("generated_actor"), dict):
        return summary["generated_actor"]
    report_json = report.report_payload_json or {}
    workflow = report_json.get("workflow") if isinstance(report_json.get("workflow"), dict) else {}
    draft_generation = workflow.get("draft_generation") if isinstance(workflow.get("draft_generation"), dict) else {}
    if isinstance(draft_generation.get("actor"), dict):
        return draft_generation["actor"]
    return fallback_actor


def _ensure_report_workflow_metadata(
    report: AuditReviewReport,
    job: AuditReviewJob,
    *,
    fallback_actor: dict[str, Any],
    fallback_at: datetime,
) -> None:
    origin = report_origin_from_job(job)
    workflow_config = get_audit_review_workflow_config()
    if report.review_type is None:
        report.review_type = origin["review_type"]
    if report.trigger_source is None:
        report.trigger_source = origin["trigger_source"]
    if report.schedule_id is None:
        report.schedule_id = origin["schedule_id"]
    if report.schedule_run_id is None:
        report.schedule_run_id = origin["schedule_run_id"]
    if report.report_version is None:
        report.report_version = workflow_config.report_version
    if report.is_e_signed is None:
        report.is_e_signed = False
    if report.is_locked is None:
        report.is_locked = False
    if report.workflow_metadata_json is None:
        generated_at = report.created_dt or fallback_at
        generation_actor = _existing_generation_actor(report, fallback_actor)
        report.workflow_metadata_json = build_initial_workflow_metadata(
            job,
            draft_generated_actor=generation_actor,
            draft_generated_at=generated_at,
            triggered_actor=fallback_actor if origin["review_type"] == "ADHOC" else None,
            report_version=report.report_version,
        )


def _build_report_json(
    job: AuditReviewJob,
    *,
    total_records_reviewed: int,
    findings: list[tuple[AuditReviewFinding, str | None, str | None]],
    scores: list[AuditReviewScore],
    overall_score: int,
    rating: str,
) -> dict[str, Any]:
    asset = job.asset
    finding_summary = _severity_counts(findings)
    selected_types = _job_selected_types(job)
    review_scope = _job_scope(job)
    run_actor = _job_run_actor(job)
    analysis_summary = job.analysis_summary_json or {}
    audit_type_scores = [
        score.scoring_summary_json or {}
        for score in scores
        if score.score_scope == "AUDIT_TYPE"
    ]
    checkpoint_scores = [
        score.scoring_summary_json or {}
        for score in scores
        if score.score_scope == "CHECKPOINT"
    ]
    records_by_type = {
        audit_trail_type: _safe_int((coverage or {}).get("record_count"), 0)
        for audit_trail_type, coverage in _coverage_by_type(job).items()
        if isinstance(coverage, dict)
    }
    checklist_applicability = analysis_summary.get("checklist_applicability")
    if not isinstance(checklist_applicability, list):
        checklist_applicability = checkpoint_scores
    parameter_cards = []
    for parameter in sorted(PARAMETER_CARD_METADATA.values(), key=lambda item: item["sort_order"]):
        check_codes = set(parameter.get("check_codes", []))
        related = [item for item in checklist_applicability if isinstance(item, dict) and item.get("check_code") in check_codes]
        statuses = {str(item.get("applicability") or item.get("score_status") or "NO_DATA") for item in related}
        if not related:
            status = "NOT_APPLICABLE"
        elif "PARTIAL" in statuses:
            status = "PARTIAL"
        elif "ACTIVE" in statuses or "PASS" in statuses or "FAIL" in statuses:
            status = "ACTIVE"
        elif "NO_DATA" in statuses:
            status = "NO_DATA"
        else:
            status = "NOT_APPLICABLE"
        parameter_cards.append({**parameter, "status": status})

    return {
        "title": REPORT_TITLE,
        "asset": {
            "asset_id": str(job.asset_id),
            "asset_name": asset.asset_name if asset is not None else None,
        },
        "review_scope": {
            "job_id": str(job.job_id),
            "review_scope": review_scope,
            "audit_trail_type": job.audit_trail_type,
            "selected_audit_trail_types": selected_types,
            "review_start_dt": _iso_datetime(job.review_start_dt),
            "review_end_dt": _iso_datetime(job.review_end_dt),
            "veeva_instance_name": job.veeva_instance_name,
            "veeva_app_name": job.veeva_app_name,
        },
        "execution_summary": {
            "run_by_name": _actor_role_name_for_report(run_actor, job.modified_by or job.requested_by),
            "run_by_user_id": _actor_user_id_for_report(run_actor),
            "total_records_reviewed": total_records_reviewed,
            "records_by_audit_type": records_by_type,
            "extraction_coverage_by_audit_type": _coverage_by_type(job),
            "total_findings": len(findings),
            "findings_by_audit_type": _findings_by_audit_type(findings),
            "overall_score": overall_score,
            "score_label": score_label_for_scope(review_scope, selected_types),
            "rating": rating,
        },
        "finding_summary": finding_summary,
        "checklist_applicability": checklist_applicability,
        "audit_trail_parameters_reviewed": parameter_cards,
        "checkpoint_scores": checkpoint_scores,
        "audit_type_scores": audit_type_scores,
        "check_summary": _check_summary(scores),
        "key_findings": _key_findings(findings),
        "qa_decision": {
            "status": "PENDING_QA_REVIEW",
            "approval_status": "DRAFT",
        },
        "scope_disclaimer": None if review_scope == REVIEW_SCOPE_FULL_GXP else SCOPE_DISCLAIMER,
        "recommendations": RECOMMENDATIONS,
        "system_notes": SYSTEM_NOTES,
    }


def _format_traceability(finding: dict[str, Any]) -> str:
    traceability = finding.get("traceability") or {}
    record_id = traceability.get("record_id")
    source_record_key = traceability.get("source_record_key")
    parts = []
    if record_id:
        parts.append(f"record_id={record_id}")
    if source_record_key:
        parts.append(f"source_record_key={source_record_key}")
    audit_trail_type = traceability.get("audit_trail_type")
    if audit_trail_type:
        parts.append(f"audit_trail_type={audit_trail_type}")
    return "; ".join(parts) if parts else "traceability unavailable"


def _build_report_markdown(report_json: dict[str, Any], job: AuditReviewJob) -> str:
    asset = report_json["asset"]
    scope = report_json["review_scope"]
    execution = report_json["execution_summary"]
    run_actor = _job_run_actor(job)
    run_by_name = _actor_role_name_for_report(run_actor, job.modified_by or job.requested_by)
    run_by_user_id = _actor_user_id_for_report(run_actor)

    lines = [
        f"# {REPORT_TITLE}",
        "",
        "## 1. Executive Summary",
        f"- Audit Review Run By: {run_by_name}",
        f"- Audit Runner User ID: {run_by_user_id}",
        f"- Asset: {_safe_str(asset.get('asset_name'), 'N/A')} ({_safe_str(asset.get('asset_id'), 'N/A')})",
        f"- Review Period: {_safe_str(scope.get('review_start_dt'), 'N/A')} to {_safe_str(scope.get('review_end_dt'), 'N/A')}",
        f"- Review Scope: {_safe_str(scope.get('review_scope'), 'N/A')}",
        f"- Selected Audit Trail Types: {_safe_str(', '.join(scope.get('selected_audit_trail_types') or []), 'N/A')}",
        f"- Total Records Reviewed: {execution['total_records_reviewed']}",
        f"- {_safe_str(execution.get('score_label'), 'Audit Review Score')}: {execution['overall_score']}",
        f"- Rating: {execution['rating']}",
        "",
        "## 2. Review Scope",
        f"- Veeva Instance: {_safe_str(scope.get('veeva_instance_name'), 'N/A')}",
        f"- Veeva App: {_safe_str(scope.get('veeva_app_name'), 'N/A')}",
        f"- Review Start: {_safe_str(scope.get('review_start_dt'), 'N/A')}",
        f"- Review End: {_safe_str(scope.get('review_end_dt'), 'N/A')}",
        f"- Trigger Mode: {_safe_str(job.trigger_mode, 'N/A')}",
        "",
        "## 3. Extraction Coverage",
        "| Audit Trail Type | Status | Records |",
        "| --- | --- | ---: |",
    ]

    coverage = execution.get("extraction_coverage_by_audit_type") or {}
    if isinstance(coverage, dict):
        for audit_trail_type, item in coverage.items():
            row = item if isinstance(item, dict) else {}
            lines.append(
                "| "
                f"{_markdown_cell(audit_trail_type)} | "
                f"{_markdown_cell(row.get('status'))} | "
                f"{_markdown_cell(row.get('record_count'))} |"
            )

    lines.extend(
        [
            "",
            "## 4. Checklist Applicability",
            "| Check | Applicability | Evaluated | Skipped |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for item in report_json.get("checklist_applicability") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('check_name') or item.get('check_code'))} | "
            f"{_markdown_cell(item.get('applicability') or item.get('score_status'))} | "
            f"{_markdown_cell(item.get('evaluated_record_count'))} | "
            f"{_markdown_cell(item.get('skipped_record_count'))} |"
        )

    lines.extend(
        [
            "",
            "## 5. Compliance Score Summary",
        "| Check | Findings | Penalty | Status |",
        "| --- | ---: | ---: | --- |",
        ]
    )

    for check in report_json["check_summary"]:
        lines.append(
            "| "
            f"{_markdown_cell(check.get('check_name'))} | "
            f"{_markdown_cell(check.get('finding_count'))} | "
            f"{_markdown_cell(check.get('penalty_points'))} | "
            f"{_markdown_cell(check.get('status'))} |"
        )

    lines.extend(
        [
            "",
            "## 6. Findings Summary",
            "| Severity | Count |",
            "| --- | ---: |",
        ]
    )
    for severity in ("critical", "high", "medium", "low"):
        lines.append(f"| {severity.upper()} | {report_json['finding_summary'].get(severity, 0)} |")

    lines.extend(["", "## 7. Findings By Audit Type", "| Audit Trail Type | Count |", "| --- | ---: |"])
    findings_by_type = execution.get("findings_by_audit_type") or {}
    if isinstance(findings_by_type, dict) and findings_by_type:
        for audit_trail_type, count in findings_by_type.items():
            lines.append(f"| {_markdown_cell(audit_trail_type)} | {_markdown_cell(count)} |")
    else:
        lines.append("| None | 0 |")

    lines.extend(["", "## 8. Key Findings"])
    key_findings = report_json["key_findings"]
    if not key_findings:
        lines.append("- No findings were identified by deterministic checks.")
    else:
        for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            severity_findings = [finding for finding in key_findings if finding.get("severity") == severity]
            if not severity_findings:
                continue
            lines.extend(["", f"### {severity}"])
            for finding in severity_findings:
                title = _safe_str(finding.get("finding_title"), "Finding")
                summary = _safe_str(finding.get("finding_summary"), "No summary provided.")
                traceability = _format_traceability(finding)
                lines.append(
                    f"- **{_markdown_cell(finding.get('check_code'))}**: {title}. "
                    f"{summary} Source record count: {finding.get('source_record_count', 1)}. "
                    f"Traceability: {traceability}."
                )

    lines.extend(
        [
            "",
            "## 9. Checkpoint Scores",
            "| Checkpoint | Score Status | Applicability |",
            "| --- | --- | --- |",
        ]
    )
    for item in report_json.get("checkpoint_scores") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('check_name') or item.get('check_code'))} | "
            f"{_markdown_cell(item.get('score_status'))} | "
            f"{_markdown_cell(item.get('applicability'))} |"
        )

    lines.extend(
        [
            "",
            "## 10. Audit Type Scores",
            "| Audit Trail Type | Score | Rating |",
            "| --- | ---: | --- |",
        ]
    )
    for item in report_json.get("audit_type_scores") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            "| "
            f"{_markdown_cell(item.get('audit_trail_type'))} | "
            f"{_markdown_cell(item.get('overall_score'))} | "
            f"{_markdown_cell(item.get('rating'))} |"
        )

    lines.extend(
        [
            "",
            "## 11. Recommendations",
            *[f"- {recommendation}" for recommendation in report_json["recommendations"]],
            "",
            "## 12. Reviewer Notes",
            "Pending QA / Compliance review.",
            "",
            "## 13. System Notes",
            "- Draft only.",
            "- AI was not used to generate this report.",
            "- Human review required before approval.",
        ]
    )
    if report_json.get("scope_disclaimer"):
        lines.extend(["", "## 14. Scope Disclaimer", _safe_str(report_json.get("scope_disclaimer"))])
    return "\n".join(lines)


def _build_generate_response(report: AuditReviewReport) -> AuditReviewReportGenerateResponse:
    summary = report.report_summary_json or {}
    metadata_fields = _report_metadata_response_fields(report)
    return AuditReviewReportGenerateResponse(
        report_id=report.report_id,
        job_id=report.job_id,
        asset_id=report.asset_id,
        status=report.report_status,
        overall_score=_safe_int(summary.get("overall_score"), 0),
        rating=_safe_str(summary.get("rating"), "CRITICAL_RISK"),
        report_summary=summary,
        **metadata_fields,
        submitted_by=report.submitted_by,
        submitted_dt=report.submitted_dt,
        reviewed_by=report.reviewed_by,
        reviewed_dt=report.reviewed_dt,
        reviewer_comments=report.reviewer_comments,
        approval_decision_json=report.approval_decision_json,
    )


def _build_detail_response(report: AuditReviewReport) -> AuditReviewReportDetailResponse:
    summary = report.report_summary_json or {}
    metadata_fields = _report_metadata_response_fields(report, report.job if "job" in report.__dict__ else None)
    return AuditReviewReportDetailResponse(
        report_id=report.report_id,
        job_id=report.job_id,
        asset_id=report.asset_id,
        status=report.report_status,
        overall_score=_safe_int(summary.get("overall_score"), None),
        rating=summary.get("rating"),
        report_summary=summary,
        report_json=report.report_payload_json or {},
        report_markdown=report.report_markdown or "",
        **metadata_fields,
        submitted_by=report.submitted_by,
        submitted_dt=report.submitted_dt,
        reviewed_by=report.reviewed_by,
        reviewed_dt=report.reviewed_dt,
        reviewer_comments=report.reviewer_comments,
        approval_decision_json=report.approval_decision_json,
        created_dt=report.created_dt,
        modified_dt=report.modified_dt,
    )


def _build_list_item(report: AuditReviewReport) -> AuditReviewReportListItem:
    summary = report.report_summary_json or {}
    metadata_fields = _report_metadata_response_fields(report)
    return AuditReviewReportListItem(
        report_id=report.report_id,
        job_id=report.job_id,
        asset_id=report.asset_id,
        status=report.report_status,
        overall_score=_safe_int(summary.get("overall_score"), None),
        rating=summary.get("rating"),
        report_summary=summary,
        **metadata_fields,
        submitted_by=report.submitted_by,
        submitted_dt=report.submitted_dt,
        reviewed_by=report.reviewed_by,
        reviewed_dt=report.reviewed_dt,
        reviewer_comments=report.reviewer_comments,
        approval_decision_json=report.approval_decision_json,
        created_dt=report.created_dt,
        modified_dt=report.modified_dt,
    )


async def generate_audit_review_report(
    db: AsyncSession,
    job_id: uuid.UUID,
    *,
    current_user: CurrentUser | None = None,
) -> AuditReviewReportGenerateResponse:
    job = await _require_job(db, job_id)
    if job.status not in REPORTABLE_STATUSES:
        raise AuditReviewValidationError(
            "Audit review report can only be generated when job status is ANALYZED or REPORT_DRAFTED.",
            data={"job_id": str(job.job_id), "status": job.status},
        )

    approved_report_result = await db.execute(
        select(AuditReviewReport.report_id).where(
            AuditReviewReport.job_id == job.job_id,
            or_(
                AuditReviewReport.report_status == AUDIT_REVIEW_REPORT_STATUS_APPROVED,
                AuditReviewReport.is_locked.is_(True),
            ),
        )
    )
    approved_report_id = approved_report_result.scalars().first()
    if approved_report_id is not None:
        raise AuditReviewValidationError(
            "Audit review report regeneration is blocked because an approved report already exists for this job.",
            data={"job_id": str(job.job_id), "approved_report_id": str(approved_report_id)},
        )

    total_records_reviewed = await _count_records(db, job.job_id)
    findings = await _load_findings_with_traceability(db, job.job_id)
    scores = await _load_scores(db, job.job_id)
    if not scores:
        raise AuditReviewValidationError(
            "Audit review report requires score rows from analysis.",
            data={"job_id": str(job.job_id), "status": job.status},
        )

    overall_score, rating = _overall_score_and_rating(job, scores)
    generation_actor = _report_generation_actor(job, current_user)
    generation_actor_label = _actor_label(generation_actor)
    origin = report_origin_from_job(job)
    workflow_config = get_audit_review_workflow_config()

    started_at = _utc_now()
    job.status = AUDIT_REVIEW_STATUS_REPORT_GENERATING
    job.error_message = None
    job.modified_dt = started_at
    job.modified_by = generation_actor_label
    await db.commit()

    report_json = _build_report_json(
        job,
        total_records_reviewed=total_records_reviewed,
        findings=findings,
        scores=scores,
        overall_score=overall_score,
        rating=rating,
    )
    workflow = dict(report_json.get("workflow") or {})
    workflow["draft_generation"] = {
        "generated_by": generation_actor_label,
        "generated_at": _iso_datetime(started_at),
        **_actor_decision_fields(generation_actor),
    }
    report_json["workflow"] = workflow
    report_markdown = _build_report_markdown(report_json, job)
    generated_at = _utc_now()
    workflow_metadata = build_initial_workflow_metadata(
        job,
        draft_generated_actor=generation_actor,
        draft_generated_at=generated_at,
        triggered_actor=generation_actor if origin["review_type"] == "ADHOC" else None,
        report_version=workflow_config.report_version,
    )
    report_summary = _report_summary(report_json, generated_at=generated_at)
    report_summary["generated_by"] = generation_actor_label
    report_summary["generated_by_user_id"] = generation_actor.get("user_id")
    report_summary["generated_by_email"] = generation_actor.get("email")
    report_summary["generated_actor"] = generation_actor
    report_summary["review_type"] = origin["review_type"]
    report_summary["trigger_source"] = origin["trigger_source"]
    report_summary["schedule_id"] = str(origin["schedule_id"]) if origin["schedule_id"] else None
    report_summary["schedule_run_id"] = str(origin["schedule_run_id"]) if origin["schedule_run_id"] else None
    report_summary["draft_generated_at"] = _iso_datetime(generated_at)
    report_summary["is_e_signed"] = False
    report_summary["is_locked"] = False
    report_summary["report_version"] = workflow_config.report_version

    existing_drafts_result = await db.execute(
        select(AuditReviewReport).where(
            AuditReviewReport.job_id == job.job_id,
            AuditReviewReport.report_status == AUDIT_REVIEW_REPORT_STATUS_DRAFT,
        )
    )
    for existing_draft in existing_drafts_result.scalars().all():
        superseded_summary = dict(existing_draft.report_summary_json or {})
        superseded_summary["status"] = AUDIT_REVIEW_REPORT_STATUS_SUPERSEDED
        superseded_summary["approval_status"] = AUDIT_REVIEW_REPORT_STATUS_SUPERSEDED
        superseded_summary["superseded_at"] = _iso_datetime(generated_at)
        existing_draft.report_status = AUDIT_REVIEW_REPORT_STATUS_SUPERSEDED
        existing_draft.report_summary_json = superseded_summary
        existing_draft.modified_by = generation_actor_label
        existing_draft.modified_dt = generated_at

    report = AuditReviewReport(
        job_id=job.job_id,
        asset_id=job.asset_id,
        report_status=AUDIT_REVIEW_REPORT_STATUS_DRAFT,
        report_summary_json=report_summary,
        report_payload_json=report_json,
        report_markdown=report_markdown,
        file_path=None,
        review_type=origin["review_type"],
        trigger_source=origin["trigger_source"],
        schedule_id=origin["schedule_id"],
        schedule_run_id=origin["schedule_run_id"],
        workflow_metadata_json=workflow_metadata,
        is_e_signed=False,
        is_locked=False,
        report_version=workflow_config.report_version,
        created_by=generation_actor_label,
        created_dt=generated_at,
        modified_by=generation_actor_label,
        modified_dt=generated_at,
    )
    db.add(report)

    job.status = AUDIT_REVIEW_STATUS_REPORT_DRAFTED
    job.report_summary_json = report_summary
    job.error_message = None
    job.completed_at = generated_at
    job.modified_dt = generated_at
    job.modified_by = generation_actor_label
    await db.commit()

    return _build_generate_response(report)


async def get_audit_review_report(
    db: AsyncSession,
    report_id: uuid.UUID,
) -> AuditReviewReportDetailResponse:
    report = await _require_report(db, report_id)
    return _build_detail_response(report)


async def submit_audit_review_report_for_review(
    db: AsyncSession,
    report_id: uuid.UUID,
    payload: AuditReviewReportSubmitReviewRequest,
    *,
    current_user: CurrentUser | None = None,
) -> AuditReviewReportListItem:
    report = await _require_report(db, report_id)
    if report.report_status not in {
        AUDIT_REVIEW_REPORT_STATUS_DRAFT,
        AUDIT_REVIEW_REPORT_STATUS_CHANGES_REQUESTED,
    }:
        raise AuditReviewValidationError(
            "Only DRAFT or CHANGES_REQUESTED audit review reports can be submitted for QA review.",
            data={"report_id": str(report.report_id), "status": report.report_status},
        )

    job = await _require_job(db, report.job_id)
    submitted_at = _utc_now()
    old_status = report.report_status
    is_resubmission = old_status == AUDIT_REVIEW_REPORT_STATUS_CHANGES_REQUESTED
    actor = _authenticated_actor(current_user, "report resubmission" if is_resubmission else "report submission")
    submitted_by = _actor_label(actor)
    _ensure_report_workflow_metadata(report, job, fallback_actor=actor, fallback_at=submitted_at)
    decision_entry = {
        "action": "RESUBMITTED_FOR_REVIEW" if is_resubmission else "SUBMITTED_FOR_REVIEW",
        **_actor_decision_fields(actor),
        "submitted_by": submitted_by,
        "submitted_by_user_id": actor.get("user_id"),
        "submitted_by_email": actor.get("email"),
        "submitted_dt": _iso_datetime(submitted_at),
        "submission_notes": payload.submission_notes,
        "previous_status": old_status,
    }
    decision = _append_approval_history(report.approval_decision_json, decision_entry)
    decision["submission"] = decision_entry
    decision.pop("decision", None)
    workflow_metadata = update_submission_metadata(
        report.workflow_metadata_json,
        submitted_actor=actor,
        submitted_at=submitted_at,
        submission_notes=payload.submission_notes,
    )
    workflow_metadata.pop("review", None)
    workflow_metadata.pop("decision", None)
    workflow_metadata["e_signature"] = {
        "is_e_signed": False,
        "e_signed_at": None,
        "e_signed_by": None,
        "signature_meaning": None,
        "authentication_method": None,
        "signature_status": "NOT_SIGNED",
    }
    workflow_metadata["lock"] = {
        "is_locked": False,
        "locked_at": None,
        "locked_by": None,
    }

    report.report_status = AUDIT_REVIEW_REPORT_STATUS_UNDER_REVIEW
    report.submitted_by = submitted_by
    report.submitted_dt = submitted_at
    report.reviewed_by = None
    report.reviewed_dt = None
    report.reviewer_comments = None
    report.approval_decision_json = decision
    report.workflow_metadata_json = workflow_metadata
    report.is_e_signed = False
    report.e_signed_at = None
    report.e_signed_by_user_id = None
    report.is_locked = False
    report.locked_at = None
    report.locked_by_user_id = None
    report.modified_by = submitted_by
    report.modified_dt = submitted_at
    _set_report_summary_status(report, AUDIT_REVIEW_REPORT_STATUS_UNDER_REVIEW, submitted_at)
    await _sync_job_report_summary_if_latest(db, job, report)
    await record_audit_event(
        db,
        table_name="audit_review_report",
        operation_type="UPDATE",
        record_pk={"report_id": str(report.report_id)},
        old_data={"report_status": old_status},
        new_data={
            "action": "RESUBMITTED_FOR_REVIEW" if is_resubmission else "SUBMITTED_FOR_REVIEW",
            "report_status": AUDIT_REVIEW_REPORT_STATUS_UNDER_REVIEW,
            **_actor_decision_fields(actor),
            "comments": payload.submission_notes,
        },
        changed_by=_actor_audit_id(actor),
    )
    await db.commit()

    return _build_list_item(report)


async def approve_audit_review_report(
    db: AsyncSession,
    report_id: uuid.UUID,
    payload: AuditReviewReportReviewDecisionRequest,
    *,
    current_user: CurrentUser | None = None,
) -> AuditReviewReportListItem:
    report = await _require_report(db, report_id)
    if report.report_status != AUDIT_REVIEW_REPORT_STATUS_UNDER_REVIEW:
        raise AuditReviewValidationError(
            "Only UNDER_REVIEW audit review reports can be approved.",
            data={"report_id": str(report.report_id), "status": report.report_status},
        )

    job = await _require_job(db, report.job_id)
    reviewed_at = _utc_now()
    actor = _authenticated_actor(current_user, "report approval")
    reviewed_by = _actor_label(actor)
    _ensure_report_workflow_metadata(report, job, fallback_actor=actor, fallback_at=reviewed_at)
    workflow_config = get_audit_review_workflow_config()
    if payload.e_signature is None:
        raise AuditReviewValidationError(
            "Electronic signature confirmation is required before approving the audit review report.",
            data={"field": "e_signature"},
        )
    if not payload.e_signature.confirmed:
        raise AuditReviewValidationError(
            "Electronic signature acknowledgement is required before approving the audit review report.",
            data={"field": "e_signature.confirmed"},
        )
    await _verify_e_signature_credentials(
        db,
        current_user,
        payload.e_signature.user_email,
        payload.e_signature.current_password,
    )
    signature_meaning = payload.e_signature.signature_meaning
    signature_record = _build_e_signature_record(
        actor=actor,
        signed_at=reviewed_at,
        signature_meaning=signature_meaning,
        reviewer_comments=payload.reviewer_comments,
        report=report,
    )
    actor_user_id = actor_user_uuid(actor)
    old_status = report.report_status
    decision_entry = {
        "action": "APPROVED",
        "decision_status": AUDIT_REVIEW_REPORT_STATUS_APPROVED,
        **_actor_decision_fields(actor),
        "reviewed_by": reviewed_by,
        "approved_by": reviewed_by,
        "approved_by_user_id": actor.get("user_id"),
        "approved_by_email": actor.get("email"),
        "reviewed_dt": _iso_datetime(reviewed_at),
        "approved_dt": _iso_datetime(reviewed_at),
        "decision_at": _iso_datetime(reviewed_at),
        "reviewer_comments": payload.reviewer_comments,
        "e_signature": {
            "is_e_signed": True,
            "e_signed_at": _iso_datetime(reviewed_at),
            "e_signed_by_user_id": actor.get("user_id"),
            "e_signed_by_name": reviewed_by,
            "e_signed_by_email": actor.get("email"),
            "e_signed_by_roles": actor.get("roles") or [],
            "signature_meaning": signature_meaning,
            "authentication_method": signature_record["authentication_method"],
            "signature_status": "SIGNED",
            "signature_records": [signature_record],
        },
        "lock": {
            "is_locked": True,
            "locked_at": _iso_datetime(reviewed_at),
            "locked_by_user_id": actor.get("user_id"),
            "locked_by_name": reviewed_by,
            "locked_by_email": actor.get("email"),
        },
    }
    decision = _append_approval_history(report.approval_decision_json, decision_entry)
    decision["decision"] = decision_entry
    workflow_metadata = update_decision_metadata(
        report.workflow_metadata_json,
        decision_status=AUDIT_REVIEW_REPORT_STATUS_APPROVED,
        decision_actor=actor,
        decision_at=reviewed_at,
        decision_comments=payload.reviewer_comments,
        e_signed=True,
        locked=True,
    )
    workflow_metadata["e_signature"].update(
        {
            "signature_meaning": signature_meaning,
            "authentication_method": signature_record["authentication_method"],
            "signature_records": [signature_record],
        }
    )
    workflow_metadata["signature_manifestation"] = {
        "template_name": "Audit Review Final QA Signature Page",
        "location": "END",
        "generated_from": "approval_workflow",
        "signature_count": 1,
    }

    report.report_status = AUDIT_REVIEW_REPORT_STATUS_APPROVED
    report.reviewed_by = reviewed_by
    report.reviewed_dt = reviewed_at
    report.reviewer_comments = payload.reviewer_comments
    report.approval_decision_json = decision
    report.workflow_metadata_json = workflow_metadata
    report.is_e_signed = True
    report.e_signed_at = reviewed_at
    report.e_signed_by_user_id = actor_user_id
    report.is_locked = True
    report.locked_at = reviewed_at
    report.locked_by_user_id = actor_user_id
    report.report_version = report.report_version or workflow_config.report_version
    report.modified_by = reviewed_by
    report.modified_dt = reviewed_at
    _set_report_summary_status(report, AUDIT_REVIEW_REPORT_STATUS_APPROVED, reviewed_at)
    await _sync_job_report_summary_if_latest(db, job, report)
    await record_audit_event(
        db,
        table_name="audit_review_report",
        operation_type="UPDATE",
        record_pk={"report_id": str(report.report_id)},
        old_data={"report_status": old_status},
        new_data={
            "action": "APPROVED",
            "report_status": AUDIT_REVIEW_REPORT_STATUS_APPROVED,
            **_actor_decision_fields(actor),
            "comments": payload.reviewer_comments,
        },
        changed_by=_actor_audit_id(actor),
    )
    await db.commit()

    return _build_list_item(report)


async def reject_audit_review_report(
    db: AsyncSession,
    report_id: uuid.UUID,
    payload: AuditReviewReportReviewDecisionRequest,
    *,
    current_user: CurrentUser | None = None,
) -> AuditReviewReportListItem:
    report = await _require_report(db, report_id)
    if report.report_status != AUDIT_REVIEW_REPORT_STATUS_UNDER_REVIEW:
        raise AuditReviewValidationError(
            "Only UNDER_REVIEW audit review reports can be rejected.",
            data={"report_id": str(report.report_id), "status": report.report_status},
        )

    job = await _require_job(db, report.job_id)
    reviewed_at = _utc_now()
    actor = _authenticated_actor(current_user, "report rejection")
    reviewed_by = _actor_label(actor)
    _ensure_report_workflow_metadata(report, job, fallback_actor=actor, fallback_at=reviewed_at)
    old_status = report.report_status
    decision_entry = {
        "action": "REJECTED",
        "decision_status": AUDIT_REVIEW_REPORT_STATUS_REJECTED,
        **_actor_decision_fields(actor),
        "reviewed_by": reviewed_by,
        "rejected_by": reviewed_by,
        "rejected_by_user_id": actor.get("user_id"),
        "rejected_by_email": actor.get("email"),
        "reviewed_dt": _iso_datetime(reviewed_at),
        "rejected_dt": _iso_datetime(reviewed_at),
        "decision_at": _iso_datetime(reviewed_at),
        "reviewer_comments": payload.reviewer_comments,
    }
    decision = _append_approval_history(report.approval_decision_json, decision_entry)
    decision["decision"] = decision_entry
    workflow_metadata = update_decision_metadata(
        report.workflow_metadata_json,
        decision_status=AUDIT_REVIEW_REPORT_STATUS_REJECTED,
        decision_actor=actor,
        decision_at=reviewed_at,
        decision_comments=payload.reviewer_comments,
        e_signed=False,
        locked=False,
    )

    report.report_status = AUDIT_REVIEW_REPORT_STATUS_REJECTED
    report.reviewed_by = reviewed_by
    report.reviewed_dt = reviewed_at
    report.reviewer_comments = payload.reviewer_comments
    report.approval_decision_json = decision
    report.workflow_metadata_json = workflow_metadata
    report.is_e_signed = False
    report.e_signed_at = None
    report.e_signed_by_user_id = None
    report.is_locked = False
    report.locked_at = None
    report.locked_by_user_id = None
    report.modified_by = reviewed_by
    report.modified_dt = reviewed_at
    _set_report_summary_status(report, AUDIT_REVIEW_REPORT_STATUS_REJECTED, reviewed_at)
    await _sync_job_report_summary_if_latest(db, job, report)
    await record_audit_event(
        db,
        table_name="audit_review_report",
        operation_type="UPDATE",
        record_pk={"report_id": str(report.report_id)},
        old_data={"report_status": old_status},
        new_data={
            "action": "REJECTED",
            "report_status": AUDIT_REVIEW_REPORT_STATUS_REJECTED,
            **_actor_decision_fields(actor),
            "comments": payload.reviewer_comments,
        },
        changed_by=_actor_audit_id(actor),
    )
    await db.commit()

    return _build_list_item(report)


async def request_changes_audit_review_report(
    db: AsyncSession,
    report_id: uuid.UUID,
    payload: AuditReviewReportReviewDecisionRequest,
    *,
    current_user: CurrentUser | None = None,
) -> AuditReviewReportListItem:
    report = await _require_report(db, report_id)
    if report.report_status != AUDIT_REVIEW_REPORT_STATUS_UNDER_REVIEW:
        raise AuditReviewValidationError(
            "Only UNDER_REVIEW audit review reports can have changes requested.",
            data={"report_id": str(report.report_id), "status": report.report_status},
        )

    job = await _require_job(db, report.job_id)
    reviewed_at = _utc_now()
    actor = _authenticated_actor(current_user, "change request")
    reviewed_by = _actor_label(actor)
    _ensure_report_workflow_metadata(report, job, fallback_actor=actor, fallback_at=reviewed_at)
    old_status = report.report_status
    decision_entry = {
        "action": "CHANGES_REQUESTED",
        "decision_status": AUDIT_REVIEW_REPORT_STATUS_CHANGES_REQUESTED,
        **_actor_decision_fields(actor),
        "reviewed_by": reviewed_by,
        "requested_changes_by": reviewed_by,
        "requested_changes_by_user_id": actor.get("user_id"),
        "requested_changes_by_email": actor.get("email"),
        "reviewed_dt": _iso_datetime(reviewed_at),
        "requested_changes_dt": _iso_datetime(reviewed_at),
        "decision_at": _iso_datetime(reviewed_at),
        "reviewer_comments": payload.reviewer_comments,
    }
    decision = _append_approval_history(report.approval_decision_json, decision_entry)
    decision["decision"] = decision_entry
    workflow_metadata = update_decision_metadata(
        report.workflow_metadata_json,
        decision_status=AUDIT_REVIEW_REPORT_STATUS_CHANGES_REQUESTED,
        decision_actor=actor,
        decision_at=reviewed_at,
        decision_comments=payload.reviewer_comments,
        e_signed=False,
        locked=False,
    )

    report.report_status = AUDIT_REVIEW_REPORT_STATUS_CHANGES_REQUESTED
    report.reviewed_by = reviewed_by
    report.reviewed_dt = reviewed_at
    report.reviewer_comments = payload.reviewer_comments
    report.approval_decision_json = decision
    report.workflow_metadata_json = workflow_metadata
    report.is_e_signed = False
    report.e_signed_at = None
    report.e_signed_by_user_id = None
    report.is_locked = False
    report.locked_at = None
    report.locked_by_user_id = None
    report.modified_by = reviewed_by
    report.modified_dt = reviewed_at
    _set_report_summary_status(report, AUDIT_REVIEW_REPORT_STATUS_CHANGES_REQUESTED, reviewed_at)
    await _sync_job_report_summary_if_latest(db, job, report)
    await record_audit_event(
        db,
        table_name="audit_review_report",
        operation_type="UPDATE",
        record_pk={"report_id": str(report.report_id)},
        old_data={"report_status": old_status},
        new_data={
            "action": "CHANGES_REQUESTED",
            "report_status": AUDIT_REVIEW_REPORT_STATUS_CHANGES_REQUESTED,
            **_actor_decision_fields(actor),
            "comments": payload.reviewer_comments,
        },
        changed_by=_actor_audit_id(actor),
    )
    await db.commit()

    return _build_list_item(report)


async def list_audit_review_reports_for_asset(
    db: AsyncSession,
    asset_id: uuid.UUID,
) -> list[AuditReviewReportListItem]:
    await _require_asset(db, asset_id)
    result = await db.execute(
        select(AuditReviewReport)
        .where(AuditReviewReport.asset_id == asset_id)
        .order_by(AuditReviewReport.created_dt.desc(), AuditReviewReport.report_id.desc())
    )
    return [_build_list_item(report) for report in result.scalars().all()]
