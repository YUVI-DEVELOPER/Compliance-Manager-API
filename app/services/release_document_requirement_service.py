from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.release_document_requirements import (
    DOCUMENT_STATUS_APPROVED,
    DOCUMENT_STATUS_DRAFT,
    DOCUMENT_STATUS_IN_REVIEW,
    DOCUMENT_STATUS_LINKED,
    DOCUMENT_STATUS_MISSING,
    DOCUMENT_STATUS_NOT_REQUIRED,
    DOCUMENT_STATUS_OBSOLETE,
    DOCUMENT_STATUS_REJECTED,
    DOCUMENT_STATUS_UPLOADED,
    DOCUMENT_STATUS_WAIVED,
    REQUIREMENT_LEVEL_CONDITIONAL,
    REQUIREMENT_LEVEL_NOT_REQUIRED,
    REQUIREMENT_LEVEL_OPTIONAL,
    REQUIREMENT_LEVEL_REQUIRED,
    VALIDATION_SCOPE_FULL_VALIDATION,
    VALIDATION_SCOPE_LIMITED_VALIDATION,
    VALIDATION_SCOPE_NO_VALIDATION_REQUIRED,
    DocumentRequirementRule,
    get_document_requirement_rules,
)
from app.models.asset_release import AssetRelease
from app.models.release_validation_document_requirement import ReleaseValidationDocumentRequirement
from app.models.release_validation_impact_assessment import ReleaseValidationImpactAssessment
from app.models.release_validation_impact_response import ReleaseValidationImpactResponse
from app.models.release_validation_package import ReleaseValidationPackage
from app.schemas.release_document_requirement_schema import (
    DocumentRequirementCompleteResponse,
    DocumentRequirementGenerateResponse,
    DocumentRequirementLinkRequest,
    DocumentRequirementRow,
    DocumentRequirementStatusUpdateRequest,
    DocumentRequirementSummary,
    DocumentRequirementWaiverRequest,
)


IMPACT_ASSESSMENT_STATUS_COMPLETED = "COMPLETED"
VALIDATION_SCOPE_NOT_ASSESSED = "NOT_ASSESSED"
RISK_LEVEL_NOT_ASSESSED = "NOT_ASSESSED"
PACKAGE_STATUS_DOCUMENTS_PENDING = "DOCUMENTS_PENDING"
PACKAGE_STATUS_TESTING_PENDING = "TESTING_PENDING"
PACKAGE_STATUS_VALIDATION_SCOPE_DEFINED = "VALIDATION_SCOPE_DEFINED"
PACKAGE_STATUS_VALIDATION_SUMMARY_PENDING = "VALIDATION_SUMMARY_PENDING"
RELEASE_STATUS_DOCUMENTS_PENDING = "DOCUMENTS_PENDING"
RELEASE_STATUS_TESTING_PENDING = "TESTING_PENDING"
RELEASE_STATUS_VALIDATION_SUMMARY_PENDING = "VALIDATION_SUMMARY_PENDING"
DOCUMENT_CHECKLIST_STATUS_NOT_GENERATED = "NOT_GENERATED"
DOCUMENT_CHECKLIST_STATUS_GENERATED = "GENERATED"
DOCUMENT_CHECKLIST_STATUS_IN_PROGRESS = "IN_PROGRESS"
DOCUMENT_CHECKLIST_STATUS_COMPLETED = "COMPLETED"
DOCUMENT_CHECKLIST_STATUS_STALE = "STALE"
NEXT_STEP_DOCUMENT_CHECKLIST = "DOCUMENT_CHECKLIST"
NEXT_STEP_TEST_EXECUTION = "TEST_EXECUTION"
NEXT_STEP_VALIDATION_SUMMARY = "VALIDATION_SUMMARY"

SOURCE_TYPE_NONE = "NONE"
SOURCE_TYPE_UPLOAD = "UPLOAD"
SOURCE_TYPE_EXTERNAL_URL = "EXTERNAL_URL"
SOURCE_TYPE_DOCUMENT_PORTAL = "DOCUMENT_PORTAL"
SOURCE_TYPE_AUTHORED_DOCUMENT = "AUTHORED_DOCUMENT"
SOURCE_TYPE_QUALIFICATION_DOCUMENT = "QUALIFICATION_DOCUMENT"

