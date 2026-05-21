import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.audit_review_job import AuditReviewJob


class AuditReviewFinding(Base):
    __tablename__ = "audit_review_finding"
    __table_args__ = (
        Index("idx_audit_review_finding_job_id", "job_id"),
        Index("idx_audit_review_finding_asset_id", "asset_id"),
        Index("idx_audit_review_finding_severity", "severity"),
        Index("idx_audit_review_finding_check_code", "check_code"),
        Index("idx_audit_review_finding_primary_record_id", "primary_record_id"),
    )

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_review_job.job_id", name="fk_audit_review_finding_job", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_audit_review_finding_asset", ondelete="CASCADE"),
        nullable=False,
    )
    primary_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "audit_trail_record.record_id",
            name="fk_audit_review_finding_primary_record",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    check_code: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        server_default=text("'UNSPECIFIED'"),
    )
    check_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        server_default=text("'Unspecified Finding'"),
    )
    audit_trail_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parameter_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    checkpoint_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    finding_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(30), nullable=True)
    score_impact: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    finding_title: Mapped[str | None] = mapped_column(String(250), nullable=True)
    finding_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(250), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    source_record_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'OPEN'"))
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped["AuditReviewJob"] = relationship("AuditReviewJob", back_populates="findings")
    asset: Mapped["Asset"] = relationship("Asset")
