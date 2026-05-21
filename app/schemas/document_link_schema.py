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
        for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(stripped, fmt).replace(tzinfo=UTC)
            except ValueError:
                continue
    return value


class DocumentLinkCreate(BaseModel):
    source_system: str = Field(..., min_length=1, max_length=50)
    document_type: str = Field(..., min_length=1, max_length=50)
    external_document_id: str = Field(..., min_length=1, max_length=150)
    document_name: str = Field(..., min_length=1, max_length=250)
    document_version: str = Field(..., min_length=1, max_length=50)
    upload_dt: datetime
    access_url: str = Field(..., min_length=1)
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    created_by: str | None = Field(default=None, max_length=150)

    @field_validator("upload_dt", mode="before")
    @classmethod
    def parse_upload_dt(cls, value: object) -> object:
        return _parse_document_datetime(value)


class DocumentLinkUpdate(BaseModel):
    source_system: str | None = Field(default=None, min_length=1, max_length=50)
    document_type: str | None = Field(default=None, min_length=1, max_length=50)
    external_document_id: str | None = Field(default=None, min_length=1, max_length=150)
    document_name: str | None = Field(default=None, min_length=1, max_length=250)
    document_version: str | None = Field(default=None, min_length=1, max_length=50)
    upload_dt: datetime | None = None
    access_url: str | None = Field(default=None, min_length=1)
    source_reference: str | None = Field(default=None, max_length=500)
    notes: str | None = None
    modified_by: str | None = Field(default=None, max_length=150)

    @field_validator("upload_dt", mode="before")
    @classmethod
    def parse_upload_dt(cls, value: object) -> object:
        return _parse_document_datetime(value)


class DocumentAiAutofillAnalyzeRequest(BaseModel):
    access_url: str | None = Field(default=None, min_length=1)
    relative_path: str | None = Field(default=None, min_length=1, max_length=1000)
    file_name: str | None = Field(default=None, min_length=1, max_length=500)
    original_file_name: str | None = Field(default=None, min_length=1, max_length=500)


class DocumentAiAutofillAnalyzeResponse(BaseModel):
    document_type: str | None = None
    external_document_id: str | None = None
    document_version: str | None = None
    confidence: dict[str, float] = Field(default_factory=dict)
    extraction_source: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentVectorizationJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rag_document_id: str | None = None
    status: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    requested_at: datetime | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    queue_started_at: datetime | None = None
    chunking_started_at: datetime | None = None
    chunking_completed_at: datetime | None = None
    embedding_started_at: datetime | None = None
    embedding_completed_at: datetime | None = None
    weaviate_write_started_at: datetime | None = None
    weaviate_write_completed_at: datetime | None = None
    current_stage: str | None = None
    process_log_json: list[dict[str, Any]] = Field(default_factory=list)
    chunk_count: int | None = None
    weaviate_collection: str | None = None
    is_active: bool = True
    can_reprocess: bool = False


class DocumentLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_link_id: uuid.UUID
    asset_id: uuid.UUID | None = None
    release_id: uuid.UUID | None = None
    source_system: str
    document_type: str | None = None
    external_document_id: str
    document_name: str
    document_version: str
    upload_dt: datetime
    access_url: str
    source_reference: str | None = None
    notes: str | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None
    asset_name: str | None = None
    asset_code: str | None = None
    release_version: str | None = None
    vectorization_status: str | None = None
    vectorization_job: DocumentVectorizationJobResponse | None = None


class AssetVectorizationSummaryResponse(BaseModel):
    asset_id: uuid.UUID
    total_linked_documents: int = 0
    tracked_document_count: int = 0
    total_vectorized_documents: int = 0
    pending_or_queued_count: int = 0
    processing_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    unsupported_count: int = 0
    total_chunk_count: int = 0
    last_requested_at: datetime | None = None
    last_completed_at: datetime | None = None


class AssetVectorizationDocumentResponse(BaseModel):
    document_link_id: uuid.UUID
    asset_id: uuid.UUID | None = None
    release_id: uuid.UUID | None = None
    release_version: str | None = None
    source_context: str
    source_system: str
    document_type: str | None = None
    external_document_id: str
    document_name: str
    document_version: str
    upload_dt: datetime
    access_url: str
    source_reference: str | None = None
    notes: str | None = None
    created_dt: datetime | None = None
    modified_dt: datetime | None = None
    original_file_name: str | None = None
    stored_file_name: str | None = None
    stored_relative_path: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    extension: str | None = None
    vectorization_status: str | None = None
    chunk_count: int | None = None
    requested_at: datetime | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    current_stage: str | None = None
    collection_name: str | None = None
    last_error: str | None = None
    can_reprocess: bool = False
    vectorization_job: DocumentVectorizationJobResponse | None = None


class DocumentVectorizationChunkResponse(BaseModel):
    chunk_id: str
    page: int | None = None
    section_name: str | None = None
    section_path: str | None = None
    chunk_length: int
    word_count: int
    preview_text: str
    text: str
    category: str | None = None
    duplicate: bool | None = None
    match_percentage: float | None = None


class DocumentVectorizationChunkListResponse(BaseModel):
    document_link_id: uuid.UUID
    status: str | None = None
    chunks: list[DocumentVectorizationChunkResponse]
    total: int
    limit: int
    offset: int
    search: str | None = None
    collection_name: str | None = None
    retrieval_error: str | None = None


class DocumentVectorizationReportResponse(BaseModel):
    document_link_id: uuid.UUID
    report: dict[str, Any]


class DocumentRagProcessStageResponse(BaseModel):
    key: str
    label: str
    status: str
    timestamp: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DocumentRagProcessResponse(BaseModel):
    document_link_id: uuid.UUID
    status: str | None = None
    current_stage: str | None = None
    stages: list[DocumentRagProcessStageResponse]
    process_log: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