TRIGGER_POSITIVE_ANSWERS = {"YES", "UNKNOWN"}
LOCKED_STATUSES = {"APPROVED", "RELEASED", "LOCKED", "REJECTED", "CANCELLED"}
BLOCKING_STATUSES = {
    DOCUMENT_STATUS_MISSING,
    DOCUMENT_STATUS_DRAFT,
    DOCUMENT_STATUS_UPLOADED,
    DOCUMENT_STATUS_LINKED,
    DOCUMENT_STATUS_IN_REVIEW,
    DOCUMENT_STATUS_REJECTED,
}
PROGRESS_STATUSES = {
    DOCUMENT_STATUS_DRAFT,
    DOCUMENT_STATUS_UPLOADED,
    DOCUMENT_STATUS_LINKED,
    DOCUMENT_STATUS_IN_REVIEW,
    DOCUMENT_STATUS_APPROVED,
    DOCUMENT_STATUS_REJECTED,
    DOCUMENT_STATUS_WAIVED,
}
READ_ONLY_STATUSES = {
    DOCUMENT_STATUS_APPROVED,
    DOCUMENT_STATUS_WAIVED,
    DOCUMENT_STATUS_NOT_REQUIRED,
    DOCUMENT_STATUS_OBSOLETE,
}
LINK_REQUEST_STATUSES = {
    DOCUMENT_STATUS_DRAFT,
    DOCUMENT_STATUS_UPLOADED,
    DOCUMENT_STATUS_LINKED,
    DOCUMENT_STATUS_IN_REVIEW,
}
STATUS_TRANSITIONS = {
    DOCUMENT_STATUS_MISSING: {
        DOCUMENT_STATUS_DRAFT,
        DOCUMENT_STATUS_UPLOADED,
        DOCUMENT_STATUS_LINKED,
        DOCUMENT_STATUS_IN_REVIEW,
    },
    DOCUMENT_STATUS_DRAFT: {DOCUMENT_STATUS_IN_REVIEW},
    DOCUMENT_STATUS_UPLOADED: {DOCUMENT_STATUS_IN_REVIEW},
    DOCUMENT_STATUS_LINKED: {DOCUMENT_STATUS_IN_REVIEW},
    DOCUMENT_STATUS_IN_REVIEW: {DOCUMENT_STATUS_APPROVED, DOCUMENT_STATUS_REJECTED},
    DOCUMENT_STATUS_REJECTED: {
        DOCUMENT_STATUS_DRAFT,
        DOCUMENT_STATUS_UPLOADED,
        DOCUMENT_STATUS_LINKED,
        DOCUMENT_STATUS_IN_REVIEW,
    },
}


class DocumentRequirementServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.data = data or {}


class DocumentRequirementNotFoundError(DocumentRequirementServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404)


class DocumentRequirementValidationError(DocumentRequirementServiceError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=400, data=data)


class DocumentRequirementConflictError(DocumentRequirementServiceError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=409, data=data)


