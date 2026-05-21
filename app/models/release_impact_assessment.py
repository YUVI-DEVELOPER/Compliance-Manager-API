import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset_release import AssetRelease


class ReleaseImpactAssessment(Base):
    __tablename__ = "release_impact_assessment"
    __table_args__ = (
        Index("idx_release_impact_assessment_release_id", "release_id"),
        Index("idx_release_impact_assessment_previous_release_id", "previous_release_id"),
        Index("idx_release_impact_assessment_generated_dt", "generated_dt"),
    )

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_release.release_id", name="fk_release_impact_assessment_release", ondelete="CASCADE"),
        nullable=False,
    )
    previous_release_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_release.release_id", name="fk_release_impact_assessment_previous_release", ondelete="SET NULL"),
        nullable=True,
    )
    report_title: Mapped[str] = mapped_column(String(250), nullable=False)
    report_content: Mapped[str] = mapped_column(Text, nullable=False)
    report_format: Mapped[str] = mapped_column(String(20), nullable=False, default="MARKDOWN", server_default=text("'MARKDOWN'"))
    diff_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    impact_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    generated_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)

    release: Mapped["AssetRelease"] = relationship(
        "AssetRelease",
        foreign_keys=[release_id],
        back_populates="impact_assessments",
    )
    previous_release: Mapped["AssetRelease | None"] = relationship(
        "AssetRelease",
        foreign_keys=[previous_release_id],
    )
