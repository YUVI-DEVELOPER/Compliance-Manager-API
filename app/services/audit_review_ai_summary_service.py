from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.audit_review_finding import AuditReviewFinding
from app.models.audit_review_job import AuditReviewJob
from app.models.audit_review_report import AuditReviewReport
from app.models.audit_review_score import AuditReviewScore
from app.models.audit_trail_record import AuditTrailRecord
from app.schemas.auth_schema import CurrentUser
from app.schemas.audit_review_schema import (
    AUDIT_REVIEW_AI_SUMMARY_STATUS_FAILED,
    AUDIT_REVIEW_AI_SUMMARY_STATUS_GENERATED,
    AUDIT_REVIEW_AI_SUMMARY_STATUS_GENERATING,
    AUDIT_REVIEW_AI_SUMMARY_STATUS_NOT_REQUESTED,
    AUDIT_REVIEW_REPORT_STATUS_APPROVED,
    AUDIT_REVIEW_REPORT_STATUS_CHANGES_REQUESTED,
    AUDIT_REVIEW_REPORT_STATUS_DRAFT,
    AUDIT_REVIEW_REPORT_STATUS_REJECTED,
    AUDIT_REVIEW_REPORT_STATUS_SUPERSEDED,
    AUDIT_REVIEW_REPORT_STATUS_UNDER_REVIEW,
    AuditReviewAiSummaryGenerateRequest,
    AuditReviewAiSummaryResponse,
)
from app.services.audit_review_scoring_service import OVERALL_CHECK_CODE
from app.services.audit_review_service import (
    AuditReviewNotFoundError,
    AuditReviewServiceError,
    AuditReviewValidationError,
)
from app.services.urs_generation_service import (
    _build_llm_headers,
    _extract_chat_completion_output_text,
)


AUDIT_REVIEW_AI_PROMPT_VERSION = "audit-review-ai-summary-capa-v1"
TOP_FINDINGS_LIMIT = 15
MAX_TEXT_FIELD_CHARS = 1200
ALLOWED_REPORT_STATUSES = {
    AUDIT_REVIEW_REPORT_STATUS_DRAFT,
    AUDIT_REVIEW_REPORT_STATUS_UNDER_REVIEW,
    AUDIT_REVIEW_REPORT_STATUS_APPROVED,
    AUDIT_REVIEW_REPORT_STATUS_REJECTED,
    AUDIT_REVIEW_REPORT_STATUS_CHANGES_REQUESTED,
    AUDIT_REVIEW_REPORT_STATUS_SUPERSEDED,
}
FORBIDDEN_KEY_PARTS = (
    "raw_payload",
    "authorization",
    "bearer",
    "credential",
    "password",
    "secret",
    "session",
    "token",
    "api_key",
)
REQUIRED_LIMITATIONS = [
    "AI did not review raw audit payload.",
    "Deterministic checks and human QA review remain authoritative.",
]
AI_DISCLAIMER = (
    "AI-generated narrative for reviewer support only. Deterministic checks, score, findings, "
    "and QA approval remain authoritative."
)


class AuditReviewAiUnavailableError(AuditReviewServiceError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=503, data=data)


class AuditReviewAiGenerationError(AuditReviewServiceError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=502, data=data)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _strip_optional(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _safe_int(value: Any, fallback: int | None = 0) -> int | None:
    if value is None:
        return fallback
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _actor_label(current_user: CurrentUser | None) -> str:
    if current_user is None:
        raise AuditReviewValidationError("Authenticated user is required for AI summary generation.")
    full_name = _strip_optional(current_user.full_name)
    email = _strip_optional(current_user.email)
    actor = full_name or email
    if not actor:
        raise AuditReviewValidationError("Unable to resolve authenticated actor for AI summary generation.")
    return actor


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _to_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _truncate_text(value: Any, max_length: int = MAX_TEXT_FIELD_CHARS) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    normalized = re.sub(r"\s+", " ", normalized)
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3].rstrip()}..."


def _is_forbidden_key(key: Any) -> bool:
    lowered = str(key).strip().lower()
    return any(part in lowered for part in FORBIDDEN_KEY_PARTS)


