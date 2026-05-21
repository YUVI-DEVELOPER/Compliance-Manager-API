import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


REVIEW_TYPE_ADHOC = "ADHOC"
REVIEW_TYPE_SCHEDULED = "SCHEDULED"
TRIGGER_SOURCE_MANUAL_USER = "MANUAL_USER"
TRIGGER_SOURCE_SYSTEM_SCHEDULER = "SYSTEM_SCHEDULER"
ACTOR_TYPE_USER = "USER"
ACTOR_TYPE_SYSTEM = "SYSTEM"
DECISION_STATUS_PENDING = "PENDING"
SIGNATURE_STATUS_SIGNED = "SIGNED"
SIGNATURE_STATUS_NOT_SIGNED = "NOT_SIGNED"
DEFAULT_SYSTEM_ACTOR = "audit-review-scheduler"


@dataclass(frozen=True)
class AuditReviewWorkflowConfig:
    signature_meaning: str = "Electronic approval of the audit review report"
    authentication_method: str = "Password re-entry during authenticated application session"
    report_version: str = "1.0"


def get_audit_review_workflow_config() -> AuditReviewWorkflowConfig:
    return AuditReviewWorkflowConfig()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def iso_datetime(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _safe_str(value)
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def uuid_or_none(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def uuid_str(value: Any) -> str | None:
    parsed = uuid_or_none(value)
    return str(parsed) if parsed is not None else _safe_str(value)


def normalize_actor_snapshot(
    actor: Any,
    *,
    fallback_actor_type: str | None = None,
    fallback_name: str | None = None,
) -> dict[str, Any]:
    source = _as_dict(actor)
    name = (
        _safe_str(source.get("name"))
        or _safe_str(source.get("display_name"))
        or _safe_str(source.get("full_name"))
        or _safe_str(source.get("email"))
        or _safe_str(fallback_name)
    )
    actor_type = _safe_str(source.get("actor_type")) or fallback_actor_type
    if actor_type:
        actor_type = actor_type.upper()
    elif source.get("user_id"):
        actor_type = ACTOR_TYPE_USER
    elif name:
        actor_type = ACTOR_TYPE_SYSTEM if name == DEFAULT_SYSTEM_ACTOR else ACTOR_TYPE_USER

    roles = source.get("roles")
    if not isinstance(roles, list):
        roles = source.get("actor_roles")
    permissions = source.get("permissions")
    if not isinstance(permissions, list):
        permissions = source.get("actor_permissions")

    return {
        "actor_type": actor_type,
        "user_id": uuid_str(source.get("user_id") or source.get("actor_user_id")),
        "name": name,
        "full_name": _safe_str(source.get("full_name")) or name,
        "email": _safe_str(source.get("email") or source.get("actor_email")),
        "roles": [str(item) for item in _as_list(roles)],
        "permissions": [str(item) for item in _as_list(permissions)],
    }


def actor_user_uuid(actor: Any) -> uuid.UUID | None:
    snapshot = normalize_actor_snapshot(actor)
    return uuid_or_none(snapshot.get("user_id"))


def actor_label(actor: Any) -> str | None:
    snapshot = normalize_actor_snapshot(actor)
    return _safe_str(snapshot.get("name")) or _safe_str(snapshot.get("email"))


def _actor_flat(prefix: str, actor: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{prefix}_actor_type": actor.get("actor_type"),
        f"{prefix}_user_id": actor.get("user_id"),
        f"{prefix}_name": actor.get("name"),
        f"{prefix}_email": actor.get("email"),
    }


def report_origin_from_job(job: Any) -> dict[str, Any]:
    input_snapshot = _as_dict(getattr(job, "input_snapshot_json", None))
    schedule_id = uuid_or_none(input_snapshot.get("schedule_id"))
    schedule_run_id = uuid_or_none(input_snapshot.get("schedule_run_id"))
    period_basis = _safe_str(getattr(job, "period_basis", None))
    trigger_mode = _safe_str(getattr(job, "trigger_mode", None))
    scheduled = (
        (period_basis or "").upper() == REVIEW_TYPE_SCHEDULED
        or (trigger_mode or "").upper().startswith(REVIEW_TYPE_SCHEDULED)
        or schedule_id is not None
        or schedule_run_id is not None
    )
    return {
        "review_type": REVIEW_TYPE_SCHEDULED if scheduled else REVIEW_TYPE_ADHOC,
        "trigger_source": TRIGGER_SOURCE_SYSTEM_SCHEDULER if scheduled else TRIGGER_SOURCE_MANUAL_USER,
        "schedule_id": schedule_id,
        "schedule_run_id": schedule_run_id,
    }


def _job_actor(job: Any, key: str) -> dict[str, Any]:
    container = _as_dict(getattr(job, "input_snapshot_json", None))
    if key == "extracted_actor":
        container = _as_dict(getattr(job, "extraction_summary_json", None))
    if key == "analyzed_actor":
        container = _as_dict(getattr(job, "analysis_summary_json", None))
    return _as_dict(container.get(key))


def build_initial_workflow_metadata(
    job: Any,
    *,
    draft_generated_actor: dict[str, Any],
    draft_generated_at: datetime,
    triggered_actor: dict[str, Any] | None = None,
    run_actor: dict[str, Any] | None = None,
    report_version: str | None = None,
) -> dict[str, Any]:
    origin = report_origin_from_job(job)
    input_actor = _job_actor(job, "requested_actor")
    extracted_actor = _job_actor(job, "extracted_actor")
    analyzed_actor = _job_actor(job, "analyzed_actor")
    is_scheduled = origin["review_type"] == REVIEW_TYPE_SCHEDULED
    fallback_actor_type = ACTOR_TYPE_SYSTEM if is_scheduled else ACTOR_TYPE_USER

    triggered = normalize_actor_snapshot(
        triggered_actor or input_actor or draft_generated_actor,
        fallback_actor_type=fallback_actor_type,
        fallback_name=DEFAULT_SYSTEM_ACTOR if is_scheduled else None,
    )
    run_by = normalize_actor_snapshot(
        run_actor or analyzed_actor or extracted_actor or input_actor or draft_generated_actor,
        fallback_actor_type=fallback_actor_type,
        fallback_name=DEFAULT_SYSTEM_ACTOR if is_scheduled else None,
    )
    draft_actor = normalize_actor_snapshot(
        draft_generated_actor,
        fallback_actor_type=fallback_actor_type,
        fallback_name=DEFAULT_SYSTEM_ACTOR if is_scheduled else None,
    )

    return {
        "schema_version": 1,
        "run_context": {
            "review_type": origin["review_type"],
            "trigger_source": origin["trigger_source"],
            "schedule_id": str(origin["schedule_id"]) if origin["schedule_id"] else None,
            "schedule_run_id": str(origin["schedule_run_id"]) if origin["schedule_run_id"] else None,
            "triggered_by": triggered,
            "run_by": run_by,
        },
        "draft_generation": {
            "draft_generated_by": draft_actor,
            "draft_generated_at": iso_datetime(draft_generated_at),
        },
        "submission": None,
        "review": None,
        "decision": {
            "decision_status": DECISION_STATUS_PENDING,
        },
        "e_signature": {
            "is_e_signed": False,
            "signature_status": SIGNATURE_STATUS_NOT_SIGNED,
        },
        "lock": {
            "is_locked": False,
        },
        "final_report": {
            "final_pdf_path": None,
            "final_pdf_hash": None,
            "report_version": report_version or get_audit_review_workflow_config().report_version,
        },
    }


def update_submission_metadata(
    existing: dict[str, Any] | None,
    *,
    submitted_actor: dict[str, Any],
    submitted_at: datetime,
    submission_notes: str | None,
) -> dict[str, Any]:
    metadata = dict(existing or {})
    metadata["submission"] = {
        "submitted_by": normalize_actor_snapshot(submitted_actor, fallback_actor_type=ACTOR_TYPE_USER),
        "submitted_at": iso_datetime(submitted_at),
        "submission_notes": submission_notes,
    }
    return metadata


def update_decision_metadata(
    existing: dict[str, Any] | None,
    *,
    decision_status: str,
    decision_actor: dict[str, Any],
    decision_at: datetime,
    decision_comments: str,
    e_signed: bool,
    locked: bool,
) -> dict[str, Any]:
    config = get_audit_review_workflow_config()
    metadata = dict(existing or {})
    actor = normalize_actor_snapshot(decision_actor, fallback_actor_type=ACTOR_TYPE_USER)
    metadata["review"] = {
        "reviewed_by": actor,
        "reviewed_at": iso_datetime(decision_at),
        "reviewer_comments": decision_comments,
    }
    metadata["decision"] = {
        "decision_status": decision_status,
        "decision_by": actor,
        "decision_at": iso_datetime(decision_at),
        "decision_comments": decision_comments,
    }
    metadata["e_signature"] = {
        "is_e_signed": e_signed,
        "e_signed_at": iso_datetime(decision_at) if e_signed else None,
        "e_signed_by": actor if e_signed else None,
        "signature_meaning": config.signature_meaning if e_signed else None,
        "authentication_method": config.authentication_method if e_signed else None,
        "signature_status": SIGNATURE_STATUS_SIGNED if e_signed else SIGNATURE_STATUS_NOT_SIGNED,
    }
    metadata["lock"] = {
        "is_locked": locked,
        "locked_at": iso_datetime(decision_at) if locked else None,
        "locked_by": actor if locked else None,
    }
    final_report = dict(_as_dict(metadata.get("final_report")))
    final_report["report_version"] = final_report.get("report_version") or config.report_version
    metadata["final_report"] = final_report
    return metadata


def update_final_pdf_metadata(
    existing: dict[str, Any] | None,
    *,
    final_pdf_path: str,
    final_pdf_hash: str,
    report_version: str | None = None,
) -> dict[str, Any]:
    metadata = dict(existing or {})
    final_report = dict(_as_dict(metadata.get("final_report")))
    final_report.update(
        {
            "final_pdf_path": final_pdf_path,
            "final_pdf_hash": final_pdf_hash,
            "report_version": report_version or final_report.get("report_version") or get_audit_review_workflow_config().report_version,
        }
    )
    metadata["final_report"] = final_report
    return metadata


def build_report_workflow_metadata(report: Any, job: Any | None = None) -> dict[str, Any]:
    stored = _as_dict(getattr(report, "workflow_metadata_json", None))
    run_context = _as_dict(stored.get("run_context"))
    draft_generation = _as_dict(stored.get("draft_generation"))
    submission = _as_dict(stored.get("submission"))
    review = _as_dict(stored.get("review"))
    decision = _as_dict(stored.get("decision"))
    e_signature = _as_dict(stored.get("e_signature"))
    lock = _as_dict(stored.get("lock"))
    final_report = _as_dict(stored.get("final_report"))
    approval_decision = _as_dict(getattr(report, "approval_decision_json", None))
    approval_submission = _as_dict(approval_decision.get("submission"))
    approval_decision_entry = _as_dict(approval_decision.get("decision"))
    report_json = _as_dict(getattr(report, "report_payload_json", None))
    report_workflow = _as_dict(report_json.get("workflow"))
    report_draft_generation = _as_dict(report_workflow.get("draft_generation"))

    origin = report_origin_from_job(job) if job is not None else {}
    review_type = _safe_str(getattr(report, "review_type", None)) or _safe_str(run_context.get("review_type")) or _safe_str(origin.get("review_type"))
    trigger_source = (
        _safe_str(getattr(report, "trigger_source", None))
        or _safe_str(run_context.get("trigger_source"))
        or _safe_str(origin.get("trigger_source"))
    )
    schedule_id = uuid_str(getattr(report, "schedule_id", None) or run_context.get("schedule_id") or origin.get("schedule_id"))
    schedule_run_id = uuid_str(
        getattr(report, "schedule_run_id", None) or run_context.get("schedule_run_id") or origin.get("schedule_run_id")
    )

    triggered_actor = normalize_actor_snapshot(run_context.get("triggered_by"), fallback_actor_type=None)
    run_actor = normalize_actor_snapshot(run_context.get("run_by"), fallback_actor_type=None)
    draft_actor = normalize_actor_snapshot(
        draft_generation.get("draft_generated_by")
        or report_draft_generation.get("actor")
        or report_draft_generation,
        fallback_actor_type=None,
    )
    submitted_actor = normalize_actor_snapshot(
        submission.get("submitted_by") or approval_submission.get("actor") or approval_submission,
        fallback_actor_type=ACTOR_TYPE_USER,
        fallback_name=getattr(report, "submitted_by", None),
    )
    reviewed_actor = normalize_actor_snapshot(
        review.get("reviewed_by") or approval_decision_entry.get("actor") or approval_decision_entry,
        fallback_actor_type=ACTOR_TYPE_USER,
        fallback_name=getattr(report, "reviewed_by", None),
    )
    decision_actor = normalize_actor_snapshot(
        decision.get("decision_by") or approval_decision_entry.get("actor") or approval_decision_entry,
        fallback_actor_type=ACTOR_TYPE_USER,
        fallback_name=getattr(report, "reviewed_by", None),
    )
    e_signed_actor = normalize_actor_snapshot(e_signature.get("e_signed_by") or decision_actor, fallback_actor_type=ACTOR_TYPE_USER)
    locked_actor = normalize_actor_snapshot(lock.get("locked_by") or decision_actor, fallback_actor_type=ACTOR_TYPE_USER)

    report_status = _safe_str(getattr(report, "report_status", None))
    if report_status in {"APPROVED", "REJECTED", "CHANGES_REQUESTED"}:
        decision_status = report_status
    else:
        decision_status = _safe_str(decision.get("decision_status")) or DECISION_STATUS_PENDING

    is_e_signed = bool(getattr(report, "is_e_signed", None) or e_signature.get("is_e_signed"))
    is_locked = bool(getattr(report, "is_locked", None) or lock.get("is_locked"))
    if not is_e_signed:
        e_signed_actor = normalize_actor_snapshot(None)
    if not is_locked:
        locked_actor = normalize_actor_snapshot(None)
    config = get_audit_review_workflow_config()

    metadata = {
        "review_type": review_type,
        "trigger_source": trigger_source,
        "schedule_id": schedule_id,
        "schedule_run_id": schedule_run_id,
        **_actor_flat("triggered_by", triggered_actor),
        **_actor_flat("run_by", run_actor),
        "run_by_roles": run_actor.get("roles") or [],
        **_actor_flat("draft_generated_by", draft_actor),
        "draft_generated_at": (
            _safe_str(draft_generation.get("draft_generated_at"))
            or _safe_str(report_draft_generation.get("generated_at"))
            or iso_datetime(getattr(report, "created_dt", None))
        ),
        **_actor_flat("submitted_by", submitted_actor),
        "submitted_at": iso_datetime(getattr(report, "submitted_dt", None)) or _safe_str(submission.get("submitted_at")) or _safe_str(approval_submission.get("submitted_dt")),
        "submission_notes": (
            _safe_str(submission.get("submission_notes"))
            or _safe_str(approval_submission.get("submission_notes"))
            or _safe_str(approval_decision.get("submission_notes"))
        ),
        **_actor_flat("reviewed_by", reviewed_actor),
        "reviewed_at": iso_datetime(getattr(report, "reviewed_dt", None)) or _safe_str(review.get("reviewed_at")) or _safe_str(approval_decision_entry.get("reviewed_dt")),
        "reviewer_comments": _safe_str(getattr(report, "reviewer_comments", None)) or _safe_str(review.get("reviewer_comments")),
        "decision_status": decision_status,
        **_actor_flat("decision_by", decision_actor),
        "decision_by_roles": decision_actor.get("roles") or [],
        "decision_by_permissions": decision_actor.get("permissions") or [],
        "decision_at": (
            _safe_str(decision.get("decision_at"))
            or iso_datetime(getattr(report, "reviewed_dt", None))
            or _safe_str(approval_decision_entry.get("approved_dt"))
            or _safe_str(approval_decision_entry.get("rejected_dt"))
            or _safe_str(approval_decision_entry.get("requested_changes_dt"))
            or _safe_str(approval_decision_entry.get("reviewed_dt"))
        ),
        "decision_comments": _safe_str(decision.get("decision_comments")) or _safe_str(getattr(report, "reviewer_comments", None)),
        "is_e_signed": is_e_signed,
        "e_signed_at": iso_datetime(getattr(report, "e_signed_at", None)) or _safe_str(e_signature.get("e_signed_at")),
        **_actor_flat("e_signed_by", e_signed_actor),
        "e_signed_by_roles": e_signed_actor.get("roles") or [],
        "signature_meaning": _safe_str(e_signature.get("signature_meaning")) or (config.signature_meaning if is_e_signed else None),
        "authentication_method": _safe_str(e_signature.get("authentication_method")) or (config.authentication_method if is_e_signed else None),
        "signature_status": _safe_str(e_signature.get("signature_status")) or (SIGNATURE_STATUS_SIGNED if is_e_signed else SIGNATURE_STATUS_NOT_SIGNED),
        "is_locked": is_locked,
        "locked_at": iso_datetime(getattr(report, "locked_at", None)) or _safe_str(lock.get("locked_at")),
        **_actor_flat("locked_by", locked_actor),
        "final_pdf_path": _safe_str(getattr(report, "final_pdf_path", None)) or _safe_str(final_report.get("final_pdf_path")),
        "final_pdf_hash": _safe_str(getattr(report, "final_pdf_hash", None)) or _safe_str(final_report.get("final_pdf_hash")),
        "report_version": _safe_str(getattr(report, "report_version", None)) or _safe_str(final_report.get("report_version")) or config.report_version,
    }
    return metadata
