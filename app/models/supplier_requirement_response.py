import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.evaluation_requirement_item import EvaluationRequirementItem
    from app.models.supplier_evaluation_response import SupplierEvaluationResponse


class SupplierRequirementResponse(Base):
    __tablename__ = "supplier_requirement_response"
    __table_args__ = (
        UniqueConstraint("response_id", "requirement_item_id", name="uq_supplier_requirement_response_response_requirement"),
        CheckConstraint(
            "fit_status IN ('MEETS', 'PARTIALLY_MEETS', 'NOT_MEETS')",
            name="chk_supplier_requirement_response_fit_status",
        ),
        Index("idx_supplier_requirement_response_response_id", "response_id"),
        Index("idx_supplier_requirement_response_requirement_item_id", "requirement_item_id"),
        Index("idx_supplier_requirement_response_fit_status", "fit_status"),
    )

    requirement_response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_evaluation_response.response_id", name="fk_supplier_requirement_response_response", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evaluation_requirement_item.requirement_item_id", name="fk_supplier_requirement_response_requirement_item", ondelete="CASCADE"),
        nullable=False,
    )
    fit_status: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    response: Mapped["SupplierEvaluationResponse"] = relationship(
        "SupplierEvaluationResponse",
        back_populates="requirement_responses",
    )
    requirement_item: Mapped["EvaluationRequirementItem"] = relationship(
        "EvaluationRequirementItem",
        back_populates="requirement_responses",
    )
