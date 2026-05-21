import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SupplierEvaluationAnalysis(Base):
    __tablename__ = "supplier_evaluation_analysis"
    __table_args__ = (
        CheckConstraint(
            "status IN ('NOT_STARTED', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="chk_supplier_evaluation_analysis_status",
        ),
        Index("idx_supplier_evaluation_analysis_evaluation_id", "evaluation_id"),
        Index("idx_supplier_evaluation_analysis_status", "status"),
        Index("idx_supplier_evaluation_analysis_created_at", "created_at"),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_evaluation.evaluation_id", name="fk_supplier_evaluation_analysis_evaluation", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'NOT_STARTED'"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_snapshot_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    requirement_analyses = relationship(
        "SupplierRequirementAnalysis",
        back_populates="analysis",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    comparison_summaries = relationship(
        "SupplierComparisonSummary",
        back_populates="analysis",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