@dataclass(frozen=True, slots=True)
class EvaluatedDocumentRequirement:
    rule: DocumentRequirementRule
    requirement_level: str
    required_flag: bool
    trigger_question_codes: tuple[str, ...]
    trigger_reason: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _strip_optional(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _actor_label(actor: str | None) -> str | None:
    return _strip_optional(actor)


def _release_query() -> Select[tuple[AssetRelease]]:
    return select(AssetRelease).options(
        selectinload(AssetRelease.validation_package)
        .selectinload(ReleaseValidationPackage.impact_assessment)
        .selectinload(ReleaseValidationImpactAssessment.responses),
        selectinload(AssetRelease.validation_package).selectinload(ReleaseValidationPackage.document_requirements),
    )


async def _get_release_with_package(db: AsyncSession, release_id: uuid.UUID) -> AssetRelease:
    result = await db.execute(_release_query().where(AssetRelease.release_id == release_id))
    release = result.scalars().first()
    if release is None:
        raise DocumentRequirementNotFoundError("Release not found")
    if release.validation_package is None:
        raise DocumentRequirementNotFoundError("Validation package not found for release")
    return release


async def _load_active_requirements(
    db: AsyncSession,
    release_id: uuid.UUID,
) -> list[ReleaseValidationDocumentRequirement]:
    result = await db.execute(
        select(ReleaseValidationDocumentRequirement)
        .where(
            ReleaseValidationDocumentRequirement.release_id == release_id,
            ReleaseValidationDocumentRequirement.is_active.is_(True),
        )
        .order_by(
            ReleaseValidationDocumentRequirement.display_order.asc(),
            ReleaseValidationDocumentRequirement.document_code.asc(),
        )
    )
    return list(result.scalars().all())


async def _get_requirement(
    db: AsyncSession,
    release_id: uuid.UUID,
    requirement_id: uuid.UUID,
) -> ReleaseValidationDocumentRequirement:
    result = await db.execute(
        select(ReleaseValidationDocumentRequirement).where(
            ReleaseValidationDocumentRequirement.release_id == release_id,
            ReleaseValidationDocumentRequirement.requirement_id == requirement_id,
            ReleaseValidationDocumentRequirement.is_active.is_(True),
        )
    )
    requirement = result.scalars().first()
    if requirement is None:
        raise DocumentRequirementNotFoundError("Document requirement not found")
    return requirement


def _is_locked(package: ReleaseValidationPackage) -> bool:
    package_status = (package.package_status or "").upper()
    release_status = (package.release.release_status if package.release is not None else "").upper()
    return package_status in LOCKED_STATUSES or release_status in LOCKED_STATUSES


def _assert_step2_completed(package: ReleaseValidationPackage) -> None:
    if package.impact_assessment_status != IMPACT_ASSESSMENT_STATUS_COMPLETED:
        raise DocumentRequirementConflictError("Impact assessment must be completed before generating document checklist.")
    if package.validation_scope == VALIDATION_SCOPE_NOT_ASSESSED or package.risk_level == RISK_LEVEL_NOT_ASSESSED:
        raise DocumentRequirementConflictError("Validation scope and risk level must be defined before document checklist.")
    assessment = package.impact_assessment
    if assessment is None or assessment.status != IMPACT_ASSESSMENT_STATUS_COMPLETED:
        raise DocumentRequirementConflictError("Completed impact assessment record is required before document checklist.")


def _positive_trigger_codes(
    responses: Iterable[ReleaseValidationImpactResponse],
) -> set[str]:
    positive_codes: set[str] = set()
    for response in responses:
        answer = (response.answer or "").upper()
        if answer in TRIGGER_POSITIVE_ANSWERS:
            positive_codes.add(response.question_code)
    return positive_codes


def evaluate_document_requirement_rules(
    validation_scope: str,
    risk_level: str,
    responses: Iterable[ReleaseValidationImpactResponse],
) -> list[EvaluatedDocumentRequirement]:
    positive_codes = _positive_trigger_codes(responses)
    evaluated: list[EvaluatedDocumentRequirement] = []

    for rule in get_document_requirement_rules():
        base_required = validation_scope in rule.base_scopes
        triggered_codes = tuple(code for code in rule.trigger_questions if code in positive_codes)
        trigger_allowed_for_scope = not rule.conditional_scopes or validation_scope in rule.conditional_scopes
        trigger_required = bool(triggered_codes) and trigger_allowed_for_scope
        if not base_required and not trigger_required:
            continue

        reason_parts: list[str] = []
        if base_required:
            reason_parts.append(f"Required for {validation_scope} validation scope.")
        if trigger_required:
            reason_parts.append(
                "Triggered by YES/UNKNOWN response to "
                + ", ".join(triggered_codes)
                + "."
            )
        if risk_level:
            reason_parts.append(f"Risk level: {risk_level}.")

        requirement_level = rule.requirement_level
        if base_required and requirement_level == REQUIREMENT_LEVEL_CONDITIONAL:
            requirement_level = REQUIREMENT_LEVEL_REQUIRED

        evaluated.append(
            EvaluatedDocumentRequirement(
                rule=rule,
                requirement_level=requirement_level,
                required_flag=rule.required_flag,
                trigger_question_codes=triggered_codes,
                trigger_reason=" ".join(reason_parts),
            )
        )

    return sorted(evaluated, key=lambda item: (item.rule.display_order, item.rule.code))


def _has_linked_source(requirement: ReleaseValidationDocumentRequirement) -> bool:
    return bool(
        requirement.linked_document_link_id
        or requirement.linked_authored_document_id
        or requirement.linked_qualification_document_id
        or _strip_optional(requirement.external_url)
        or _strip_optional(requirement.file_path)
    )


def _available_actions(requirement: ReleaseValidationDocumentRequirement) -> list[str]:
    if requirement.status in {DOCUMENT_STATUS_NOT_REQUIRED, DOCUMENT_STATUS_OBSOLETE}:
        return []

    actions: list[str] = []
    if _has_linked_source(requirement):
        actions.append("VIEW_SOURCE")

    if requirement.status in {DOCUMENT_STATUS_APPROVED, DOCUMENT_STATUS_WAIVED}:
        return actions

    if requirement.status in {DOCUMENT_STATUS_MISSING, DOCUMENT_STATUS_DRAFT, DOCUMENT_STATUS_REJECTED}:
        actions.extend(["LINK_EXISTING", "ADD_EXTERNAL_URL"])
    elif requirement.status in {DOCUMENT_STATUS_LINKED, DOCUMENT_STATUS_UPLOADED}:
        actions.extend(["LINK_EXISTING", "ADD_EXTERNAL_URL", "MARK_IN_REVIEW"])
    elif requirement.status == DOCUMENT_STATUS_IN_REVIEW:
        actions.extend(["MARK_APPROVED", "MARK_REJECTED"])

    if requirement.status == DOCUMENT_STATUS_REJECTED:
        actions.append("MARK_IN_REVIEW")

    if requirement.waivable_flag:
        if requirement.waiver_requires_qa_flag and requirement.waiver_reason and requirement.status == DOCUMENT_STATUS_IN_REVIEW:
            actions.append("APPROVE_WAIVER")
        actions.append("REQUEST_WAIVER")

    return list(dict.fromkeys(actions))


def _row_schema(requirement: ReleaseValidationDocumentRequirement) -> DocumentRequirementRow:
    return DocumentRequirementRow(
        requirement_id=requirement.requirement_id,
        release_id=requirement.release_id,
        package_id=requirement.package_id,
        document_code=requirement.document_code,
        document_name=requirement.document_name,
        document_category=requirement.document_category,
        document_description=requirement.document_description,
        requirement_level=requirement.requirement_level,
        required_flag=requirement.required_flag,
        waivable_flag=requirement.waivable_flag,
        waiver_requires_qa_flag=requirement.waiver_requires_qa_flag,
        status=requirement.status,
        owner_role=requirement.owner_role,
        owner_user_id=requirement.owner_user_id,
        source_type=requirement.source_type,
        linked_document_link_id=requirement.linked_document_link_id,
        linked_authored_document_id=requirement.linked_authored_document_id,
        linked_qualification_document_id=requirement.linked_qualification_document_id,
        file_name=requirement.file_name,
        file_path=requirement.file_path,
        external_url=requirement.external_url,
        waiver_reason=requirement.waiver_reason,
        waiver_requested_by=requirement.waiver_requested_by,
        waiver_requested_at=requirement.waiver_requested_at,
        waiver_approved_by=requirement.waiver_approved_by,
        waiver_approved_at=requirement.waiver_approved_at,
        trigger_scope=requirement.trigger_scope,
        trigger_risk_level=requirement.trigger_risk_level,
        trigger_question_codes_json=requirement.trigger_question_codes_json,
        trigger_reason=requirement.trigger_reason,
        generated_version=requirement.generated_version,
        is_active=requirement.is_active,
        display_order=requirement.display_order,
        available_actions=_available_actions(requirement),
    )


def is_requirement_blocking(requirement: ReleaseValidationDocumentRequirement) -> bool:
    if not requirement.is_active or not requirement.required_flag:
        return False
    if requirement.status == DOCUMENT_STATUS_WAIVED and not requirement.waivable_flag:
        return True
    return requirement.status in BLOCKING_STATUSES


def summarize_requirements(
    requirements: Iterable[ReleaseValidationDocumentRequirement],
) -> DocumentRequirementSummary:
    active = [requirement for requirement in requirements if requirement.is_active]
    blocking_count = sum(1 for requirement in active if is_requirement_blocking(requirement))
    return DocumentRequirementSummary(
        total=len(active),
        required=sum(1 for requirement in active if requirement.requirement_level == REQUIREMENT_LEVEL_REQUIRED),
        conditional=sum(1 for requirement in active if requirement.requirement_level == REQUIREMENT_LEVEL_CONDITIONAL),
        optional=sum(1 for requirement in active if requirement.requirement_level == REQUIREMENT_LEVEL_OPTIONAL),
        approved=sum(1 for requirement in active if requirement.status == DOCUMENT_STATUS_APPROVED),
        missing=sum(1 for requirement in active if requirement.status == DOCUMENT_STATUS_MISSING),
        in_review=sum(1 for requirement in active if requirement.status == DOCUMENT_STATUS_IN_REVIEW),
        rejected=sum(1 for requirement in active if requirement.status == DOCUMENT_STATUS_REJECTED),
        waived=sum(1 for requirement in active if requirement.status == DOCUMENT_STATUS_WAIVED and requirement.waivable_flag),
        not_required=sum(1 for requirement in active if requirement.status == DOCUMENT_STATUS_NOT_REQUIRED),
        obsolete=sum(1 for requirement in active if requirement.status == DOCUMENT_STATUS_OBSOLETE),
        blocking_count=blocking_count,
        can_complete=blocking_count == 0,
    )


def _sorted_requirements(
    requirements: Iterable[ReleaseValidationDocumentRequirement],
) -> list[ReleaseValidationDocumentRequirement]:
    return sorted(
        requirements,
        key=lambda item: (item.display_order or 0, item.document_code or ""),
    )


def _build_generate_response(
    release: AssetRelease,
    requirements: Iterable[ReleaseValidationDocumentRequirement],
) -> DocumentRequirementGenerateResponse:
    package = release.validation_package
    if package is None:
        raise DocumentRequirementNotFoundError("Validation package not found for release")
    sorted_requirements = _sorted_requirements(requirements)
    return DocumentRequirementGenerateResponse(
        release_id=release.release_id,
        validation_package_id=package.package_id,
        package_no=package.package_no,
        release_status=release.release_status,
        package_status=package.package_status,
        validation_scope=package.validation_scope,
        risk_level=package.risk_level,
        document_checklist_status=package.document_checklist_status,
        summary=summarize_requirements(sorted_requirements),
        requirements=[_row_schema(requirement) for requirement in sorted_requirements],
        nextStep=NEXT_STEP_DOCUMENT_CHECKLIST,
    )


def _build_complete_response(
    release: AssetRelease,
    requirements: Iterable[ReleaseValidationDocumentRequirement],
    next_step: str,
    blocking_requirements: Iterable[ReleaseValidationDocumentRequirement] = (),
) -> DocumentRequirementCompleteResponse:
    package = release.validation_package
    if package is None:
        raise DocumentRequirementNotFoundError("Validation package not found for release")
    sorted_requirements = _sorted_requirements(requirements)
    return DocumentRequirementCompleteResponse(
        release_id=release.release_id,
        validation_package_id=package.package_id,
        package_no=package.package_no,
        release_status=release.release_status,
        package_status=package.package_status,
        validation_scope=package.validation_scope,
        risk_level=package.risk_level,
        document_checklist_status=package.document_checklist_status,
        summary=summarize_requirements(sorted_requirements),
        requirements=[_row_schema(requirement) for requirement in sorted_requirements],
        blocking_requirements=[_row_schema(requirement) for requirement in _sorted_requirements(blocking_requirements)],
        nextStep=next_step,
    )


def _requirement_codes(requirements: Iterable[ReleaseValidationDocumentRequirement]) -> set[str]:
    return {
        requirement.document_code
        for requirement in requirements
        if requirement.is_active and requirement.status not in {DOCUMENT_STATUS_OBSOLETE, DOCUMENT_STATUS_NOT_REQUIRED}
    }


def _generation_scope_changed(
    existing_requirements: Iterable[ReleaseValidationDocumentRequirement],
    *,
    validation_scope: str,
    risk_level: str,
) -> bool:
    for requirement in existing_requirements:
        if requirement.status in {DOCUMENT_STATUS_OBSOLETE, DOCUMENT_STATUS_NOT_REQUIRED}:
            continue
        if requirement.trigger_scope != validation_scope or requirement.trigger_risk_level != risk_level:
            return True
    return False


def _next_generated_version(
    existing_requirements: list[ReleaseValidationDocumentRequirement],
    package: ReleaseValidationPackage,
    evaluated: list[EvaluatedDocumentRequirement],
) -> int:
    current_version = max((requirement.generated_version or 1 for requirement in existing_requirements), default=1)
    existing_codes = _requirement_codes(existing_requirements)
    evaluated_codes = {item.rule.code for item in evaluated}
    needs_increment = bool(existing_requirements) and (
        package.document_checklist_status == DOCUMENT_CHECKLIST_STATUS_STALE
        or existing_codes != evaluated_codes
        or _generation_scope_changed(
            existing_requirements,
            validation_scope=package.validation_scope,
            risk_level=package.risk_level,
        )
    )
    return current_version + 1 if needs_increment else current_version


def _reactivated_status(requirement: ReleaseValidationDocumentRequirement) -> str:
    if requirement.status not in {DOCUMENT_STATUS_NOT_REQUIRED, DOCUMENT_STATUS_OBSOLETE}:
        return requirement.status
    return DOCUMENT_STATUS_LINKED if _has_linked_source(requirement) else DOCUMENT_STATUS_MISSING


def _apply_rule_to_requirement(
    requirement: ReleaseValidationDocumentRequirement,
    evaluated: EvaluatedDocumentRequirement,
    *,
    package: ReleaseValidationPackage,
    actor: str | None,
    now: datetime,
    generated_version: int,
) -> None:
    rule = evaluated.rule
    requirement.document_name = rule.name
    requirement.document_category = rule.category
    requirement.document_description = rule.description
    requirement.requirement_level = evaluated.requirement_level
    requirement.required_flag = evaluated.required_flag
    requirement.waivable_flag = rule.waivable_flag
    requirement.waiver_requires_qa_flag = rule.waiver_requires_qa_flag
    requirement.owner_role = rule.owner_role
    requirement.status = _reactivated_status(requirement)
    requirement.trigger_scope = package.validation_scope
    requirement.trigger_risk_level = package.risk_level
    requirement.trigger_question_codes_json = list(evaluated.trigger_question_codes)
    requirement.trigger_reason = evaluated.trigger_reason
    requirement.generated_version = generated_version
    requirement.is_active = True
    requirement.display_order = rule.display_order
    requirement.updated_by = actor
    requirement.updated_dt = now


def _mark_requirement_no_longer_required(
    requirement: ReleaseValidationDocumentRequirement,
    *,
    package: ReleaseValidationPackage,
    actor: str | None,
    now: datetime,
    generated_version: int,
) -> None:
    requirement.requirement_level = REQUIREMENT_LEVEL_NOT_REQUIRED
    requirement.required_flag = False
    requirement.status = DOCUMENT_STATUS_OBSOLETE
    requirement.trigger_scope = package.validation_scope
    requirement.trigger_risk_level = package.risk_level
    requirement.trigger_question_codes_json = []
    requirement.trigger_reason = "No longer required for the current validation scope and impact responses."
    requirement.generated_version = generated_version
    requirement.updated_by = actor
    requirement.updated_dt = now


def _checklist_has_progress(requirements: Iterable[ReleaseValidationDocumentRequirement]) -> bool:
    return any(requirement.status in PROGRESS_STATUSES for requirement in requirements if requirement.is_active)


async def generate_checklist(
    db: AsyncSession,
    release_id: uuid.UUID,
    actor: str | None = None,
) -> DocumentRequirementGenerateResponse:
    release = await _get_release_with_package(db, release_id)
    package = release.validation_package
    if package is None:
        raise DocumentRequirementNotFoundError("Validation package not found for release")
    if _is_locked(package):
        raise DocumentRequirementConflictError("Validation package is locked for document checklist changes.")
    _assert_step2_completed(package)

    assessment = package.impact_assessment
    if assessment is None:
        raise DocumentRequirementConflictError("Completed impact assessment record is required before document checklist.")

    existing_requirements = await _load_active_requirements(db, release_id)
    evaluated = evaluate_document_requirement_rules(package.validation_scope, package.risk_level, assessment.responses)
    evaluated_by_code = {item.rule.code: item for item in evaluated}
    existing_by_code = {requirement.document_code: requirement for requirement in existing_requirements}
    generated_version = _next_generated_version(existing_requirements, package, evaluated)
    actor_label = _actor_label(actor)
    now = _utc_now()

    try:
        for code, evaluated_requirement in evaluated_by_code.items():
            existing = existing_by_code.get(code)
            if existing is not None:
                _apply_rule_to_requirement(
                    existing,
                    evaluated_requirement,
                    package=package,
                    actor=actor_label,
                    now=now,
                    generated_version=generated_version,
                )
                continue

            rule = evaluated_requirement.rule
            requirement = ReleaseValidationDocumentRequirement(
                package_id=package.package_id,
                release_id=release.release_id,
                document_code=rule.code,
                document_name=rule.name,
                document_category=rule.category,
                document_description=rule.description,
                requirement_level=evaluated_requirement.requirement_level,
                required_flag=evaluated_requirement.required_flag,
                waivable_flag=rule.waivable_flag,
                waiver_requires_qa_flag=rule.waiver_requires_qa_flag,
                status=DOCUMENT_STATUS_MISSING,
                owner_role=rule.owner_role,
                source_type=SOURCE_TYPE_NONE,
                trigger_scope=package.validation_scope,
                trigger_risk_level=package.risk_level,
                trigger_question_codes_json=list(evaluated_requirement.trigger_question_codes),
                trigger_reason=evaluated_requirement.trigger_reason,
                generated_version=generated_version,
                is_active=True,
                display_order=rule.display_order,
                created_by=actor_label,
                created_dt=now,
                updated_by=actor_label,
                updated_dt=now,
            )
            existing_requirements.append(requirement)
            db.add(requirement)

        for requirement in existing_requirements:
            if requirement.document_code not in evaluated_by_code:
                _mark_requirement_no_longer_required(
                    requirement,
                    package=package,
                    actor=actor_label,
                    now=now,
                    generated_version=generated_version,
                )

        package.package_status = PACKAGE_STATUS_DOCUMENTS_PENDING
        package.document_checklist_status = (
            DOCUMENT_CHECKLIST_STATUS_IN_PROGRESS
            if _checklist_has_progress(existing_requirements)
            else DOCUMENT_CHECKLIST_STATUS_GENERATED
        )
        package.modified_by = actor_label
        package.modified_dt = now
        release.release_status = RELEASE_STATUS_DOCUMENTS_PENDING
        release.modified_by = actor_label
        release.modified_dt = now
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DocumentRequirementConflictError("Document checklist generation conflicted with existing rows.") from exc
    except Exception:
        await db.rollback()
        raise

    refreshed_requirements = await _load_active_requirements(db, release_id)
    if not refreshed_requirements and existing_requirements:
        refreshed_requirements = existing_requirements
    return _build_generate_response(release, refreshed_requirements)


async def get_checklist(
    db: AsyncSession,
    release_id: uuid.UUID,
) -> DocumentRequirementGenerateResponse:
    release = await _get_release_with_package(db, release_id)
    requirements = await _load_active_requirements(db, release_id)
    return _build_generate_response(release, requirements)


async def get_summary(
    db: AsyncSession,
    release_id: uuid.UUID,
) -> DocumentRequirementSummary:
    await _get_release_with_package(db, release_id)
    return summarize_requirements(await _load_active_requirements(db, release_id))


def _infer_source_type(payload: DocumentRequirementLinkRequest) -> str:
    if payload.source_type:
        return payload.source_type
    if payload.linked_document_link_id:
        return SOURCE_TYPE_DOCUMENT_PORTAL
    if payload.linked_authored_document_id:
        return SOURCE_TYPE_AUTHORED_DOCUMENT
    if payload.linked_qualification_document_id:
        return SOURCE_TYPE_QUALIFICATION_DOCUMENT
    if payload.external_url:
        return SOURCE_TYPE_EXTERNAL_URL
    if payload.file_name or payload.file_path:
        return SOURCE_TYPE_UPLOAD
    return SOURCE_TYPE_NONE


def _assert_requirement_editable(requirement: ReleaseValidationDocumentRequirement) -> None:
    if requirement.status in {DOCUMENT_STATUS_NOT_REQUIRED, DOCUMENT_STATUS_OBSOLETE}:
        raise DocumentRequirementValidationError("Not-required or obsolete document requirements cannot be edited.")
    if requirement.status in {DOCUMENT_STATUS_APPROVED, DOCUMENT_STATUS_WAIVED}:
        raise DocumentRequirementConflictError("Approved or waived document requirements are read-only in Step 3.")


def _apply_progress_statuses(
    release: AssetRelease,
    actor: str | None,
    now: datetime,
) -> None:
    package = release.validation_package
    if package is None:
        raise DocumentRequirementNotFoundError("Validation package not found for release")
    if package.document_checklist_status != DOCUMENT_CHECKLIST_STATUS_STALE:
        package.document_checklist_status = DOCUMENT_CHECKLIST_STATUS_IN_PROGRESS
    package.package_status = PACKAGE_STATUS_DOCUMENTS_PENDING
    package.modified_by = actor
    package.modified_dt = now
    release.release_status = RELEASE_STATUS_DOCUMENTS_PENDING
    release.modified_by = actor
    release.modified_dt = now


async def link_requirement(
    db: AsyncSession,
    release_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: DocumentRequirementLinkRequest,
    actor: str | None = None,
) -> DocumentRequirementRow:
    release = await _get_release_with_package(db, release_id)
    package = release.validation_package
    if package is None:
        raise DocumentRequirementNotFoundError("Validation package not found for release")
    if _is_locked(package):
        raise DocumentRequirementConflictError("Validation package is locked for document checklist changes.")

    requirement = await _get_requirement(db, release_id, requirement_id)
    _assert_requirement_editable(requirement)
    source_type = _infer_source_type(payload)
    if source_type == SOURCE_TYPE_NONE:
        raise DocumentRequirementValidationError("A document source is required.")
    if source_type == SOURCE_TYPE_EXTERNAL_URL and not payload.external_url:
        raise DocumentRequirementValidationError("external_url is required when linking an external URL.")

    requested_status = payload.status or DOCUMENT_STATUS_LINKED
    if requested_status not in LINK_REQUEST_STATUSES:
        raise DocumentRequirementValidationError(
            "Linked requirement status must be one of: DRAFT, UPLOADED, LINKED, IN_REVIEW."
        )

    actor_label = _actor_label(actor)
    now = _utc_now()
    requirement.source_type = source_type
    requirement.linked_document_link_id = payload.linked_document_link_id
    requirement.linked_authored_document_id = payload.linked_authored_document_id
    requirement.linked_qualification_document_id = payload.linked_qualification_document_id
    requirement.file_name = payload.file_name
    requirement.file_path = payload.file_path
    requirement.external_url = payload.external_url
    requirement.status = requested_status
    requirement.updated_by = actor_label
    requirement.updated_dt = now
    _apply_progress_statuses(release, actor_label, now)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return _row_schema(requirement)


async def update_requirement_status(
    db: AsyncSession,
    release_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: DocumentRequirementStatusUpdateRequest,
    actor: str | None = None,
) -> DocumentRequirementRow:
    release = await _get_release_with_package(db, release_id)
    package = release.validation_package
    if package is None:
        raise DocumentRequirementNotFoundError("Validation package not found for release")
    if _is_locked(package):
        raise DocumentRequirementConflictError("Validation package is locked for document checklist changes.")

    requirement = await _get_requirement(db, release_id, requirement_id)
    if requirement.status in READ_ONLY_STATUSES:
        raise DocumentRequirementConflictError("This document requirement status is read-only in Step 3.")
    allowed_targets = STATUS_TRANSITIONS.get(requirement.status, set())
    if payload.status == requirement.status:
        return _row_schema(requirement)
    if payload.status not in allowed_targets:
        raise DocumentRequirementValidationError(
            f"Cannot transition document requirement from {requirement.status} to {payload.status}."
        )

    actor_label = _actor_label(actor)
    now = _utc_now()
    requirement.status = payload.status
    requirement.updated_by = actor_label
    requirement.updated_dt = now
    _apply_progress_statuses(release, actor_label, now)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return _row_schema(requirement)


async def request_or_approve_waiver(
    db: AsyncSession,
    release_id: uuid.UUID,
    requirement_id: uuid.UUID,
    payload: DocumentRequirementWaiverRequest,
    actor: str | None = None,
) -> DocumentRequirementRow:
    release = await _get_release_with_package(db, release_id)
    package = release.validation_package
    if package is None:
        raise DocumentRequirementNotFoundError("Validation package not found for release")
    if _is_locked(package):
        raise DocumentRequirementConflictError("Validation package is locked for document checklist changes.")

    requirement = await _get_requirement(db, release_id, requirement_id)
    if not requirement.waivable_flag:
        raise DocumentRequirementValidationError("This document requirement is non-waivable.")
    if requirement.status in {DOCUMENT_STATUS_APPROVED, DOCUMENT_STATUS_WAIVED}:
        raise DocumentRequirementConflictError("Approved or waived document requirements are read-only in Step 3.")
    if requirement.status in {DOCUMENT_STATUS_NOT_REQUIRED, DOCUMENT_STATUS_OBSOLETE}:
        raise DocumentRequirementValidationError("Not-required or obsolete document requirements cannot be waived.")

    reason = _strip_optional(payload.waiver_reason)
    if reason is None:
        raise DocumentRequirementValidationError("waiver_reason is required.")

    actor_label = _actor_label(actor)
    now = _utc_now()
    requirement.waiver_reason = reason
    requirement.waiver_requested_by = actor_label
    requirement.waiver_requested_at = now
    if not requirement.waiver_requires_qa_flag or payload.approve:
        requirement.status = DOCUMENT_STATUS_WAIVED
        requirement.waiver_approved_by = actor_label
        requirement.waiver_approved_at = now
    else:
        requirement.status = DOCUMENT_STATUS_IN_REVIEW
        requirement.waiver_approved_by = None
        requirement.waiver_approved_at = None
    requirement.updated_by = actor_label
    requirement.updated_dt = now
    _apply_progress_statuses(release, actor_label, now)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return _row_schema(requirement)


async def complete_checklist(
    db: AsyncSession,
    release_id: uuid.UUID,
    actor: str | None = None,
) -> DocumentRequirementCompleteResponse:
    release = await _get_release_with_package(db, release_id)
    package = release.validation_package
    if package is None:
        raise DocumentRequirementNotFoundError("Validation package not found for release")
    if _is_locked(package):
        raise DocumentRequirementConflictError("Validation package is locked for document checklist changes.")
    if package.document_checklist_status == DOCUMENT_CHECKLIST_STATUS_STALE:
        raise DocumentRequirementConflictError("Document checklist is stale. Regenerate it before completion.")
    if package.document_checklist_status in {DOCUMENT_CHECKLIST_STATUS_NOT_GENERATED, None}:
        raise DocumentRequirementConflictError("Document checklist has not been generated.")

    requirements = await _load_active_requirements(db, release_id)
    blocking_requirements = [requirement for requirement in requirements if is_requirement_blocking(requirement)]
    if blocking_requirements:
        raise DocumentRequirementValidationError(
            "Mandatory document requirements are still missing, rejected, or under review.",
            data={
                "blockingRequirements": [
                    {
                        "requirement_id": str(requirement.requirement_id),
                        "document_code": requirement.document_code,
                        "document_name": requirement.document_name,
                        "status": requirement.status,
                    }
                    for requirement in blocking_requirements
                ]
            },
        )

    if package.validation_scope in {VALIDATION_SCOPE_LIMITED_VALIDATION, VALIDATION_SCOPE_FULL_VALIDATION}:
        next_step = NEXT_STEP_TEST_EXECUTION
        release_status = RELEASE_STATUS_TESTING_PENDING
        package_status = PACKAGE_STATUS_TESTING_PENDING
    elif package.validation_scope == VALIDATION_SCOPE_NO_VALIDATION_REQUIRED:
        next_step = NEXT_STEP_VALIDATION_SUMMARY
        release_status = RELEASE_STATUS_VALIDATION_SUMMARY_PENDING
        package_status = PACKAGE_STATUS_VALIDATION_SUMMARY_PENDING
    else:
        raise DocumentRequirementConflictError("Unsupported validation scope for checklist completion.")

    actor_label = _actor_label(actor)
    now = _utc_now()
    release.release_status = release_status
    release.modified_by = actor_label
    release.modified_dt = now
    package.package_status = package_status
    package.document_checklist_status = DOCUMENT_CHECKLIST_STATUS_COMPLETED
    package.modified_by = actor_label
    package.modified_dt = now

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return _build_complete_response(release, requirements, next_step)
