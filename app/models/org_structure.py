import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class OrgStructure(Base):
    __tablename__ = "org_structure"
    __table_args__ = (
        CheckConstraint("(parent_id IS NULL) OR (parent_id <> id)", name="chk_no_self_parent"),
        UniqueConstraint("code", name="uq_org_code"),
        Index("idx_org_structure_code", "code"),
        Index("idx_org_structure_parent_id", "parent_id"),
        Index("idx_org_structure_status", "status"),
        Index("idx_org_structure_type", "type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org_structure.id", name="fk_org_structure_parent", ondelete="RESTRICT"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    code: Mapped[str] = mapped_column(String(25), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    address: Mapped[str | None] = mapped_column(String(250), nullable=True)
    city: Mapped[str | None] = mapped_column(String(50), nullable=True)
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    lat: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    long: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    parent: Mapped["OrgStructure | None"] = relationship(
        "OrgStructure",
        remote_side=[id],
        back_populates="children",
    )
    children: Mapped[list["OrgStructure"]] = relationship(
        "OrgStructure",
        back_populates="parent",
    )
    role_assignments: Mapped[list["OrgEntityRoleAssignment"]] = relationship(
        "OrgEntityRoleAssignment",
        back_populates="org",
    )
