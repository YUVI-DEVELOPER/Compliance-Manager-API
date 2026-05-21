import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.asset import Asset


class AssetLocation(Base):
    __tablename__ = "asset_location"
    __table_args__ = (
        UniqueConstraint("asset_uuid", name="uq_asset_location_asset_uuid"),
        CheckConstraint(
            "char_length(btrim(building_reference)) > 0",
            name="chk_asset_location_building_reference_not_blank",
        ),
        CheckConstraint(
            "char_length(btrim(floor_reference)) > 0",
            name="chk_asset_location_floor_reference_not_blank",
        ),
        CheckConstraint(
            "char_length(btrim(local_reference)) > 0",
            name="chk_asset_location_local_reference_not_blank",
        ),
    )

    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    asset_uuid: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("asset_basic_info.asset_id", name="fk_asset_location_asset", ondelete="CASCADE"),
        nullable=False,
    )
    building_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    floor_reference: Mapped[str] = mapped_column(String(60), nullable=False)
    local_reference: Mapped[str] = mapped_column(String(150), nullable=False)
    remarks: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    asset: Mapped["Asset"] = relationship("Asset", back_populates="location")
