from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Iterable

from sqlalchemy import Select, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.release_impact_questions import (
    ReleaseImpactQuestion,
    get_release_impact_question_map,
    get_release_impact_questions,
)
from app.models.asset import Asset
from app.models.asset_release import AssetRelease
from app.models.release_validation_ai_suggestion import ReleaseValidationAISuggestion
from app.models.release_validation_document_requirement import ReleaseValidationDocumentRequirement
from app.models.release_validation_impact_assessment import ReleaseValidationImpactAssessment
from app.models.release_validation_impact_response import ReleaseValidationImpactResponse
from app.models.release_validation_package import ReleaseValidationPackage
from app.schemas.release_impact_assessment_schema import (
    ImpactAssessmentAISuggestRequest,
    ImpactAssessmentAISuggestResponse,
    ImpactAssessmentAISuggestion,
    ImpactAssessmentCompleteResult,
    ImpactAssessmentDetail,
    ImpactAssessmentSaveResult,
    ImpactQuestionSchema,
    ImpactResponseInput,
    ImpactResponseSchema,
    ImpactValidationErrorSchema,
)
from app.services.llm_gateway import (
    LLMGatewayError,
    LLMGatewayUnavailableError,
    get_step2_llm_gateway,
)
from app.services.release_impact_scoring_service import (
    ImpactResponseForScoring,
    ImpactScoringResult,
    calculate_impact_assessment_score,
)


ASSESSMENT_STATUS_DRAFT = "DRAFT"
ASSESSMENT_STATUS_IN_PROGRESS = "IN_PROGRESS"
ASSESSMENT_STATUS_COMPLETED = "COMPLETED"
ASSESSMENT_STATUS_REOPENED = "REOPENED"

PACKAGE_STATUS_DRAFT = "DRAFT"
PACKAGE_STATUS_VALIDATION_SCOPE_DEFINED = "VALIDATION_SCOPE_DEFINED"
IMPACT_ASSESSMENT_STATUS_DRAFT = "DRAFT"
IMPACT_ASSESSMENT_STATUS_IN_PROGRESS = "IN_PROGRESS"
IMPACT_ASSESSMENT_STATUS_COMPLETED = "COMPLETED"
DOCUMENT_CHECKLIST_STATUS_NOT_GENERATED = "NOT_GENERATED"
DOCUMENT_CHECKLIST_STATUS_STALE = "STALE"
RELEASE_STATUS_IMPACT_ASSESSMENT_PENDING = "IMPACT_ASSESSMENT_PENDING"
RELEASE_STATUS_VALIDATION_SCOPE_DEFINED = "VALIDATION_SCOPE_DEFINED"
NEXT_STEP_IMPACT_ASSESSMENT = "IMPACT_ASSESSMENT"
NEXT_STEP_DOCUMENT_CHECKLIST = "DOCUMENT_CHECKLIST"
STEP2_AI_PROMPT_VERSION = "release-impact-assessment-step2-v1"
LOCKED_STATUSES = {"APPROVED", "RELEASED", "LOCKED", "REJECTED", "CANCELLED"}


class ImpactAssessmentServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data or {}


class ImpactAssessmentNotFoundError(ImpactAssessmentServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404)


class ImpactAssessmentValidationError(ImpactAssessmentServiceError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=400, data=data)


class ImpactAssessmentConflictError(ImpactAssessmentServiceError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=409, data=data)


class ImpactAssessmentAIUnavailableError(ImpactAssessmentServiceError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=503, data=data)


