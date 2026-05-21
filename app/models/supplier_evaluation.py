import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.authored_document import AuthoredDocument
    from app.models.evaluation_requirement_item import EvaluationRequirementItem
    from app.models.supplier_evaluation_response import SupplierEvaluationResponse


class SupplierEvaluation(Base):
    __tablename__ = "supplier_evaluation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'OPEN_FOR_RESPONSE', 'LOCKED', 'CLOSED')",
            name="chk_supplier_evaluation_status",
        ),
        Index("idx_supplier_evaluation_asset_uuid", "asset_uuid"),
        Index("idx_supplier_evaluation_urs_document_id", "urs_document_id"),
        Index("idx_supplier_evaluation_status", "status"),
    )

    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    evaluation_name: Mapped[str] = mapped_column(String(250), nullable=False)
    asset_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_supplier_evaluation_asset", ondelete="RESTRICT"),
        nullable=False,
    )
    urs_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("authored_document.authored_document_id", name="fk_supplier_evaluation_urs_document", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    asset: Mapped["Asset"] = relationship("Asset", back_populates="supplier_evaluations")
    urs_document: Mapped["AuthoredDocument"] = relationship("AuthoredDocument", back_populates="supplier_evaluations")
    responses: Mapped[list["SupplierEvaluationResponse"]] = relationship(
        "SupplierEvaluationResponse",
        back_populates="evaluation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    requirement_items: Mapped[list["EvaluationRequirementItem"]] = relationship(
        "EvaluationRequirementItem",
        back_populates="evaluation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