def _sanitize_value(value: Any, *, max_depth: int = 6) -> Any:
    if max_depth <= 0:
        return None
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            if _is_forbidden_key(key):
                continue
            sanitized[str(key)] = _sanitize_value(child, max_depth=max_depth - 1)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item, max_depth=max_depth - 1) for item in value[:100]]
    if isinstance(value, tuple):
        return [_sanitize_value(item, max_depth=max_depth - 1) for item in value[:100]]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return _iso_datetime(value)
    if isinstance(value, str):
        return _truncate_text(value, max_length=MAX_TEXT_FIELD_CHARS)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _truncate_text(value, max_length=MAX_TEXT_FIELD_CHARS)


def _assert_sanitized_payload(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=True, default=str).lower()
    forbidden_terms = (
        "raw_payload_json",
        "authorization",
        "bearer ",
        "sessionid",
        "session_id",
        "password",
        "api_key",
        "secret",
    )
    if any(term in serialized for term in forbidden_terms):
        raise AuditReviewValidationError("AI summary input failed safety validation.")


def _safe_error_message(value: Any) -> str:
    settings = get_settings()
    text = str(value or "AI summary generation failed.").strip()
    api_key = _strip_optional(settings.LLM_API_KEY)
    if api_key:
        text = text.replace(api_key, "[redacted]")
    text = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text, flags=re.IGNORECASE)
    text = re.sub(r"(api[_-]?key|token|password|secret|session)[=:]\S+", r"\1=[redacted]", text, flags=re.IGNORECASE)
    return text[:1000] or "AI summary generation failed."


def _extract_json_payload(raw_text: str) -> dict[str, Any] | None:
    stripped = raw_text.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _configured_model_name() -> str | None:
    return _strip_optional(get_settings().LLM_MODEL)


def _is_ai_configured() -> bool:
    settings = get_settings()
    return bool(settings.LLM_ENABLED and _strip_optional(settings.LLM_API_KEY) and _configured_model_name())


async def _require_report(db: AsyncSession, report_id: uuid.UUID) -> AuditReviewReport:
    result = await db.execute(
        select(AuditReviewReport)
        .options(
            selectinload(AuditReviewReport.asset),
            selectinload(AuditReviewReport.job).selectinload(AuditReviewJob.asset),
        )
        .where(AuditReviewReport.report_id == report_id)
    )
    report = result.scalars().first()
    if report is None:
        raise AuditReviewNotFoundError("Audit review report not found")
    return report


async def _load_scores(db: AsyncSession, job_id: uuid.UUID) -> list[AuditReviewScore]:
    result = await db.execute(
        select(AuditReviewScore)
        .where(AuditReviewScore.job_id == job_id)
        .order_by(AuditReviewScore.sort_order.asc(), AuditReviewScore.check_code.asc())
    )
    return list(result.scalars().all())


async def _load_top_findings(db: AsyncSession, job_id: uuid.UUID) -> list[AuditReviewFinding]:
    result = await db.execute(
        select(AuditReviewFinding)
        .where(AuditReviewFinding.job_id == job_id)
        .order_by(
            AuditReviewFinding.severity.asc().nullslast(),
            AuditReviewFinding.created_dt.asc(),
            AuditReviewFinding.finding_id.asc(),
        )
        .limit(TOP_FINDINGS_LIMIT)
    )
    return list(result.scalars().all())


async def _count_records(db: AsyncSession, job_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count(AuditTrailRecord.record_id)).where(AuditTrailRecord.job_id == job_id)
    )
    return int(result.scalar_one() or 0)


def _score_summary_from_scores(scores: list[AuditReviewScore]) -> list[dict[str, Any]]:
    return [
        {
            "check_code": score.check_code,
            "check_name": score.check_name,
            "finding_count": score.finding_count,
            "penalty_points": score.applied_penalty,
            "status": score.score_status,
        }
        for score in scores
        if score.score_scope == "CHECKPOINT"
    ]


