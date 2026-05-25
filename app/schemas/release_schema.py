import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.release_validation_package_schema import ReleaseValidationPackageResponse


DOCUMENTATION_MODE_MANUAL = "MANUAL"
DOCUMENTATION_MODE_ONLINE_FETCH = "ONLINE_FETCH"
ALLOWED_DOCUMENTATION_MODES = {DOCUMENTATION_MODE_MANUAL, DOCUMENTATION_MODE_ONLINE_FETCH}

RELEASE_STATUS_IMPACT_ASSESSMENT_PENDING = "IMPACT_ASSESSMENT_PENDING"

ALLOWED_RELEASE_TYPES = {
    "MAJOR",
    "MINOR",
    "PATCH",
    "HOTFIX",
    "CONFIGURATION_CHANGE",
    "SECURITY_UPDATE",
    "INFRASTRUCTURE_CHANGE",
}
ALLOWED_RELEASE_ENVIRONMENTS = {"DEV", "QA", "UAT", "PROD", "MULTI_ENV"}
ALLOWED_EXPECTED_VALIDATED_FUNCTIONALITY_IMPACTS = {"YES", "NO", "UNKNOWN"}


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


def _normalize_allowed(value: str, field_name: str, allowed_values: set[str]) -> str:
    normalized = value.strip().upper()
    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"{field_name} must be one of: {allowed}")
    return normalized


class ReleaseCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    release_name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        validation_alias=AliasChoices("release_name", "releaseName"),
    )
    previous_version: str = Field(
        ...,
        min_length=1,
        max_length=50,
        validation_alias=AliasChoices("previous_version", "previousVersion"),
    )
    version: str = Field(
        ...,
        min_length=1,
        max_length=50,
        validation_alias=AliasChoices("version", "new_version", "newVersion"),
    )
    release_type: str = Field(
        ...,
        min_length=1,
        max_length=40,
        validation_alias=AliasChoices("release_type", "releaseType"),
    )
    vendor_name: str | None = Field(
        default=None,
        max_length=150,
        validation_alias=AliasChoices("vendor_name", "vendorName"),
    )
    planned_implementation_date: datetime = Field(
        ...,
        validation_alias=AliasChoices("planned_implementation_date", "plannedImplementationDate"),
    )
    environment: str = Field(
        ...,
        min_length=1,
        max_length=30,
    )
    release_description: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("release_description", "releaseDescription"),
    )
    business_reason: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("business_reason", "businessReason"),
    )
    change_control_no: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=AliasChoices("change_control_no", "changeControlNo"),
    )
    expected_validated_functionality_impact: str = Field(
        ...,
        min_length=1,
        max_length=20,
        validation_alias=AliasChoices(
            "expected_validated_functionality_impact",
            "expectedValidatedFunctionalityImpact",
        ),
    )
    release_status: str | None = Field(
        default=RELEASE_STATUS_IMPACT_ASSESSMENT_PENDING,
        max_length=50,
        validation_alias=AliasChoices("release_status", "releaseStatus"),
    )
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

    @field_validator("planned_implementation_date", mode="before")
    @classmethod
    def parse_planned_implementation_date(cls, value: object) -> object:
        return _parse_release_datetime(value)

    @field_validator("release_type")
    @classmethod
    def normalize_release_type(cls, value: str) -> str:
        return _normalize_allowed(value, "release_type", ALLOWED_RELEASE_TYPES)

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return _normalize_allowed(value, "environment", ALLOWED_RELEASE_ENVIRONMENTS)

    @field_validator("expected_validated_functionality_impact")
    @classmethod
    def normalize_expected_validated_functionality_impact(cls, value: str) -> str:
        return _normalize_allowed(
            value,
            "expected_validated_functionality_impact",
            ALLOWED_EXPECTED_VALIDATED_FUNCTIONALITY_IMPACTS,
        )

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
            source_url = self.documentation_source_url.strip()
            if not (source_url.startswith("http://") or source_url.startswith("https://")):
                raise ValueError("documentation_source_url must start with http:// or https://")
        return self


class ReleaseUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    release_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        validation_alias=AliasChoices("release_name", "releaseName"),
    )
    previous_version: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        validation_alias=AliasChoices("previous_version", "previousVersion"),
    )
    version: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        validation_alias=AliasChoices("version", "new_version", "newVersion"),
    )
    release_type: str | None = Field(
        default=None,
        min_length=1,
        max_length=40,
        validation_alias=AliasChoices("release_type", "releaseType"),
    )
    vendor_name: str | None = Field(
        default=None,
        max_length=150,
        validation_alias=AliasChoices("vendor_name", "vendorName"),
    )
    planned_implementation_date: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("planned_implementation_date", "plannedImplementationDate"),
    )
    environment: str | None = Field(default=None, min_length=1, max_length=30)
    release_description: str | None = Field(
        default=None,
        min_length=1,
        validation_alias=AliasChoices("release_description", "releaseDescription"),
    )
    business_reason: str | None = Field(
        default=None,
        min_length=1,
        validation_alias=AliasChoices("business_reason", "businessReason"),
    )
    change_control_no: str | None = Field(
        default=None,
        max_length=100,
        validation_alias=AliasChoices("change_control_no", "changeControlNo"),
    )
    expected_validated_functionality_impact: str | None = Field(
        default=None,
        min_length=1,
        max_length=20,
        validation_alias=AliasChoices(
            "expected_validated_functionality_impact",
            "expectedValidatedFunctionalityImpact",
        ),
    )
    release_status: str | None = Field(
        default=None,
        max_length=50,
        validation_alias=AliasChoices("release_status", "releaseStatus"),
    )
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

    @field_validator("planned_implementation_date", mode="before")
    @classmethod
    def parse_planned_implementation_date(cls, value: object) -> object:
        return _parse_release_datetime(value)

    @field_validator("release_type")
    @classmethod
    def normalize_release_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_allowed(value, "release_type", ALLOWED_RELEASE_TYPES)

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_allowed(value, "environment", ALLOWED_RELEASE_ENVIRONMENTS)

    @field_validator("expected_validated_functionality_impact")
    @classmethod
    def normalize_expected_validated_functionality_impact(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_allowed(
            value,
            "expected_validated_functionality_impact",
            ALLOWED_EXPECTED_VALIDATED_FUNCTIONALITY_IMPACTS,
        )

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
    release_name: str | None = None
    previous_version: str | None = None
    release_type: str | None = None
    vendor_name: str | None = None
    planned_implementation_date: datetime | None = None
    environment: str | None = None
    release_description: str | None = None
    business_reason: str | None = None
    change_control_no: str | None = None
    expected_validated_functionality_impact: str | None = None
    release_status: str | None = None
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
    validation_package: ReleaseValidationPackageResponse | None = None


class ReleaseCreateResult(BaseModel):
    release: ReleaseResponse
    validation_package: ReleaseValidationPackageResponse
    nextStep: str = "IMPACT_ASSESSMENT"


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
