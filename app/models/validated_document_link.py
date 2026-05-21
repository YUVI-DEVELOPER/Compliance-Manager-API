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
    from app.models.document_vectorization_job import DocumentVectorizationJob


class ValidatedDocumentLink(Base):
    __tablename__ = "validated_document_link"
    __table_args__ = (
        CheckConstraint(
            "(asset_id IS NOT NULL AND release_id IS NULL) OR (asset_id IS NULL AND release_id IS NOT NULL)",
            name="chk_validated_document_link_exactly_one_target",
        ),
        Index("idx_validated_document_link_asset_id", "asset_id"),
        Index("idx_validated_document_link_release_id", "release_id"),
        Index("idx_validated_document_link_source_system", "source_system"),
        Index("idx_validated_document_link_document_type", "document_type"),
        Index("idx_validated_document_link_external_document_id", "external_document_id"),
        Index(
            "uq_vdl_asset_ext_doc",
            "asset_id",
            "source_system",
            "external_document_id",
            unique=True,
            postgresql_where=text("asset_id IS NOT NULL"),
        ),
        Index(
            "uq_vdl_release_ext_doc",
            "release_id",
            "source_system",
            "external_document_id",
            unique=True,
            postgresql_where=text("release_id IS NOT NULL"),
        ),
    )

    document_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_validated_document_link_asset", ondelete="CASCADE"),
        nullable=True,
    )
    release_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_release.release_id", name="fk_validated_document_link_release", ondelete="CASCADE"),
        nullable=True,
    )
    source_system: Mapped[str] = mapped_column(String(50), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_document_id: Mapped[str] = mapped_column(String(150), nullable=False)
    document_name: Mapped[str] = mapped_column(String(250), nullable=False)
    document_version: Mapped[str] = mapped_column(String(50), nullable=False)
    upload_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    access_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    asset: Mapped["Asset | None"] = relationship("Asset", back_populates="document_links")
    release: Mapped["AssetRelease | None"] = relationship("AssetRelease", back_populates="document_links")
    vectorization_job: Mapped["DocumentVectorizationJob | None"] = relationship(
        "DocumentVectorizationJob",
        back_populates="document_link",
        uselist=False,
    )
