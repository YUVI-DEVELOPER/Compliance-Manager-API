import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.asset_release import AssetRelease
    from app.models.authored_document_review_action import AuthoredDocumentReviewAction
    from app.models.document_template import DocumentTemplate
    from app.models.supplier_evaluation import SupplierEvaluation


class AuthoredDocument(Base):
    __tablename__ = "authored_document"
    __table_args__ = (
        CheckConstraint(
            "(asset_id IS NOT NULL AND release_id IS NULL) OR (asset_id IS NULL AND release_id IS NOT NULL)",
            name="chk_authored_document_exactly_one_target",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'IN_REVIEW', 'CHANGES_REQUESTED', 'APPROVED', 'REJECTED')",
            name="chk_authored_document_status",
        ),
        CheckConstraint(
            "publish_status IN ('NOT_PUBLISHED', 'PUBLISH_PENDING', 'PUBLISHED', 'PUBLISH_FAILED')",
            name="chk_authored_document_publish_status",
        ),
        Index("idx_authored_document_asset_id", "asset_id"),
        Index("idx_authored_document_release_id", "release_id"),
        Index("idx_authored_document_template_id", "template_id"),
        Index("idx_authored_document_document_type", "document_type"),
        Index("idx_authored_document_status", "status"),
        Index("idx_authored_document_publish_status", "publish_status"),
        Index("idx_authored_document_external_system", "external_system"),
        Index("idx_authored_document_external_document_id", "external_document_id"),
    )

    authored_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'DRAFT'"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_authored_document_asset", ondelete="CASCADE"),
        nullable=True,
    )
    release_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_release.release_id", name="fk_authored_document_release", ondelete="CASCADE"),
        nullable=True,
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_template.template_id", name="fk_authored_document_template", ondelete="RESTRICT"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_context_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reviewer_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    approver_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    publish_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'NOT_PUBLISHED'"),
    )
    last_publish_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_publish_attempt_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    external_system: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_document_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    external_document_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    external_document_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_document_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publish_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    asset: Mapped["Asset | None"] = relationship("Asset", back_populates="authored_documents")
    release: Mapped["AssetRelease | None"] = relationship("AssetRelease", back_populates="authored_documents")
    template: Mapped["DocumentTemplate"] = relationship("DocumentTemplate", back_populates="authored_documents")
    review_actions: Mapped[list["AuthoredDocumentReviewAction"]] = relationship(
        "AuthoredDocumentReviewAction",
        back_populates="authored_document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    supplier_evaluations: Mapped[list["SupplierEvaluation"]] = relationship(
        "SupplierEvaluation",
        back_populates="urs_document",
        passive_deletes=True,
    )