class ImpactAssessmentAIGenerationError(ImpactAssessmentServiceError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=502, data=data)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _strip_optional(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _actor_label(actor: str | None) -> str | None:
    return _strip_optional(actor)


def _question_schema(question: ReleaseImpactQuestion) -> ImpactQuestionSchema:
    return ImpactQuestionSchema(
        questionCode=question.question_code,
        category=question.category,
        questionText=question.question_text,
        weight=question.weight,
        critical=question.critical,
        mandatory=question.mandatory,
    )


def get_questions() -> list[ImpactQuestionSchema]:
    return [_question_schema(question) for question in get_release_impact_questions()]


def _assessment_query() -> Select[tuple[ReleaseValidationImpactAssessment]]:
    return select(ReleaseValidationImpactAssessment).options(
        selectinload(ReleaseValidationImpactAssessment.responses),
        selectinload(ReleaseValidationImpactAssessment.package)
        .selectinload(ReleaseValidationPackage.release)
        .selectinload(AssetRelease.asset),
    )


def _release_query() -> Select[tuple[AssetRelease]]:
    return select(AssetRelease).options(
        selectinload(AssetRelease.asset),
        selectinload(AssetRelease.validation_package)
        .selectinload(ReleaseValidationPackage.impact_assessment)
        .selectinload(ReleaseValidationImpactAssessment.responses),
    )


async def _get_release_with_package(db: AsyncSession, release_id: uuid.UUID) -> AssetRelease:
    result = await db.execute(_release_query().where(AssetRelease.release_id == release_id))
    release = result.scalars().first()
    if release is None:
        raise ImpactAssessmentNotFoundError("Release not found")
    if release.validation_package is None:
        raise ImpactAssessmentNotFoundError("Validation package not found for release")
    return release


async def _get_assessment(db: AsyncSession, assessment_id: uuid.UUID) -> ReleaseValidationImpactAssessment:
    result = await db.execute(
        _assessment_query().where(ReleaseValidationImpactAssessment.assessment_id == assessment_id)
    )
    assessment = result.scalars().first()
    if assessment is None:
        raise ImpactAssessmentNotFoundError("Impact assessment not found")
    return assessment


async def _get_assessment_by_package_id(
    db: AsyncSession,
    package_id: uuid.UUID,
) -> ReleaseValidationImpactAssessment | None:
    result = await db.execute(
        _assessment_query().where(ReleaseValidationImpactAssessment.package_id == package_id)
    )
    return result.scalars().first()


async def _package_has_active_document_requirements(db: AsyncSession, package_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(ReleaseValidationDocumentRequirement.requirement_id)
        .where(
            ReleaseValidationDocumentRequirement.package_id == package_id,
            ReleaseValidationDocumentRequirement.is_active.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _generate_assessment_no(db: AsyncSession, reference_dt: datetime) -> str:
    year = reference_dt.year
    prefix = f"VAL-IA-{year}-"
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
        {"lock_name": f"release_validation_impact_assessment:{year}"},
    )
    result = await db.execute(
        text(
            """
            SELECT COALESCE(MAX(CAST(SUBSTRING(assessment_no FROM :pattern) AS INTEGER)), 0)
            FROM public.release_validation_impact_assessment
            WHERE assessment_no LIKE :like_pattern
            """
        ),
        {
            "pattern": f"^{prefix}([0-9]+)$",
            "like_pattern": f"{prefix}%",
        },
    )
    latest_sequence = result.scalar_one_or_none() or 0
    return f"{prefix}{int(latest_sequence) + 1:04d}"


def _responses_for_scoring(
    responses: Iterable[ReleaseValidationImpactResponse],
) -> list[ImpactResponseForScoring]:
    return [
        ImpactResponseForScoring(
            question_code=response.question_code,
            answer=response.answer,
            rationale=response.rationale,
        )
        for response in responses
    ]


def _issue_schema(issue: Any) -> ImpactValidationErrorSchema:
    return ImpactValidationErrorSchema(
        questionCode=issue.question_code,
        field=issue.field,
        message=issue.message,
    )


def _response_schema(response: ReleaseValidationImpactResponse) -> ImpactResponseSchema:
    return ImpactResponseSchema(
        responseId=response.response_id,
        assessmentId=response.assessment_id,
        questionCode=response.question_code,
        category=response.category,
        questionText=response.question_text,
        answer=response.answer,
        weight=response.weight,
        critical=response.critical,
        mandatory=response.mandatory,
        score=response.score,
        rationale=response.rationale,
        evidenceReference=response.evidence_reference,
        answeredBy=response.answered_by,
        answeredAt=response.answered_at,
        createdAt=response.created_at,
        updatedAt=response.updated_at,
    )


def _response_order_key(response: ReleaseValidationImpactResponse) -> int:
    question_codes = [question.question_code for question in get_release_impact_questions()]
    try:
        return question_codes.index(response.question_code)
    except ValueError:
        return len(question_codes)


def _is_locked(package: ReleaseValidationPackage) -> bool:
    package_status = (package.package_status or "").upper()
    release_status = (package.release.release_status if package.release is not None else "").upper()
    return package_status in LOCKED_STATUSES or release_status in LOCKED_STATUSES


def _can_reopen(assessment: ReleaseValidationImpactAssessment) -> bool:
    return assessment.status == ASSESSMENT_STATUS_COMPLETED and not _is_locked(assessment.package)


def _next_step_for_assessment(assessment: ReleaseValidationImpactAssessment) -> str:
    if assessment.status == ASSESSMENT_STATUS_COMPLETED:
        return NEXT_STEP_DOCUMENT_CHECKLIST
    return NEXT_STEP_IMPACT_ASSESSMENT


def _ai_assistant_enabled() -> bool:
    return get_step2_llm_gateway().is_configured()


def _build_detail(assessment: ReleaseValidationImpactAssessment) -> ImpactAssessmentDetail:
    package = assessment.package
    release = package.release
    scoring = calculate_impact_assessment_score(
        get_release_impact_questions(),
        _responses_for_scoring(assessment.responses),
    )
    ordered_responses = sorted(assessment.responses, key=_response_order_key)
    return ImpactAssessmentDetail(
        assessmentId=assessment.assessment_id,
        releaseId=package.release_id,
        validationPackageId=assessment.package_id,
        assessmentNo=assessment.assessment_no,
        packageNo=package.package_no,
        status=assessment.status,
        totalScore=assessment.total_score,
        riskLevel=assessment.risk_level,
        validationScope=assessment.validation_scope,
        summary=assessment.summary,
        packageStatus=package.package_status,
        releaseStatus=release.release_status if release is not None else None,
        impactAssessmentStatus=package.impact_assessment_status,
        nextStep=_next_step_for_assessment(assessment),
        createdBy=assessment.created_by,
        createdAt=assessment.created_at,
        updatedBy=assessment.updated_by,
        updatedAt=assessment.updated_at,
        completedBy=assessment.completed_by,
        completedAt=assessment.completed_at,
        reopenedBy=assessment.reopened_by,
        reopenedAt=assessment.reopened_at,
        reopenReason=assessment.reopen_reason,
        questions=get_questions(),
        responses=[_response_schema(response) for response in ordered_responses],
        missingAnswers=scoring.missing_answers,
        validationErrors=[_issue_schema(issue) for issue in scoring.validation_errors],
        aiAssistantEnabled=_ai_assistant_enabled(),
        canReopen=_can_reopen(assessment),
    )


def _build_save_result(
    assessment: ReleaseValidationImpactAssessment,
    scoring: ImpactScoringResult,
) -> ImpactAssessmentSaveResult:
    package = assessment.package
    release = package.release
    ordered_responses = sorted(assessment.responses, key=_response_order_key)
    return ImpactAssessmentSaveResult(
        assessmentId=assessment.assessment_id,
        releaseId=package.release_id,
        validationPackageId=assessment.package_id,
        assessmentNo=assessment.assessment_no,
        status=assessment.status,
        totalScore=scoring.total_score,
        riskLevel=scoring.risk_level,
        validationScope=scoring.validation_scope,
        summary=scoring.summary,
        packageStatus=package.package_status,
        releaseStatus=release.release_status if release is not None else None,
        impactAssessmentStatus=package.impact_assessment_status,
        nextStep=_next_step_for_assessment(assessment),
        responses=[_response_schema(response) for response in ordered_responses],
        missingAnswers=scoring.missing_answers,
        validationErrors=[_issue_schema(issue) for issue in scoring.validation_errors],
    )


async def initialize_assessment(
    db: AsyncSession,
    release_id: uuid.UUID,
    actor: str | None = None,
) -> ImpactAssessmentDetail:
    release = await _get_release_with_package(db, release_id)
    package = release.validation_package
    if package is None:
        raise ImpactAssessmentNotFoundError("Validation package not found for release")
    if package.impact_assessment is not None:
        existing_assessment = await _get_assessment_by_package_id(db, package.package_id)
        if existing_assessment is not None:
            return _build_detail(existing_assessment)
    if _is_locked(package):
        raise ImpactAssessmentConflictError("Validation package is locked for impact assessment changes.")

    now = _utc_now()
    actor_label = _actor_label(actor)
    package_id = package.package_id
    assessment = ReleaseValidationImpactAssessment(
        package_id=package_id,
        assessment_no=await _generate_assessment_no(db, now),
        status=ASSESSMENT_STATUS_DRAFT,
        total_score=0,
        risk_level="NOT_ASSESSED",
        validation_scope="NOT_ASSESSED",
        summary="Impact assessment draft initialized.",
        created_by=actor_label,
        created_at=now,
        updated_by=actor_label,
        updated_at=now,
    )
    db.add(assessment)
    package.impact_assessment_status = IMPACT_ASSESSMENT_STATUS_DRAFT
    package.modified_by = actor_label
    package.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing_assessment = await _get_assessment_by_package_id(db, package_id)
        if existing_assessment is not None:
            return _build_detail(existing_assessment)
        raise ImpactAssessmentConflictError("Impact assessment already exists for this validation package.") from exc
    except Exception:
        await db.rollback()
        raise

    detail = await get_assessment_by_release(db, release_id)
    if detail is None:
        raise ImpactAssessmentConflictError("Impact assessment initialization failed.")
    return detail


async def get_assessment_by_release(
    db: AsyncSession,
    release_id: uuid.UUID,
) -> ImpactAssessmentDetail | None:
    release = await _get_release_with_package(db, release_id)
    package = release.validation_package
    if package is None:
        raise ImpactAssessmentNotFoundError("Validation package not found for release")
    if package.impact_assessment is None:
        return None
    return _build_detail(await _get_assessment(db, package.impact_assessment.assessment_id))


def _validate_response_inputs(responses: list[ImpactResponseInput]) -> None:
    question_map = get_release_impact_question_map()
    seen_codes: set[str] = set()
    errors: list[dict[str, str]] = []
    for response in responses:
        if response.questionCode in seen_codes:
            errors.append(
                {
                    "questionCode": response.questionCode,
                    "field": "questionCode",
                    "message": "Duplicate response for question.",
                }
            )
        seen_codes.add(response.questionCode)
        if response.questionCode not in question_map:
            errors.append(
                {
                    "questionCode": response.questionCode,
                    "field": "questionCode",
                    "message": "Unknown impact assessment question.",
                }
            )
    if errors:
        raise ImpactAssessmentValidationError("Impact assessment responses are invalid.", data={"errors": errors})


def _upsert_response(
    assessment: ReleaseValidationImpactAssessment,
    payload: ImpactResponseInput,
    *,
    actor: str | None,
    now: datetime,
) -> None:
    question = get_release_impact_question_map()[payload.questionCode]
    existing = next((response for response in assessment.responses if response.question_code == payload.questionCode), None)
    if existing is None:
        existing = ReleaseValidationImpactResponse(
            assessment_id=assessment.assessment_id,
            question_code=question.question_code,
            category=question.category,
            question_text=question.question_text,
            answer=payload.answer,
            weight=question.weight,
            critical=question.critical,
            mandatory=question.mandatory,
            score=0,
            rationale=payload.rationale,
            evidence_reference=payload.evidenceReference,
            answered_by=actor,
            answered_at=now,
            created_at=now,
            updated_at=now,
        )
        assessment.responses.append(existing)
        return

    existing.category = question.category
    existing.question_text = question.question_text
    existing.answer = payload.answer
    existing.weight = question.weight
    existing.critical = question.critical
    existing.mandatory = question.mandatory
    existing.rationale = payload.rationale
    existing.evidence_reference = payload.evidenceReference
    existing.answered_by = actor
    existing.answered_at = now
    existing.updated_at = now


def _apply_scoring(assessment: ReleaseValidationImpactAssessment, scoring: ImpactScoringResult) -> None:
    score_by_code = {score.question_code: score.score for score in scoring.response_scores}
    for response in assessment.responses:
        response.score = score_by_code.get(response.question_code, 0)
    assessment.total_score = scoring.total_score
    assessment.risk_level = scoring.risk_level
    assessment.validation_scope = scoring.validation_scope
    assessment.summary = scoring.summary


async def save_responses(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    responses: list[ImpactResponseInput],
    actor: str | None = None,
) -> ImpactAssessmentSaveResult:
    assessment = await _get_assessment(db, assessment_id)
    if assessment.status == ASSESSMENT_STATUS_COMPLETED:
        raise ImpactAssessmentConflictError("Completed assessment cannot be edited unless it is reopened.")
    if _is_locked(assessment.package):
        raise ImpactAssessmentConflictError("Validation package is locked for impact assessment changes.")
    _validate_response_inputs(responses)

    now = _utc_now()
    actor_label = _actor_label(actor)
    for response in responses:
        _upsert_response(assessment, response, actor=actor_label, now=now)

    scoring = calculate_impact_assessment_score(
        get_release_impact_questions(),
        _responses_for_scoring(assessment.responses),
    )
    _apply_scoring(assessment, scoring)
    has_any_answer = bool(assessment.responses)
    assessment.status = ASSESSMENT_STATUS_IN_PROGRESS if has_any_answer else ASSESSMENT_STATUS_DRAFT
    assessment.updated_by = actor_label
    assessment.updated_at = now

    package = assessment.package
    package.impact_assessment_status = (
        IMPACT_ASSESSMENT_STATUS_IN_PROGRESS if has_any_answer else IMPACT_ASSESSMENT_STATUS_DRAFT
    )
    package.risk_level = scoring.risk_level
    package.validation_scope = scoring.validation_scope
    package.package_status = PACKAGE_STATUS_DRAFT
    package.modified_by = actor_label
    package.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ImpactAssessmentConflictError("Failed to save impact assessment responses.") from exc
    except Exception:
        await db.rollback()
        raise

    refreshed = await _get_assessment(db, assessment_id)
    return _build_save_result(refreshed, scoring)


async def complete_assessment(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    actor: str | None = None,
) -> ImpactAssessmentCompleteResult:
    assessment = await _get_assessment(db, assessment_id)
    if assessment.status == ASSESSMENT_STATUS_COMPLETED:
        raise ImpactAssessmentConflictError("Impact assessment is already completed.")
    if _is_locked(assessment.package):
        raise ImpactAssessmentConflictError("Validation package is locked for impact assessment changes.")

    scoring = calculate_impact_assessment_score(
        get_release_impact_questions(),
        _responses_for_scoring(assessment.responses),
    )
    validation_errors = scoring.validation_errors
    if validation_errors:
        raise ImpactAssessmentValidationError(
            "Impact assessment cannot be completed until all mandatory answers and rationale are provided.",
            data={
                "errors": [
                    {
                        "questionCode": issue.question_code,
                        "field": issue.field,
                        "message": issue.message,
                    }
                    for issue in validation_errors
                ],
                "missingAnswers": scoring.missing_answers,
                "totalScore": scoring.total_score,
                "riskLevel": scoring.risk_level,
                "validationScope": scoring.validation_scope,
                "summary": scoring.summary,
            },
        )

    now = _utc_now()
    actor_label = _actor_label(actor)
    package = assessment.package
    release = package.release
    if release is None:
        raise ImpactAssessmentNotFoundError("Release not found for validation package")

    try:
        _apply_scoring(assessment, scoring)
        assessment.status = ASSESSMENT_STATUS_COMPLETED
        assessment.completed_by = actor_label
        assessment.completed_at = now
        assessment.updated_by = actor_label
        assessment.updated_at = now

        package.impact_assessment_status = IMPACT_ASSESSMENT_STATUS_COMPLETED
        package.risk_level = scoring.risk_level
        package.validation_scope = scoring.validation_scope
        package.package_status = PACKAGE_STATUS_VALIDATION_SCOPE_DEFINED
        package.modified_by = actor_label
        package.modified_dt = now

        release.release_status = RELEASE_STATUS_VALIDATION_SCOPE_DEFINED
        release.modified_by = actor_label
        release.modified_dt = now
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return ImpactAssessmentCompleteResult(
        assessmentId=assessment.assessment_id,
        releaseId=release.release_id,
        validationPackageId=package.package_id,
        status=ASSESSMENT_STATUS_COMPLETED,
        totalScore=scoring.total_score,
        riskLevel=scoring.risk_level,
        validationScope=scoring.validation_scope,
        releaseStatus=RELEASE_STATUS_VALIDATION_SCOPE_DEFINED,
        packageStatus=PACKAGE_STATUS_VALIDATION_SCOPE_DEFINED,
        nextStep=NEXT_STEP_DOCUMENT_CHECKLIST,
        summary=scoring.summary,
    )


async def reopen_assessment(
    db: AsyncSession,
    assessment_id: uuid.UUID,
    reason: str,
    actor: str | None = None,
) -> ImpactAssessmentDetail:
    normalized_reason = _strip_optional(reason)
    if normalized_reason is None:
        raise ImpactAssessmentValidationError("Reopen reason is required.")

    assessment = await _get_assessment(db, assessment_id)
    if assessment.status != ASSESSMENT_STATUS_COMPLETED:
        raise ImpactAssessmentConflictError("Only completed impact assessments can be reopened.")
    if _is_locked(assessment.package):
        raise ImpactAssessmentConflictError("Validation package is locked and cannot be reopened.")

    now = _utc_now()
    actor_label = _actor_label(actor)
    package = assessment.package
    release = package.release
    if release is None:
        raise ImpactAssessmentNotFoundError("Release not found for validation package")

    assessment.status = ASSESSMENT_STATUS_REOPENED
    assessment.reopened_by = actor_label
    assessment.reopened_at = now
    assessment.reopen_reason = normalized_reason
    assessment.updated_by = actor_label
    assessment.updated_at = now

    package.impact_assessment_status = IMPACT_ASSESSMENT_STATUS_IN_PROGRESS
    package.package_status = PACKAGE_STATUS_DRAFT
    if (
        package.document_checklist_status != DOCUMENT_CHECKLIST_STATUS_NOT_GENERATED
        and await _package_has_active_document_requirements(db, package.package_id)
    ):
        package.document_checklist_status = DOCUMENT_CHECKLIST_STATUS_STALE
    package.modified_by = actor_label
    package.modified_dt = now
    release.release_status = RELEASE_STATUS_IMPACT_ASSESSMENT_PENDING
    release.modified_by = actor_label
    release.modified_dt = now

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return _build_detail(await _get_assessment(db, assessment_id))


def _truncate_text(value: str | None, max_chars: int = 12000) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 3].rstrip()}..."


