import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.permission import Permission
    from app.models.permission_group import PermissionGroup


class PermissionGroupItem(Base):
    __tablename__ = "permission_group_item"
    __table_args__ = (
        UniqueConstraint("group_id", "permission_id", name="uq_permission_group_item_group_permission"),
        Index("idx_permission_group_item_group_id", "group_id"),
        Index("idx_permission_group_item_permission_id", "permission_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permission_group.id", name="fk_permission_group_item_group", ondelete="CASCADE"),
        nullable=False,
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permission.id", name="fk_permission_group_item_permission", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    group: Mapped["PermissionGroup"] = relationship("PermissionGroup", back_populates="items")
    permission: Mapped["Permission"] = relationship("Permission", back_populates="group_items")
