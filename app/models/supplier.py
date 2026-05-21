import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.supplier_evaluation_response import SupplierEvaluationResponse
    from app.models.supplier_qualification_document import SupplierQualificationDocument


class Supplier(Base):
    __tablename__ = "supplier"
    __table_args__ = (
        Index("idx_supplier_country", "supplier_country"),
        Index("idx_supplier_name", "supplier_name"),
        Index("idx_supplier_type", "supplier_type"),
    )

    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    supplier_name: Mapped[str] = mapped_column(String(250), nullable=False)
    supplier_type: Mapped[str] = mapped_column(String(50), nullable=False)
    supplier_add1: Mapped[str | None] = mapped_column(String(250), nullable=True)
    supplier_add2: Mapped[str | None] = mapped_column(String(250), nullable=True)
    supplier_city: Mapped[str | None] = mapped_column(String(150), nullable=True)
    supplier_pincode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    supplier_state: Mapped[str | None] = mapped_column(String(150), nullable=True)
    supplier_country: Mapped[str | None] = mapped_column(String(10), nullable=True)

    contact_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    enrolled_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    qualification_documents: Mapped[list["SupplierQualificationDocument"]] = relationship(
        "SupplierQualificationDocument",
        back_populates="supplier",
        passive_deletes=True,
    )
    evaluation_responses: Mapped[list["SupplierEvaluationResponse"]] = relationship(
        "SupplierEvaluationResponse",
        back_populates="supplier",
        passive_deletes=True,
    )
