from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.release_validation_impact_assessment import ReleaseValidationImpactAssessment


class ReleaseValidationImpactResponse(Base):
    __tablename__ = "release_validation_impact_response"
    __table_args__ = (
        UniqueConstraint("assessment_id", "question_code", name="uq_release_validation_impact_response_question"),
        Index("idx_release_validation_impact_response_assessment_id", "assessment_id"),
        Index("idx_release_validation_impact_response_question_code", "question_code"),
        Index("idx_release_validation_impact_response_answer", "answer"),
    )

    response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "release_validation_impact_assessment.assessment_id",
            name="fk_release_validation_impact_response_assessment",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    question_code: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(String(30), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    critical: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by: Mapped[str | None] = mapped_column(String, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    assessment: Mapped["ReleaseValidationImpactAssessment"] = relationship(
        "ReleaseValidationImpactAssessment",
        back_populates="responses",
    )
