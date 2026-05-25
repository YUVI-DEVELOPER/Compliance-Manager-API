import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset_release import AssetRelease
    from app.models.release_validation_document_requirement import ReleaseValidationDocumentRequirement
    from app.models.release_validation_impact_assessment import ReleaseValidationImpactAssessment


class ReleaseValidationPackage(Base):
    __tablename__ = "release_validation_package"
    __table_args__ = (
        UniqueConstraint("release_id", name="uq_release_validation_package_release"),
        UniqueConstraint("package_no", name="uq_release_validation_package_no"),
        Index("idx_release_validation_package_release_id", "release_id"),
        Index("idx_release_validation_package_package_no", "package_no"),
        Index("idx_release_validation_package_package_status", "package_status"),
        Index("idx_release_validation_package_validation_scope", "validation_scope"),
        Index("idx_release_validation_package_impact_assessment_status", "impact_assessment_status"),
    )

    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_release.release_id", name="fk_release_validation_package_release", ondelete="CASCADE"),
        nullable=False,
    )
    package_no: Mapped[str] = mapped_column(String(50), nullable=False)
    package_status: Mapped[str] = mapped_column(String(50), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))
    validation_scope: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="NOT_ASSESSED",
        server_default=text("'NOT_ASSESSED'"),
    )
    risk_level: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="NOT_ASSESSED",
        server_default=text("'NOT_ASSESSED'"),
    )
    impact_assessment_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PENDING",
        server_default=text("'PENDING'"),
    )
    document_checklist_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="NOT_GENERATED",
        server_default=text("'NOT_GENERATED'"),
    )
    testing_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="NOT_STARTED",
        server_default=text("'NOT_STARTED'"),
    )
    approval_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="NOT_STARTED",
        server_default=text("'NOT_STARTED'"),
    )
    final_decision: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    modified_by: Mapped[str | None] = mapped_column(String, nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    release: Mapped["AssetRelease"] = relationship("AssetRelease", back_populates="validation_package")
    impact_assessment: Mapped["ReleaseValidationImpactAssessment | None"] = relationship(
        "ReleaseValidationImpactAssessment",
        back_populates="package",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    document_requirements: Mapped[list["ReleaseValidationDocumentRequirement"]] = relationship(
        "ReleaseValidationDocumentRequirement",
        back_populates="package",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ReleaseValidationDocumentRequirement.display_order",
    )