def _overall_from_report(report: AuditReviewReport, scores: list[AuditReviewScore]) -> tuple[int | None, str | None]:
    summary = report.report_summary_json or {}
    report_json = report.report_payload_json or {}
    execution = report_json.get("execution_summary") if isinstance(report_json.get("execution_summary"), dict) else {}
    overall_row = next(
        (score for score in scores if score.check_code == OVERALL_CHECK_CODE and score.score_scope == "OVERALL"),
        None,
    )
    overall_score = (
        _safe_int(summary.get("overall_score"), None)
        if summary.get("overall_score") is not None
        else _safe_int(execution.get("overall_score"), None)
    )
    if overall_score is None and overall_row is not None:
        overall_score = overall_row.overall_score
    rating = _strip_optional(summary.get("rating")) or _strip_optional(execution.get("rating"))
    if rating is None and overall_row is not None:
        rating = overall_row.rating
    return overall_score, rating


def _finding_counts(report: AuditReviewReport) -> dict[str, int]:
    summary = report.report_summary_json or {}
    report_json = report.report_payload_json or {}
    source = summary.get("finding_summary")
    if not isinstance(source, dict):
        source = report_json.get("finding_summary")
    if not isinstance(source, dict):
        return {"critical": 0, "high": 0, "medium": 0, "low": 0}
    return {
        "critical": int(source.get("critical") or source.get("CRITICAL") or 0),
        "high": int(source.get("high") or source.get("HIGH") or 0),
        "medium": int(source.get("medium") or source.get("MEDIUM") or 0),
        "low": int(source.get("low") or source.get("LOW") or 0),
    }


def _top_findings_from_report(report: AuditReviewReport, fallback_findings: list[AuditReviewFinding]) -> list[dict[str, Any]]:
    report_json = report.report_payload_json or {}
    key_findings = report_json.get("key_findings")
    if isinstance(key_findings, list):
        return [
            _sanitize_value(
                {
                    "check_code": item.get("check_code"),
                    "severity": item.get("severity"),
                    "finding_title": item.get("finding_title"),
                    "finding_summary": item.get("finding_summary"),
                    "source_record_count": item.get("source_record_count"),
                    "traceability": item.get("traceability"),
                }
            )
            for item in key_findings[:TOP_FINDINGS_LIMIT]
            if isinstance(item, dict)
        ]

    return [
        _sanitize_value(
            {
                "check_code": finding.check_code,
                "severity": finding.severity,
                "finding_title": finding.finding_title or finding.title or finding.check_name,
                "finding_summary": finding.finding_summary or finding.description,
                "source_record_count": finding.source_record_count,
            }
        )
        for finding in fallback_findings[:TOP_FINDINGS_LIMIT]
    ]


async def _build_sanitized_ai_input(
    db: AsyncSession,
    report: AuditReviewReport,
    payload: AuditReviewAiSummaryGenerateRequest,
) -> dict[str, Any]:
    job = report.job
    scores = await _load_scores(db, report.job_id)
    fallback_findings = await _load_top_findings(db, report.job_id)
    total_records = _safe_int((report.report_summary_json or {}).get("total_records_reviewed"), None)
    if total_records is None:
        report_json = report.report_payload_json or {}
        execution = report_json.get("execution_summary") if isinstance(report_json.get("execution_summary"), dict) else {}
        total_records = _safe_int(execution.get("total_records_reviewed"), None)
    if total_records is None:
        total_records = await _count_records(db, report.job_id)

    overall_score, rating = _overall_from_report(report, scores)
    report_json = report.report_payload_json or {}
    asset = report.asset or (job.asset if job is not None else None)
    asset_code = getattr(asset, "asset_id", None) or getattr(asset, "asset_code", None)
    check_summary = report_json.get("check_summary")
    recommendations = report_json.get("recommendations")

    safe_input = {
        "task": "audit_review_ai_summary_capa",
        "prompt_version": AUDIT_REVIEW_AI_PROMPT_VERSION,
        "summary_style": payload.summary_style,
        "include_capa_recommendations": payload.include_capa_recommendations,
        "asset": {
            "asset_id": str(report.asset_id),
            "asset_code": asset_code,
            "asset_name": getattr(asset, "asset_name", None),
        },
        "review_scope": {
            "report_id": str(report.report_id),
            "job_id": str(report.job_id),
            "audit_trail_type": job.audit_trail_type if job is not None else None,
            "review_start_dt": _iso_datetime(job.review_start_dt) if job is not None else None,
            "review_end_dt": _iso_datetime(job.review_end_dt) if job is not None else None,
            "veeva_instance_name": job.veeva_instance_name if job is not None else None,
            "veeva_app_name": job.veeva_app_name if job is not None else None,
            "trigger_mode": job.trigger_mode if job is not None else None,
        },
        "deterministic_source_of_truth": {
            "total_records_reviewed": total_records,
            "overall_score": overall_score,
            "rating": rating,
            "finding_counts_by_severity": _finding_counts(report),
            "score_breakdown": check_summary if isinstance(check_summary, list) else _score_summary_from_scores(scores),
            "top_findings": _top_findings_from_report(report, fallback_findings),
            "deterministic_recommendations": recommendations if isinstance(recommendations, list) else [],
        },
        "approval_metadata": {
            "report_status": report.report_status,
            "submitted_by": report.submitted_by,
            "submitted_dt": _iso_datetime(report.submitted_dt),
            "reviewed_by": report.reviewed_by,
            "reviewed_dt": _iso_datetime(report.reviewed_dt),
            "reviewer_comments": report.reviewer_comments,
        },
        "report_metadata": {
            "title": report_json.get("title") if isinstance(report_json, dict) else None,
            "created_dt": _iso_datetime(report.created_dt),
            "report_markdown_available": bool(_strip_optional(report.report_markdown)),
        },
    }
    sanitized = _sanitize_value(safe_input)
    _assert_sanitized_payload(sanitized)
    return sanitized


