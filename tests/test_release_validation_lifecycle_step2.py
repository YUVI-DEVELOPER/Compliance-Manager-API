from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.release_impact_questions import get_release_impact_question_map, get_release_impact_questions
from app.services import llm_gateway
from app.services import release_impact_assessment_service as assessment_service
from app.services.llm_gateway import LLMGatewayError, LLMGatewayUnavailableError, Step2LLMGateway
from app.services.release_impact_assessment_service import get_questions
from app.services.release_impact_scoring_service import (
    ImpactResponseForScoring,
    RISK_LEVEL_HIGH,
    RISK_LEVEL_MEDIUM,
    RISK_LEVEL_NO_IMPACT,
    VALIDATION_SCOPE_FULL_VALIDATION,
    VALIDATION_SCOPE_LIMITED_VALIDATION,
    VALIDATION_SCOPE_NO_VALIDATION_REQUIRED,
    calculate_impact_assessment_score,
)


def _response(question_code: str, answer: str, rationale: str | None = "Controlled rationale") -> ImpactResponseForScoring:
    return ImpactResponseForScoring(question_code=question_code, answer=answer, rationale=rationale)


def _score(*responses: ImpactResponseForScoring):
    return calculate_impact_assessment_score(get_release_impact_questions(), responses)


def test_question_metadata_returned_from_backend_service() -> None:
    questions = get_questions()

    assert len(questions) == 13
    assert questions[0].questionCode == "GXP_IMPACT"
    assert questions[0].critical is True
    assert questions[0].mandatory is True
    assert questions[-1].questionCode == "REGRESSION_IMPACT"


def test_all_no_and_na_returns_no_impact_scope() -> None:
    question_map = get_release_impact_question_map()
    responses = []
    for code, question in question_map.items():
        answer = "NOT_APPLICABLE" if question.critical else "NO"
        rationale = "Not applicable to this critical control." if question.critical else None
        responses.append(_response(code, answer, rationale))

    result = _score(*responses)

    assert result.total_score == 0
    assert result.risk_level == RISK_LEVEL_NO_IMPACT
    assert result.validation_scope == VALIDATION_SCOPE_NO_VALIDATION_REQUIRED
    assert result.validation_errors == []


def test_critical_yes_forces_high_and_full_validation() -> None:
    result = _score(_response("AUDIT_TRAIL", "YES", "Audit trail export behavior may change."))

    assert result.total_score == 5
    assert result.risk_level == RISK_LEVEL_HIGH
    assert result.validation_scope == VALIDATION_SCOPE_FULL_VALIDATION


def test_critical_unknown_forces_high_and_full_validation() -> None:
    result = _score(_response("DATA_INTEGRITY", "UNKNOWN", "Release notes do not clarify data handling."))

    assert result.total_score == 5
    assert result.risk_level == RISK_LEVEL_HIGH
    assert result.validation_scope == VALIDATION_SCOPE_FULL_VALIDATION


def test_medium_score_maps_to_limited_validation_without_critical_risk() -> None:
    result = _score(
        _response("SECURITY_ACCESS", "YES", "Role behavior changes."),
        _response("WORKFLOW", "YES", "Approval routing changes."),
    )

    assert result.total_score == 8
    assert result.risk_level == RISK_LEVEL_MEDIUM
    assert result.validation_scope == VALIDATION_SCOPE_LIMITED_VALIDATION


def test_missing_mandatory_answer_blocks_completion() -> None:
    result = _score(_response("SECURITY_ACCESS", "NO"))

    assert "GXP_IMPACT" in result.missing_answers
    assert any(issue.field == "answer" for issue in result.validation_errors)


