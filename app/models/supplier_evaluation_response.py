import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.supplier_requirement_response import SupplierRequirementResponse
    from app.models.supplier import Supplier
    from app.models.supplier_evaluation import SupplierEvaluation
    from app.models.supplier_response_document import SupplierResponseDocument


class SupplierEvaluationResponse(Base):
    __tablename__ = "supplier_evaluation_response"
    __table_args__ = (
        UniqueConstraint(
            "evaluation_id",
            "supplier_id",
            name="uq_supplier_evaluation_response_evaluation_supplier",
        ),
        CheckConstraint(
            "submission_status IN ('NOT_STARTED', 'IN_PROGRESS', 'SUBMITTED', 'LOCKED')",
            name="chk_supplier_evaluation_response_submission_status",
        ),
        Index("idx_supplier_evaluation_response_evaluation_id", "evaluation_id"),
        Index("idx_supplier_evaluation_response_supplier_id", "supplier_id"),
        Index("idx_supplier_evaluation_response_submission_status", "submission_status"),
    )

    response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_evaluation.evaluation_id", name="fk_supplier_evaluation_response_evaluation", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.supplier_id", name="fk_supplier_evaluation_response_supplier", ondelete="RESTRICT"),
        nullable=False,
    )
    submission_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'NOT_STARTED'"))
    quotation_reference: Mapped[str | None] = mapped_column(String(250), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    evaluation: Mapped["SupplierEvaluation"] = relationship("SupplierEvaluation", back_populates="responses")
    supplier: Mapped["Supplier"] = relationship("Supplier", back_populates="evaluation_responses")
    documents: Mapped[list["SupplierResponseDocument"]] = relationship(
        "SupplierResponseDocument",
        back_populates="response",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    requirement_responses: Mapped[list["SupplierRequirementResponse"]] = relationship(
        "SupplierRequirementResponse",
        back_populates="response",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
