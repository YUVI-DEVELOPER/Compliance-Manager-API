from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset_release import AssetRelease
    from app.models.release_validation_impact_assessment import ReleaseValidationImpactAssessment
    from app.models.release_validation_package import ReleaseValidationPackage


class ReleaseValidationAISuggestion(Base):
    __tablename__ = "release_validation_ai_suggestion"
    __table_args__ = (
        Index("idx_release_validation_ai_suggestion_assessment_id", "assessment_id"),
        Index("idx_release_validation_ai_suggestion_release_id", "release_id"),
        Index("idx_release_validation_ai_suggestion_package_id", "package_id"),
        Index("idx_release_validation_ai_suggestion_question_code", "question_code"),
    )

    suggestion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "release_validation_impact_assessment.assessment_id",
            name="fk_release_validation_ai_suggestion_assessment",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_release.release_id", name="fk_release_validation_ai_suggestion_release", ondelete="CASCADE"),
        nullable=False,
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "release_validation_package.package_id",
            name="fk_release_validation_ai_suggestion_package",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    question_code: Mapped[str] = mapped_column(String(80), nullable=False)
    suggested_answer: Mapped[str] = mapped_column(String(30), nullable=False)
    suggested_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    caveat: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_fields_used: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    accepted_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    assessment: Mapped["ReleaseValidationImpactAssessment | None"] = relationship(
        "ReleaseValidationImpactAssessment",
        back_populates="ai_suggestions",
    )
    release: Mapped["AssetRelease"] = relationship("AssetRelease")
    package: Mapped["ReleaseValidationPackage"] = relationship("ReleaseValidationPackage")
