import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.authored_document import AuthoredDocument
    from app.models.release_impact_assessment import ReleaseImpactAssessment
    from app.models.release_validation_document_requirement import ReleaseValidationDocumentRequirement
    from app.models.release_validation_package import ReleaseValidationPackage
    from app.models.supplier_qualification_document import SupplierQualificationDocument
    from app.models.validated_document_link import ValidatedDocumentLink


class AssetRelease(Base):
    __tablename__ = "asset_release"
    __table_args__ = (
        UniqueConstraint("asset_id", "version", name="uq_asset_release_asset_version"),
        CheckConstraint("end_dt IS NULL OR end_dt >= created_dt", name="chk_asset_release_end_dt"),
        CheckConstraint(
            "documentation_mode IN ('MANUAL', 'ONLINE_FETCH')",
            name="chk_asset_release_documentation_mode",
        ),
        CheckConstraint(
            "("
            "(documentation_mode = 'MANUAL' AND documentation_text IS NOT NULL AND btrim(documentation_text) <> '') "
            "OR "
            "("
            "documentation_mode = 'ONLINE_FETCH' "
            "AND documentation_source_url IS NOT NULL "
            "AND btrim(documentation_source_url) <> '' "
            "AND documentation_text IS NOT NULL "
            "AND btrim(documentation_text) <> ''"
            ")"
            ")",
            name="chk_asset_release_documentation_payload",
        ),
        Index("idx_asset_release_asset_id", "asset_id"),
        Index("idx_asset_release_version", "version"),
    )

    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_asset_release_asset", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    release_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    previous_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    release_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    vendor_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    planned_implementation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(30), nullable=True)
    release_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_control_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expected_validated_functionality_impact: Mapped[str | None] = mapped_column(String(20), nullable=True)
    release_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    system_config_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    documentation_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    documentation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    documentation_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    documentation_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    end_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    asset: Mapped["Asset"] = relationship("Asset", back_populates="releases")
    document_links: Mapped[list["ValidatedDocumentLink"]] = relationship(
        "ValidatedDocumentLink",
        back_populates="release",
        passive_deletes=True,
    )
    authored_documents: Mapped[list["AuthoredDocument"]] = relationship(
        "AuthoredDocument",
        back_populates="release",
        passive_deletes=True,
    )
    qualification_documents: Mapped[list["SupplierQualificationDocument"]] = relationship(
        "SupplierQualificationDocument",
        back_populates="release",
        passive_deletes=True,
    )
    impact_assessments: Mapped[list["ReleaseImpactAssessment"]] = relationship(
        "ReleaseImpactAssessment",
        back_populates="release",
        foreign_keys="ReleaseImpactAssessment.release_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    validation_package: Mapped["ReleaseValidationPackage | None"] = relationship(
        "ReleaseValidationPackage",
        back_populates="release",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    document_requirements: Mapped[list["ReleaseValidationDocumentRequirement"]] = relationship(
        "ReleaseValidationDocumentRequirement",
        back_populates="release",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
