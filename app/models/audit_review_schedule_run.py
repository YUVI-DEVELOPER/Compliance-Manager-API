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
    from app.models.audit_review_schedule import AuditReviewSchedule


class AuditReviewScheduleRun(Base):
    __tablename__ = "audit_review_schedule_run"
    __table_args__ = (
        Index("idx_audit_review_schedule_run_schedule_id", "schedule_id"),
        Index("idx_audit_review_schedule_run_asset_id", "asset_id"),
        Index("idx_audit_review_schedule_run_job_id", "job_id"),
        Index("idx_audit_review_schedule_run_status", "status"),
        Index("idx_audit_review_schedule_run_started_at", "started_at"),
        Index(
            "uq_audit_review_schedule_run_active",
            "schedule_id",
            unique=True,
            postgresql_where=text("status = 'STARTED' AND completed_at IS NULL"),
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_review_schedule.schedule_id", name="fk_audit_review_schedule_run_schedule", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_audit_review_schedule_run_asset", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_review_job.job_id", name="fk_audit_review_schedule_run_job", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    schedule: Mapped["AuditReviewSchedule"] = relationship("AuditReviewSchedule", back_populates="runs")
    asset: Mapped["Asset"] = relationship("Asset")
    job: Mapped["AuditReviewJob | None"] = relationship("AuditReviewJob")
