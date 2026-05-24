import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.authored_document import AuthoredDocument
    from app.models.asset_finance import AssetFinance
    from app.models.asset_group_membership import AssetGroupMembership
    from app.models.asset_location import AssetLocation
    from app.models.asset_release import AssetRelease
    from app.models.org_structure import OrgStructure
    from app.models.supplier_qualification_document import SupplierQualificationDocument
    from app.models.supplier_evaluation import SupplierEvaluation
    from app.models.supplier import Supplier
    from app.models.validated_document_link import ValidatedDocumentLink


class Asset(Base):
    __tablename__ = "asset_basic_info"
    __table_args__ = (
        UniqueConstraint("asset_code", name="uq_asset_code"),
        UniqueConstraint("asset_serial_no", name="uq_asset_serial_no"),
        Index("idx_asset_code", "asset_code"),
        Index("idx_asset_org_node", "org_node_id"),
        Index("idx_asset_status", "asset_status"),
        Index("idx_asset_supplier", "supplier_id"),
        Index("idx_asset_type", "asset_type"),
        Index("idx_asset_class", "asset_class"),
        Index("idx_asset_category", "asset_category"),
        Index("idx_asset_sub_category", "asset_sub_category"),
    )

    asset_uuid: Mapped[uuid.UUID] = mapped_column(
        "asset_id",
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org_structure.id", name="fk_asset_org", ondelete="RESTRICT"),
        nullable=False,
    )

    asset_id: Mapped[str] = mapped_column("asset_code", String(20), nullable=False)
    legacy_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    qr_barcode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rfid_tag: Mapped[str | None] = mapped_column(String(30), nullable=True)
    serial_number: Mapped[str | None] = mapped_column("asset_serial_no", String(50), nullable=True)

    asset_class: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_category: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_sub_category: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    criticality_class: Mapped[str] = mapped_column("asset_criticality", String(50), nullable=False)
    asset_nature: Mapped[str] = mapped_column(String(50), nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    asset_spec_values: Mapped[list[dict[str, str | None]] | None] = mapped_column(JSONB, nullable=True)

    asset_name: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_description: Mapped[str] = mapped_column(String(500), nullable=False)
    short_description: Mapped[str] = mapped_column(String(40), nullable=False)
    tag_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    asset_owner: Mapped[str] = mapped_column(String(150), nullable=False)

    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.supplier_id", name="fk_asset_supplier", ondelete="SET NULL"),
        nullable=True,
    )

    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    asset_version: Mapped[str | None] = mapped_column(String(25), nullable=True)

    asset_commission_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    asset_purchase_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    asset_purchase_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)

    warranty_period: Mapped[int | None] = mapped_column(Integer, nullable=True)

    asset_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    asset_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    asset_release_url: Mapped[str | None] = mapped_column(String(250), nullable=True)
    asset_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    org_node: Mapped["OrgStructure"] = relationship("OrgStructure")
    supplier: Mapped["Supplier | None"] = relationship("Supplier")
    finance: Mapped["AssetFinance | None"] = relationship(
        "AssetFinance",
        back_populates="asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        foreign_keys="AssetFinance.asset_uuid",
        primaryjoin="Asset.asset_uuid == AssetFinance.asset_uuid",
    )
    location: Mapped["AssetLocation | None"] = relationship(
        "AssetLocation",
        back_populates="asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        foreign_keys="AssetLocation.asset_uuid",
        primaryjoin="Asset.asset_uuid == AssetLocation.asset_uuid",
    )
    releases: Mapped[list["AssetRelease"]] = relationship(
        "AssetRelease",
        back_populates="asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="AssetRelease.asset_id",
        primaryjoin="Asset.asset_uuid == AssetRelease.asset_id",
    )
    document_links: Mapped[list["ValidatedDocumentLink"]] = relationship(
        "ValidatedDocumentLink",
        back_populates="asset",
        passive_deletes=True,
        foreign_keys="ValidatedDocumentLink.asset_id",
        primaryjoin="Asset.asset_uuid == ValidatedDocumentLink.asset_id",
    )
    authored_documents: Mapped[list["AuthoredDocument"]] = relationship(
        "AuthoredDocument",
        back_populates="asset",
        passive_deletes=True,
        foreign_keys="AuthoredDocument.asset_id",
        primaryjoin="Asset.asset_uuid == AuthoredDocument.asset_id",
    )
    qualification_documents: Mapped[list["SupplierQualificationDocument"]] = relationship(
        "SupplierQualificationDocument",
        back_populates="asset",
        passive_deletes=True,
        foreign_keys="SupplierQualificationDocument.asset_id",
        primaryjoin="Asset.asset_uuid == SupplierQualificationDocument.asset_id",
    )
    supplier_evaluations: Mapped[list["SupplierEvaluation"]] = relationship(
        "SupplierEvaluation",
        back_populates="asset",
        passive_deletes=True,
        foreign_keys="SupplierEvaluation.asset_uuid",
        primaryjoin="Asset.asset_uuid == SupplierEvaluation.asset_uuid",
    )
    group_memberships: Mapped[list["AssetGroupMembership"]] = relationship(
        "AssetGroupMembership",
        back_populates="asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="AssetGroupMembership.asset_uuid",
        primaryjoin="Asset.asset_uuid == AssetGroupMembership.asset_uuid",
    )

    @property
    def asset_code(self) -> str:
        return self.asset_id

    @property
    def asset_serial_no(self) -> str | None:
        return self.serial_number

    @property
    def asset_criticality(self) -> str:
        return self.criticality_class
