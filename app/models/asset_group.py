import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset_group_membership import AssetGroupMembership
    from app.models.org_structure import OrgStructure


class AssetGroup(Base):
    __tablename__ = "asset_group"
    __table_args__ = (
        CheckConstraint("(parent_group_id IS NULL) OR (parent_group_id <> group_id)", name="chk_asset_group_no_self_parent"),
        CheckConstraint("group_type IN ('SYSTEM', 'SUB_SYSTEM')", name="chk_asset_group_type"),
        CheckConstraint("(group_type <> 'SYSTEM') OR (parent_group_id IS NULL)", name="chk_asset_group_system_parent"),
        UniqueConstraint("group_code", name="uq_asset_group_code"),
        Index("idx_asset_group_parent", "parent_group_id"),
        Index("idx_asset_group_type", "group_type"),
        Index("idx_asset_group_org_node", "org_node_id"),
        Index("idx_asset_group_active", "is_active"),
        Index("idx_asset_group_name", "group_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        "group_id",
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    parent_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_group.group_id", name="fk_asset_group_parent", ondelete="RESTRICT"),
        nullable=True,
    )
    org_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org_structure.id", name="fk_asset_group_org_node", ondelete="SET NULL"),
        nullable=True,
    )
    group_name: Mapped[str] = mapped_column(String(150), nullable=False)
    group_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    group_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    parent: Mapped["AssetGroup | None"] = relationship(
        "AssetGroup",
        remote_side=[id],
        back_populates="children",
    )
    children: Mapped[list["AssetGroup"]] = relationship(
        "AssetGroup",
        back_populates="parent",
    )
    org_node: Mapped["OrgStructure | None"] = relationship("OrgStructure")
    memberships: Mapped[list["AssetGroupMembership"]] = relationship(
        "AssetGroupMembership",
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
