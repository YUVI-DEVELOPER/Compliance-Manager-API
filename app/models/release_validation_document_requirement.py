from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset_release import AssetRelease
    from app.models.release_validation_package import ReleaseValidationPackage


class ReleaseValidationDocumentRequirement(Base):
    __tablename__ = "release_validation_document_requirement"
    __table_args__ = (
        CheckConstraint(
            "requirement_level IN ('REQUIRED', 'CONDITIONAL', 'OPTIONAL', 'NOT_REQUIRED')",
            name="chk_release_validation_document_requirement_level",
        ),
        CheckConstraint(
            "status IN ("
            "'MISSING', 'DRAFT', 'UPLOADED', 'LINKED', 'IN_REVIEW', 'APPROVED', "
            "'REJECTED', 'WAIVED', 'NOT_REQUIRED', 'OBSOLETE'"
            ")",
            name="chk_release_validation_document_requirement_status",
        ),
        CheckConstraint(
            "source_type IS NULL OR source_type IN ("
            "'NONE', 'UPLOAD', 'EXTERNAL_URL', 'DOCUMENT_PORTAL', "
            "'AUTHORED_DOCUMENT', 'QUALIFICATION_DOCUMENT'"
            ")",
            name="chk_release_validation_document_requirement_source_type",
        ),
        CheckConstraint("generated_version >= 1", name="chk_release_validation_document_requirement_generated_version"),
        Index("idx_release_validation_document_requirement_package_id", "package_id"),
        Index("idx_release_validation_document_requirement_release_id", "release_id"),
        Index("idx_release_validation_document_requirement_status", "status"),
        Index("idx_release_validation_document_requirement_document_code", "document_code"),
        Index("idx_release_validation_document_requirement_level", "requirement_level"),
        Index("idx_release_validation_document_requirement_active", "is_active"),
        Index(
            "uq_release_validation_document_requirement_active_code",
            "package_id",
            "document_code",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "release_validation_package.package_id",
            name="fk_release_validation_document_requirement_package",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "asset_release.release_id",
            name="fk_release_validation_document_requirement_release",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    document_code: Mapped[str] = mapped_column(String(100), nullable=False)
    document_name: Mapped[str] = mapped_column(String(250), nullable=False)
    document_category: Mapped[str] = mapped_column(String(100), nullable=False)
    document_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirement_level: Mapped[str] = mapped_column(String(40), nullable=False)
    required_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    waivable_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    waiver_requires_qa_flag: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    linked_document_link_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    linked_authored_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    linked_qualification_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    waiver_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    waiver_requested_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    waiver_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    waiver_approved_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    waiver_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trigger_scope: Mapped[str | None] = mapped_column(String(80), nullable=True)
    trigger_risk_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    trigger_question_codes_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    trigger_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    updated_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    package: Mapped["ReleaseValidationPackage"] = relationship(
        "ReleaseValidationPackage",
        back_populates="document_requirements",
    )
    release: Mapped["AssetRelease"] = relationship("AssetRelease", back_populates="document_requirements")
