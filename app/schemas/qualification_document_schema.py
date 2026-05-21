import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _parse_document_datetime(value: object) -> object:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=UTC)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(stripped, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
    return value


class QualificationDocumentCreate(BaseModel):
    qualification_type: str = Field(..., min_length=1, max_length=10)
    asset_id: uuid.UUID | None = None
    release_id: uuid.UUID | None = None
    supplier_id: uuid.UUID
    document_name: str = Field(..., min_length=1, max_length=250)
    document_version: str | None = Field(default=None, max_length=50)
    source_system: str | None = Field(default=None, max_length=50)
    external_document_id: str | None = Field(default=None, max_length=150)
    document_url: str = Field(..., min_length=1)
    source_reference: str | None = Field(default=None, max_length=500)
    submission_date: datetime | None = None
    notes: str | None = None
    created_by: str | None = Field(default=None, max_length=150)

    @field_validator("submission_date", mode="before")
    @classmethod
    def parse_submission_date(cls, value: object) -> object:
        return _parse_document_datetime(value)

    @model_validator(mode="after")
    def validate_target(self) -> "QualificationDocumentCreate":
        if self.asset_id is None and self.release_id is None:
            raise ValueError("At least one of asset_id or release_id must be provided")
        return self


class QualificationDocumentUpdate(BaseModel):
    qualification_type: str | None = Field(default=None, min_length=1, max_length=10)
    asset_id: uuid.UUID | None = None
    release_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    document_name: str | None = Field(default=None, min_length=1, max_length=250)
    document_version: str | None = Field(default=None, max_length=50)
    source_system: str | None = Field(default=None, max_length=50)
    external_document_id: str | None = Field(default=None, max_length=150)
    document_url: str | None = Field(default=None, min_length=1)
    source_reference: str | None = Field(default=None, max_length=500)
    submission_date: datetime | None = None
    notes: str | None = None
    status: str | None = Field(default=None, min_length=1, max_length=30)
    modified_by: str | None = Field(default=None, max_length=150)

    @field_validator("submission_date", mode="before")
    @classmethod
    def parse_submission_date(cls, value: object) -> object:
        return _parse_document_datetime(value)


class QualificationDocumentWorkflowActionRequest(BaseModel):
    action_by: str | None = Field(default=None, max_length=150)
    comment_text: str | None = Field(default=None, max_length=5000)


class QualificationDocumentActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    qualification_document_id: uuid.UUID
    action_type: str
    action_by: str | None = None
    action_dt: datetime | None = None
    comment_text: str | None = None
    from_status: str
    to_status: str


class QualificationDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    qualification_document_id: uuid.UUID
    qualification_type: str
    status: str
    context_scope: str
    asset_id: uuid.UUID | None = None
    release_id: uuid.UUID | None = None
    supplier_id: uuid.UUID
    document_name: str
    document_version: str | None = None
    source_system: str | None = None
    external_document_id: str | None = None
    document_url: str
    source_reference: str | None = None
    submission_date: datetime | None = None
    notes: str | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None
    asset_name: str | None = None
    asset_code: str | None = None
    release_version: str | None = None
    supplier_name: str | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
