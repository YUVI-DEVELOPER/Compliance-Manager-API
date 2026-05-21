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


class AuditReviewReport(Base):
    __tablename__ = "audit_review_report"
    __table_args__ = (
        Index("idx_audit_review_report_job_id", "job_id"),
        Index("idx_audit_review_report_asset_id", "asset_id"),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_review_job.job_id", name="fk_audit_review_report_job", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_audit_review_report_asset", ondelete="CASCADE"),
        nullable=False,
    )
    report_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'NOT_GENERATED'"))
    report_summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    report_payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    trigger_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    schedule_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    workflow_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    submitted_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    submitted_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    reviewed_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_decision_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_e_signed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    e_signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    e_signed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_locked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    final_pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_pdf_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    report_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ai_summary_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_generation_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ai_generated_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    ai_generated_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ai_model_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    ai_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped["AuditReviewJob"] = relationship("AuditReviewJob", back_populates="reports")
    asset: Mapped["Asset"] = relationship("Asset")
