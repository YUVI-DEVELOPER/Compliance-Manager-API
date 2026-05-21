from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset_spec import AssetSpec


class LookupValue(Base):
    __tablename__ = "lookup_value"
    __table_args__ = (
        UniqueConstraint("lookup_id", "code", name="lookup_value_lookup_id_code_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lookup_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("lookup_master.id", name="lookup_value_lookup_id_fkey", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )

    lookup_master: Mapped["LookupMaster"] = relationship(
        "LookupMaster",
        back_populates="values",
    )
    asset_specs: Mapped[list["AssetSpec"]] = relationship(
        "AssetSpec",
        back_populates="asset_sub_category",
    )
