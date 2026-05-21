import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.audit_review_finding import AuditReviewFinding
    from app.models.audit_review_report import AuditReviewReport
    from app.models.audit_review_score import AuditReviewScore
    from app.models.audit_trail_record import AuditTrailRecord


class AuditReviewJob(Base):
    __tablename__ = "audit_review_job"
    __table_args__ = (
        Index("idx_audit_review_job_asset_id", "asset_id"),
        Index("idx_audit_review_job_status", "status"),
        Index("idx_audit_review_job_created_dt", "created_dt"),
        Index("idx_audit_review_job_review_candidate_key", "review_candidate_key"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_audit_review_job_asset", ondelete="CASCADE"),
        nullable=False,
    )
    review_candidate_key: Mapped[str] = mapped_column(String(500), nullable=False)
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
    review_start_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_end_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_basis: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'MANUAL'"))
    trigger_mode: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'MANUAL'"))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    extraction_summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    analysis_summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    report_summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    asset: Mapped["Asset"] = relationship("Asset")
    records: Mapped[list["AuditTrailRecord"]] = relationship(
        "AuditTrailRecord",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    findings: Mapped[list["AuditReviewFinding"]] = relationship(
        "AuditReviewFinding",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    scores: Mapped[list["AuditReviewScore"]] = relationship(
        "AuditReviewScore",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reports: Mapped[list["AuditReviewReport"]] = relationship(
        "AuditReviewReport",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
