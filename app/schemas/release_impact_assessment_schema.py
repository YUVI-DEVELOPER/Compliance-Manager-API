from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.services.release_impact_scoring_service import ALLOWED_IMPACT_ANSWERS


CONFIDENCE_VALUES = {"LOW", "MEDIUM", "HIGH"}


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_answer(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in ALLOWED_IMPACT_ANSWERS:
        allowed = ", ".join(sorted(ALLOWED_IMPACT_ANSWERS))
        raise ValueError(f"answer must be one of: {allowed}")
    return normalized


class ImpactQuestionSchema(BaseModel):
    questionCode: str
    category: str
    questionText: str
    weight: int
    critical: bool
    mandatory: bool


class ImpactResponseInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    questionCode: str = Field(validation_alias=AliasChoices("questionCode", "question_code"))
    answer: str
    rationale: str | None = None
    evidenceReference: str | None = Field(
        default=None,
        validation_alias=AliasChoices("evidenceReference", "evidence_reference"),
    )

    @field_validator("answer")
    @classmethod
    def normalize_answer(cls, value: str) -> str:
        return _normalize_answer(value)

    @field_validator("rationale", "evidenceReference")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class ImpactResponsesSaveRequest(BaseModel):
    responses: list[ImpactResponseInput] = Field(default_factory=list)


class ImpactResponseSchema(BaseModel):
    responseId: uuid.UUID | None = None
    assessmentId: uuid.UUID | None = None
    questionCode: str
    category: str
    questionText: str
    answer: str | None = None
    weight: int
    critical: bool
    mandatory: bool
    score: int = 0
    rationale: str | None = None
    evidenceReference: str | None = None
    answeredBy: str | None = None
    answeredAt: datetime | None = None
    createdAt: datetime | None = None
    updatedAt: datetime | None = None


class ImpactValidationErrorSchema(BaseModel):
    questionCode: str
    field: str
    message: str


class ImpactAssessmentSummary(BaseModel):
    assessmentId: uuid.UUID
    releaseId: uuid.UUID
    validationPackageId: uuid.UUID
    assessmentNo: str
    status: str
    totalScore: int
    riskLevel: str
    validationScope: str
    summary: str | None = None
    packageStatus: str | None = None
    releaseStatus: str | None = None
    impactAssessmentStatus: str | None = None
    nextStep: str | None = None


class ImpactAssessmentDetail(ImpactAssessmentSummary):
    packageNo: str
    createdBy: str | None = None
    createdAt: datetime | None = None
    updatedBy: str | None = None
    updatedAt: datetime | None = None
    completedBy: str | None = None
    completedAt: datetime | None = None
    reopenedBy: str | None = None
    reopenedAt: datetime | None = None
    reopenReason: str | None = None
    questions: list[ImpactQuestionSchema] = Field(default_factory=list)
    responses: list[ImpactResponseSchema] = Field(default_factory=list)
    missingAnswers: list[str] = Field(default_factory=list)
    validationErrors: list[ImpactValidationErrorSchema] = Field(default_factory=list)
    aiAssistantEnabled: bool = False
    canReopen: bool = False


class ImpactAssessmentSaveResult(ImpactAssessmentSummary):
    responses: list[ImpactResponseSchema] = Field(default_factory=list)
    missingAnswers: list[str] = Field(default_factory=list)
    validationErrors: list[ImpactValidationErrorSchema] = Field(default_factory=list)


class ImpactAssessmentCompleteResult(BaseModel):
    assessmentId: uuid.UUID
    releaseId: uuid.UUID
    validationPackageId: uuid.UUID
    status: str
    totalScore: int
    riskLevel: str
    validationScope: str
    releaseStatus: str
    packageStatus: str
    nextStep: str
    summary: str


class ImpactAssessmentReopenRequest(BaseModel):
    reason: str = Field(..., min_length=1)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason is required")
        return normalized


class ImpactAssessmentAISuggestRequest(BaseModel):
    additionalContext: str | None = None
    includeDocumentationText: bool = True

    @field_validator("additionalContext")
    @classmethod
    def normalize_additional_context(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class ImpactAssessmentAISuggestion(BaseModel):
    questionCode: str
    suggestedAnswer: str
    suggestedRationale: str | None = None
    confidence: str
    evidenceReference: str | None = None
    caveat: str | None = None
    sourceFieldsUsed: list[str] = Field(default_factory=list)

    @field_validator("suggestedAnswer")
    @classmethod
    def normalize_suggested_answer(cls, value: str) -> str:
        return _normalize_answer(value)

    @field_validator("confidence")
    @classmethod
    def normalize_confidence(cls, value: str) -> str:
        normalized = value.strip().upper()
        return normalized if normalized in CONFIDENCE_VALUES else "LOW"


class ImpactAssessmentAISuggestResponse(BaseModel):
    aiEnabled: bool
    assessmentId: uuid.UUID | None = None
    releaseId: uuid.UUID
    validationPackageId: uuid.UUID
    modelName: str | None = None
    provider: str | None = None
    promptVersion: str
    suggestions: list[ImpactAssessmentAISuggestion] = Field(default_factory=list)
    message: str | None = None
    rawResponse: dict[str, Any] | None = None
