import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.supplier_qualification_document import SupplierQualificationDocument


class SupplierQualificationDocumentAction(Base):
    __tablename__ = "supplier_qualification_document_action"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('REGISTER', 'SUBMIT_FOR_REVIEW', 'ACCEPT', 'REJECT', 'REQUEST_CLARIFICATION')",
            name="chk_supplier_qualification_document_action_type",
        ),
        CheckConstraint(
            "from_status IN ('SUBMITTED', 'IN_REVIEW', 'ACCEPTED', 'REJECTED', 'NEEDS_CLARIFICATION')",
            name="chk_supplier_qualification_document_action_from_status",
        ),
        CheckConstraint(
            "to_status IN ('SUBMITTED', 'IN_REVIEW', 'ACCEPTED', 'REJECTED', 'NEEDS_CLARIFICATION')",
            name="chk_supplier_qualification_document_action_to_status",
        ),
        Index(
            "idx_supplier_qualification_document_action_document_id",
            "qualification_document_id",
        ),
        Index("idx_supplier_qualification_document_action_type", "action_type"),
        Index("idx_supplier_qualification_document_action_dt", "action_dt"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    qualification_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "supplier_qualification_document.qualification_document_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    action_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    action_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    comment_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_status: Mapped[str] = mapped_column(String(30), nullable=False)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)

    qualification_document: Mapped["SupplierQualificationDocument"] = relationship(
        "SupplierQualificationDocument",
        back_populates="actions",
    )
