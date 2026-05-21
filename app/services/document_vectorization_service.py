from __future__ import annotations

import asyncio
import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from fastapi import HTTPException, status
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.asset import Asset
from app.models.asset_release import AssetRelease
from app.models.document_vectorization_job import DocumentVectorizationJob
from app.models.validated_document_link import ValidatedDocumentLink
from app.schemas.document_link_schema import (
    AssetVectorizationDocumentResponse,
    AssetVectorizationSummaryResponse,
    DocumentRagProcessResponse,
    DocumentRagProcessStageResponse,
    DocumentVectorizationChunkListResponse,
    DocumentVectorizationChunkResponse,
    DocumentVectorizationJobResponse,
    DocumentVectorizationReportResponse,
)

logger = logging.getLogger(__name__)

STATUS_PENDING = "PENDING"
STATUS_QUEUED = "QUEUED"
STATUS_PROCESSING = "PROCESSING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_NOT_SUPPORTED = "NOT_SUPPORTED_FOR_VECTORIZATION"

STAGE_FILE_UPLOADED = "FILE_UPLOADED"
STAGE_FILE_STORED = "FILE_STORED"
STAGE_DOCUMENT_LINK_CREATED = "DOCUMENT_LINK_CREATED"
STAGE_JOB_CREATED = "VECTORIZATION_JOB_CREATED"
STAGE_QUEUED = "QUEUED"
STAGE_PROCESSING = "PROCESSING"
STAGE_CHUNKING = "CHUNKING"
STAGE_EMBEDDING = "EMBEDDING"
STAGE_WEAVIATE_STORAGE = "WEAVIATE_STORAGE"
STAGE_COMPLETED = "COMPLETED"
STAGE_FAILED = "FAILED"
STAGE_UNSUPPORTED = "UNSUPPORTED"

SUPPORTED_VECTOR_EXTENSIONS = {".pdf", ".docx", ".txt"}
REPROCESS_BLOCKING_STATUSES = {STATUS_PENDING, STATUS_QUEUED, STATUS_PROCESSING}
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
STAGED_NAME_PATTERN = re.compile(r"^[0-9a-fA-F]{32}_(?P<name>.+)$")
MIN_CHUNK_WORD_FLOOR = 20
DEFAULT_CHUNK_PAGE_SIZE = 25
MAX_CHUNK_PAGE_SIZE = 100
MAX_CHUNK_SEARCH_FETCH = 1000


class VectorizationNotFoundError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class VectorizationValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@dataclass
class LocalStoredFile:
    original_file_name: str | None = None
    stored_file_name: str | None = None
    stored_relative_path: str | None = None
    access_url: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    extension: str | None = None
    local_path: Path | None = None
    reason: str | None = None


@dataclass
class Block:
    text: str
    page: int
    style: str = ""
    font_name: str = ""
    font_size: float = 0.0
    bold: bool = False
    italic: bool = False
    alignment: str = "left"
    indent_left: float = 0.0
    is_toc_entry: bool = False


@dataclass
class DocumentChunk:
    chunk_id: str
    text: str
    page: int
    section_name: str
    section_path: str
    normalized_text: str = ""
    embedding: list[float] | None = None


