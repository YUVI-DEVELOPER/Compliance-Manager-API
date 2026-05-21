import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentTemplateCreate(BaseModel):
    template_code: str = Field(..., min_length=1, max_length=100)
    template_name: str = Field(..., min_length=1, max_length=150)
    document_type: str = Field(..., min_length=1, max_length=50)
    template_content: str = Field(..., min_length=1)
    is_active: bool = True
    created_by: str | None = Field(default=None, max_length=150)


class DocumentTemplateUpdate(BaseModel):
    template_code: str | None = Field(default=None, min_length=1, max_length=100)
    template_name: str | None = Field(default=None, min_length=1, max_length=150)
    document_type: str | None = Field(default=None, min_length=1, max_length=50)
    template_content: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None
    modified_by: str | None = Field(default=None, max_length=150)


class DocumentTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    template_id: uuid.UUID
    template_code: str
    template_name: str
    document_type: str
    template_content: str
    is_active: bool
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class AuthoredDocumentCreateFromTemplateRequest(BaseModel):
    document_type: str = Field(..., min_length=1, max_length=50)
    template_id: uuid.UUID | None = None
    template_code: str | None = Field(default=None, min_length=1, max_length=100)
    asset_id: uuid.UUID | None = None
    release_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=250)
    purpose_notes: str | None = None
    special_instructions: str | None = None
    source_document_url: str | None = None
    source_document_name: str | None = Field(default=None, max_length=250)
    source_document_relative_path: str | None = Field(default=None, max_length=1000)
    source_urs_text: str | None = None
    created_by: str | None = Field(default=None, max_length=150)

    @model_validator(mode="after")
    def validate_template_and_target(self) -> "AuthoredDocumentCreateFromTemplateRequest":
        has_template_id = self.template_id is not None
        has_template_code = self.template_code is not None and bool(self.template_code.strip())
        if has_template_id == has_template_code:
            raise ValueError("Exactly one of template_id or template_code must be provided")

        has_asset_id = self.asset_id is not None
        has_release_id = self.release_id is not None
        if has_asset_id == has_release_id:
            raise ValueError("Exactly one of asset_id or release_id must be provided")

        return self


class AuthoredDocumentCreateAiDraftRequest(BaseModel):
    document_type: str = Field(..., min_length=1, max_length=50)
    template_id: uuid.UUID | None = None
    template_code: str | None = Field(default=None, min_length=1, max_length=100)
    asset_id: uuid.UUID | None = None
    release_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=250)
    purpose_notes: str | None = None
    special_instructions: str | None = None
    source_document_url: str | None = None
    source_document_name: str | None = Field(default=None, max_length=250)
    source_document_relative_path: str | None = Field(default=None, max_length=1000)
    source_urs_text: str | None = None
    created_by: str | None = Field(default=None, max_length=150)
    fallback_to_template_prefill: bool = True

    @model_validator(mode="after")
    def validate_template_and_target(self) -> "AuthoredDocumentCreateAiDraftRequest":
        has_template_id = self.template_id is not None
        has_template_code = self.template_code is not None and bool(self.template_code.strip())
        if has_template_id == has_template_code:
            raise ValueError("Exactly one of template_id or template_code must be provided")

        has_asset_id = self.asset_id is not None
        has_release_id = self.release_id is not None
        if has_asset_id == has_release_id:
            raise ValueError("Exactly one of asset_id or release_id must be provided")

        return self


class AuthoredDocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=250)
    content: str | None = Field(default=None, min_length=1)
    status: str | None = Field(default=None, min_length=1, max_length=30)
    modified_by: str | None = Field(default=None, max_length=150)


class AuthoredDocumentWorkflowActionRequest(BaseModel):
    action_by: str | None = Field(default=None, max_length=150)
    comment_text: str | None = Field(default=None, max_length=5000)
    reviewer_name: str | None = Field(default=None, max_length=150)
    approver_name: str | None = Field(default=None, max_length=150)


class AuthoredDocumentAiRegenerateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=250)
    existing_content: str | None = None
    purpose_notes: str | None = None
    special_instructions: str | None = None
    modified_by: str | None = Field(default=None, max_length=150)
    operation: Literal["REGENERATE", "IMPROVE"] = "REGENERATE"


class AuthoredDocumentCommentRequest(BaseModel):
    action_by: str | None = Field(default=None, max_length=150)
    comment_text: str = Field(..., min_length=1, max_length=5000)


class AuthoredDocumentPublishRequest(BaseModel):
    action_by: str | None = Field(default=None, max_length=150)


class AuthoredDocumentReviewActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    authored_document_id: uuid.UUID
    action_type: str
    action_by: str | None = None
    action_dt: datetime | None = None
    comment_text: str | None = None
    from_status: str
    to_status: str


class AuthoredDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    authored_document_id: uuid.UUID
    document_type: str
    title: str
    status: str
    asset_id: uuid.UUID | None = None
    release_id: uuid.UUID | None = None
    template_id: uuid.UUID
    template_code: str | None = None
    template_name: str | None = None
    content: str
    source_context_json: dict[str, Any] | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None
    reviewer_name: str | None = None
    approver_name: str | None = None
    publish_status: str
    last_publish_attempt_at: datetime | None = None
    last_publish_attempt_by: str | None = None
    published_at: datetime | None = None
    published_by: str | None = None
    external_system: str | None = None
    external_document_id: str | None = None
    external_document_name: str | None = None
    external_document_version: str | None = None
    external_document_url: str | None = None
    external_source_reference: str | None = None
    publish_error_message: str | None = None
    asset_name: str | None = None
    asset_code: str | None = None
    release_version: str | None = None
    generation_mode: str | None = None
    generation_requested_mode: str | None = None
    generation_status: str | None = None
    generation_operation: str | None = None
    generation_provider: str | None = None
    generation_model: str | None = None
    generation_fallback_reason: str | None = None
    last_generated_at: datetime | None = None


class AuthoredDocumentPublishStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    authored_document_id: uuid.UUID
    document_type: str
    document_status: str
    publish_status: str
    last_publish_attempt_at: datetime | None = None
    last_publish_attempt_by: str | None = None
    published_at: datetime | None = None
    published_by: str | None = None
    external_system: str | None = None
    external_document_id: str | None = None
    external_document_name: str | None = None
    external_document_version: str | None = None
    external_document_url: str | None = None
    external_source_reference: str | None = None
    publish_error_message: str | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
