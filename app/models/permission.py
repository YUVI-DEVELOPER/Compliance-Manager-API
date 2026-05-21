import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.permission_group_item import PermissionGroupItem
    from app.models.role_permission import RolePermission


class Permission(Base):
    __tablename__ = "permission"
    __table_args__ = (
        Index("idx_permission_code", "permission_code"),
        Index("idx_permission_module", "module_name"),
        Index("idx_permission_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    permission_code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    permission_name: Mapped[str] = mapped_column(String(150), nullable=False)
    module_name: Mapped[str] = mapped_column(String(80), nullable=False)
    action_name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system_permission: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission",
        back_populates="permission",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    group_items: Mapped[list["PermissionGroupItem"]] = relationship(
        "PermissionGroupItem",
        back_populates="permission",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
