import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class OrgRole(Base):
    __tablename__ = "org_role"
    __table_args__ = (
        UniqueConstraint("role_name", name="uq_org_role_role_name"),
        Index("idx_org_role_is_active", "is_active"),
        Index("idx_org_role_role_raci", "role_raci"),
        Index("idx_org_role_role_type", "role_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    role_name: Mapped[str] = mapped_column(String(150), nullable=False)
    role_raci: Mapped[str] = mapped_column(String(50), nullable=False)
    ownership: Mapped[str] = mapped_column(String(150), nullable=False)
    role_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(150), nullable=True)

    actions: Mapped[list["OrgRoleAction"]] = relationship(
        "OrgRoleAction",
        back_populates="role",
        cascade="all, delete-orphan",
        order_by="OrgRoleAction.seq",
    )
    assignments: Mapped[list["OrgEntityRoleAssignment"]] = relationship(
        "OrgEntityRoleAssignment",
        back_populates="role",
    )
