from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_event_time", "event_time"),
        Index("idx_audit_module_name", "module_name"),
        Index("idx_audit_entity_name", "entity_name"),
        Index("idx_audit_action", "action"),
        Index("idx_audit_record_id", "record_id"),
        Index("idx_audit_performed_by_user_id", "performed_by_user_id"),
        Index("idx_audit_status", "status"),
        Index("idx_audit_changed_at", "changed_at"),
        Index("idx_audit_operation", "operation_type"),
        Index("idx_audit_record_pk", "record_pk", postgresql_using="gin"),
        Index("idx_audit_table", "table_name"),
    )

    audit_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    module_name: Mapped[str] = mapped_column(String(120), nullable=False, server_default=text("'System'"))
    entity_name: Mapped[str] = mapped_column(String(120), nullable=False, server_default=text("'Record'"))
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    record_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False, server_default=text("'SYSTEM_EVENT'"))
    event_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    operation_type: Mapped[str] = mapped_column(String(10), nullable=False)
    record_pk: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    old_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    changed_columns: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    changed_fields: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    performed_by_user_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    performed_by_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    performed_by_email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    performed_by_role: Mapped[str | None] = mapped_column(String(150), nullable=True)
    changed_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now())
    application_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'SUCCESS'"))
    request_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
