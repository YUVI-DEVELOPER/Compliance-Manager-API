import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.supplier_evaluation_response import SupplierEvaluationResponse


class SupplierResponseDocument(Base):
    __tablename__ = "supplier_response_document"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('QUOTATION', 'TECHNICAL_RESPONSE', 'COMMERCIAL_RESPONSE', 'SUPPORTING_DOCUMENT')",
            name="chk_supplier_response_document_type",
        ),
        Index("idx_supplier_response_document_response_id", "response_id"),
        Index("idx_supplier_response_document_type", "document_type"),
        Index("idx_supplier_response_document_source_system", "source_system"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier_evaluation_response.response_id", name="fk_supplier_response_document_response", ondelete="CASCADE"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_document_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    document_name: Mapped[str] = mapped_column(String(250), nullable=False)
    document_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    upload_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    access_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    response: Mapped["SupplierEvaluationResponse"] = relationship("SupplierEvaluationResponse", back_populates="documents")
