import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Sequence, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.lookup_value import LookupValue


class AssetSpec(Base):
    __tablename__ = "asset_specs"
    __table_args__ = (
        UniqueConstraint("parameter_seq", name="uq_asset_specs_parameter_seq"),
        Index("idx_asset_specs_sub_category", "asset_sub_category_id"),
        Index("idx_asset_specs_sub_category_grouping", "asset_sub_category_id", "parameter_grouping"),
        Index("idx_asset_specs_grouping", "parameter_grouping"),
        Index("idx_asset_specs_active", "is_active"),
        Index(
            "uq_asset_specs_active_group_name",
            "asset_sub_category_id",
            "parameter_grouping",
            "parameter_name",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    asset_spec_id: Mapped[uuid.UUID] = mapped_column(
        "asset_spec_id",
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    asset_sub_category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("lookup_value.id", name="fk_asset_specs_sub_category", ondelete="RESTRICT"),
        nullable=False,
    )
    parameter_seq: Mapped[int] = mapped_column(
        Integer,
        Sequence("asset_specs_parameter_seq_seq"),
        nullable=False,
        server_default=text("nextval('asset_specs_parameter_seq_seq'::regclass)"),
    )
    parameter_grouping: Mapped[str] = mapped_column(String(50), nullable=False)
    parameter_name: Mapped[str] = mapped_column(String(50), nullable=False)
    parameter_value: Mapped[str] = mapped_column(String(150), nullable=False)
    guidelines: Mapped[str | None] = mapped_column(String(150), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)

    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    asset_sub_category: Mapped["LookupValue"] = relationship(
        "LookupValue",
        back_populates="asset_specs",
    )
