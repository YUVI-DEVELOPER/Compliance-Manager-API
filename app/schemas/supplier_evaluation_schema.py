import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class SupplierEvaluationCreate(BaseModel):
    evaluation_name: str = Field(..., min_length=1, max_length=250)
    asset_uuid: uuid.UUID
    urs_document_id: uuid.UUID
    supplier_ids: list[uuid.UUID] = Field(default_factory=list)
    created_by: str | None = Field(default=None, max_length=150)


class SupplierEvaluationUpdate(BaseModel):
    evaluation_name: str | None = Field(default=None, min_length=1, max_length=250)
    urs_document_id: uuid.UUID | None = None
    status: str | None = Field(default=None, min_length=1, max_length=30)
    modified_by: str | None = Field(default=None, max_length=150)


class SupplierEvaluationWorkflowActionRequest(BaseModel):
    action_by: str | None = Field(default=None, max_length=150)


class SupplierEvaluationResponseCreate(BaseModel):
    supplier_ids: list[uuid.UUID] = Field(..., min_length=1)
    created_by: str | None = Field(default=None, max_length=150)


class SupplierEvaluationResponseUpdate(BaseModel):
    quotation_reference: str | None = Field(default=None, max_length=250)
    notes: str | None = None
    modified_by: str | None = Field(default=None, max_length=150)


class SupplierEvaluationResponseSubmitRequest(BaseModel):
    action_by: str | None = Field(default=None, max_length=150)


class EvaluationRequirementSeedRequest(BaseModel):
    created_by: str | None = Field(default=None, max_length=150)


class EvaluationRequirementItemCreate(BaseModel):
    requirement_key: str | None = Field(default=None, max_length=100)
    requirement_section: str | None = Field(default=None, max_length=250)
    requirement_text: str = Field(..., min_length=1)
    requirement_order: int | None = Field(default=None, ge=0)
    source_reference: str | None = Field(default=None, max_length=500)
    created_by: str | None = Field(default=None, max_length=150)


class EvaluationRequirementItemUpdate(BaseModel):
    requirement_key: str | None = Field(default=None, max_length=100)
    requirement_section: str | None = Field(default=None, max_length=250)
    requirement_text: str | None = Field(default=None, min_length=1)
    requirement_order: int | None = Field(default=None, ge=0)
    source_reference: str | None = Field(default=None, max_length=500)
    modified_by: str | None = Field(default=None, max_length=150)


class SupplierRequirementResponseCreate(BaseModel):
    requirement_item_id: uuid.UUID
    fit_status: str = Field(..., min_length=1, max_length=30)
    supplier_response_text: str | None = None
    evidence_reference: str | None = Field(default=None, max_length=1000)
    notes: str | None = None
    created_by: str | None = Field(default=None, max_length=150)


class SupplierRequirementResponseUpdate(BaseModel):
    fit_status: str | None = Field(default=None, min_length=1, max_length=30)
    supplier_response_text: str | None = None
    evidence_reference: str | None = Field(default=None, max_length=1000)
    notes: str | None = None
    modified_by: str | None = Field(default=None, max_length=150)


class SupplierRequirementResponseBulkSaveItem(BaseModel):
    requirement_item_id: uuid.UUID
    fit_status: str | None = Field(default=None, min_length=1, max_length=30)
    supplier_response_text: str | None = None
    evidence_reference: str | None = Field(default=None, max_length=1000)
    notes: str | None = None


class SupplierRequirementResponseBulkSaveRequest(BaseModel):
    modified_by: str | None = Field(default=None, max_length=150)
    items: list[SupplierRequirementResponseBulkSaveItem] = Field(..., min_length=1)


class SupplierEvaluationAnalysisRunRequest(BaseModel):
    triggered_by: str | None = Field(default=None, max_length=150)


class SupplierResponseDocumentCreate(BaseModel):
    document_type: str = Field(..., min_length=1, max_length=30)
    source_system: str | None = Field(default=None, max_length=50)
    external_document_id: str | None = Field(default=None, max_length=150)
    document_name: str = Field(..., min_length=1, max_length=250)
    document_version: str | None = Field(default=None, max_length=50)
    upload_dt: datetime
    access_url: str = Field(..., min_length=1)
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    created_by: str | None = Field(default=None, max_length=150)

    @field_validator("upload_dt", mode="before")
    @classmethod
    def parse_upload_dt(cls, value: object) -> object:
        return _parse_document_datetime(value)


class SupplierResponseDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    response_id: uuid.UUID
    document_type: str
    source_system: str | None = None
    external_document_id: str | None = None
    document_name: str
    document_version: str | None = None
    upload_dt: datetime
    access_url: str
    source_reference: str | None = None
    notes: str | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class EvaluationRequirementItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    requirement_item_id: uuid.UUID
    evaluation_id: uuid.UUID
    urs_document_id: uuid.UUID
    requirement_key: str | None = None
    requirement_section: str | None = None
    requirement_text: str
    requirement_order: int | None = None
    source_reference: str | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class EvaluationRequirementSeedResult(BaseModel):
    created_count: int
    skipped_count: int
    strategy: str
    requirements: list[EvaluationRequirementItemResponse]


class SupplierRequirementResponseMatrixRow(BaseModel):
    requirement_item_id: uuid.UUID
    requirement_response_id: uuid.UUID | None = None
    response_id: uuid.UUID
    requirement_key: str | None = None
    requirement_section: str | None = None
    requirement_text: str
    requirement_order: int | None = None
    source_reference: str | None = None
    fit_status: str | None = None
    supplier_response_text: str | None = None
    evidence_reference: str | None = None
    notes: str | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None


class SupplierRequirementAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    analysis_id: uuid.UUID
    supplier_response_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    requirement_id: uuid.UUID
    requirement_key: str | None = None
    requirement_section: str | None = None
    requirement_text: str
    evaluated_fit: str
    structured_fit: str | None = None
    confidence_score: float
    reasoning_text: str
    evidence_reference: str | None = None
    created_at: datetime | None = None


class SupplierComparisonSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    analysis_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    supplier_type: str | None = None
    supplier_response_id: uuid.UUID | None = None
    overall_score: float
    meets_count: int = 0
    partially_meets_count: int = 0
    not_meets_count: int = 0
    total_requirements: int = 0
    meets_percent: float = 0
    partially_meets_percent: float = 0
    not_meets_percent: float = 0
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    recommendation_rank: int
    created_at: datetime | None = None


class SupplierEvaluationAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    analysis_id: uuid.UUID
    evaluation_id: uuid.UUID
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    triggered_by: str | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    input_snapshot_json: dict[str, Any] | None = None
    summary_json: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    requirement_analyses: list[SupplierRequirementAnalysisResponse] = Field(default_factory=list)
    comparison_summaries: list[SupplierComparisonSummaryResponse] = Field(default_factory=list)


class SupplierEvaluationAnalysisListResponse(BaseModel):
    latest: SupplierEvaluationAnalysisResponse | None = None
    history: list[SupplierEvaluationAnalysisResponse] = Field(default_factory=list)


class SupplierEvaluationComparisonResponse(BaseModel):
    analysis_id: uuid.UUID | None = None
    evaluation_id: uuid.UUID
    status: str
    summary_json: dict[str, Any] | None = None
    comparison_summaries: list[SupplierComparisonSummaryResponse] = Field(default_factory=list)
    requirement_analyses: list[SupplierRequirementAnalysisResponse] = Field(default_factory=list)


class SupplierEvaluationResponseSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    response_id: uuid.UUID
    evaluation_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    supplier_type: str | None = None
    submission_status: str
    quotation_reference: str | None = None
    submitted_at: datetime | None = None
    submitted_by: str | None = None
    notes: str | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None
    document_count: int = 0


class SupplierEvaluationResponseDetail(SupplierEvaluationResponseSummary):
    evaluation_status: str
    documents: list[SupplierResponseDocumentResponse] = Field(default_factory=list)


class SupplierEvaluationResponseCreateResult(BaseModel):
    created_count: int
    responses: list[SupplierEvaluationResponseSummary]


class SupplierEvaluationResponseLockResult(BaseModel):
    locked_count: int
    responses: list[SupplierEvaluationResponseSummary]


class SupplierEvaluationResponseBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evaluation_id: uuid.UUID
    evaluation_name: str
    asset_uuid: uuid.UUID
    asset_name: str | None = None
    asset_code: str | None = None
    urs_document_id: uuid.UUID
    urs_title: str | None = None
    urs_status: str | None = None
    urs_release_id: uuid.UUID | None = None
    urs_release_version: str | None = None
    status: str
    opened_at: datetime | None = None
    locked_at: datetime | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None
    response_count: int = 0
    submitted_response_count: int = 0
    locked_response_count: int = 0


class SupplierEvaluationSummary(SupplierEvaluationResponseBase):
    pass


class SupplierEvaluationDetail(SupplierEvaluationResponseBase):
    pass


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
