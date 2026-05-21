import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.audit_review_job import AuditReviewJob
    from app.models.audit_review_report import AuditReviewReport


class AuditReviewNotification(Base):
    __tablename__ = "audit_review_notification"
    __table_args__ = (
        Index("idx_audit_review_notification_report_id", "report_id"),
        Index("idx_audit_review_notification_job_id", "job_id"),
        Index("idx_audit_review_notification_asset_id", "asset_id"),
        Index("idx_audit_review_notification_status", "status"),
        Index("idx_audit_review_notification_priority", "priority"),
        Index("idx_audit_review_notification_created_dt", "created_dt"),
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_review_report.report_id", name="fk_audit_review_notification_report", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_review_job.job_id", name="fk_audit_review_notification_job", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_audit_review_notification_asset", ondelete="CASCADE"),
        nullable=False,
    )
    notification_type: Mapped[str] = mapped_column(String(80), nullable=False)
    priority: Mapped[str] = mapped_column(String(30), nullable=False)
    rating: Mapped[str] = mapped_column(String(50), nullable=False)
    recipient_role: Mapped[str] = mapped_column(String(150), nullable=False)
    recipient_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'READY'"))
    delivery_channel: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'IN_APP'"))
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    report: Mapped["AuditReviewReport"] = relationship("AuditReviewReport")
    job: Mapped["AuditReviewJob"] = relationship("AuditReviewJob")
    asset: Mapped["Asset"] = relationship("Asset")
