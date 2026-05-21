import uuid
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AUDIT_REVIEW_STATUS_CREATED = "CREATED"
AUDIT_REVIEW_STATUS_EXTRACTING = "EXTRACTING"
AUDIT_REVIEW_STATUS_EXTRACTED = "EXTRACTED"
AUDIT_REVIEW_STATUS_PARTIAL_EXTRACTION = "PARTIAL_EXTRACTION"
AUDIT_REVIEW_STATUS_ANALYZING = "ANALYZING"
AUDIT_REVIEW_STATUS_ANALYZED = "ANALYZED"
AUDIT_REVIEW_STATUS_REPORT_GENERATING = "REPORT_GENERATING"
AUDIT_REVIEW_STATUS_REPORT_DRAFTED = "REPORT_DRAFTED"
AUDIT_REVIEW_STATUS_FAILED = "FAILED"
AUDIT_REVIEW_STATUS_CANCELLED = "CANCELLED"
AUDIT_REVIEW_REPORT_STATUS_DRAFT = "DRAFT"
AUDIT_REVIEW_REPORT_STATUS_UNDER_REVIEW = "UNDER_REVIEW"
AUDIT_REVIEW_REPORT_STATUS_APPROVED = "APPROVED"
AUDIT_REVIEW_REPORT_STATUS_REJECTED = "REJECTED"
AUDIT_REVIEW_REPORT_STATUS_CHANGES_REQUESTED = "CHANGES_REQUESTED"
AUDIT_REVIEW_REPORT_STATUS_SUPERSEDED = "SUPERSEDED"
DEFAULT_AUDIT_TRAIL_TYPE = "login_audit_trail"
DEFAULT_REVIEW_SCOPE = "LOGIN_ONLY"
AUDIT_REVIEW_SCHEDULE_FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "HALF_YEARLY", "ANNUAL"}
AUDIT_REVIEW_SCHEDULE_END_CONDITIONS = {"NO_END_DATE", "END_ON_DATE", "END_AFTER_RUNS"}
AUDIT_REVIEW_RETRIEVAL_MODES = {"AUTO", "SINCE_LAST_SUCCESSFUL", "CUSTOM"}
AUDIT_REVIEW_SCHEDULE_CYCLE_TYPES = {
    "CALENDAR_QUARTER",
    "CUSTOM_QUARTER_CYCLE",
    "CALENDAR_HALF_YEAR",
    "CUSTOM_SIX_MONTH_CYCLE",
    "CALENDAR_YEAR",
    "FISCAL_YEAR",
}
AUDIT_REVIEW_SCHEDULE_RUN_TIMINGS = {"FIRST_DAY_AFTER_PERIOD_END", "CUSTOM_RUN_DAY"}
AUDIT_REVIEW_SCHEDULE_RUN_STATUS_STARTED = "STARTED"
AUDIT_REVIEW_SCHEDULE_RUN_STATUS_COMPLETED = "COMPLETED"
AUDIT_REVIEW_SCHEDULE_RUN_STATUS_FAILED = "FAILED"
AUDIT_REVIEW_SCHEDULE_RUN_STATUS_SKIPPED = "SKIPPED"
AUDIT_REVIEW_NOTIFICATION_STATUS_PENDING = "PENDING"
AUDIT_REVIEW_NOTIFICATION_STATUS_READY = "READY"
AUDIT_REVIEW_NOTIFICATION_STATUS_SENT = "SENT"
AUDIT_REVIEW_NOTIFICATION_STATUS_FAILED = "FAILED"
AUDIT_REVIEW_NOTIFICATION_STATUS_DISMISSED = "DISMISSED"
AUDIT_REVIEW_NOTIFICATION_STATUSES = {
    AUDIT_REVIEW_NOTIFICATION_STATUS_PENDING,
    AUDIT_REVIEW_NOTIFICATION_STATUS_READY,
    AUDIT_REVIEW_NOTIFICATION_STATUS_SENT,
    AUDIT_REVIEW_NOTIFICATION_STATUS_FAILED,
    AUDIT_REVIEW_NOTIFICATION_STATUS_DISMISSED,
}
AUDIT_REVIEW_NOTIFICATION_CHANNEL_IN_APP = "IN_APP"
AUDIT_REVIEW_NOTIFICATION_CHANNEL_EMAIL = "EMAIL"
AUDIT_REVIEW_NOTIFICATION_CHANNEL_BOTH = "BOTH"
AUDIT_REVIEW_NOTIFICATION_CHANNELS = {
    AUDIT_REVIEW_NOTIFICATION_CHANNEL_IN_APP,
    AUDIT_REVIEW_NOTIFICATION_CHANNEL_EMAIL,
    AUDIT_REVIEW_NOTIFICATION_CHANNEL_BOTH,
}
AUDIT_REVIEW_NOTIFICATION_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
AUDIT_REVIEW_AI_SUMMARY_STATUS_NOT_REQUESTED = "NOT_REQUESTED"
AUDIT_REVIEW_AI_SUMMARY_STATUS_GENERATING = "GENERATING"
AUDIT_REVIEW_AI_SUMMARY_STATUS_GENERATED = "GENERATED"
AUDIT_REVIEW_AI_SUMMARY_STATUS_FAILED = "FAILED"
AUDIT_REVIEW_AI_SUMMARY_STATUSES = {
    AUDIT_REVIEW_AI_SUMMARY_STATUS_NOT_REQUESTED,
    AUDIT_REVIEW_AI_SUMMARY_STATUS_GENERATING,
    AUDIT_REVIEW_AI_SUMMARY_STATUS_GENERATED,
    AUDIT_REVIEW_AI_SUMMARY_STATUS_FAILED,
}
AUDIT_REVIEW_AI_SUMMARY_STYLES = {"executive", "reviewer", "stakeholder", "technical", "brief"}
FIXED_TIMEZONE_FALLBACKS: dict[str, tzinfo] = {
    "UTC": UTC,
    "Asia/Kolkata": timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata"),
    "Asia/Calcutta": timezone(timedelta(hours=5, minutes=30), "Asia/Calcutta"),
}


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _validate_timezone_name(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("timezone must not be empty")
    try:
        ZoneInfo(cleaned)
    except ZoneInfoNotFoundError as exc:
        if cleaned not in FIXED_TIMEZONE_FALLBACKS:
            raise ValueError(f"Unsupported timezone: {cleaned}") from exc
    return cleaned


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None


class AuditReviewJobCreateRequest(BaseModel):
    review_start_dt: datetime
    review_end_dt: datetime
    audit_trail_type: str = Field(default=DEFAULT_AUDIT_TRAIL_TYPE, min_length=1, max_length=100)
    review_scope: str | None = Field(default=None, max_length=50)
    selected_audit_trail_types: list[str] | None = Field(default=None, max_length=5)
    veeva_instance_name: str | None = Field(default=None, max_length=150)
    veeva_app_name: str | None = Field(default=None, max_length=150)
    vault_dns: str | None = Field(default=None, max_length=255)
    requested_by: str | None = Field(default=None, max_length=150)

    @field_validator("review_start_dt", "review_end_dt")
    @classmethod
    def datetime_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("datetime must include UTC timezone, for example 2026-04-01T00:00:00Z")
        return value.astimezone(UTC)

    @field_validator("audit_trail_type")
    @classmethod
    def audit_trail_type_must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("audit_trail_type must not be empty")
        return cleaned

    @field_validator("review_scope")
    @classmethod
    def normalize_review_scope(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        return cleaned.upper() if cleaned else None

    @field_validator("selected_audit_trail_types")
    @classmethod
    def normalize_selected_audit_trail_types(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            cleaned = item.strip().lower()
            if not cleaned:
                continue
            if cleaned not in normalized:
                normalized.append(cleaned)
        return normalized or None

    @field_validator("veeva_instance_name", "veeva_app_name", "vault_dns", "requested_by")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @model_validator(mode="after")
    def end_must_be_after_start(self) -> "AuditReviewJobCreateRequest":
        if self.review_end_dt < self.review_start_dt:
            raise ValueError("review_start_dt must be before or equal to review_end_dt")
        return self


class AuditReviewJobCreateResponse(BaseModel):
    job_id: uuid.UUID
    asset_id: uuid.UUID
    status: str
    review_scope: str = DEFAULT_REVIEW_SCOPE
    selected_audit_trail_types: list[str] = Field(default_factory=lambda: [DEFAULT_AUDIT_TRAIL_TYPE])


class AuditReviewJobListItem(BaseModel):
    job_id: uuid.UUID
    asset_id: uuid.UUID
    review_start_dt: datetime
    review_end_dt: datetime
    audit_trail_type: str
    review_scope: str = DEFAULT_REVIEW_SCOPE
    selected_audit_trail_types: list[str] = Field(default_factory=lambda: [DEFAULT_AUDIT_TRAIL_TYPE])
    status: str
    record_count: int
    created_dt: datetime
    completed_at: datetime | None = None


class AuditReviewJobDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: uuid.UUID
    asset_id: uuid.UUID
    review_candidate_key: str
    vault_dns: str | None = None
    veeva_instance_name: str | None = None
    veeva_app_name: str | None = None
    audit_trail_type: str
    review_scope: str = DEFAULT_REVIEW_SCOPE
    selected_audit_trail_types: list[str] = Field(default_factory=lambda: [DEFAULT_AUDIT_TRAIL_TYPE])
    score_label: str | None = None
    review_start_dt: datetime
    review_end_dt: datetime
    period_basis: str
    trigger_mode: str
    status: str
    input_snapshot_json: dict[str, Any]
    extraction_summary_json: dict[str, Any]
    analysis_summary_json: dict[str, Any] | None = None
    report_summary_json: dict[str, Any] | None = None
    error_message: str | None = None
    requested_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_by: str | None = None
    created_dt: datetime
    modified_by: str | None = None
    modified_dt: datetime | None = None
    record_count: int
    finding_count: int = 0
    overall_score: int | None = None
    rating: str | None = None
    latest_report_id: uuid.UUID | None = None
    latest_report_status: str | None = None
    latest_report_approval_status: str | None = None
    latest_report_submitted_by: str | None = None
    latest_report_submitted_dt: datetime | None = None
    latest_report_reviewed_by: str | None = None
    latest_report_reviewed_dt: datetime | None = None
    coverage_by_audit_type: dict[str, Any] = Field(default_factory=dict)
    audit_type_scores: list[dict[str, Any]] = Field(default_factory=list)
    checkpoint_scores: list[dict[str, Any]] = Field(default_factory=list)
    checklist_applicability: list[dict[str, Any]] = Field(default_factory=list)


class AuditReviewExtractResponse(BaseModel):
    job_id: uuid.UUID
    asset_id: uuid.UUID
    status: str
    record_count: int
    extraction_summary_json: dict[str, Any]
    coverage_by_audit_type: dict[str, Any] = Field(default_factory=dict)


class AuditReviewAnalyzeRequest(BaseModel):
    business_timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=100)
    business_start_hour: int = Field(default=9, ge=0, le=23)
    business_end_hour: int = Field(default=18, ge=1, le=24)

    @field_validator("business_timezone")
    @classmethod
    def validate_business_timezone(cls, value: str) -> str:
        return _validate_timezone_name(value)

    @model_validator(mode="after")
    def end_hour_must_be_after_start_hour(self) -> "AuditReviewAnalyzeRequest":
        if self.business_end_hour <= self.business_start_hour:
            raise ValueError("business_end_hour must be after business_start_hour")
        return self


class AuditReviewAnalyzeResponse(BaseModel):
    job_id: uuid.UUID
    asset_id: uuid.UUID
    status: str
    overall_score: int
    rating: str
    score_label: str | None = None
    total_records_analyzed: int
    total_findings: int
    finding_counts_by_severity: dict[str, int]
    score_breakdown: list[dict[str, Any]]
    audit_type_scores: list[dict[str, Any]] = Field(default_factory=list)
    checkpoint_scores: list[dict[str, Any]] = Field(default_factory=list)
    checklist_applicability: list[dict[str, Any]] = Field(default_factory=list)


class AuditReviewReportSubmitReviewRequest(BaseModel):
    submitted_by: str | None = Field(default=None, min_length=1, max_length=150)
    submission_notes: str | None = Field(default=None, max_length=2000)

    @field_validator("submitted_by")
    @classmethod
    def submitted_by_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("submitted_by must not be empty")
        return cleaned

    @field_validator("submission_notes")
    @classmethod
    def normalize_submission_notes(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class AuditReviewReportESignatureRequest(BaseModel):
    user_email: str = Field(min_length=1, max_length=150)
    current_password: str = Field(min_length=1, max_length=100)
    signature_meaning: str = Field(
        default="Electronic approval of the audit review report",
        min_length=1,
        max_length=250,
    )
    confirmed: bool = False

    @field_validator("user_email", "current_password")
    @classmethod
    def credential_must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator("signature_meaning")
    @classmethod
    def strings_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned


class AuditReviewReportReviewDecisionRequest(BaseModel):
    reviewed_by: str | None = Field(default=None, min_length=1, max_length=150)
    reviewer_comments: str = Field(min_length=1, max_length=4000)
    e_signature: AuditReviewReportESignatureRequest | None = None

    @field_validator("reviewed_by", "reviewer_comments")
    @classmethod
    def strings_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned


class AuditReviewFindingResponse(BaseModel):
    finding_id: uuid.UUID
    job_id: uuid.UUID
    asset_id: uuid.UUID
    primary_record_id: uuid.UUID | None = None
    check_code: str
    check_name: str
    audit_trail_type: str | None = None
    parameter_code: str | None = None
    checkpoint_code: str | None = None
    finding_type: str | None = None
    severity: str | None = None
    status: str
    score_impact: int
    finding_title: str | None = None
    finding_summary: str | None = None
    title: str | None = None
    description: str | None = None
    evidence_json: dict[str, Any]
    source_record_count: int
    created_dt: datetime


class AuditReviewScoreResponse(BaseModel):
    score_id: uuid.UUID
    job_id: uuid.UUID
    asset_id: uuid.UUID
    check_code: str
    check_name: str
    score_scope: str = "CHECKPOINT"
    audit_trail_type: str = "ALL"
    score_label: str | None = None
    applicability: str | None = None
    evaluated_record_count: int = 0
    skipped_record_count: int = 0
    no_data_count: int = 0
    overall_score: int | None = None
    rating: str | None = None
    score_status: str
    source_record_count: int
    finding_count: int
    penalty_per_finding: int
    penalty_cap: int
    raw_penalty: int
    applied_penalty: int
    sort_order: int
    scoring_summary_json: dict[str, Any]
    created_dt: datetime


class AuditReviewReportGenerateResponse(BaseModel):
    report_id: uuid.UUID
    job_id: uuid.UUID
    asset_id: uuid.UUID
    status: str
    overall_score: int
    rating: str
    report_summary: dict[str, Any]
    review_type: str | None = None
    trigger_source: str | None = None
    schedule_id: uuid.UUID | None = None
    schedule_run_id: uuid.UUID | None = None
    workflow_metadata_json: dict[str, Any] | None = None
    workflow_metadata: dict[str, Any] = Field(default_factory=dict)
    submitted_by: str | None = None
    submitted_dt: datetime | None = None
    reviewed_by: str | None = None
    reviewed_dt: datetime | None = None
    reviewer_comments: str | None = None
    approval_decision_json: dict[str, Any] | None = None
    is_e_signed: bool = False
    e_signed_at: datetime | None = None
    e_signed_by_user_id: uuid.UUID | None = None
    is_locked: bool = False
    locked_at: datetime | None = None
    locked_by_user_id: uuid.UUID | None = None
    final_pdf_path: str | None = None
    final_pdf_hash: str | None = None
    report_version: str | None = None


class AuditReviewReportListItem(BaseModel):
    report_id: uuid.UUID
    job_id: uuid.UUID
    asset_id: uuid.UUID
    status: str
    overall_score: int | None = None
    rating: str | None = None
    report_summary: dict[str, Any]
    review_type: str | None = None
    trigger_source: str | None = None
    schedule_id: uuid.UUID | None = None
    schedule_run_id: uuid.UUID | None = None
    workflow_metadata_json: dict[str, Any] | None = None
    workflow_metadata: dict[str, Any] = Field(default_factory=dict)
    submitted_by: str | None = None
    submitted_dt: datetime | None = None
    reviewed_by: str | None = None
    reviewed_dt: datetime | None = None
    reviewer_comments: str | None = None
    approval_decision_json: dict[str, Any] | None = None
    is_e_signed: bool = False
    e_signed_at: datetime | None = None
    e_signed_by_user_id: uuid.UUID | None = None
    is_locked: bool = False
    locked_at: datetime | None = None
    locked_by_user_id: uuid.UUID | None = None
    final_pdf_path: str | None = None
    final_pdf_hash: str | None = None
    report_version: str | None = None
    created_dt: datetime
    modified_dt: datetime | None = None


class AuditReviewReportDetailResponse(BaseModel):
    report_id: uuid.UUID
    job_id: uuid.UUID
    asset_id: uuid.UUID
    status: str
    overall_score: int | None = None
    rating: str | None = None
    report_summary: dict[str, Any]
    report_json: dict[str, Any]
    report_markdown: str
    review_type: str | None = None
    trigger_source: str | None = None
    schedule_id: uuid.UUID | None = None
    schedule_run_id: uuid.UUID | None = None
    workflow_metadata_json: dict[str, Any] | None = None
    workflow_metadata: dict[str, Any] = Field(default_factory=dict)
    submitted_by: str | None = None
    submitted_dt: datetime | None = None
    reviewed_by: str | None = None
    reviewed_dt: datetime | None = None
    reviewer_comments: str | None = None
    approval_decision_json: dict[str, Any] | None = None
    is_e_signed: bool = False
    e_signed_at: datetime | None = None
    e_signed_by_user_id: uuid.UUID | None = None
    is_locked: bool = False
    locked_at: datetime | None = None
    locked_by_user_id: uuid.UUID | None = None
    final_pdf_path: str | None = None
    final_pdf_hash: str | None = None
    report_version: str | None = None
    created_dt: datetime
    modified_dt: datetime | None = None


class AuditReviewAiSummaryGenerateRequest(BaseModel):
    requested_by: str | None = Field(default=None, min_length=1, max_length=150)
    summary_style: str = Field(default="executive", min_length=1, max_length=50)
    include_capa_recommendations: bool = True

    @field_validator("requested_by")
    @classmethod
    def requested_by_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("requested_by must not be empty")
        return cleaned

    @field_validator("summary_style")
    @classmethod
    def validate_summary_style(cls, value: str) -> str:
        cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
        if cleaned not in AUDIT_REVIEW_AI_SUMMARY_STYLES:
            allowed = ", ".join(sorted(AUDIT_REVIEW_AI_SUMMARY_STYLES))
            raise ValueError(f"summary_style must be one of: {allowed}")
        return cleaned


class AuditReviewAiSummaryResponse(BaseModel):
    report_id: uuid.UUID
    job_id: uuid.UUID
    asset_id: uuid.UUID
    report_status: str
    status: str
    ai_configured: bool = True
    requested_by: str | None = None
    generated_by: str | None = None
    generated_dt: datetime | None = None
    model_name: str | None = None
    summary_style: str | None = None
    include_capa_recommendations: bool | None = None
    overall_score: int | None = None
    rating: str | None = None
    ai_summary_json: dict[str, Any] | None = None
    ai_summary_markdown: str | None = None
    error_message: str | None = None


class AuditTrailRecordResponse(BaseModel):
    record_id: uuid.UUID
    job_id: uuid.UUID
    asset_id: uuid.UUID
    source_record_key: str | None = None
    audit_trail_type: str = DEFAULT_AUDIT_TRAIL_TYPE
    event_timestamp: datetime | None = None
    event_timezone: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    raw_action: str | None = None
    action_type: str | None = None
    detected_action_category: str | None = None
    display_action: str | None = None
    object_type: str | None = None
    object_name: str | None = None
    object_id: str | None = None
    field_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    event_status: str | None = None
    reason: str | None = None
    change_control_id: str | None = None
    ip_address: str | None = None
    session_id: str | None = None
    auth_method: str | None = None
    failure_reason: str | None = None
    is_delete_action: bool
    is_permission_change: bool
    is_export_action: bool = False
    is_configuration_change: bool = False
    record_quality_status: str
    created_dt: datetime
    raw_payload_json: dict[str, Any] | None = None
    normalized_extra_json: dict[str, Any] | None = None


class AuditReviewScheduleUpsertRequest(BaseModel):
    enabled: bool = True
    audit_trail_type: str = Field(default=DEFAULT_AUDIT_TRAIL_TYPE, min_length=1, max_length=100)
    review_scope: str | None = Field(default="FULL_GXP", max_length=50)
    selected_audit_trail_types: list[str] | None = Field(default=None, max_length=5)
    veeva_instance_name: str | None = Field(default=None, max_length=150)
    veeva_app_name: str | None = Field(default=None, max_length=150)
    vault_dns: str | None = Field(default=None, max_length=255)
    frequency: str = Field(default="MONTHLY", min_length=1, max_length=30)
    review_window_days: int | None = Field(default=None, ge=1, le=366)
    next_run_dt: datetime | None = None
    schedule_start_dt: datetime | None = None
    schedule_end_dt: datetime | None = None
    end_condition: str | None = Field(default="NO_END_DATE", max_length=30)
    end_after_runs: int | None = Field(default=None, ge=1, le=10000)
    run_time: str | None = Field(default=None, min_length=5, max_length=5)
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    use_last_day_of_month: bool | None = None
    cycle_type: str | None = Field(default=None, max_length=50)
    run_timing: str | None = Field(default=None, max_length=50)
    run_month: int | None = Field(default=None, ge=1, le=12)
    custom_cycle_start_month: int | None = Field(default=None, ge=1, le=12)
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    audit_retrieval_mode: str | None = Field(default=None, max_length=40)
    custom_audit_start_dt: datetime | None = None
    custom_audit_end_dt: datetime | None = None
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=100)
    business_start_hour: int | None = Field(default=None, ge=0, le=23)
    business_end_hour: int | None = Field(default=None, ge=1, le=24)
    created_by: str | None = Field(default=None, max_length=150)

    @field_validator("audit_trail_type", "frequency", "timezone")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator("review_scope")
    @classmethod
    def normalize_schedule_review_scope(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        return cleaned.upper() if cleaned else None

    @field_validator("selected_audit_trail_types")
    @classmethod
    def normalize_schedule_selected_audit_trail_types(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            cleaned = item.strip().lower()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized or None

    @field_validator("frequency")
    @classmethod
    def validate_frequency(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if cleaned not in AUDIT_REVIEW_SCHEDULE_FREQUENCIES:
            raise ValueError("frequency must be DAILY, WEEKLY, MONTHLY, QUARTERLY, HALF_YEARLY, or ANNUAL")
        return cleaned

    @field_validator("end_condition")
    @classmethod
    def validate_end_condition(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        if cleaned is None:
            return None
        normalized = cleaned.upper()
        if normalized not in AUDIT_REVIEW_SCHEDULE_END_CONDITIONS:
            raise ValueError("end_condition must be NO_END_DATE, END_ON_DATE, or END_AFTER_RUNS")
        return normalized

    @field_validator("cycle_type")
    @classmethod
    def validate_cycle_type(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        if cleaned is None:
            return None
        normalized = cleaned.upper()
        if normalized not in AUDIT_REVIEW_SCHEDULE_CYCLE_TYPES:
            raise ValueError("cycle_type is not supported")
        return normalized

    @field_validator("run_timing")
    @classmethod
    def validate_run_timing(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        if cleaned is None:
            return None
        normalized = cleaned.upper()
        if normalized not in AUDIT_REVIEW_SCHEDULE_RUN_TIMINGS:
            raise ValueError("run_timing must be FIRST_DAY_AFTER_PERIOD_END or CUSTOM_RUN_DAY")
        return normalized

    @field_validator("audit_retrieval_mode")
    @classmethod
    def validate_audit_retrieval_mode(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        if cleaned is None:
            return None
        normalized = cleaned.upper()
        if normalized == "AUTOMATIC_COMPLETED_PERIOD":
            return "AUTO"
        if normalized not in AUDIT_REVIEW_RETRIEVAL_MODES:
            raise ValueError("audit_retrieval_mode must be AUTO, AUTOMATIC_COMPLETED_PERIOD, SINCE_LAST_SUCCESSFUL, or CUSTOM")
        return normalized

    @field_validator("run_time")
    @classmethod
    def validate_run_time(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        if cleaned is None:
            return None
        parts = cleaned.split(":")
        if len(parts) != 2:
            raise ValueError("run_time must use HH:mm format")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as exc:
            raise ValueError("run_time must use HH:mm format") from exc
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("run_time must use HH:mm format")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _validate_timezone_name(value)

    @field_validator("next_run_dt", "schedule_start_dt", "schedule_end_dt", "custom_audit_start_dt", "custom_audit_end_dt")
    @classmethod
    def next_run_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("datetime must include timezone, for example 2026-05-01T00:00:00Z")
        return value.astimezone(UTC)

    @field_validator("veeva_instance_name", "veeva_app_name", "vault_dns", "created_by")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @model_validator(mode="after")
    def business_hours_must_be_ordered(self) -> "AuditReviewScheduleUpsertRequest":
        if self.business_start_hour is not None and self.business_end_hour is not None:
            if self.business_end_hour <= self.business_start_hour:
                raise ValueError("business_end_hour must be after business_start_hour")
        if self.frequency == "DAILY" and self.audit_retrieval_mode != "CUSTOM":
            self.audit_retrieval_mode = "AUTO"
        if self.frequency == "QUARTERLY":
            self.audit_retrieval_mode = "AUTO"
            self.custom_audit_start_dt = None
            self.custom_audit_end_dt = None
            self.end_condition = "END_ON_DATE" if self.schedule_end_dt is not None else "NO_END_DATE"
            self.end_after_runs = None
        if self.end_condition == "END_ON_DATE":
            if self.schedule_start_dt is not None and self.schedule_end_dt is not None:
                if self.schedule_end_dt < self.schedule_start_dt:
                    raise ValueError("schedule_end_dt must be on or after schedule_start_dt")
        if self.audit_retrieval_mode == "CUSTOM":
            if self.custom_audit_start_dt is None or self.custom_audit_end_dt is None:
                raise ValueError("custom_audit_start_dt and custom_audit_end_dt are required for CUSTOM audit retrieval mode")
            if self.custom_audit_end_dt < self.custom_audit_start_dt:
                raise ValueError("custom_audit_start_dt must be before or equal to custom_audit_end_dt")
        return self


class AuditReviewSchedulePatchRequest(BaseModel):
    enabled: bool | None = None
    audit_trail_type: str | None = Field(default=None, min_length=1, max_length=100)
    review_scope: str | None = Field(default=None, max_length=50)
    selected_audit_trail_types: list[str] | None = Field(default=None, max_length=5)
    veeva_instance_name: str | None = Field(default=None, max_length=150)
    veeva_app_name: str | None = Field(default=None, max_length=150)
    vault_dns: str | None = Field(default=None, max_length=255)
    frequency: str | None = Field(default=None, min_length=1, max_length=30)
    review_window_days: int | None = Field(default=None, ge=1, le=366)
    next_run_dt: datetime | None = None
    schedule_start_dt: datetime | None = None
    schedule_end_dt: datetime | None = None
    end_condition: str | None = Field(default=None, max_length=30)
    end_after_runs: int | None = Field(default=None, ge=1, le=10000)
    run_time: str | None = Field(default=None, min_length=5, max_length=5)
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    use_last_day_of_month: bool | None = None
    cycle_type: str | None = Field(default=None, max_length=50)
    run_timing: str | None = Field(default=None, max_length=50)
    run_month: int | None = Field(default=None, ge=1, le=12)
    custom_cycle_start_month: int | None = Field(default=None, ge=1, le=12)
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    audit_retrieval_mode: str | None = Field(default=None, max_length=40)
    custom_audit_start_dt: datetime | None = None
    custom_audit_end_dt: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    business_start_hour: int | None = Field(default=None, ge=0, le=23)
    business_end_hour: int | None = Field(default=None, ge=1, le=24)
    modified_by: str | None = Field(default=None, max_length=150)

    @field_validator("audit_trail_type", "frequency", "timezone")
    @classmethod
    def normalize_optional_required_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned

    @field_validator("review_scope")
    @classmethod
    def normalize_patch_review_scope(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        return cleaned.upper() if cleaned else None

    @field_validator("selected_audit_trail_types")
    @classmethod
    def normalize_patch_selected_audit_trail_types(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            cleaned = item.strip().lower()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized or None

    @field_validator("frequency")
    @classmethod
    def validate_patch_frequency(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().upper()
        if cleaned not in AUDIT_REVIEW_SCHEDULE_FREQUENCIES:
            raise ValueError("frequency must be DAILY, WEEKLY, MONTHLY, QUARTERLY, HALF_YEARLY, or ANNUAL")
        return cleaned

    @field_validator("end_condition")
    @classmethod
    def validate_patch_end_condition(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        if cleaned is None:
            return None
        normalized = cleaned.upper()
        if normalized not in AUDIT_REVIEW_SCHEDULE_END_CONDITIONS:
            raise ValueError("end_condition must be NO_END_DATE, END_ON_DATE, or END_AFTER_RUNS")
        return normalized

    @field_validator("cycle_type")
    @classmethod
    def validate_patch_cycle_type(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        if cleaned is None:
            return None
        normalized = cleaned.upper()
        if normalized not in AUDIT_REVIEW_SCHEDULE_CYCLE_TYPES:
            raise ValueError("cycle_type is not supported")
        return normalized

    @field_validator("run_timing")
    @classmethod
    def validate_patch_run_timing(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        if cleaned is None:
            return None
        normalized = cleaned.upper()
        if normalized not in AUDIT_REVIEW_SCHEDULE_RUN_TIMINGS:
            raise ValueError("run_timing must be FIRST_DAY_AFTER_PERIOD_END or CUSTOM_RUN_DAY")
        return normalized

    @field_validator("audit_retrieval_mode")
    @classmethod
    def validate_patch_audit_retrieval_mode(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        if cleaned is None:
            return None
        normalized = cleaned.upper()
        if normalized == "AUTOMATIC_COMPLETED_PERIOD":
            return "AUTO"
        if normalized not in AUDIT_REVIEW_RETRIEVAL_MODES:
            raise ValueError("audit_retrieval_mode must be AUTO, AUTOMATIC_COMPLETED_PERIOD, SINCE_LAST_SUCCESSFUL, or CUSTOM")
        return normalized

    @field_validator("run_time")
    @classmethod
    def validate_patch_run_time(cls, value: str | None) -> str | None:
        cleaned = _strip_optional(value)
        if cleaned is None:
            return None
        parts = cleaned.split(":")
        if len(parts) != 2:
            raise ValueError("run_time must use HH:mm format")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError as exc:
            raise ValueError("run_time must use HH:mm format") from exc
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("run_time must use HH:mm format")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("timezone")
    @classmethod
    def validate_patch_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_timezone_name(value)

    @field_validator("next_run_dt", "schedule_start_dt", "schedule_end_dt", "custom_audit_start_dt", "custom_audit_end_dt")
    @classmethod
    def patch_next_run_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("datetime must include timezone, for example 2026-05-01T00:00:00Z")
        return value.astimezone(UTC)

    @field_validator("veeva_instance_name", "veeva_app_name", "vault_dns", "modified_by")
    @classmethod
    def normalize_patch_optional_strings(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @model_validator(mode="after")
    def patch_business_hours_must_be_ordered(self) -> "AuditReviewSchedulePatchRequest":
        if self.business_start_hour is not None and self.business_end_hour is not None:
            if self.business_end_hour <= self.business_start_hour:
                raise ValueError("business_end_hour must be after business_start_hour")
        if self.frequency == "DAILY" and self.audit_retrieval_mode not in {None, "CUSTOM"}:
            self.audit_retrieval_mode = "AUTO"
        if self.frequency == "QUARTERLY":
            self.audit_retrieval_mode = "AUTO"
            self.custom_audit_start_dt = None
            self.custom_audit_end_dt = None
            self.end_condition = "END_ON_DATE" if self.schedule_end_dt is not None else "NO_END_DATE"
            self.end_after_runs = None
        if self.schedule_start_dt is not None and self.schedule_end_dt is not None:
            if self.schedule_end_dt < self.schedule_start_dt:
                raise ValueError("schedule_end_dt must be on or after schedule_start_dt")
        if self.custom_audit_start_dt is not None and self.custom_audit_end_dt is not None:
            if self.custom_audit_end_dt < self.custom_audit_start_dt:
                raise ValueError("custom_audit_start_dt must be before or equal to custom_audit_end_dt")
        return self


class AuditReviewScheduleResponse(BaseModel):
    schedule_id: uuid.UUID
    asset_id: uuid.UUID
    enabled: bool
    vault_dns: str | None = None
    veeva_instance_name: str | None = None
    veeva_app_name: str | None = None
    audit_trail_type: str
    review_scope: str = DEFAULT_REVIEW_SCOPE
    selected_audit_trail_types: list[str] = Field(default_factory=lambda: [DEFAULT_AUDIT_TRAIL_TYPE])
    frequency: str
    review_window_days: int | None = None
    next_run_dt: datetime
    schedule_start_dt: datetime | None = None
    schedule_end_dt: datetime | None = None
    end_condition: str | None = None
    end_after_runs: int | None = None
    run_time: str | None = None
    day_of_week: int | None = None
    day_of_month: int | None = None
    use_last_day_of_month: bool | None = None
    cycle_type: str | None = None
    run_timing: str | None = None
    run_month: int | None = None
    custom_cycle_start_month: int | None = None
    fiscal_year_start_month: int | None = None
    audit_retrieval_mode: str | None = None
    custom_audit_start_dt: datetime | None = None
    custom_audit_end_dt: datetime | None = None
    last_run_dt: datetime | None = None
    last_job_id: uuid.UUID | None = None
    timezone: str
    business_start_hour: int | None = None
    business_end_hour: int | None = None
    created_by: str | None = None
    created_dt: datetime
    modified_by: str | None = None
    modified_dt: datetime | None = None


class AuditReviewScheduleRunResponse(BaseModel):
    run_id: uuid.UUID
    schedule_id: uuid.UUID
    asset_id: uuid.UUID
    job_id: uuid.UUID | None = None
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    message: str | None = None
    error_message: str | None = None
    run_summary_json: dict[str, Any]


class AuditReviewScheduleRunNowResponse(BaseModel):
    schedule: AuditReviewScheduleResponse
    run: AuditReviewScheduleRunResponse
    job: AuditReviewJobDetailResponse | None = None
    report: AuditReviewReportGenerateResponse | None = None


class AuditReviewSchedulerRunDueResponse(BaseModel):
    processed_count: int
    completed_count: int
    failed_count: int
    skipped_count: int
    runs: list[AuditReviewScheduleRunResponse]


class PrepareNotificationsRequest(BaseModel):
    requested_by: str | None = Field(default=None, max_length=150)
    regenerate: bool = False
    delivery_channel: str = Field(default=AUDIT_REVIEW_NOTIFICATION_CHANNEL_IN_APP, min_length=1, max_length=30)

    @field_validator("requested_by")
    @classmethod
    def normalize_requested_by(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("delivery_channel")
    @classmethod
    def validate_delivery_channel(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if cleaned not in AUDIT_REVIEW_NOTIFICATION_CHANNELS:
            raise ValueError("delivery_channel must be IN_APP, EMAIL, or BOTH")
        return cleaned


class SendNotificationRequest(BaseModel):
    sent_by: str | None = Field(default=None, min_length=1, max_length=150)

    @field_validator("sent_by")
    @classmethod
    def sent_by_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("sent_by must not be empty")
        return cleaned


class DismissNotificationRequest(BaseModel):
    dismissed_by: str | None = Field(default=None, min_length=1, max_length=150)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("dismissed_by")
    @classmethod
    def dismissed_by_must_not_be_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("dismissed_by must not be empty")
        return cleaned

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be empty")
        return cleaned


class AuditReviewNotificationResponse(BaseModel):
    notification_id: uuid.UUID
    report_id: uuid.UUID
    job_id: uuid.UUID
    asset_id: uuid.UUID
    notification_type: str
    priority: str
    rating: str
    recipient_role: str
    recipient_email: str | None = None
    subject: str
    message: str
    status: str
    delivery_channel: str
    created_by: str | None = None
    created_dt: datetime
    sent_dt: datetime | None = None
    error_message: str | None = None
    metadata_json: dict[str, Any]


class SendNotificationResponse(BaseModel):
    notification: AuditReviewNotificationResponse
    sent: bool
    failed: bool = False
    skipped: bool = False
    message: str


class SendNotificationsResponse(BaseModel):
    total: int
    sent: int
    failed: int
    skipped: int
    notifications: list[AuditReviewNotificationResponse]
    message: str | None = None
