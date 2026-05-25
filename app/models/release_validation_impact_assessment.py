from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.release_validation_ai_suggestion import ReleaseValidationAISuggestion
    from app.models.release_validation_impact_response import ReleaseValidationImpactResponse
    from app.models.release_validation_package import ReleaseValidationPackage


class ReleaseValidationImpactAssessment(Base):
    __tablename__ = "release_validation_impact_assessment"
    __table_args__ = (
        Index("idx_release_validation_impact_assessment_package_id", "package_id"),
        Index("idx_release_validation_impact_assessment_assessment_no", "assessment_no"),
        Index("idx_release_validation_impact_assessment_status", "status"),
        Index("idx_release_validation_impact_assessment_risk_level", "risk_level"),
        Index("idx_release_validation_impact_assessment_validation_scope", "validation_scope"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "release_validation_package.package_id",
            name="fk_release_validation_impact_assessment_package",
            ondelete="CASCADE",
        ),
        nullable=False,
        unique=True,
    )
    assessment_no: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))
    total_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    risk_level: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="NOT_ASSESSED",
        server_default=text("'NOT_ASSESSED'"),
    )
    validation_scope: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default="NOT_ASSESSED",
        server_default=text("'NOT_ASSESSED'"),
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    package: Mapped["ReleaseValidationPackage"] = relationship(
        "ReleaseValidationPackage",
        back_populates="impact_assessment",
    )
    responses: Mapped[list["ReleaseValidationImpactResponse"]] = relationship(
        "ReleaseValidationImpactResponse",
        back_populates="assessment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ReleaseValidationImpactResponse.question_code",
    )
    ai_suggestions: Mapped[list["ReleaseValidationAISuggestion"]] = relationship(
        "ReleaseValidationAISuggestion",
        back_populates="assessment",
        passive_deletes=True,
    )