def _build_ai_system_prompt() -> str:
    return (
        "You are an impact assessment assistant for a regulated software validation workflow.\n"
        "You only suggest impact assessment answers and rationale.\n"
        "You must not finalize risk level, validation scope, approval, or lifecycle status.\n"
        "If release documentation is unclear, choose UNKNOWN.\n"
        "Return JSON only.\n"
        "Use only allowed answer values: YES, NO, NOT_APPLICABLE, UNKNOWN.\n"
        "Include concise evidence reference from release details/documentation.\n"
        "Prefer conservative interpretation for regulated/GxP impact."
    )


def _build_ai_context(
    release: AssetRelease,
    package: ReleaseValidationPackage,
    payload: ImpactAssessmentAISuggestRequest,
) -> dict[str, Any]:
    asset: Asset | None = release.asset
    documentation_text = release.documentation_text if payload.includeDocumentationText else None
    return {
        "prompt_version": STEP2_AI_PROMPT_VERSION,
        "task": "release_validation_step2_impact_assessment_suggestions",
        "release_name": release.release_name,
        "previous_version": release.previous_version,
        "version": release.version,
        "new_version": release.version,
        "release_type": release.release_type,
        "environment": release.environment,
        "release_description": release.release_description,
        "business_reason": release.business_reason,
        "documentation_mode": release.documentation_mode,
        "documentation_text": _truncate_text(documentation_text),
        "documentation_source_url": release.documentation_source_url,
        "system_config_report": _truncate_text(release.system_config_report, max_chars=6000),
        "expected_validated_functionality_impact": release.expected_validated_functionality_impact,
        "asset": {
            "asset_id": str(release.asset_id),
            "asset_code": getattr(asset, "asset_id", None),
            "asset_name": getattr(asset, "asset_name", None),
            "asset_class": getattr(asset, "asset_class", None),
            "asset_type": getattr(asset, "asset_type", None),
            "asset_category": getattr(asset, "asset_category", None),
            "asset_sub_category": getattr(asset, "asset_sub_category", None),
            "current_validated_version": getattr(asset, "asset_version", None),
        },
        "package_number": package.package_no,
        "additional_context": payload.additionalContext,
        "active_backend_questions": [question.model_dump() for question in get_questions()],
        "required_json_shape": {
            "suggestions": [
                {
                    "question_code": "AUDIT_TRAIL",
                    "suggested_answer": "UNKNOWN",
                    "suggested_rationale": (
                        "The release mentions workflow/reporting updates but does not clearly confirm whether "
                        "audit trail generation or export is affected."
                    ),
                    "confidence": "MEDIUM",
                    "evidence_reference": "Release description mentions reporting enhancements.",
                    "caveat": "Confirm with vendor release note or system owner.",
                    "source_fields_used": ["release_description", "documentation_text"],
                }
            ]
        },
    }


