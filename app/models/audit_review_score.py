import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.audit_review_job import AuditReviewJob


class AuditReviewScore(Base):
    __tablename__ = "audit_review_score"
    __table_args__ = (
        Index("idx_audit_review_score_job_id", "job_id"),
        Index("idx_audit_review_score_asset_id", "asset_id"),
        Index("idx_audit_review_score_check_code", "check_code"),
        Index(
            "uq_audit_review_score_scope_type_check",
            "job_id",
            "score_scope",
            "audit_trail_type",
            "check_code",
            unique=True,
        ),
    )

    score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_review_job.job_id", name="fk_audit_review_score_job", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_audit_review_score_asset", ondelete="CASCADE"),
        nullable=False,
    )
    check_code: Mapped[str] = mapped_column(String(80), nullable=False, server_default=text("'OVERALL'"))
    check_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        server_default=text("'Overall Compliance Score'"),
    )
    score_scope: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'CHECKPOINT'"))
    audit_trail_type: Mapped[str] = mapped_column(String(100), nullable=False, server_default=text("'ALL'"))
    score_label: Mapped[str | None] = mapped_column(String(150), nullable=True)
    applicability: Mapped[str | None] = mapped_column(String(30), nullable=True)
    evaluated_record_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    skipped_record_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    no_data_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[str | None] = mapped_column(String(30), nullable=True)
    score_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'NOT_SCORED'"))
    source_record_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    penalty_per_finding: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    penalty_cap: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    raw_penalty: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    applied_penalty: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    scoring_summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped["AuditReviewJob"] = relationship("AuditReviewJob", back_populates="scores")
    asset: Mapped["Asset"] = relationship("Asset")