def _build_prompt_instructions(include_capa_recommendations: bool) -> str:
    capa_instruction = (
        "Return CAPA recommendation suggestions as optional reviewer wording."
        if include_capa_recommendations
        else "Return an empty capa_recommendations array because CAPA recommendations were not requested."
    )
    return (
        "You are generating a reviewer-support narrative only for a GxP Veeva audit trail periodic review.\n"
        "You must use only the provided structured data.\n"
        "Do not change the compliance score.\n"
        "Do not change the rating.\n"
        "Do not invent findings.\n"
        "Do not invent regulatory violations.\n"
        "Do not claim final QA approval.\n"
        "Do not say remediation was completed.\n"
        "Human QA/Compliance review remains authoritative.\n"
        "Deterministic checks, score rows, findings, and report approval metadata are the source of truth.\n"
        "CAPA recommendations are suggestions only and must be phrased as reviewer-consideration wording.\n"
        "If evidence is insufficient, state that reviewer confirmation is required.\n"
        f"{capa_instruction}\n"
        "Return strict JSON only, with this exact top-level shape: "
        "{"
        '"executive_summary":"string",'
        '"risk_statement":"string",'
        '"key_observations":["string"],'
        '"capa_recommendations":[{"title":"string","description":"string","suggested_owner":"string","suggested_due_days":30,"priority":"LOW / MEDIUM / HIGH / CRITICAL"}],'
        '"stakeholder_summary":"string",'
        '"reviewer_notes_suggestion":"string",'
        '"limitations":["string"]'
        "}."
    )


def _build_prompt_input(sanitized_input: dict[str, Any]) -> str:
    payload = {
        "required_disclaimer": AI_DISCLAIMER,
        "structured_audit_review_summary": sanitized_input,
    }
    return json.dumps(payload, ensure_ascii=True, indent=2, default=str)


async def _generate_ai_summary_payload(
    sanitized_input: dict[str, Any],
    *,
    include_capa_recommendations: bool,
) -> tuple[dict[str, Any], str]:
    settings = get_settings()
    if not _is_ai_configured():
        raise AuditReviewAiUnavailableError(
            "AI summary service is not configured.",
            data={"ai_configured": False},
        )

    api_key = _strip_optional(settings.LLM_API_KEY)
    model = _configured_model_name()
    if api_key is None or model is None:
        raise AuditReviewAiUnavailableError(
            "AI summary service is not configured.",
            data={"ai_configured": False},
        )

    request_id = str(uuid.uuid4())
    request_payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": _build_prompt_instructions(include_capa_recommendations),
            },
            {
                "role": "user",
                "content": _build_prompt_input(sanitized_input),
            },
        ],
        "temperature": 0,
    }
    max_attempts = max(1, settings.LLM_MAX_RETRIES + 1)
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
                    headers=_build_llm_headers(api_key, request_id),
                    json=request_payload,
                )
                response.raise_for_status()

            response_payload = response.json()
            if not isinstance(response_payload, dict):
                raise ValueError("AI provider returned an unexpected response payload")
            content = _extract_chat_completion_output_text(response_payload)
            ai_payload = _extract_json_payload(content)
            if ai_payload is None:
                raise ValueError("AI provider did not return parseable JSON")
            return ai_payload, model
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            await asyncio.sleep(min(1.5 * attempt, 3.0))

    raise AuditReviewAiGenerationError(
        "AI summary generation failed.",
        data={"ai_configured": True, "error_message": _safe_error_message(last_error)},
    )


