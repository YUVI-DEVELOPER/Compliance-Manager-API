import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ReleaseImpactAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    assessment_id: uuid.UUID
    release_id: uuid.UUID
    previous_release_id: uuid.UUID | None = None
    report_title: str
    report_content: str
    report_format: str
    diff_summary: dict[str, Any] | None = None
    impact_level: str | None = None
    generated_dt: datetime | None = None
    created_by: str | None = None


class ReleaseImpactAssessmentDownloadResponse(BaseModel):
    file_name: str
    media_type: str
    report_content: str
    generated_dt: datetime | None = None