def test_initialize_assessment_returns_existing_after_unique_race(monkeypatch: pytest.MonkeyPatch) -> None:
    release_id = uuid.uuid4()
    package_id = uuid.uuid4()
    assessment_id = uuid.uuid4()
    now = datetime(2026, 5, 24, tzinfo=UTC)
    release = SimpleNamespace(
        release_id=release_id,
        release_status="IMPACT_ASSESSMENT_PENDING",
        asset=None,
    )
    package = SimpleNamespace(
        package_id=package_id,
        release_id=release_id,
        package_no="VAL-PKG-2026-0007",
        package_status="DRAFT",
        impact_assessment_status="PENDING",
        release=release,
        impact_assessment=None,
        modified_by=None,
        modified_dt=None,
    )
    release.validation_package = package
    existing_assessment = SimpleNamespace(
        assessment_id=assessment_id,
        package_id=package_id,
        assessment_no="VAL-IA-2026-0003",
        status="DRAFT",
        total_score=0,
        risk_level="NOT_ASSESSED",
        validation_scope="NOT_ASSESSED",
        summary="Impact assessment draft initialized.",
        created_by="qa.user@example.com",
        created_at=now,
        updated_by="qa.user@example.com",
        updated_at=now,
        completed_by=None,
        completed_at=None,
        reopened_by=None,
        reopened_at=None,
        reopen_reason=None,
        package=package,
        responses=[],
    )

    class _RaceDb:
        rollback_called = False

        def add(self, obj: object) -> None:
            return None

        async def commit(self) -> None:
            raise IntegrityError("INSERT", {}, Exception("uq_release_validation_impact_assessment_package"))

        async def rollback(self) -> None:
            self.rollback_called = True

    async def fake_get_release_with_package(db: object, requested_release_id: uuid.UUID) -> object:
        assert requested_release_id == release_id
        return release

    async def fake_generate_assessment_no(db: object, reference_dt: datetime) -> str:
        return "VAL-IA-2026-0004"

    async def fake_get_assessment_by_package_id(db: _RaceDb, requested_package_id: uuid.UUID) -> object | None:
        assert requested_package_id == package_id
        return existing_assessment if db.rollback_called else None

    monkeypatch.setattr(assessment_service, "_get_release_with_package", fake_get_release_with_package)
    monkeypatch.setattr(assessment_service, "_generate_assessment_no", fake_generate_assessment_no)
    monkeypatch.setattr(assessment_service, "_get_assessment_by_package_id", fake_get_assessment_by_package_id)

    result = asyncio.run(
        assessment_service.initialize_assessment(_RaceDb(), release_id, "qa.user@example.com")
    )

    assert result.assessmentId == assessment_id
    assert result.validationPackageId == package_id
    assert result.status == "DRAFT"


def test_yes_unknown_and_critical_na_require_rationale() -> None:
    result = _score(
        _response("WORKFLOW", "YES", None),
        _response("INFRASTRUCTURE", "UNKNOWN", ""),
        _response("AUDIT_TRAIL", "NOT_APPLICABLE", None),
    )

    rationale_errors = [issue for issue in result.validation_errors if issue.field == "rationale"]
    assert {issue.question_code for issue in rationale_errors} >= {"WORKFLOW", "INFRASTRUCTURE", "AUDIT_TRAIL"}


def test_step2_ai_disabled_is_controlled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = llm_gateway.get_settings()
    monkeypatch.setattr(settings, "STEP2_AI_ASSISTANT_ENABLED", False, raising=False)

    gateway = Step2LLMGateway()

    with pytest.raises(LLMGatewayUnavailableError, match="disabled"):
        asyncio.run(gateway.generate_json(system_prompt="Return JSON only.", user_payload={}))


def test_step2_ai_invalid_json_is_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = llm_gateway.get_settings()
    monkeypatch.setattr(settings, "STEP2_AI_ASSISTANT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "STEP2_AI_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "STEP2_AI_MODEL", "test-model", raising=False)
    monkeypatch.setattr(settings, "STEP2_AI_BASE_URL", "https://example.invalid/v1", raising=False)

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "not json"}}]}

    class _FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, *args: object, **kwargs: object) -> _FakeResponse:
            return _FakeResponse()

    monkeypatch.setattr(llm_gateway.httpx, "AsyncClient", _FakeAsyncClient)

    gateway = Step2LLMGateway()

    with pytest.raises(LLMGatewayError, match="valid JSON"):
        asyncio.run(gateway.generate_json(system_prompt="Return JSON only.", user_payload={}))