def _as_string(value: Any, fallback: str) -> str:
    text = _truncate_text(value, max_length=4000)
    return text or fallback


def _as_string_list(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return fallback
    items: list[str] = []
    for item in value[:12]:
        text = _truncate_text(item, max_length=1200)
        if text:
            items.append(text)
    return items or fallback


def _normalize_priority(value: Any) -> str:
    normalized = _strip_optional(value)
    if normalized is None:
        return "MEDIUM"
    upper_value = normalized.upper()
    return upper_value if upper_value in {"LOW", "MEDIUM", "HIGH", "CRITICAL"} else "MEDIUM"


def _normalize_due_days(value: Any) -> int:
    numeric = _safe_int(value, 30)
    if numeric is None:
        return 30
    return max(1, min(numeric, 365))


def _normalize_capa_recommendations(value: Any, include_capa_recommendations: bool) -> list[dict[str, Any]]:
    if not include_capa_recommendations:
        return []
    if not isinstance(value, list):
        return []
    recommendations: list[dict[str, Any]] = []
    for item in value[:6]:
        if not isinstance(item, dict):
            continue
        title = _as_string(item.get("title"), "Reviewer confirmation action")
        description = _as_string(
            item.get("description"),
            "QA/Compliance should confirm whether a corrective or preventive action is required.",
        )
        recommendations.append(
            {
                "title": title,
                "description": description,
                "suggested_owner": _as_string(item.get("suggested_owner"), "QA / Compliance"),
                "suggested_due_days": _normalize_due_days(item.get("suggested_due_days")),
                "priority": _normalize_priority(item.get("priority")),
            }
        )
    return recommendations


def _normalize_ai_summary_json(
    ai_payload: dict[str, Any],
    *,
    include_capa_recommendations: bool,
) -> dict[str, Any]:
    limitations = _as_string_list(ai_payload.get("limitations"), [])
    for limitation in REQUIRED_LIMITATIONS:
        if limitation not in limitations:
            limitations.append(limitation)

    return {
        "executive_summary": _as_string(
            ai_payload.get("executive_summary"),
            "Reviewer confirmation is required because the AI narrative did not include an executive summary.",
        ),
        "risk_statement": _as_string(
            ai_payload.get("risk_statement"),
            "Risk interpretation should be confirmed by QA/Compliance using the deterministic score and findings.",
        ),
        "key_observations": _as_string_list(
            ai_payload.get("key_observations"),
            ["Reviewer should verify the deterministic checklist outputs before using this narrative."],
        ),
        "capa_recommendations": _normalize_capa_recommendations(
            ai_payload.get("capa_recommendations"),
            include_capa_recommendations,
        ),
        "stakeholder_summary": _as_string(
            ai_payload.get("stakeholder_summary"),
            "Stakeholder summary requires reviewer confirmation.",
        ),
        "reviewer_notes_suggestion": _as_string(
            ai_payload.get("reviewer_notes_suggestion"),
            "Confirm that deterministic findings, score, and approval metadata support the final reviewer note.",
        ),
        "limitations": limitations,
    }


def _markdown_bullet(value: str) -> str:
    text = value.replace("\r", " ").strip()
    return text or "Reviewer confirmation required."


def _build_ai_summary_markdown(summary_json: dict[str, Any]) -> str:
    lines = [
        "# AI-Assisted Executive Summary",
        "",
        f"**{AI_DISCLAIMER}**",
        "",
        "## Executive Summary",
        "",
        summary_json["executive_summary"],
        "",
        "## Risk Statement",
        "",
        summary_json["risk_statement"],
        "",
        "## Key Observations",
        "",
    ]
    lines.extend(f"- {_markdown_bullet(item)}" for item in summary_json.get("key_observations") or [])

    lines.extend(["", "## CAPA Recommendation Suggestions", ""])
    capa_recommendations = summary_json.get("capa_recommendations") or []
    if not capa_recommendations:
        lines.append("- No AI-assisted CAPA recommendation suggestions were requested or generated.")
    else:
        for recommendation in capa_recommendations:
            title = _markdown_bullet(str(recommendation.get("title") or "CAPA suggestion"))
            description = _markdown_bullet(str(recommendation.get("description") or "Reviewer confirmation required."))
            owner = _markdown_bullet(str(recommendation.get("suggested_owner") or "QA / Compliance"))
            due_days = recommendation.get("suggested_due_days") or 30
            priority = _markdown_bullet(str(recommendation.get("priority") or "MEDIUM"))
            lines.append(f"- **{title}** ({priority}, owner: {owner}, due: {due_days} days): {description}")

    lines.extend(
        [
            "",
            "## Stakeholder Summary",
            "",
            summary_json["stakeholder_summary"],
            "",
            "## Reviewer Notes Suggestion",
            "",
            summary_json["reviewer_notes_suggestion"],
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {_markdown_bullet(item)}" for item in summary_json.get("limitations") or REQUIRED_LIMITATIONS)
    return "\n".join(lines)


def _build_ai_summary_response(
    report: AuditReviewReport,
    *,
    ai_configured: bool = True,
    requested_by: str | None = None,
    summary_style: str | None = None,
    include_capa_recommendations: bool | None = None,
) -> AuditReviewAiSummaryResponse:
    overall_score, rating = _overall_from_report(report, [])
    return AuditReviewAiSummaryResponse(
        report_id=report.report_id,
        job_id=report.job_id,
        asset_id=report.asset_id,
        report_status=report.report_status,
        status=report.ai_generation_status or AUDIT_REVIEW_AI_SUMMARY_STATUS_NOT_REQUESTED,
        ai_configured=ai_configured,
        requested_by=requested_by or report.ai_generated_by,
        generated_by=report.ai_generated_by,
        generated_dt=report.ai_generated_dt,
        model_name=report.ai_model_name,
        summary_style=summary_style,
        include_capa_recommendations=include_capa_recommendations,
        overall_score=overall_score,
        rating=rating,
        ai_summary_json=report.ai_summary_json,
        ai_summary_markdown=report.ai_summary_markdown,
        error_message=report.ai_error_message,
    )


def _service_data(response: AuditReviewAiSummaryResponse) -> dict[str, Any]:
    return response.model_dump()


async def get_audit_review_ai_summary(
    db: AsyncSession,
    report_id: uuid.UUID,
) -> AuditReviewAiSummaryResponse:
    report = await _require_report(db, report_id)
    return _build_ai_summary_response(report, ai_configured=_is_ai_configured())


async def clear_audit_review_ai_summary(
    db: AsyncSession,
    report_id: uuid.UUID,
) -> AuditReviewAiSummaryResponse:
    report = await _require_report(db, report_id)
    if report.report_status not in ALLOWED_REPORT_STATUSES:
        raise AuditReviewValidationError(
            "AI summary can only be cleared for DRAFT, UNDER_REVIEW, APPROVED, REJECTED, or SUPERSEDED reports.",
            data={"report_id": str(report.report_id), "status": report.report_status},
        )

    report.ai_generation_status = AUDIT_REVIEW_AI_SUMMARY_STATUS_NOT_REQUESTED
    report.ai_summary_json = None
    report.ai_summary_markdown = None
    report.ai_generated_by = None
    report.ai_generated_dt = None
    report.ai_model_name = None
    report.ai_error_message = None
    await db.commit()
    await db.refresh(report)
    return _build_ai_summary_response(report, ai_configured=_is_ai_configured())


async def generate_audit_review_ai_summary(
    db: AsyncSession,
    report_id: uuid.UUID,
    payload: AuditReviewAiSummaryGenerateRequest,
    *,
    current_user: CurrentUser | None = None,
) -> AuditReviewAiSummaryResponse:
    report = await _require_report(db, report_id)
    if report.report_status not in ALLOWED_REPORT_STATUSES:
        raise AuditReviewValidationError(
            "AI summary can only be generated for DRAFT, UNDER_REVIEW, APPROVED, REJECTED, or SUPERSEDED reports.",
            data={"report_id": str(report.report_id), "status": report.report_status},
        )

    requested_by = _actor_label(current_user)

    report.ai_generation_status = AUDIT_REVIEW_AI_SUMMARY_STATUS_GENERATING
    report.ai_generated_by = requested_by
    report.ai_generated_dt = None
    report.ai_model_name = _configured_model_name()
    report.ai_error_message = None
    report.ai_summary_json = None
    report.ai_summary_markdown = None
    await db.commit()

    if not _is_ai_configured():
        report.ai_generation_status = AUDIT_REVIEW_AI_SUMMARY_STATUS_FAILED
        report.ai_error_message = "AI summary service is not configured."
        await db.commit()
        response = _build_ai_summary_response(
            report,
            ai_configured=False,
            requested_by=requested_by,
            summary_style=payload.summary_style,
            include_capa_recommendations=payload.include_capa_recommendations,
        )
        raise AuditReviewAiUnavailableError(
            "AI summary service is not configured.",
            data=_service_data(response),
        )

    try:
        sanitized_input = await _build_sanitized_ai_input(db, report, payload)
        ai_payload, model = await _generate_ai_summary_payload(
            sanitized_input,
            include_capa_recommendations=payload.include_capa_recommendations,
        )
        summary_json = _normalize_ai_summary_json(
            ai_payload,
            include_capa_recommendations=payload.include_capa_recommendations,
        )
        summary_markdown = _build_ai_summary_markdown(summary_json)
    except AuditReviewAiUnavailableError as exc:
        report.ai_generation_status = AUDIT_REVIEW_AI_SUMMARY_STATUS_FAILED
        report.ai_error_message = _safe_error_message(exc.message)
        report.ai_generated_dt = _utc_now()
        await db.commit()
        response = _build_ai_summary_response(
            report,
            ai_configured=False,
            requested_by=requested_by,
            summary_style=payload.summary_style,
            include_capa_recommendations=payload.include_capa_recommendations,
        )
        raise AuditReviewAiUnavailableError(exc.message, data=_service_data(response)) from exc
    except AuditReviewValidationError as exc:
        report.ai_generation_status = AUDIT_REVIEW_AI_SUMMARY_STATUS_FAILED
        report.ai_error_message = _safe_error_message(exc.message)
        report.ai_generated_dt = _utc_now()
        await db.commit()
        response = _build_ai_summary_response(
            report,
            ai_configured=True,
            requested_by=requested_by,
            summary_style=payload.summary_style,
            include_capa_recommendations=payload.include_capa_recommendations,
        )
        raise AuditReviewValidationError(exc.message, data=_service_data(response)) from exc
    except Exception as exc:
        report.ai_generation_status = AUDIT_REVIEW_AI_SUMMARY_STATUS_FAILED
        report.ai_error_message = _safe_error_message(exc)
        report.ai_generated_dt = _utc_now()
        await db.commit()
        response = _build_ai_summary_response(
            report,
            ai_configured=True,
            requested_by=requested_by,
            summary_style=payload.summary_style,
            include_capa_recommendations=payload.include_capa_recommendations,
        )
        raise AuditReviewAiGenerationError(
            "AI summary generation failed.",
            data=_service_data(response),
        ) from exc

    generated_at = _utc_now()
    report.ai_generation_status = AUDIT_REVIEW_AI_SUMMARY_STATUS_GENERATED
    report.ai_summary_json = summary_json
    report.ai_summary_markdown = summary_markdown
    report.ai_generated_by = requested_by
    report.ai_generated_dt = generated_at
    report.ai_model_name = model
    report.ai_error_message = None
    await db.commit()
    await db.refresh(report)

    response = _build_ai_summary_response(
        report,
        ai_configured=True,
        requested_by=requested_by,
        summary_style=payload.summary_style,
        include_capa_recommendations=payload.include_capa_recommendations,
    )
    return response
