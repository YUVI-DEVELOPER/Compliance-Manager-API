from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from app.models.release_validation_document_requirement import ReleaseValidationDocumentRequirement
from app.schemas.release_document_requirement_schema import DocumentRequirementWaiverRequest
from app.services import release_document_requirement_service as document_service


class FakeDb:
    def __init__(self, release: object, requirements: list[ReleaseValidationDocumentRequirement] | None = None) -> None:
        self.release = release
        self.requirements = requirements or []
        self.added: list[object] = []
        self.commit_count = 0
        self.rollback_count = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, ReleaseValidationDocumentRequirement):
            if obj.requirement_id is None:
                obj.requirement_id = uuid.uuid4()
            if obj not in self.requirements:
                self.requirements.append(obj)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def _response(question_code: str, answer: str) -> SimpleNamespace:
    return SimpleNamespace(question_code=question_code, answer=answer)


def _release(
    *,
    scope: str = "FULL_VALIDATION",
    risk: str = "HIGH",
    impact_status: str = "COMPLETED",
    assessment_status: str = "COMPLETED",
    checklist_status: str = "NOT_GENERATED",
    responses: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    release_id = uuid.uuid4()
    package_id = uuid.uuid4()
    release = SimpleNamespace(
        release_id=release_id,
        release_status="VALIDATION_SCOPE_DEFINED",
        modified_by=None,
        modified_dt=None,
        validation_package=None,
    )
    assessment = SimpleNamespace(
        status=assessment_status,
        responses=responses or [],
    )
    package = SimpleNamespace(
        package_id=package_id,
        release_id=release_id,
        package_no="VAL-PKG-2026-0043",
        package_status="VALIDATION_SCOPE_DEFINED",
        validation_scope=scope,
        risk_level=risk,
        impact_assessment_status=impact_status,
        document_checklist_status=checklist_status,
        impact_assessment=assessment,
        document_requirements=[],
        release=release,
        modified_by=None,
        modified_dt=None,
    )
    release.validation_package = package
    return release


def _requirement(
    release: SimpleNamespace,
    code: str,
    *,
    status: str = "MISSING",
    required: bool = True,
    waivable: bool = True,
    waiver_requires_qa: bool = True,
    level: str = "REQUIRED",
    version: int = 1,
) -> ReleaseValidationDocumentRequirement:
    package = release.validation_package
    return ReleaseValidationDocumentRequirement(
        requirement_id=uuid.uuid4(),
        package_id=package.package_id,
        release_id=release.release_id,
        document_code=code,
        document_name=code.replace("_", " ").title(),
        document_category="GOVERNANCE",
        requirement_level=level,
        required_flag=required,
        waivable_flag=waivable,
        waiver_requires_qa_flag=waiver_requires_qa,
        status=status,
        trigger_scope=package.validation_scope,
        trigger_risk_level=package.risk_level,
        trigger_question_codes_json=[],
        generated_version=version,
        is_active=True,
        display_order=1,
    )


def _patch_loaders(
    monkeypatch: pytest.MonkeyPatch,
    release: SimpleNamespace,
    requirements: list[ReleaseValidationDocumentRequirement] | None = None,
) -> FakeDb:
    db = FakeDb(release, requirements)

    async def fake_get_release_with_package(db_arg: FakeDb, release_id: uuid.UUID) -> SimpleNamespace:
        assert db_arg is db
        assert release_id == release.release_id
        return release

    async def fake_load_active_requirements(db_arg: FakeDb, release_id: uuid.UUID) -> list[ReleaseValidationDocumentRequirement]:
        assert db_arg is db
        assert release_id == release.release_id
        return db.requirements

    async def fake_get_requirement(
        db_arg: FakeDb,
        release_id: uuid.UUID,
        requirement_id: uuid.UUID,
    ) -> ReleaseValidationDocumentRequirement:
        assert db_arg is db
        assert release_id == release.release_id
        for requirement in db.requirements:
            if requirement.requirement_id == requirement_id:
                return requirement
        raise document_service.DocumentRequirementNotFoundError("Document requirement not found")

    monkeypatch.setattr(document_service, "_get_release_with_package", fake_get_release_with_package)
    monkeypatch.setattr(document_service, "_load_active_requirements", fake_load_active_requirements)
    monkeypatch.setattr(document_service, "_get_requirement", fake_get_requirement)
    return db


def _codes(requirements: list[ReleaseValidationDocumentRequirement]) -> set[str]:
    return {
        requirement.document_code
        for requirement in requirements
        if requirement.status not in {"OBSOLETE", "NOT_REQUIRED"}
    }


def test_cannot_generate_checklist_before_step2_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(impact_status="IN_PROGRESS", assessment_status="IN_PROGRESS")
    db = _patch_loaders(monkeypatch, release)

    with pytest.raises(document_service.DocumentRequirementConflictError, match="Impact assessment"):
        asyncio.run(document_service.generate_checklist(db, release.release_id, "qa.user@example.com"))


def test_full_validation_high_generates_full_document_set(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(
        scope="FULL_VALIDATION",
        risk="HIGH",
        responses=[_response("GXP_IMPACT", "YES"), _response("CONFIGURATION", "YES")],
    )
    db = _patch_loaders(monkeypatch, release)

    result = asyncio.run(document_service.generate_checklist(db, release.release_id, "qa.user@example.com"))

    generated_codes = {row.document_code for row in result.requirements}
    assert {"RELEASE_NOTES", "IMPACT_ASSESSMENT", "VALIDATION_PLAN", "IQ_PROTOCOL", "ROLLBACK_PLAN"} <= generated_codes
    assert result.release_status == "DOCUMENTS_PENDING"
    assert result.package_status == "DOCUMENTS_PENDING"
    assert result.nextStep == "DOCUMENT_CHECKLIST"


def test_limited_validation_medium_generates_limited_base_and_triggered_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(
        scope="LIMITED_VALIDATION",
        risk="MEDIUM",
        responses=[_response("CONFIGURATION", "YES"), _response("WORKFLOW", "UNKNOWN")],
    )
    db = _patch_loaders(monkeypatch, release)

    result = asyncio.run(document_service.generate_checklist(db, release.release_id, "validation.owner@example.com"))

    generated_codes = {row.document_code for row in result.requirements}
    assert {"CHANGE_CONTROL", "REGRESSION_PROTOCOL", "REGRESSION_EVIDENCE"} <= generated_codes
    assert {"CONFIGURATION_SPECIFICATION", "OQ_PROTOCOL", "FRS", "SOP_TRAINING_REVIEW"} <= generated_codes
    assert "VALIDATION_PLAN" not in generated_codes


def test_no_validation_required_generates_minimal_justification_set(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(
        scope="NO_VALIDATION_REQUIRED",
        risk="NO_IMPACT",
        responses=[_response("GXP_IMPACT", "NO"), _response("REGRESSION_IMPACT", "NO")],
    )
    db = _patch_loaders(monkeypatch, release)

    result = asyncio.run(document_service.generate_checklist(db, release.release_id, "qa.user@example.com"))

    generated_codes = {row.document_code for row in result.requirements}
    assert generated_codes == {
        "RELEASE_NOTES",
        "IMPACT_ASSESSMENT",
        "RISK_ASSESSMENT",
        "NO_VALIDATION_JUSTIFICATION",
        "QA_APPROVAL_PLACEHOLDER",
    }


def test_repeated_generation_does_not_duplicate_active_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(scope="LIMITED_VALIDATION", risk="MEDIUM", responses=[_response("REGRESSION_IMPACT", "YES")])
    db = _patch_loaders(monkeypatch, release)

    first = asyncio.run(document_service.generate_checklist(db, release.release_id, "qa.user@example.com"))
    first_count = len(db.requirements)
    second = asyncio.run(document_service.generate_checklist(db, release.release_id, "qa.user@example.com"))

    assert first_count == len(db.requirements)
    assert len(second.requirements) == len(first.requirements)
    assert {requirement.generated_version for requirement in db.requirements} == {1}


def test_linked_approved_rows_are_preserved_during_regeneration(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(
        scope="LIMITED_VALIDATION",
        risk="MEDIUM",
        checklist_status="STALE",
        responses=[_response("GXP_IMPACT", "YES")],
    )
    existing = _requirement(release, "CHANGE_CONTROL", status="APPROVED", version=1)
    existing.linked_document_link_id = uuid.uuid4()
    db = _patch_loaders(monkeypatch, release, [existing])

    asyncio.run(document_service.generate_checklist(db, release.release_id, "qa.user@example.com"))

    assert existing.status == "APPROVED"
    assert existing.linked_document_link_id is not None
    assert existing.generated_version == 2


def test_documents_no_longer_required_become_obsolete(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(scope="LIMITED_VALIDATION", risk="MEDIUM", checklist_status="STALE")
    old_full_requirement = _requirement(release, "VALIDATION_PLAN", status="LINKED", version=1)
    db = _patch_loaders(monkeypatch, release, [old_full_requirement])

    asyncio.run(document_service.generate_checklist(db, release.release_id, "qa.user@example.com"))

    assert old_full_requirement.status in {"OBSOLETE", "NOT_REQUIRED"}
    assert old_full_requirement.required_flag is False


def test_non_waivable_document_waiver_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release()
    requirement = _requirement(release, "QA_APPROVAL", waivable=False)
    db = _patch_loaders(monkeypatch, release, [requirement])
    payload = DocumentRequirementWaiverRequest(waiver_reason="Not needed", approve=True)

    with pytest.raises(document_service.DocumentRequirementValidationError, match="non-waivable"):
        asyncio.run(
            document_service.request_or_approve_waiver(
                db,
                release.release_id,
                requirement.requirement_id,
                payload,
                "qa.user@example.com",
            )
        )


def test_waivable_document_waiver_with_justification_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release()
    requirement = _requirement(release, "ROLLBACK_PLAN", waivable=True, waiver_requires_qa=False)
    db = _patch_loaders(monkeypatch, release, [requirement])
    payload = DocumentRequirementWaiverRequest(waiver_reason="Superseded by release SOP", approve=False)

    result = asyncio.run(
        document_service.request_or_approve_waiver(
            db,
            release.release_id,
            requirement.requirement_id,
            payload,
            "qa.user@example.com",
        )
    )

    assert result.status == "WAIVED"
    assert requirement.waiver_reason == "Superseded by release SOP"
    assert requirement.waiver_approved_by == "qa.user@example.com"


def test_missing_required_documents_block_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(scope="LIMITED_VALIDATION", risk="MEDIUM", checklist_status="IN_PROGRESS")
    requirement = _requirement(release, "CHANGE_CONTROL", status="MISSING")
    db = _patch_loaders(monkeypatch, release, [requirement])

    with pytest.raises(document_service.DocumentRequirementValidationError) as exc_info:
        asyncio.run(document_service.complete_checklist(db, release.release_id, "qa.user@example.com"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.data["blockingRequirements"][0]["document_code"] == "CHANGE_CONTROL"


@pytest.mark.parametrize("status", ["REJECTED", "IN_REVIEW"])
def test_rejected_or_in_review_required_documents_block_completion(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    release = _release(scope="FULL_VALIDATION", risk="HIGH", checklist_status="IN_PROGRESS")
    requirement = _requirement(release, "VALIDATION_PLAN", status=status)
    db = _patch_loaders(monkeypatch, release, [requirement])

    with pytest.raises(document_service.DocumentRequirementValidationError):
        asyncio.run(document_service.complete_checklist(db, release.release_id, "qa.user@example.com"))


@pytest.mark.parametrize("scope", ["LIMITED_VALIDATION", "FULL_VALIDATION"])
def test_approved_required_documents_allow_limited_or_full_completion_to_testing(
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
) -> None:
    release = _release(scope=scope, risk="HIGH" if scope == "FULL_VALIDATION" else "MEDIUM", checklist_status="IN_PROGRESS")
    requirement = _requirement(release, "CHANGE_CONTROL", status="APPROVED")
    db = _patch_loaders(monkeypatch, release, [requirement])

    result = asyncio.run(document_service.complete_checklist(db, release.release_id, "qa.user@example.com"))

    assert result.nextStep == "TEST_EXECUTION"
    assert result.release_status == "TESTING_PENDING"
    assert result.package_status == "TESTING_PENDING"
    assert result.document_checklist_status == "COMPLETED"


def test_waived_required_documents_allow_completion_if_waivable(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(scope="FULL_VALIDATION", risk="HIGH", checklist_status="IN_PROGRESS")
    requirement = _requirement(release, "ROLLBACK_PLAN", status="WAIVED", waivable=True)
    db = _patch_loaders(monkeypatch, release, [requirement])

    result = asyncio.run(document_service.complete_checklist(db, release.release_id, "qa.user@example.com"))

    assert result.nextStep == "TEST_EXECUTION"


def test_complete_no_validation_required_moves_to_validation_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(scope="NO_VALIDATION_REQUIRED", risk="NO_IMPACT", checklist_status="IN_PROGRESS")
    requirement = _requirement(release, "NO_VALIDATION_JUSTIFICATION", status="APPROVED")
    db = _patch_loaders(monkeypatch, release, [requirement])

    result = asyncio.run(document_service.complete_checklist(db, release.release_id, "qa.user@example.com"))

    assert result.nextStep == "VALIDATION_SUMMARY"
    assert result.release_status == "VALIDATION_SUMMARY_PENDING"
    assert result.package_status == "VALIDATION_SUMMARY_PENDING"


def test_checklist_status_stale_blocks_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    release = _release(scope="LIMITED_VALIDATION", risk="MEDIUM", checklist_status="STALE")
    requirement = _requirement(release, "CHANGE_CONTROL", status="APPROVED")
    db = _patch_loaders(monkeypatch, release, [requirement])

    with pytest.raises(document_service.DocumentRequirementConflictError, match="stale"):
        asyncio.run(document_service.complete_checklist(db, release.release_id, "qa.user@example.com"))


def test_old_release_without_package_returns_controlled_error(monkeypatch: pytest.MonkeyPatch) -> None:
    release_id = uuid.uuid4()

    async def fake_get_release_with_package(db: object, requested_release_id: uuid.UUID) -> object:
        assert requested_release_id == release_id
        raise document_service.DocumentRequirementNotFoundError("Validation package not found for release")

    monkeypatch.setattr(document_service, "_get_release_with_package", fake_get_release_with_package)

    with pytest.raises(document_service.DocumentRequirementNotFoundError, match="Validation package"):
        asyncio.run(document_service.get_checklist(object(), release_id))  # type: ignore[arg-type]
