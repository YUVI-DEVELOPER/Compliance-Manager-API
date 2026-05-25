from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class DocumentRequirementRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    requirement_id: uuid.UUID
    release_id: uuid.UUID
    package_id: uuid.UUID
    document_code: str
    document_name: str
    document_category: str
    document_description: str | None = None
    requirement_level: str
    required_flag: bool
    waivable_flag: bool
    waiver_requires_qa_flag: bool
    status: str
    owner_role: str | None = None
    owner_user_id: uuid.UUID | None = None
    source_type: str | None = None
    linked_document_link_id: uuid.UUID | None = None
    linked_authored_document_id: uuid.UUID | None = None
    linked_qualification_document_id: uuid.UUID | None = None
    file_name: str | None = None
    file_path: str | None = None
    external_url: str | None = None
    waiver_reason: str | None = None
    waiver_requested_by: str | None = None
    waiver_requested_at: datetime | None = None
    waiver_approved_by: str | None = None
    waiver_approved_at: datetime | None = None
    trigger_scope: str | None = None
    trigger_risk_level: str | None = None
    trigger_question_codes_json: list[str] | None = None
    trigger_reason: str | None = None
    generated_version: int
    is_active: bool
    display_order: int
    available_actions: list[str] = Field(default_factory=list)


class DocumentRequirementSummary(BaseModel):
    total: int = 0
    required: int = 0
    conditional: int = 0
    optional: int = 0
    approved: int = 0
    missing: int = 0
    in_review: int = 0
    rejected: int = 0
    waived: int = 0
    not_required: int = 0
    obsolete: int = 0
    blocking_count: int = 0
    can_complete: bool = False


class DocumentRequirementGenerateResponse(BaseModel):
    release_id: uuid.UUID
    validation_package_id: uuid.UUID
    package_no: str
    release_status: str | None = None
    package_status: str
    validation_scope: str
    risk_level: str
    document_checklist_status: str
    summary: DocumentRequirementSummary
    requirements: list[DocumentRequirementRow] = Field(default_factory=list)
    nextStep: str


class DocumentRequirementLinkRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_type: str | None = Field(
        default=None,
        validation_alias=AliasChoices("source_type", "sourceType"),
    )
    linked_document_link_id: uuid.UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("linked_document_link_id", "linkedDocumentLinkId"),
    )
    linked_authored_document_id: uuid.UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("linked_authored_document_id", "linkedAuthoredDocumentId"),
    )
    linked_qualification_document_id: uuid.UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("linked_qualification_document_id", "linkedQualificationDocumentId"),
    )
    file_name: str | None = Field(default=None, validation_alias=AliasChoices("file_name", "fileName"))
    file_path: str | None = Field(default=None, validation_alias=AliasChoices("file_path", "filePath"))
    external_url: str | None = Field(default=None, validation_alias=AliasChoices("external_url", "externalUrl"))
    status: str | None = None

    @field_validator("source_type", "file_name", "file_path", "external_url", "status")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("source_type", "status")
    @classmethod
    def normalize_optional_code(cls, value: str | None) -> str | None:
        normalized = _normalize_optional_text(value)
        return normalized.upper() if normalized is not None else None


class DocumentRequirementStatusUpdateRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("status is required")
        return normalized


class DocumentRequirementWaiverRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    waiver_reason: str = Field(validation_alias=AliasChoices("waiver_reason", "waiverReason"))
    approve: bool = False

    @field_validator("waiver_reason")
    @classmethod
    def normalize_waiver_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("waiver_reason is required")
        return normalized


class DocumentRequirementCompleteResponse(BaseModel):
    release_id: uuid.UUID
    validation_package_id: uuid.UUID
    package_no: str
    release_status: str | None = None
    package_status: str
    validation_scope: str
    risk_level: str
    document_checklist_status: str
    summary: DocumentRequirementSummary
    requirements: list[DocumentRequirementRow] = Field(default_factory=list)
    blocking_requirements: list[DocumentRequirementRow] = Field(default_factory=list)
    nextStep: str
