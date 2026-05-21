import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.asset_group import AssetGroup


class AssetGroupMembership(Base):
    __tablename__ = "asset_group_membership"
    __table_args__ = (
        UniqueConstraint("group_id", "asset_uuid", name="uq_asset_group_membership_group_asset"),
        Index("idx_asset_group_membership_group", "group_id"),
        Index("idx_asset_group_membership_asset", "asset_uuid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        "membership_id",
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_group.group_id", name="fk_asset_group_membership_group", ondelete="CASCADE"),
        nullable=False,
    )
    asset_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_asset_group_membership_asset", ondelete="CASCADE"),
        nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    group: Mapped["AssetGroup"] = relationship("AssetGroup", back_populates="memberships")
    asset: Mapped["Asset"] = relationship("Asset", back_populates="group_memberships")
