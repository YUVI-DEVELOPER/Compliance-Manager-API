import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.supplier_evaluation import SupplierEvaluation
    from app.models.supplier_requirement_response import SupplierRequirementResponse


class EvaluationRequirementItem(Base):
    __tablename__ = "evaluation_requirement_item"
    __table_args__ = (
        Index("idx_evaluation_requirement_item_evaluation_id", "evaluation_id"),
        Index("idx_evaluation_requirement_item_urs_document_id", "urs_document_id"),
        Index("idx_evaluation_requirement_item_order", "evaluation_id", "requirement_order"),
    )

    requirement_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_evaluation.evaluation_id", name="fk_evaluation_requirement_item_evaluation", ondelete="CASCADE"),
        nullable=False,
    )
    urs_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("authored_document.authored_document_id", name="fk_evaluation_requirement_item_urs_document", ondelete="RESTRICT"),
        nullable=False,
    )
    requirement_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requirement_section: Mapped[str | None] = mapped_column(String(250), nullable=True)
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    evaluation: Mapped["SupplierEvaluation"] = relationship("SupplierEvaluation", back_populates="requirement_items")
    requirement_responses: Mapped[list["SupplierRequirementResponse"]] = relationship(
        "SupplierRequirementResponse",
        back_populates="requirement_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
