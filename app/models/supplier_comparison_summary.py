import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SupplierComparisonSummary(Base):
    __tablename__ = "supplier_comparison_summary"
    __table_args__ = (
        Index("idx_supplier_comparison_summary_analysis_id", "analysis_id"),
        Index("idx_supplier_comparison_summary_supplier_id", "supplier_id"),
        Index("idx_supplier_comparison_summary_rank", "analysis_id", "recommendation_rank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_evaluation_analysis.analysis_id", name="fk_supplier_comparison_summary_analysis", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.supplier_id", name="fk_supplier_comparison_summary_supplier", ondelete="RESTRICT"),
        nullable=False,
    )
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    strengths: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    weaknesses: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    risk_flags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    recommendation_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    analysis: Mapped["SupplierEvaluationAnalysis"] = relationship(
        "SupplierEvaluationAnalysis",
        back_populates="comparison_summaries",
    )
