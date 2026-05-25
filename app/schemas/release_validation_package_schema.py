import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReleaseValidationPackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    package_id: uuid.UUID
    release_id: uuid.UUID
    package_no: str
    package_status: str
    validation_scope: str
    risk_level: str
    impact_assessment_status: str
    document_checklist_status: str
    testing_status: str
    approval_status: str
    final_decision: str | None = None
    created_by: str | None = None
    created_dt: datetime | None = None
    modified_by: str | None = None
    modified_dt: datetime | None = None
