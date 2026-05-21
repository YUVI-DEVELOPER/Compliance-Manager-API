from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class LookupMaster(Base):
    __tablename__ = "lookup_master"
    __table_args__ = (
        UniqueConstraint("lookup_key", name="lookup_master_lookup_key_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lookup_key: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(250), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, server_default=func.now())
    modified_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modified_dt: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )


    values: Mapped[list["LookupValue"]] = relationship(
        "LookupValue",
        back_populates="lookup_master",
    )