def can_reprocess_vectorization_job(job: DocumentVectorizationJob | None) -> bool:
    if job is None or not job.is_active:
        return False
    metadata = job.metadata_json or {}
    extension = str(metadata.get("extension") or "").lower()
    return extension in SUPPORTED_VECTOR_EXTENSIONS and job.status not in REPROCESS_BLOCKING_STATUSES


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _append_process_log(
    job: DocumentVectorizationJob,
    *,
    stage: str,
    status_value: str,
    message: str,
    at: datetime | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    timestamp = at or _utc_now()
    log = list(job.process_log_json or [])
    entry: dict[str, Any] = {
        "stage": stage,
        "status": status_value,
        "timestamp": timestamp.isoformat(),
        "message": message,
    }
    if details:
        entry["details"] = details
    log.append(entry)
    job.process_log_json = log


def _reset_process_tracking(job: DocumentVectorizationJob, *, keep_log: bool = False) -> None:
    job.queue_started_at = None
    job.chunking_started_at = None
    job.chunking_completed_at = None
    job.embedding_started_at = None
    job.embedding_completed_at = None
    job.weaviate_write_started_at = None
    job.weaviate_write_completed_at = None
    job.current_stage = None
    if not keep_log:
        job.process_log_json = []


def _mark_process_stage(
    job: DocumentVectorizationJob,
    *,
    stage: str,
    message: str,
    at: datetime | None = None,
    status_value: str = "in_progress",
    details: dict[str, Any] | None = None,
) -> datetime:
    timestamp = at or _utc_now()
    job.current_stage = stage
    _append_process_log(
        job,
        stage=stage,
        status_value=status_value,
        message=message,
        at=timestamp,
        details=details,
    )
    return timestamp


def _current_stage_for_job(job: DocumentVectorizationJob | None) -> str | None:
    if job is None:
        return None
    if job.current_stage:
        return job.current_stage
    status_value = (job.status or "").upper()
    if status_value == STATUS_COMPLETED:
        return STAGE_COMPLETED
    if status_value == STATUS_FAILED:
        return STAGE_FAILED
    if status_value == STATUS_NOT_SUPPORTED:
        return STAGE_UNSUPPORTED
    if status_value in {STATUS_PENDING, STATUS_QUEUED}:
        return STAGE_QUEUED
    if status_value == STATUS_PROCESSING:
        return STAGE_PROCESSING
    return None


def _job_response(job: DocumentVectorizationJob | None) -> DocumentVectorizationJobResponse | None:
    if job is None or not job.is_active:
        return None
    return DocumentVectorizationJobResponse(
        id=job.id,
        rag_document_id=job.rag_document_id,
        status=job.status,
        metadata_json=job.metadata_json or {},
        error_message=job.error_message,
        requested_at=job.requested_at,
        queued_at=job.queued_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        queue_started_at=job.queue_started_at,
        chunking_started_at=job.chunking_started_at,
        chunking_completed_at=job.chunking_completed_at,
        embedding_started_at=job.embedding_started_at,
        embedding_completed_at=job.embedding_completed_at,
        weaviate_write_started_at=job.weaviate_write_started_at,
        weaviate_write_completed_at=job.weaviate_write_completed_at,
        current_stage=_current_stage_for_job(job),
        process_log_json=job.process_log_json or [],
        chunk_count=job.chunk_count,
        weaviate_collection=job.weaviate_collection,
        is_active=job.is_active,
        can_reprocess=can_reprocess_vectorization_job(job),
    )


def _sanitize_filename(value: str) -> str:
    candidate = Path(value).name.strip()
    if not candidate:
        candidate = f"document-{uuid.uuid4().hex[:8]}"
    sanitized = SAFE_FILENAME_PATTERN.sub("_", candidate)
    return sanitized.strip("._") or f"document-{uuid.uuid4().hex[:8]}"


def _strip_staged_prefix(file_name: str) -> str:
    match = STAGED_NAME_PATTERN.match(file_name)
    if match:
        return match.group("name")
    return file_name


def _base_file_storage_dir() -> Path:
    return Path(get_settings().FILE_STORAGE_DIR).resolve()


def _document_storage_root() -> Path:
    return _base_file_storage_dir() / "documents"


def _public_filestorage_url(relative_path: str, base_url: str | None) -> str:
    prefix = (base_url or "").rstrip("/")
    if prefix:
        return f"{prefix}/filestorage/{relative_path}"
    return f"/filestorage/{relative_path}"


def _resolve_local_access_path(access_url: str | None) -> Path | None:
    if not access_url:
        return None

    settings = get_settings()
    parsed = urlparse(access_url)
    if parsed.scheme in {"http", "https"}:
        url_path = unquote(parsed.path).lstrip("/")
    else:
        candidate = Path(access_url)
        if candidate.is_file():
            return candidate.resolve()
        url_path = unquote(access_url).lstrip("/\\")

    normalized = url_path.replace("\\", "/")
    if normalized.startswith("filestorage/"):
        relative = normalized.removeprefix("filestorage/")
        return (Path(settings.FILE_STORAGE_DIR) / relative).resolve()
    if normalized.startswith("uploads/"):
        relative = normalized.removeprefix("uploads/")
        return (Path(settings.FILE_UPLOAD_DIR) / relative).resolve()
    return None


def _safe_relative_to(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _guess_original_file_name(document_link: ValidatedDocumentLink, source_path: Path) -> str:
    reference = (document_link.source_reference or "").strip()
    if reference and Path(reference).suffix:
        return _sanitize_filename(reference)
    return _sanitize_filename(_strip_staged_prefix(source_path.name))


def _target_kind_and_id(document_link: ValidatedDocumentLink) -> tuple[str, uuid.UUID | None]:
    if document_link.asset_id is not None:
        return "asset", document_link.asset_id
    return "release", document_link.release_id


def _finalize_local_document_file(
    document_link: ValidatedDocumentLink,
    *,
    base_url: str | None = None,
) -> LocalStoredFile:
    source_path = _resolve_local_access_path(document_link.access_url)
    if source_path is None:
        return LocalStoredFile(reason="Document link does not reference a local uploaded file.")
    if not source_path.is_file():
        return LocalStoredFile(reason="Local uploaded file is no longer available.")

    document_type = (document_link.document_type or "UNKNOWN").upper()
    target_kind, target_id = _target_kind_and_id(document_link)
    if target_id is None:
        return LocalStoredFile(reason="Document link target is missing.")

    original_file_name = _guess_original_file_name(document_link, source_path)
    extension = Path(original_file_name).suffix.lower() or source_path.suffix.lower()
    stored_file_name = f"{document_link.document_link_id.hex}_{original_file_name}"
    target_dir = _document_storage_root() / target_kind / str(target_id) / document_type
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = (target_dir / stored_file_name).resolve()

    if source_path.resolve() != target_path:
        shutil.copy2(source_path, target_path)

    storage_root = _base_file_storage_dir()
    relative_path = _safe_relative_to(target_path, storage_root)
    if relative_path is None:
        return LocalStoredFile(reason="Stored file path is outside configured file storage.")

    access_url = _public_filestorage_url(relative_path, base_url)
    document_link.access_url = access_url

    return LocalStoredFile(
        original_file_name=original_file_name,
        stored_file_name=stored_file_name,
        stored_relative_path=relative_path,
        access_url=access_url,
        mime_type=None,
        file_size=target_path.stat().st_size,
        extension=extension,
        local_path=target_path,
    )


def _job_metadata(document_link: ValidatedDocumentLink, stored_file: LocalStoredFile) -> dict[str, Any]:
    settings = get_settings()
    release = document_link.release
    release_asset_id = release.asset_id if release is not None else None
    asset_id = document_link.asset_id or release_asset_id
    tenant_id = settings.VECTOR_TENANT_ID.strip() or None

    return {
        "original_file_name": stored_file.original_file_name,
        "stored_file_name": stored_file.stored_file_name,
        "stored_relative_path": stored_file.stored_relative_path,
        "mime_type": stored_file.mime_type,
        "file_size": stored_file.file_size,
        "extension": stored_file.extension,
        "asset_id": str(asset_id) if asset_id is not None else None,
        "release_id": str(document_link.release_id) if document_link.release_id is not None else None,
        "document_link_id": str(document_link.document_link_id),
        "document_type": document_link.document_type,
        "source_system": document_link.source_system,
        "external_document_id": document_link.external_document_id,
        "document_name": document_link.document_name,
        "document_version": document_link.document_version,
        "source_reference": document_link.source_reference,
        "upload_dt": document_link.upload_dt.isoformat() if document_link.upload_dt else None,
        "access_url": document_link.access_url,
        "notes": document_link.notes,
        "target_type": "asset" if document_link.asset_id is not None else "release",
        "target_id": str(document_link.asset_id or document_link.release_id),
        "storage_reason": stored_file.reason,
        "source_system_for_vectorizer": "ValidateNow",
        "rag_pattern": "rag-builder chunking + sentence-transformer embeddings + Weaviate",
        "local_storage_root": "filestorage",
        "supported_extensions": sorted(SUPPORTED_VECTOR_EXTENSIONS),
        "requested_at": _utc_now().isoformat(),
        "collection_name": settings.WEAVIATE_COLLECTION,
        "tenant_id": tenant_id,
        "weaviate_url": settings.WEAVIATE_URL,
        "embedding_model": settings.VECTOR_EMBEDDING_MODEL,
        "chunk_size": settings.VECTOR_CHUNK_SIZE,
        "chunk_overlap_sentences": settings.VECTOR_CHUNK_OVERLAP_SENTENCES,
        "min_content_words": settings.VECTOR_MIN_CONTENT_WORDS,
        "vectorization_enabled": settings.DOCUMENT_VECTORIZATION_ENABLED,
    }


async def prepare_vectorization_job_for_document_link(
    db: AsyncSession,
    document_link: ValidatedDocumentLink,
    *,
    base_url: str | None = None,
) -> bool:
    settings = get_settings()
    now = _utc_now()
    finalize_error: str | None = None
    try:
        stored_file = _finalize_local_document_file(document_link, base_url=base_url)
    except Exception as exc:  # noqa: BLE001 - document link creation must survive vectorization prep failures.
        logger.exception("Failed to finalize document-link file for vectorization")
        finalize_error = str(exc)
        stored_file = LocalStoredFile(reason=f"Failed to finalize local document file: {finalize_error}")
    metadata = _job_metadata(document_link, stored_file)

    status = STATUS_QUEUED
    error_message = None
    extension = (stored_file.extension or "").lower()
    if finalize_error is not None:
        status = STATUS_FAILED
        error_message = finalize_error
    elif not settings.DOCUMENT_VECTORIZATION_ENABLED:
        status = STATUS_NOT_SUPPORTED
        error_message = "Document vectorization is disabled by configuration."
    elif stored_file.local_path is None:
        status = STATUS_NOT_SUPPORTED
        error_message = stored_file.reason or "Document is not available in local file storage."
    elif extension not in SUPPORTED_VECTOR_EXTENSIONS:
        status = STATUS_NOT_SUPPORTED
        error_message = f"File type {extension or '(none)'} is not supported for vectorization."

    result = await db.execute(
        select(DocumentVectorizationJob).where(DocumentVectorizationJob.document_link_id == document_link.document_link_id)
    )
    job = result.scalars().first()
    if job is None:
        job = DocumentVectorizationJob(
            document_link_id=document_link.document_link_id,
            requested_at=now,
            status=STATUS_PENDING,
        )
        db.add(job)

    _reset_process_tracking(job)
    job.rag_document_id = str(document_link.document_link_id)
    job.status = status
    job.metadata_json = metadata
    job.error_message = error_message
    job.requested_at = now
    job.queued_at = now if status == STATUS_QUEUED else None
    job.queue_started_at = now if status == STATUS_QUEUED else None
    job.started_at = None
    job.completed_at = now if status in {STATUS_NOT_SUPPORTED, STATUS_FAILED} else None
    job.chunk_count = None
    job.weaviate_collection = settings.WEAVIATE_COLLECTION
    job.is_active = True
    job.current_stage = (
        STAGE_QUEUED
        if status == STATUS_QUEUED
        else STAGE_FAILED
        if status == STATUS_FAILED
        else STAGE_UNSUPPORTED
        if status == STATUS_NOT_SUPPORTED
        else STAGE_JOB_CREATED
    )
    job.modified_dt = now

    _append_process_log(
        job,
        stage=STAGE_FILE_UPLOADED,
        status_value="completed",
        message="Document link references an uploaded or external source file.",
        at=document_link.upload_dt or now,
        details={
            "access_url": document_link.access_url,
            "source_reference": document_link.source_reference,
        },
    )
    file_stored_status = "completed" if stored_file.local_path is not None else "failed" if status == STATUS_FAILED else "skipped"
    _append_process_log(
        job,
        stage=STAGE_FILE_STORED,
        status_value=file_stored_status,
        message=(
            "Document file stored in ValidateNow filestorage."
            if stored_file.local_path is not None
            else stored_file.reason
            or "Document file was not stored for vectorization."
        ),
        at=now,
        details={
            "stored_relative_path": stored_file.stored_relative_path,
            "stored_file_name": stored_file.stored_file_name,
            "file_size": stored_file.file_size,
            "extension": stored_file.extension,
        },
    )
    _append_process_log(
        job,
        stage=STAGE_DOCUMENT_LINK_CREATED,
        status_value="completed",
        message="Validated document link is available for this asset or release.",
        at=document_link.created_dt or now,
        details={
            "document_link_id": str(document_link.document_link_id),
            "target_type": metadata.get("target_type"),
            "target_id": metadata.get("target_id"),
        },
    )
    _append_process_log(
        job,
        stage=STAGE_JOB_CREATED,
        status_value="completed",
        message="Vectorization tracking job was created or refreshed.",
        at=now,
        details={"job_id": str(job.id) if job.id else None},
    )
    if status == STATUS_QUEUED:
        _append_process_log(
            job,
            stage=STAGE_QUEUED,
            status_value="completed",
            message="Document is queued for background chunking, embedding, and Weaviate storage.",
            at=now,
        )
    elif status == STATUS_NOT_SUPPORTED:
        _append_process_log(
            job,
            stage=STAGE_UNSUPPORTED,
            status_value="skipped",
            message=error_message or "Document is not supported for vectorization.",
            at=now,
        )
    elif status == STATUS_FAILED:
        _append_process_log(
            job,
            stage=STAGE_FAILED,
            status_value="failed",
            message=error_message or "Document vectorization preparation failed.",
            at=now,
        )
    return status == STATUS_QUEUED


async def deactivate_vectorization_for_document_link(db: AsyncSession, document_link_id: uuid.UUID) -> None:
    result = await db.execute(
        select(DocumentVectorizationJob).where(DocumentVectorizationJob.document_link_id == document_link_id)
    )
    job = result.scalars().first()
    if job is not None:
        now = _utc_now()
        job.is_active = False
        job.current_stage = "DEACTIVATED"
        _append_process_log(
            job,
            stage="DEACTIVATED",
            status_value="completed",
            message="Vectorization tracking was deactivated because the document link was deleted.",
            at=now,
        )
        job.modified_dt = now


async def requeue_vectorization_for_document_link(
    db: AsyncSession,
    document_link: ValidatedDocumentLink,
    *,
    base_url: str | None = None,
) -> bool:
    return await prepare_vectorization_job_for_document_link(db, document_link, base_url=base_url)


def _word_count(text: str) -> int:
    return len([part for part in re.split(r"\s+", text.strip()) if part])


def _split_into_sentences(text: str) -> list[str]:
    if not text:
        return []
    abbreviations = (
        r"\b(e\.g|i\.e|vs|dr|mr|mrs|ms|prof|st|no|fig|sec|approx|dept|govt|inc|ltd|etc)\."
    )
    protected = re.sub(
        abbreviations,
        lambda match: match.group().replace(".", "<DOT>"),
        text,
        flags=re.IGNORECASE,
    )
    raw = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"])', protected)
    sentences = [item.replace("<DOT>", ".").strip() for item in raw if item.strip()]
    return sentences or [text.strip()]


def _normalize_text_for_embedding(text: str) -> str:
    if not text:
        return ""
    normalized = re.sub(r"[\r\n]+", " ", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"\s+([.,;:])", r"\1", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _split_into_paragraphs(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|[\r\n]+", text) if part.strip()]
    return paragraphs or ([text.strip()] if text.strip() else [])


def _is_skip_heading(text: str) -> bool:
    value = _normalize_text_for_embedding(text).lower()
    if not value:
        return True
    skip_patterns = (
        r"^table\s+of\s+contents$",
        r"^contents$",
        r"^revision\s+history$",
        r"^document\s+history$",
        r"^approval\s+history$",
    )
    return any(re.match(pattern, value, flags=re.IGNORECASE) for pattern in skip_patterns)


def _is_body_line(text: str) -> bool:
    value = _normalize_text_for_embedding(text)
    if not value or _is_skip_heading(value):
        return False
    return not re.fullmatch(r"[\W_]+", value)


def _looks_like_heading(block: Block) -> bool:
    text = block.text.strip()
    if not text or _is_skip_heading(text):
        return False
    style = block.style.lower()
    if "heading" in style or "title" in style:
        return True
    if block.bold and _word_count(text) <= 12:
        return True
    if re.match(r"^\d+(?:\.\d+)*\.?\s+\S+", text):
        return True
    return text.isupper() and 2 <= _word_count(text) <= 12


def _auto_detect_sections(blocks: list[Block]) -> list[tuple[str, list[Block]]]:
    sections: list[tuple[str, list[Block]]] = []
    current_name = "Document"
    current_blocks: list[Block] = []

    def flush() -> None:
        nonlocal current_blocks
        if current_blocks:
            sections.append((current_name, current_blocks))
            current_blocks = []

    for block in blocks:
        if _looks_like_heading(block):
            flush()
            current_name = block.text.strip()
            continue
        current_blocks.append(block)

    flush()
    return sections or [("Document", blocks)]


def _chunk_section_text(
    text: str,
    *,
    chunk_size: int,
    min_words: int,
    overlap_sentences: int,
) -> list[str]:
    effective_min_words = max(MIN_CHUNK_WORD_FLOOR, min_words)
    effective_chunk_size = max(chunk_size, effective_min_words)
    sentences: list[str] = []
    for paragraph in _split_into_paragraphs(text):
        sentences.extend(_split_into_sentences(paragraph))

    chunks: list[str] = []
    start_index = 0
    while start_index < len(sentences):
        current: list[str] = []
        current_words = 0
        index = start_index

        while index < len(sentences):
            sentence = sentences[index]
            sentence_words = _word_count(sentence)
            if sentence_words == 0:
                index += 1
                continue
            if sentence_words > effective_chunk_size and not current:
                words = sentence.split()
                for word_index in range(0, len(words), effective_chunk_size):
                    chunks.append(" ".join(words[word_index : word_index + effective_chunk_size]))
                index += 1
                start_index = index
                break
            if current and current_words + sentence_words > effective_chunk_size:
                break
            current.append(sentence)
            current_words += sentence_words
            index += 1

        if current:
            chunks.append(" ".join(current).strip())
            if index >= len(sentences):
                break
            consumed = len(current)
            overlap = min(overlap_sentences, max(consumed - 1, 0))
            start_index += max(consumed - overlap, 1)
        else:
            start_index = max(start_index + 1, index)

    merged: list[str] = []
    carry = ""
    for chunk in chunks:
        candidate = " ".join(part for part in (carry, chunk) if part).strip()
        if _word_count(candidate) < effective_min_words:
            carry = candidate
            continue
        merged.append(candidate)
        carry = ""
    if carry:
        if merged:
            merged[-1] = f"{merged[-1]} {carry}".strip()
        else:
            merged.append(carry)
    return [chunk for chunk in merged if chunk.strip()]


def _load_txt_blocks(path: Path) -> list[Block]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    blocks: list[Block] = []
    for line in content.splitlines():
        text = line.strip()
        if text:
            blocks.append(Block(text=text, page=1))
    if not blocks and content.strip():
        blocks.append(Block(text=content.strip(), page=1))
    return blocks


def _load_docx_blocks(path: Path) -> list[Block]:
    try:
        from docx import Document as DocxDocument
        from docx.oxml.ns import qn
    except ImportError as exc:
        raise RuntimeError("python-docx is required for DOCX vectorization.") from exc

    document = DocxDocument(str(path))
    blocks: list[Block] = []
    page_number = 1
    for paragraph in document.paragraphs:
        if any(
            br.get(qn("w:type"), "") == "page"
            for run in paragraph.runs
            for br in run._r.findall(qn("w:br"))
        ):
            page_number += 1
        text = paragraph.text.strip()
        if not text:
            continue
        primary_run = next((run for run in paragraph.runs if run.font.size), None)
        if primary_run is None and paragraph.runs:
            primary_run = paragraph.runs[0]
        font_size = float(primary_run.font.size.pt) if primary_run is not None and primary_run.font.size else 0.0
        font_name = primary_run.font.name if primary_run is not None and primary_run.font.name else ""
        blocks.append(
            Block(
                text=text,
                page=page_number,
                style=paragraph.style.name if paragraph.style else "",
                font_name=font_name,
                font_size=font_size,
                bold=bool(primary_run.bold) if primary_run is not None else False,
                italic=bool(primary_run.italic) if primary_run is not None else False,
                is_toc_entry="toc" in (paragraph.style.name.lower() if paragraph.style else ""),
            )
        )
    return blocks


def _load_pdf_blocks(path: Path) -> list[Block]:
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required for PDF vectorization.") from exc

    blocks: list[Block] = []
    bold_hints = ("bold", "bd", "-b", "heavy", "black", "demi", "semibold")
    with pdfplumber.open(str(path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            chars = page.chars
            if not chars:
                continue
            chars_sorted = sorted(chars, key=lambda item: (round(item["top"], 1), item["x0"]))
            lines: list[list[dict[str, Any]]] = []
            current: list[dict[str, Any]] = []
            last_top: float | None = None
            for char in chars_sorted:
                top = round(char["top"], 1)
                if last_top is None or abs(top - last_top) <= 3:
                    current.append(char)
                    last_top = top
                else:
                    if current:
                        lines.append(current)
                    current = [char]
                    last_top = top
            if current:
                lines.append(current)
            for line_chars in lines:
                text = "".join(char["text"] for char in line_chars).strip()
                if not text:
                    continue
                representative = next((char for char in line_chars if char["text"].strip()), line_chars[0])
                font_name = str(representative.get("fontname", "") or "")
                blocks.append(
                    Block(
                        text=text,
                        page=page_number,
                        font_name=font_name,
                        font_size=float(representative.get("size", 0) or 0),
                        bold=any(hint in font_name.lower() for hint in bold_hints),
                    )
                )
    return blocks


def _load_document_blocks(path: Path) -> list[Block]:
    extension = path.suffix.lower()
    if extension == ".pdf":
        return _load_pdf_blocks(path)
    if extension == ".docx":
        return _load_docx_blocks(path)
    if extension == ".txt":
        return _load_txt_blocks(path)
    raise RuntimeError(f"Unsupported vectorization file type: {extension}")


def _chunk_document_file(path: Path, metadata: dict[str, Any]) -> list[DocumentChunk]:
    settings = get_settings()
    blocks = _load_document_blocks(path)
    chunks: list[DocumentChunk] = []
    for section_name, section_blocks in _auto_detect_sections(blocks):
        if _is_skip_heading(section_name):
            continue
        body_lines = [(block.text.strip(), block.page) for block in section_blocks if _is_body_line(block.text)]
        section_text = "\n".join(line for line, _ in body_lines).strip()
        if not section_text:
            continue
        for text in _chunk_section_text(
            section_text,
            chunk_size=settings.VECTOR_CHUNK_SIZE,
            min_words=settings.VECTOR_MIN_CONTENT_WORDS,
            overlap_sentences=settings.VECTOR_CHUNK_OVERLAP_SENTENCES,
        ):
            page = body_lines[0][1] if body_lines else 1
            chunks.append(
                DocumentChunk(
                    chunk_id="",
                    text=text,
                    page=page,
                    section_name=section_name,
                    section_path=section_name,
                    normalized_text=_normalize_text_for_embedding(text),
                )
            )

    document_link_id = str(metadata.get("document_link_id") or uuid.uuid4())
    for index, chunk in enumerate(chunks, start=1):
        chunk.chunk_id = f"{document_link_id}:{index:05d}"
    return chunks


@lru_cache(maxsize=2)
def _load_embedding_model(model_source: str):
    from sentence_transformers import SentenceTransformer

    logger.info("Loading vectorization embedding model: %s", model_source)
    return SentenceTransformer(model_source)


def _embedding_model_source() -> str:
    settings = get_settings()
    model_dir = settings.VECTOR_EMBEDDING_MODEL_DIR.strip()
    if model_dir:
        return model_dir
    return settings.VECTOR_EMBEDDING_MODEL


def _embed_chunks(chunks: list[DocumentChunk]) -> None:
    if not chunks:
        return
    model = _load_embedding_model(_embedding_model_source())
    texts = [chunk.normalized_text or _normalize_text_for_embedding(chunk.text) for chunk in chunks]
    valid = [(index, text) for index, text in enumerate(texts) if text.strip()]
    if not valid:
        return
    embeddings = model.encode(
        [text for _, text in valid],
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    for (index, _), embedding in zip(valid, embeddings):
        chunks[index].embedding = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)


def _connect_weaviate():
    from weaviate import connect_to_custom
    from weaviate.auth import Auth

    settings = get_settings()
    parsed = urlparse(settings.WEAVIATE_URL)
    secure = (parsed.scheme or "http").lower() == "https"
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if secure else 8080)
    kwargs: dict[str, Any] = {
        "http_host": host,
        "http_port": port,
        "http_secure": secure,
        "grpc_host": host,
        "grpc_port": settings.WEAVIATE_GRPC_PORT,
        "grpc_secure": secure,
    }
    api_key = settings.WEAVIATE_API_KEY.strip()
    if api_key:
        kwargs["auth_credentials"] = Auth.api_key(api_key)
    return connect_to_custom(**kwargs)


def _ensure_weaviate_collection(client: Any, collection_name: str) -> None:
    import weaviate.classes.config as wc

    if client.collections.exists(collection_name):
        return
    client.collections.create(
        name=collection_name,
        vector_config=wc.Configure.Vectors.self_provided(),
        inverted_index_config=wc.Configure.inverted_index(bm25_b=0.75, bm25_k1=1.2),
        properties=[
            wc.Property(name="chunk_id", data_type=wc.DataType.TEXT, index_filterable=True, tokenization=wc.Tokenization.FIELD),
            wc.Property(name="document_link_id", data_type=wc.DataType.TEXT, index_filterable=True, tokenization=wc.Tokenization.FIELD),
            wc.Property(name="asset_id", data_type=wc.DataType.TEXT, index_filterable=True, tokenization=wc.Tokenization.FIELD),
            wc.Property(name="release_id", data_type=wc.DataType.TEXT, index_filterable=True, tokenization=wc.Tokenization.FIELD),
            wc.Property(name="document_type", data_type=wc.DataType.TEXT, index_filterable=True, tokenization=wc.Tokenization.FIELD),
            wc.Property(name="source_system", data_type=wc.DataType.TEXT, index_filterable=True, tokenization=wc.Tokenization.FIELD),
            wc.Property(name="original_file_name", data_type=wc.DataType.TEXT, index_filterable=True),
            wc.Property(name="stored_file_name", data_type=wc.DataType.TEXT, index_filterable=True, tokenization=wc.Tokenization.FIELD),
            wc.Property(name="page", data_type=wc.DataType.INT, index_filterable=True),
            wc.Property(name="section_name", data_type=wc.DataType.TEXT, index_filterable=True, index_searchable=True),
            wc.Property(name="section_path", data_type=wc.DataType.TEXT, skip_vectorization=True),
            wc.Property(name="tenant_id", data_type=wc.DataType.TEXT, index_filterable=True, tokenization=wc.Tokenization.FIELD),
            wc.Property(name="text", data_type=wc.DataType.TEXT, index_searchable=True, skip_vectorization=True),
        ],
    )


def _delete_weaviate_chunks(document_link_id: str, collection_name: str | None = None) -> None:
    from weaviate.classes.query import Filter

    settings = get_settings()
    collection = collection_name or settings.WEAVIATE_COLLECTION
    client = _connect_weaviate()
    try:
        if not client.collections.exists(collection):
            return
        col = client.collections.get(collection)
        col.data.delete_many(where=Filter.by_property("document_link_id").equal(document_link_id))
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _store_chunks_in_weaviate(chunks: list[DocumentChunk], metadata: dict[str, Any]) -> int:
    from weaviate.util import generate_uuid5
    from weaviate.classes.query import Filter

    settings = get_settings()
    collection_name = str(metadata.get("collection_name") or settings.WEAVIATE_COLLECTION)
    document_link_id = str(metadata.get("document_link_id") or "")
    client = _connect_weaviate()
    try:
        _ensure_weaviate_collection(client, collection_name)
        col = client.collections.get(collection_name)
        col.data.delete_many(where=Filter.by_property("document_link_id").equal(document_link_id))
        stored_count = 0
        with col.batch.dynamic() as batch:
            for chunk in chunks:
                if chunk.embedding is None:
                    continue
                properties = {
                    "chunk_id": chunk.chunk_id,
                    "document_link_id": document_link_id,
                    "asset_id": metadata.get("asset_id"),
                    "release_id": metadata.get("release_id"),
                    "document_type": metadata.get("document_type"),
                    "source_system": metadata.get("source_system"),
                    "original_file_name": metadata.get("original_file_name"),
                    "stored_file_name": metadata.get("stored_file_name"),
                    "page": int(chunk.page or 1),
                    "section_name": chunk.section_name,
                    "section_path": chunk.section_path,
                    "tenant_id": metadata.get("tenant_id"),
                    "text": chunk.normalized_text or chunk.text,
                }
                batch.add_object(
                    properties=properties,
                    vector=chunk.embedding,
                    uuid=generate_uuid5(chunk.chunk_id),
                )
                stored_count += 1
        return stored_count
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _vectorization_document_query() -> Select[tuple[ValidatedDocumentLink]]:
    return select(ValidatedDocumentLink).options(
        selectinload(ValidatedDocumentLink.asset),
        selectinload(ValidatedDocumentLink.release).selectinload(AssetRelease.asset),
        selectinload(ValidatedDocumentLink.vectorization_job),
    )


async def _ensure_asset_exists(db: AsyncSession, asset_id: uuid.UUID) -> None:
    result = await db.execute(select(Asset.asset_uuid).where(Asset.asset_uuid == asset_id))
    if result.scalar_one_or_none() is None:
        raise VectorizationNotFoundError("Asset not found")


async def _get_document_link_with_vectorization(
    db: AsyncSession,
    document_link_id: uuid.UUID,
) -> ValidatedDocumentLink:
    result = await db.execute(
        _vectorization_document_query().where(ValidatedDocumentLink.document_link_id == document_link_id)
    )
    document_link = result.scalars().first()
    if document_link is None:
        raise VectorizationNotFoundError("Document link not found")
    return document_link


async def _get_asset_document_links(
    db: AsyncSession,
    asset_id: uuid.UUID,
) -> list[ValidatedDocumentLink]:
    await _ensure_asset_exists(db, asset_id)
    release_ids = select(AssetRelease.release_id).where(AssetRelease.asset_id == asset_id)
    stmt = (
        _vectorization_document_query()
        .where(
            or_(
                ValidatedDocumentLink.asset_id == asset_id,
                ValidatedDocumentLink.release_id.in_(release_ids),
            )
        )
        .order_by(ValidatedDocumentLink.upload_dt.desc(), ValidatedDocumentLink.document_name.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _build_asset_vectorization_document_response(
    document_link: ValidatedDocumentLink,
) -> AssetVectorizationDocumentResponse:
    release = document_link.release
    job = document_link.vectorization_job if document_link.vectorization_job and document_link.vectorization_job.is_active else None
    metadata = job.metadata_json if job is not None else {}
    source_context = "Asset document" if document_link.asset_id is not None else "Release document"
    if release is not None and release.version:
        source_context = f"Release {release.version}"

    return AssetVectorizationDocumentResponse(
        document_link_id=document_link.document_link_id,
        asset_id=document_link.asset_id or (release.asset_id if release is not None else None),
        release_id=document_link.release_id,
        release_version=release.version if release is not None else None,
        source_context=source_context,
        source_system=document_link.source_system,
        document_type=document_link.document_type,
        external_document_id=document_link.external_document_id,
        document_name=document_link.document_name,
        document_version=document_link.document_version,
        upload_dt=document_link.upload_dt,
        access_url=document_link.access_url,
        source_reference=document_link.source_reference,
        notes=document_link.notes,
        created_dt=document_link.created_dt,
        modified_dt=document_link.modified_dt,
        original_file_name=metadata.get("original_file_name"),
        stored_file_name=metadata.get("stored_file_name"),
        stored_relative_path=metadata.get("stored_relative_path"),
        mime_type=metadata.get("mime_type"),
        file_size=metadata.get("file_size"),
        extension=metadata.get("extension"),
        vectorization_status=job.status if job is not None else None,
        chunk_count=job.chunk_count if job is not None else None,
        requested_at=job.requested_at if job is not None else None,
        queued_at=job.queued_at if job is not None else None,
        started_at=job.started_at if job is not None else None,
        completed_at=job.completed_at if job is not None else None,
        current_stage=_current_stage_for_job(job),
        collection_name=(job.weaviate_collection or metadata.get("collection_name")) if job is not None else None,
        last_error=job.error_message if job is not None else None,
        can_reprocess=can_reprocess_vectorization_job(job),
        vectorization_job=_job_response(job),
    )


async def get_asset_vectorization_documents(
    db: AsyncSession,
    asset_id: uuid.UUID,
) -> list[AssetVectorizationDocumentResponse]:
    document_links = await _get_asset_document_links(db, asset_id)
    return [_build_asset_vectorization_document_response(document_link) for document_link in document_links]


async def get_asset_vectorization_summary(
    db: AsyncSession,
    asset_id: uuid.UUID,
) -> AssetVectorizationSummaryResponse:
    document_links = await _get_asset_document_links(db, asset_id)
    active_jobs = [
        document_link.vectorization_job
        for document_link in document_links
        if document_link.vectorization_job is not None and document_link.vectorization_job.is_active
    ]
    statuses = [(job.status or "").upper() for job in active_jobs]
    requested_values = [job.requested_at for job in active_jobs if job.requested_at is not None]
    completed_values = [job.completed_at for job in active_jobs if job.completed_at is not None]
    return AssetVectorizationSummaryResponse(
        asset_id=asset_id,
        total_linked_documents=len(document_links),
        tracked_document_count=len(active_jobs),
        total_vectorized_documents=sum(1 for status_value in statuses if status_value == STATUS_COMPLETED),
        pending_or_queued_count=sum(1 for status_value in statuses if status_value in {STATUS_PENDING, STATUS_QUEUED}),
        processing_count=sum(1 for status_value in statuses if status_value == STATUS_PROCESSING),
        completed_count=sum(1 for status_value in statuses if status_value == STATUS_COMPLETED),
        failed_count=sum(1 for status_value in statuses if status_value == STATUS_FAILED),
        unsupported_count=sum(1 for status_value in statuses if status_value == STATUS_NOT_SUPPORTED),
        total_chunk_count=sum(job.chunk_count or 0 for job in active_jobs if job.status == STATUS_COMPLETED),
        last_requested_at=max(requested_values) if requested_values else None,
        last_completed_at=max(completed_values) if completed_values else None,
    )


async def get_document_vectorization_detail(
    db: AsyncSession,
    document_link_id: uuid.UUID,
) -> AssetVectorizationDocumentResponse:
    document_link = await _get_document_link_with_vectorization(db, document_link_id)
    return _build_asset_vectorization_document_response(document_link)


def _fetch_weaviate_chunks(
    *,
    document_link_id: str,
    collection_name: str,
    limit: int,
    offset: int,
    search: str | None = None,
) -> tuple[list[dict[str, Any]], int, str | None]:
    from weaviate.classes.query import Filter

    client = None
    try:
        client = _connect_weaviate()
        if not client.collections.exists(collection_name):
            return [], 0, f"Weaviate collection {collection_name} does not exist."

        col = client.collections.get(collection_name)
        fetch_limit = MAX_CHUNK_SEARCH_FETCH
        response = col.query.fetch_objects(
            filters=Filter.by_property("document_link_id").equal(document_link_id),
            limit=fetch_limit,
            offset=0,
            return_properties=[
                "chunk_id",
                "page",
                "section_name",
                "section_path",
                "text",
            ],
        )
        objects = getattr(response, "objects", []) or []
        rows = [dict(getattr(item, "properties", {}) or {}) for item in objects]
        rows.sort(key=lambda item: str(item.get("chunk_id") or ""))

        query = (search or "").strip().lower()
        if query:
            rows = [
                item
                for item in rows
                if query
                in " ".join(
                    str(item.get(key) or "")
                    for key in ("chunk_id", "section_name", "section_path", "text", "category")
                ).lower()
            ]

        total = len(rows)
        return rows[offset : offset + limit], total, None
    except Exception as exc:  # noqa: BLE001 - API should show a friendly retrieval problem.
        logger.exception("Failed to retrieve Weaviate chunks for document_link_id=%s", document_link_id)
        return [], 0, str(exc)
    finally:
        close = getattr(client, "close", None) if client is not None else None
        if callable(close):
            close()


def _word_count_for_chunk(text: str) -> int:
    return len([part for part in re.split(r"\s+", text.strip()) if part])


def _chunk_response_from_properties(properties: dict[str, Any]) -> DocumentVectorizationChunkResponse:
    text = str(properties.get("text") or "")
    preview = text[:280].strip()
    if len(text) > 280:
        preview = f"{preview}..."
    return DocumentVectorizationChunkResponse(
        chunk_id=str(properties.get("chunk_id") or ""),
        page=properties.get("page"),
        section_name=properties.get("section_name"),
        section_path=properties.get("section_path"),
        chunk_length=len(text),
        word_count=_word_count_for_chunk(text),
        preview_text=preview,
        text=text,
        category=properties.get("category"),
        duplicate=properties.get("duplicate"),
        match_percentage=properties.get("match_percentage"),
    )


async def get_document_vectorization_chunks(
    db: AsyncSession,
    document_link_id: uuid.UUID,
    *,
    limit: int = DEFAULT_CHUNK_PAGE_SIZE,
    offset: int = 0,
    search: str | None = None,
) -> DocumentVectorizationChunkListResponse:
    document_link = await _get_document_link_with_vectorization(db, document_link_id)
    job = document_link.vectorization_job if document_link.vectorization_job and document_link.vectorization_job.is_active else None
    safe_limit = min(max(limit, 1), MAX_CHUNK_PAGE_SIZE)
    safe_offset = max(offset, 0)

    if job is None:
        return DocumentVectorizationChunkListResponse(
            document_link_id=document_link_id,
            status=None,
            chunks=[],
            total=0,
            limit=safe_limit,
            offset=safe_offset,
            search=search,
            retrieval_error="Vectorization has not been tracked for this document.",
        )

    collection_name = job.weaviate_collection or str((job.metadata_json or {}).get("collection_name") or get_settings().WEAVIATE_COLLECTION)
    if job.status != STATUS_COMPLETED:
        return DocumentVectorizationChunkListResponse(
            document_link_id=document_link_id,
            status=job.status,
            chunks=[],
            total=0,
            limit=safe_limit,
            offset=safe_offset,
            search=search,
            collection_name=collection_name,
            retrieval_error="Chunks are shown only for the latest completed vectorization job.",
        )

    rows, total, retrieval_error = await asyncio.to_thread(
        _fetch_weaviate_chunks,
        document_link_id=str(document_link_id),
        collection_name=collection_name,
        limit=safe_limit,
        offset=safe_offset,
        search=search,
    )
    return DocumentVectorizationChunkListResponse(
        document_link_id=document_link_id,
        status=job.status,
        chunks=[_chunk_response_from_properties(item) for item in rows],
        total=total if search else job.chunk_count or total,
        limit=safe_limit,
        offset=safe_offset,
        search=search,
        collection_name=collection_name,
        retrieval_error=retrieval_error,
    )


def _document_report(document_link: ValidatedDocumentLink) -> dict[str, Any]:
    release = document_link.release
    asset = document_link.asset or (release.asset if release is not None else None)
    job = document_link.vectorization_job if document_link.vectorization_job and document_link.vectorization_job.is_active else None
    metadata = dict(job.metadata_json or {}) if job is not None else {}
    return {
        "document_link_id": str(document_link.document_link_id),
        "asset_id": str(document_link.asset_id or (release.asset_id if release is not None else "")) or None,
        "release_id": str(document_link.release_id) if document_link.release_id else None,
        "release_version": release.version if release is not None else None,
        "asset_code": asset.asset_id if asset is not None else None,
        "asset_name": asset.asset_name if asset is not None else None,
        "document_type": document_link.document_type,
        "source_system": document_link.source_system,
        "external_document_id": document_link.external_document_id,
        "document_name": document_link.document_name,
        "document_version": document_link.document_version,
        "upload_dt": document_link.upload_dt.isoformat() if document_link.upload_dt else None,
        "access_url": document_link.access_url,
        "source_reference": document_link.source_reference,
        "notes": document_link.notes,
        "original_file_name": metadata.get("original_file_name"),
        "stored_file_name": metadata.get("stored_file_name"),
        "stored_relative_path": metadata.get("stored_relative_path"),
        "mime_type": metadata.get("mime_type"),
        "file_size": metadata.get("file_size"),
        "extension": metadata.get("extension"),
        "vectorization": {
            "job_id": str(job.id) if job is not None else None,
            "rag_document_id": job.rag_document_id if job is not None else None,
            "status": job.status if job is not None else None,
            "requested_at": job.requested_at.isoformat() if job is not None and job.requested_at else None,
            "queued_at": job.queued_at.isoformat() if job is not None and job.queued_at else None,
            "started_at": job.started_at.isoformat() if job is not None and job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job is not None and job.completed_at else None,
            "current_stage": _current_stage_for_job(job),
            "chunk_count": job.chunk_count if job is not None else None,
            "collection_name": (job.weaviate_collection or metadata.get("collection_name")) if job is not None else None,
            "error_message": job.error_message if job is not None else None,
            "is_active": job.is_active if job is not None else False,
        },
        "weaviate": {
            "collection_name": (job.weaviate_collection or metadata.get("collection_name")) if job is not None else None,
            "document_filter": {"document_link_id": str(document_link.document_link_id)},
            "stored_chunk_count": job.chunk_count if job is not None else None,
            "tenant_id": metadata.get("tenant_id"),
            "weaviate_url": metadata.get("weaviate_url"),
        },
        "metadata_json": metadata,
    }


async def get_document_vectorization_report(
    db: AsyncSession,
    document_link_id: uuid.UUID,
) -> DocumentVectorizationReportResponse:
    document_link = await _get_document_link_with_vectorization(db, document_link_id)
    return DocumentVectorizationReportResponse(
        document_link_id=document_link_id,
        report=_document_report(document_link),
    )


def _stage_status_for_pair(
    job: DocumentVectorizationJob | None,
    stage: str,
    *,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    requires_completed_job: bool = False,
) -> str:
    if completed_at is not None:
        return "completed"
    if job is None:
        return "pending"
    if job.status == STATUS_FAILED and started_at is not None:
        return "failed"
    if job.current_stage == stage and job.status in {STATUS_PROCESSING, STATUS_QUEUED}:
        return "in_progress"
    if started_at is not None:
        return "in_progress"
    if requires_completed_job and job.status in {STATUS_NOT_SUPPORTED, STATUS_FAILED}:
        return "skipped"
    return "pending"


def _build_process_stages(document_link: ValidatedDocumentLink) -> list[DocumentRagProcessStageResponse]:
    job = document_link.vectorization_job if document_link.vectorization_job and document_link.vectorization_job.is_active else None
    metadata = dict(job.metadata_json or {}) if job is not None else {}
    final_status = (job.status if job is not None else None) or "NOT_REQUESTED"
    final_stage_status = "completed" if final_status == STATUS_COMPLETED else "failed" if final_status == STATUS_FAILED else "skipped" if final_status == STATUS_NOT_SUPPORTED else "in_progress" if final_status in {STATUS_PENDING, STATUS_QUEUED, STATUS_PROCESSING} else "pending"
    legacy_completed_at = (
        job.completed_at
        if job is not None
        and job.status == STATUS_COMPLETED
        and job.completed_at is not None
        and job.chunk_count
        else None
    )
    chunking_completed_at = job.chunking_completed_at if job is not None else None
    embedding_completed_at = job.embedding_completed_at if job is not None else None
    weaviate_write_completed_at = job.weaviate_write_completed_at if job is not None else None
    if legacy_completed_at is not None:
        chunking_completed_at = chunking_completed_at or legacy_completed_at
        embedding_completed_at = embedding_completed_at or legacy_completed_at
        weaviate_write_completed_at = weaviate_write_completed_at or legacy_completed_at

    file_stored_status = "completed" if metadata.get("stored_relative_path") else "skipped"
    if job is not None and job.status == STATUS_FAILED and not metadata.get("stored_relative_path"):
        file_stored_status = "failed"

    return [
        DocumentRagProcessStageResponse(
            key="file_uploaded",
            label="File uploaded",
            status="completed",
            timestamp=document_link.upload_dt,
            message="Document source is registered on the document link.",
            details={"access_url": document_link.access_url, "source_reference": document_link.source_reference},
        ),
        DocumentRagProcessStageResponse(
            key="file_stored",
            label="File stored in filestorage",
            status=file_stored_status,
            timestamp=job.requested_at if job is not None else None,
            message=(
                "Local copy is available for vectorization."
                if metadata.get("stored_relative_path")
                else metadata.get("storage_reason")
                or "No local vectorization file is available."
            ),
            details={
                "stored_relative_path": metadata.get("stored_relative_path"),
                "stored_file_name": metadata.get("stored_file_name"),
                "extension": metadata.get("extension"),
                "file_size": metadata.get("file_size"),
            },
        ),
        DocumentRagProcessStageResponse(
            key="document_link_created",
            label="Document link created",
            status="completed",
            timestamp=document_link.created_dt,
            message="The document is linked to the asset or release context.",
            details={
                "document_link_id": str(document_link.document_link_id),
                "target_type": metadata.get("target_type") or ("asset" if document_link.asset_id else "release"),
            },
        ),
        DocumentRagProcessStageResponse(
            key="job_created",
            label="Vectorization job created",
            status="completed" if job is not None else "pending",
            timestamp=job.created_dt if job is not None else None,
            message="PostgreSQL vectorization tracking is available." if job is not None else "No vectorization job has been created yet.",
            details={"job_id": str(job.id) if job is not None else None},
        ),
        DocumentRagProcessStageResponse(
            key="queued",
            label="Queued for processing",
            status="completed" if job is not None and job.queued_at else "skipped" if final_status in {STATUS_NOT_SUPPORTED, STATUS_FAILED} else "pending",
            timestamp=job.queued_at if job is not None else None,
            message="Document was placed on the background vectorization queue." if job is not None and job.queued_at else "Document did not enter the processing queue.",
        ),
        DocumentRagProcessStageResponse(
            key="chunking",
            label="Chunking completed",
            status=_stage_status_for_pair(
                job,
                STAGE_CHUNKING,
                started_at=job.chunking_started_at if job is not None else None,
                completed_at=chunking_completed_at,
                requires_completed_job=True,
            ),
            started_at=job.chunking_started_at if job is not None else None,
            completed_at=chunking_completed_at,
            message="Document text was split into retrieval-sized chunks.",
            details={"chunk_count": job.chunk_count if job is not None and chunking_completed_at else None},
        ),
        DocumentRagProcessStageResponse(
            key="embedding",
            label="Embedding completed",
            status=_stage_status_for_pair(
                job,
                STAGE_EMBEDDING,
                started_at=job.embedding_started_at if job is not None else None,
                completed_at=embedding_completed_at,
                requires_completed_job=True,
            ),
            started_at=job.embedding_started_at if job is not None else None,
            completed_at=embedding_completed_at,
            message="Embeddings were generated for chunks that contained searchable text.",
            details={"embedding_model": metadata.get("embedding_model")},
        ),
        DocumentRagProcessStageResponse(
            key="weaviate_storage",
            label="Weaviate storage completed",
            status=_stage_status_for_pair(
                job,
                STAGE_WEAVIATE_STORAGE,
                started_at=job.weaviate_write_started_at if job is not None else None,
                completed_at=weaviate_write_completed_at,
                requires_completed_job=True,
            ),
            started_at=job.weaviate_write_started_at if job is not None else None,
            completed_at=weaviate_write_completed_at,
            message="Embedded chunks were written to the Compliance collection.",
            details={
                "collection_name": (job.weaviate_collection or metadata.get("collection_name")) if job is not None else None,
                "document_link_id": str(document_link.document_link_id),
            },
        ),
        DocumentRagProcessStageResponse(
            key="final_status",
            label=f"Final status: {final_status.replace('_', ' ').title()}",
            status=final_stage_status,
            timestamp=job.completed_at if job is not None else None,
            message=job.error_message if job is not None and job.error_message else "Latest active job status for this document.",
            details={"status": final_status, "chunk_count": job.chunk_count if job is not None else None},
        ),
    ]


async def get_document_vectorization_process(
    db: AsyncSession,
    document_link_id: uuid.UUID,
) -> DocumentRagProcessResponse:
    document_link = await _get_document_link_with_vectorization(db, document_link_id)
    job = document_link.vectorization_job if document_link.vectorization_job and document_link.vectorization_job.is_active else None
    return DocumentRagProcessResponse(
        document_link_id=document_link_id,
        status=job.status if job is not None else None,
        current_stage=_current_stage_for_job(job),
        stages=_build_process_stages(document_link),
        process_log=job.process_log_json if job is not None else [],
        error_message=job.error_message if job is not None else None,
    )


def _process_vectorization_sync(metadata: dict[str, Any]) -> int:
    relative_path = metadata.get("stored_relative_path")
    if not relative_path:
        raise RuntimeError("Vectorization metadata is missing stored_relative_path.")
    source_path = (_base_file_storage_dir() / str(relative_path)).resolve()
    if not source_path.is_file():
        raise RuntimeError(f"Stored document file is missing: {source_path}")
    chunks = _chunk_document_file(source_path, metadata)
    if not chunks:
        raise RuntimeError("No chunks were produced for the document.")
    _embed_chunks(chunks)
    embedded_count = len([chunk for chunk in chunks if chunk.embedding is not None])
    if embedded_count == 0:
        raise RuntimeError("No embeddings were produced for the document chunks.")
    return _store_chunks_in_weaviate(chunks, metadata)


async def process_document_vectorization_background(document_link_id: uuid.UUID | str) -> None:
    parsed_document_link_id = uuid.UUID(str(document_link_id))
    async with SessionLocal() as db:
        result = await db.execute(
            select(DocumentVectorizationJob).where(
                DocumentVectorizationJob.document_link_id == parsed_document_link_id,
                DocumentVectorizationJob.is_active.is_(True),
            )
        )
        job = result.scalars().first()
        if job is None or job.status != STATUS_QUEUED:
            return

        now = _utc_now()
        job.status = STATUS_PROCESSING
        job.started_at = now
        job.completed_at = None
        job.error_message = None
        job.current_stage = STAGE_PROCESSING
        _append_process_log(
            job,
            stage=STAGE_PROCESSING,
            status_value="in_progress",
            message="Background vectorization worker started processing this document.",
            at=now,
        )
        job.modified_dt = now
        await db.commit()

        try:
            metadata = dict(job.metadata_json or {})
            relative_path = metadata.get("stored_relative_path")
            if not relative_path:
                raise RuntimeError("Vectorization metadata is missing stored_relative_path.")
            source_path = (_base_file_storage_dir() / str(relative_path)).resolve()
            if not source_path.is_file():
                raise RuntimeError(f"Stored document file is missing: {source_path}")

            chunking_started_at = _mark_process_stage(
                job,
                stage=STAGE_CHUNKING,
                message="Reading the document and splitting it into searchable chunks.",
            )
            job.chunking_started_at = chunking_started_at
            job.modified_dt = chunking_started_at
            await db.commit()

            chunks = await asyncio.to_thread(_chunk_document_file, source_path, metadata)
            if not chunks:
                raise RuntimeError("No chunks were produced for the document.")

            chunking_completed_at = _utc_now()
            job.chunking_completed_at = chunking_completed_at
            _append_process_log(
                job,
                stage=STAGE_CHUNKING,
                status_value="completed",
                message=f"Chunking completed with {len(chunks)} chunk(s).",
                at=chunking_completed_at,
                details={"chunk_count": len(chunks)},
            )
            job.modified_dt = chunking_completed_at
            await db.commit()

            embedding_started_at = _mark_process_stage(
                job,
                stage=STAGE_EMBEDDING,
                message="Generating embeddings for each document chunk.",
            )
            job.embedding_started_at = embedding_started_at
            job.modified_dt = embedding_started_at
            await db.commit()

            await asyncio.to_thread(_embed_chunks, chunks)
            embedded_count = len([chunk for chunk in chunks if chunk.embedding is not None])
            if embedded_count == 0:
                raise RuntimeError("No embeddings were produced for the document chunks.")

            embedding_completed_at = _utc_now()
            job.embedding_completed_at = embedding_completed_at
            _append_process_log(
                job,
                stage=STAGE_EMBEDDING,
                status_value="completed",
                message=f"Embedding completed for {embedded_count} chunk(s).",
                at=embedding_completed_at,
                details={"embedded_chunk_count": embedded_count},
            )
            job.modified_dt = embedding_completed_at
            await db.commit()

            weaviate_write_started_at = _mark_process_stage(
                job,
                stage=STAGE_WEAVIATE_STORAGE,
                message="Writing embedded chunks to the Compliance Weaviate collection.",
            )
            job.weaviate_write_started_at = weaviate_write_started_at
            job.modified_dt = weaviate_write_started_at
            await db.commit()

            chunk_count = await asyncio.to_thread(_store_chunks_in_weaviate, chunks, metadata)
            if chunk_count == 0:
                raise RuntimeError("No embedded chunks were stored in Weaviate.")

            weaviate_write_completed_at = _utc_now()
            job.weaviate_write_completed_at = weaviate_write_completed_at
            _append_process_log(
                job,
                stage=STAGE_WEAVIATE_STORAGE,
                status_value="completed",
                message=f"Weaviate storage completed with {chunk_count} active chunk(s).",
                at=weaviate_write_completed_at,
                details={
                    "stored_chunk_count": chunk_count,
                    "collection_name": metadata.get("collection_name"),
                    "document_link_id": str(parsed_document_link_id),
                },
            )
        except Exception as exc:
            logger.exception("Document vectorization failed for document_link_id=%s", parsed_document_link_id)
            failed_at = _utc_now()
            job.status = STATUS_FAILED
            job.error_message = str(exc)
            job.completed_at = failed_at
            job.current_stage = STAGE_FAILED
            _append_process_log(
                job,
                stage=STAGE_FAILED,
                status_value="failed",
                message=str(exc),
                at=failed_at,
            )
            job.modified_dt = failed_at
            await db.commit()
            return

        completed_at = _utc_now()
        metadata = dict(job.metadata_json or {})
        metadata["chunk_count"] = chunk_count
        metadata["completed_at"] = completed_at.isoformat()
        job.status = STATUS_COMPLETED
        job.current_stage = STAGE_COMPLETED
        job.chunk_count = chunk_count
        job.metadata_json = metadata
        job.completed_at = completed_at
        job.error_message = None
        _append_process_log(
            job,
            stage=STAGE_COMPLETED,
            status_value="completed",
            message="Document is ready for RAG retrieval and inspection.",
            at=completed_at,
            details={"chunk_count": chunk_count},
        )
        job.modified_dt = completed_at
        await db.commit()


async def process_queued_document_vectorizations_background(limit: int | None = None) -> None:
    settings = get_settings()
    if not settings.DOCUMENT_VECTORIZATION_ENABLED:
        return

    batch_limit = limit if limit is not None else settings.DOCUMENT_VECTORIZATION_STARTUP_BATCH_SIZE
    async with SessionLocal() as db:
        stmt = (
            select(DocumentVectorizationJob.document_link_id)
            .where(
                DocumentVectorizationJob.status == STATUS_QUEUED,
                DocumentVectorizationJob.is_active.is_(True),
                DocumentVectorizationJob.document_link_id.is_not(None),
            )
            .order_by(DocumentVectorizationJob.queued_at.asc().nulls_last(), DocumentVectorizationJob.requested_at.asc())
            .limit(batch_limit)
        )
        result = await db.execute(stmt)
        document_link_ids = [document_link_id for document_link_id in result.scalars().all() if document_link_id]

    if not document_link_ids:
        return

    logger.info("Resuming %d queued document vectorization job(s).", len(document_link_ids))
    for document_link_id in document_link_ids:
        await process_document_vectorization_background(document_link_id)


async def delete_document_vectors_background(document_link_id: uuid.UUID | str) -> None:
    try:
        await asyncio.to_thread(_delete_weaviate_chunks, str(document_link_id))
    except Exception:
        logger.exception("Weaviate cleanup failed for document_link_id=%s", document_link_id)
