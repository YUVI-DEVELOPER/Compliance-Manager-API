import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.permission_group import PermissionGroup
    from app.models.role import Role


class RolePermissionGroup(Base):
    __tablename__ = "role_permission_group"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_group_id", name="uq_role_permission_group_role_group"),
        Index("idx_role_permission_group_role_id", "role_id"),
        Index("idx_role_permission_group_group_id", "permission_group_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("role.id", name="fk_role_permission_group_role", ondelete="CASCADE"),
        nullable=False,
    )
    permission_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permission_group.id", name="fk_role_permission_group_group", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    role: Mapped["Role"] = relationship("Role", back_populates="permission_groups")
    permission_group: Mapped["PermissionGroup"] = relationship("PermissionGroup", back_populates="role_groups")