def _normalize_ai_suggestion(item: Any) -> ImpactAssessmentAISuggestion | None:
    if not isinstance(item, dict):
        return None
    question_code = _strip_optional(item.get("question_code") or item.get("questionCode"))
    if question_code is None or question_code not in get_release_impact_question_map():
        return None
    source_fields = item.get("source_fields_used") or item.get("sourceFieldsUsed") or []
    if not isinstance(source_fields, list):
        source_fields = []
    try:
        return ImpactAssessmentAISuggestion(
            questionCode=question_code,
            suggestedAnswer=str(item.get("suggested_answer") or item.get("suggestedAnswer") or "UNKNOWN"),
            suggestedRationale=_strip_optional(item.get("suggested_rationale") or item.get("suggestedRationale")),
            confidence=str(item.get("confidence") or "LOW"),
            evidenceReference=_strip_optional(item.get("evidence_reference") or item.get("evidenceReference")),
            caveat=_strip_optional(item.get("caveat")),
            sourceFieldsUsed=[str(value).strip() for value in source_fields if str(value).strip()],
        )
    except ValueError:
        return None


async def suggest_impact_assessment_answers(
    db: AsyncSession,
    release_id: uuid.UUID,
    payload: ImpactAssessmentAISuggestRequest,
    actor: str | None = None,
) -> ImpactAssessmentAISuggestResponse:
    release = await _get_release_with_package(db, release_id)
    package = release.validation_package
    if package is None:
        raise ImpactAssessmentNotFoundError("Validation package not found for release")

    gateway = get_step2_llm_gateway()
    if not gateway.is_enabled():
        raise ImpactAssessmentAIUnavailableError(
            "Step 2 AI assistant is disabled by configuration.",
            data={"aiEnabled": False},
        )
    if not gateway.is_configured():
        raise ImpactAssessmentAIUnavailableError(
            "Step 2 AI assistant is not configured.",
            data={"aiEnabled": False},
        )

    try:
        llm_result = await gateway.generate_json(
            system_prompt=_build_ai_system_prompt(),
            user_payload=_build_ai_context(release, package, payload),
        )
    except LLMGatewayUnavailableError as exc:
        raise ImpactAssessmentAIUnavailableError(str(exc), data={"aiEnabled": False}) from exc
    except LLMGatewayError as exc:
        raise ImpactAssessmentAIGenerationError(
            "AI suggestion generation failed.",
            data={"aiEnabled": True, "error": str(exc)},
        ) from exc

    raw_suggestions = llm_result.payload.get("suggestions")
    if not isinstance(raw_suggestions, list):
        raise ImpactAssessmentAIGenerationError(
            "AI suggestion generation failed because the provider did not return a suggestions array.",
            data={"aiEnabled": True},
        )

    suggestions = [
        suggestion
        for suggestion in (_normalize_ai_suggestion(item) for item in raw_suggestions)
        if suggestion is not None
    ]

    assessment_id = package.impact_assessment.assessment_id if package.impact_assessment is not None else None
    now = _utc_now()
    actor_label = _actor_label(actor)
    for suggestion in suggestions:
        db.add(
            ReleaseValidationAISuggestion(
                assessment_id=assessment_id,
                release_id=release.release_id,
                package_id=package.package_id,
                question_code=suggestion.questionCode,
                suggested_answer=suggestion.suggestedAnswer,
                suggested_rationale=suggestion.suggestedRationale,
                confidence=suggestion.confidence,
                evidence_reference=suggestion.evidenceReference,
                caveat=suggestion.caveat,
                source_fields_used=suggestion.sourceFieldsUsed,
                model_name=llm_result.model_name,
                provider=llm_result.provider,
                prompt_version=STEP2_AI_PROMPT_VERSION,
                raw_response=llm_result.payload,
                accepted_by_user=False,
                created_by=actor_label,
                created_at=now,
            )
        )

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return ImpactAssessmentAISuggestResponse(
        aiEnabled=True,
        assessmentId=assessment_id,
        releaseId=release.release_id,
        validationPackageId=package.package_id,
        modelName=llm_result.model_name,
        provider=llm_result.provider,
        promptVersion=STEP2_AI_PROMPT_VERSION,
        suggestions=suggestions,
        message="AI suggestions generated. User review and deterministic completion are still required.",
        rawResponse=json.loads(json.dumps(llm_result.payload, ensure_ascii=True, default=str)),
    )
