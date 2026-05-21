import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


DOCUMENTATION_MODE_MANUAL = "MANUAL"
DOCUMENTATION_MODE_ONLINE_FETCH = "ONLINE_FETCH"
ALLOWED_DOCUMENTATION_MODES = {DOCUMENTATION_MODE_MANUAL, DOCUMENTATION_MODE_ONLINE_FETCH}


def _parse_release_datetime(value: object) -> object:
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


def _normalize_documentation_mode(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in ALLOWED_DOCUMENTATION_MODES:
        allowed = ", ".join(sorted(ALLOWED_DOCUMENTATION_MODES))
        raise ValueError(f"documentation_mode must be one of: {allowed}")
    return normalized


class ReleaseCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str = Field(..., min_length=1, max_length=50)
    system_config_report: str | None = Field(
        default=None,
        validation_alias=AliasChoices("system_config_report", "systemConfigurationReport"),
    )
    documentation_mode: str = Field(
        ...,
        min_length=1,
        max_length=20,
        validation_alias=AliasChoices("documentation_mode", "documentationMode"),
    )
    documentation_text: str | None = Field(
        default=None,
        validation_alias=AliasChoices("documentation_text", "documentationText"),
    )
    documentation_source_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("documentation_source_url", "documentationSourceUrl"),
    )
    created_by: str | None = Field(
        default=None,
        max_length=150,
        validation_alias=AliasChoices("created_by", "createdBy"),
    )
    end_dt: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("end_dt", "endDate"),
    )

    @field_validator("end_dt", mode="before")
    @classmethod
    def parse_end_dt(cls, value: object) -> object:
        return _parse_release_datetime(value)

    @field_validator("documentation_mode")
    @classmethod
    def normalize_documentation_mode(cls, value: str) -> str:
        return _normalize_documentation_mode(value)

    @model_validator(mode="after")
    def validate_documentation_payload(self) -> "ReleaseCreate":
        if self.documentation_mode == DOCUMENTATION_MODE_MANUAL:
            if self.documentation_text is None or not self.documentation_text.strip():
                raise ValueError("documentation_text is required when documentation_mode is MANUAL")
        if self.documentation_mode == DOCUMENTATION_MODE_ONLINE_FETCH:
            if self.documentation_source_url is None or not self.documentation_source_url.strip():
                raise ValueError("documentation_source_url is required when documentation_mode is ONLINE_FETCH")
        return self


class ReleaseUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str | None = Field(default=None, min_length=1, max_length=50)
    system_config_report: str | None = Field(
        default=None,
        validation_alias=AliasChoices("system_config_report", "systemConfigurationReport"),
    )
    documentation_mode: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        validation_alias=AliasChoices("documentation_mode", "documentationMode"),
    )
    documentation_text: str | None = Field(
        default=None,
        validation_alias=AliasChoices("documentation_text", "documentationText"),
    )
    documentation_source_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("documentation_source_url", "documentationSourceUrl"),
    )
    modified_by: str | None = Field(
        default=None,
        max_length=150,
        validation_alias=AliasChoices("modified_by", "modifiedBy"),
    )
    end_dt: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("end_dt", "endDate"),
    )

    @field_validator("end_dt", mode="before")
    @classmethod
    def parse_end_dt(cls, value: object) -> object:
        return _parse_release_datetime(value)

    @field_validator("documentation_mode")
    @classmethod
    def normalize_documentation_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_documentation_mode(value)


class ReleaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    release_id: uuid.UUID
    asset_id: uuid.UUID
    version: str
    system_config_report: str | None = None
    documentation_mode: str
    documentation_text: str | None = None
    documentation_source_url: str | None = None
    documentation_fetched_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("documentation_fetched_at", "documentationFetchedAt"),
    )

    created_by: str | None = None
    created_dt: datetime | None = None

    modified_by: str | None = None
    modified_dt: datetime | None = None

    end_dt: datetime | None = None

    asset_name: str | None = None
    asset_type: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    supplier_name: str | None = None


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
