import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SupplierRequirementAnalysis(Base):
    __tablename__ = "supplier_requirement_analysis"
    __table_args__ = (
        CheckConstraint(
            "evaluated_fit IN ('MEETS', 'PARTIALLY_MEETS', 'NOT_MEETS')",
            name="chk_supplier_requirement_analysis_evaluated_fit",
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="chk_supplier_requirement_analysis_confidence_score",
        ),
        Index("idx_supplier_requirement_analysis_analysis_id", "analysis_id"),
        Index("idx_supplier_requirement_analysis_supplier_response_id", "supplier_response_id"),
        Index("idx_supplier_requirement_analysis_requirement_id", "requirement_id"),
        Index("idx_supplier_requirement_analysis_evaluated_fit", "evaluated_fit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_evaluation_analysis.analysis_id", name="fk_supplier_requirement_analysis_analysis", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_evaluation_response.response_id", name="fk_supplier_requirement_analysis_supplier_response", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_requirement_item.requirement_item_id", name="fk_supplier_requirement_analysis_requirement", ondelete="CASCADE"),
        nullable=False,
    )
    evaluated_fit: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning_text: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    analysis: Mapped["SupplierEvaluationAnalysis"] = relationship(
        "SupplierEvaluationAnalysis",
        back_populates="requirement_analyses",
    )
