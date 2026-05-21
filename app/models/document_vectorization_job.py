import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.validated_document_link import ValidatedDocumentLink


class DocumentVectorizationJob(Base):
    __tablename__ = "document_vectorization_job"
    __table_args__ = (
        Index("idx_document_vectorization_job_document_link_id", "document_link_id"),
        Index("idx_document_vectorization_job_status", "status"),
        Index("idx_document_vectorization_job_is_active", "is_active"),
        Index(
            "uq_document_vectorization_job_document_link",
            "document_link_id",
            unique=True,
            postgresql_where=text("document_link_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    document_link_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "validated_document_link.document_link_id",
            name="fk_document_vectorization_job_document_link",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    rag_document_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    queue_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chunking_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chunking_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    weaviate_write_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    weaviate_write_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_stage: Mapped[str | None] = mapped_column(String(80), nullable=True)
    process_log_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weaviate_collection: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    modified_dt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document_link: Mapped["ValidatedDocumentLink | None"] = relationship(
        "ValidatedDocumentLink",
        back_populates="vectorization_job",
    )
