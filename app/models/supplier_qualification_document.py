import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.asset_release import AssetRelease
    from app.models.supplier import Supplier
    from app.models.supplier_qualification_document_action import SupplierQualificationDocumentAction


class SupplierQualificationDocument(Base):
    __tablename__ = "supplier_qualification_document"
    __table_args__ = (
        CheckConstraint(
            "(asset_id IS NOT NULL OR release_id IS NOT NULL)",
            name="chk_supplier_qualification_document_target",
        ),
        CheckConstraint(
            "qualification_type IN ('IQ', 'OQ', 'PQ')",
            name="chk_supplier_qualification_document_type",
        ),
        CheckConstraint(
            "status IN ('SUBMITTED', 'IN_REVIEW', 'ACCEPTED', 'REJECTED', 'NEEDS_CLARIFICATION')",
            name="chk_supplier_qualification_document_status",
        ),
        Index("idx_supplier_qualification_document_asset_id", "asset_id"),
        Index("idx_supplier_qualification_document_release_id", "release_id"),
        Index("idx_supplier_qualification_document_supplier_id", "supplier_id"),
        Index("idx_supplier_qualification_document_type", "qualification_type"),
        Index("idx_supplier_qualification_document_status", "status"),
        Index("idx_supplier_qualification_document_source_system", "source_system"),
        Index("idx_supplier_qualification_document_external_document_id", "external_document_id"),
    )

    qualification_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    qualification_type: Mapped[str] = mapped_column(String(10), nullable=False)
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_supplier_qualification_document_asset", ondelete="CASCADE"),
        nullable=True,
    )
    release_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_release.release_id", name="fk_supplier_qualification_document_release", ondelete="CASCADE"),
        nullable=True,
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.supplier_id", name="fk_supplier_qualification_document_supplier", ondelete="RESTRICT"),
        nullable=False,
    )
    document_name: Mapped[str] = mapped_column(String(250), nullable=False)
    document_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_system: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_document_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    document_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submission_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'SUBMITTED'"))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    asset: Mapped["Asset | None"] = relationship("Asset", back_populates="qualification_documents")
    release: Mapped["AssetRelease | None"] = relationship("AssetRelease", back_populates="qualification_documents")
    supplier: Mapped["Supplier"] = relationship("Supplier", back_populates="qualification_documents")
    actions: Mapped[list["SupplierQualificationDocumentAction"]] = relationship(
        "SupplierQualificationDocumentAction",
        back_populates="qualification_document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
