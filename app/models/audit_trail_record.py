import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.audit_review_job import AuditReviewJob


class AuditTrailRecord(Base):
    __tablename__ = "audit_trail_record"
    __table_args__ = (
        Index("idx_audit_trail_record_job_id", "job_id"),
        Index("idx_audit_trail_record_asset_id", "asset_id"),
        Index("idx_audit_trail_record_event_timestamp", "event_timestamp"),
        Index("idx_audit_trail_record_source_key", "source_record_key"),
    )

    record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_review_job.job_id", name="fk_audit_trail_record_job", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_audit_trail_record_asset", ondelete="CASCADE"),
        nullable=False,
    )
    source_record_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    audit_trail_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        server_default=text("'login_audit_trail'"),
    )
    event_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    action_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    object_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    object_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    field_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_control_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    auth_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_delete_action: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_permission_change: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_export_action: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_configuration_change: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    record_quality_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'VALID'"))
    raw_payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    normalized_extra_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    job: Mapped["AuditReviewJob"] = relationship("AuditReviewJob", back_populates="records")
    asset: Mapped["Asset"] = relationship("Asset")
