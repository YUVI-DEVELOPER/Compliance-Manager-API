import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class OrgEntityRoleAssignment(Base):
    __tablename__ = "org_entity_role_assignment"
    __table_args__ = (
        Index("idx_org_entity_role_assignment_is_active", "is_active"),
        Index("idx_org_entity_role_assignment_org_id", "org_id"),
        Index("idx_org_entity_role_assignment_role_id", "role_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org_structure.id", name="fk_org_entity_role_assignment_org", ondelete="RESTRICT"),
        nullable=False,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org_role.id", name="fk_org_entity_role_assignment_role", ondelete="RESTRICT"),
        nullable=False,
    )
    person_name: Mapped[str] = mapped_column(String(150), nullable=False)
    person_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    employee_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(String(150), nullable=True)

    org: Mapped["OrgStructure"] = relationship(
        "OrgStructure",
        back_populates="role_assignments",
    )
    role: Mapped["OrgRole"] = relationship(
        "OrgRole",
        back_populates="assignments",
    )
