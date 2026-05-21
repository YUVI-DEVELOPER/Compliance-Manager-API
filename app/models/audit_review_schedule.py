import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.audit_review_job import AuditReviewJob
    from app.models.audit_review_schedule_run import AuditReviewScheduleRun


class AuditReviewSchedule(Base):
    __tablename__ = "audit_review_schedule"
    __table_args__ = (
        Index("idx_audit_review_schedule_asset_id", "asset_id"),
        Index("idx_audit_review_schedule_enabled_next_run", "enabled", "next_run_dt"),
        Index("idx_audit_review_schedule_last_job_id", "last_job_id"),
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_audit_review_schedule_asset", ondelete="CASCADE"),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    vault_dns: Mapped[str | None] = mapped_column(String(255), nullable=True)
    veeva_instance_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    veeva_app_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    audit_trail_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        server_default=text("'login_audit_trail'"),
    )
    review_scope: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'LOGIN_ONLY'"))
    selected_audit_trail_types_json: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[\"login_audit_trail\"]'::jsonb"),
    )
    frequency: Mapped[str] = mapped_column(String(30), nullable=False)
    review_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schedule_start_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schedule_end_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_condition: Mapped[str | None] = mapped_column(String(30), nullable=True)
    end_after_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_last_day_of_month: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cycle_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_timing: Mapped[str | None] = mapped_column(String(50), nullable=True)
    run_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    custom_cycle_start_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_year_start_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audit_retrieval_mode: Mapped[str | None] = mapped_column(String(40), nullable=True)
    custom_audit_start_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    custom_audit_end_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_review_job.job_id", name="fk_audit_review_schedule_last_job", ondelete="SET NULL"),
        nullable=True,
    )
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, server_default=text("'Asia/Kolkata'"))
    business_start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    business_end_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    asset: Mapped["Asset"] = relationship("Asset")
    last_job: Mapped["AuditReviewJob | None"] = relationship("AuditReviewJob")
    runs: Mapped[list["AuditReviewScheduleRun"]] = relationship(
        "AuditReviewScheduleRun",
        back_populates="schedule",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
