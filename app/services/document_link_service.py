import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.asset_release import AssetRelease
from app.models.lookup_master import LookupMaster
from app.models.lookup_value import LookupValue
from app.models.validated_document_link import ValidatedDocumentLink
from app.schemas.document_link_schema import (
    DocumentLinkCreate,
    DocumentLinkResponse,
    DocumentLinkUpdate,
    DocumentVectorizationJobResponse,
)
from app.services.document_vectorization_service import (
    can_reprocess_vectorization_job,
    deactivate_vectorization_for_document_link,
    prepare_vectorization_job_for_document_link,
    requeue_vectorization_for_document_link,
)

OMS_SOURCE_SYSTEM_LOOKUP_KEY = "OMS_SOURCE_SYSTEM"
DEFAULT_OMS_SOURCE_SYSTEM_CODES = {"MANUAL_URL", "OTHER", "SHAREPOINT", "VEEVA_VAULT"}
SOURCE_SYSTEM_VEEVA_VAULT = "VEEVA_VAULT"
DOCUMENT_TYPE_URS = "URS"
DOCUMENT_TYPE_FRS = "FRS"
DOCUMENT_TYPE_SOP = "SOP"
DOCUMENT_TYPE_OTHER = "OTHER"
DOCUMENT_TYPE_TRAINING_CONTENT = "TRAINING_CONTENT"
ALLOWED_DOCUMENT_TYPES = {
    DOCUMENT_TYPE_URS,
    DOCUMENT_TYPE_FRS,
    DOCUMENT_TYPE_SOP,
    DOCUMENT_TYPE_OTHER,
    DOCUMENT_TYPE_TRAINING_CONTENT,
}


class ServiceValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class ServiceNotFoundError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ServiceConflictError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_required(value: str, field_name: str, max_len: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ServiceValidationError(f"{field_name} is required")
    if len(normalized) > max_len:
        raise ServiceValidationError(f"{field_name} must not exceed {max_len} characters")
    return normalized


def _normalize_required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ServiceValidationError(f"{field_name} is required")
    return normalized


def _format_allowed_codes(codes: set[str]) -> str:
    return ", ".join(sorted(codes))


def _document_link_query() -> Select[tuple[ValidatedDocumentLink]]:
    return select(ValidatedDocumentLink).options(
        selectinload(ValidatedDocumentLink.asset),
        selectinload(ValidatedDocumentLink.release).selectinload(AssetRelease.asset),
        selectinload(ValidatedDocumentLink.vectorization_job),
    )


async def _get_asset_by_id(db: AsyncSession, asset_id: uuid.UUID) -> Asset | None:
    stmt = select(Asset).where(Asset.asset_uuid == asset_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_release_by_id(db: AsyncSession, release_id: uuid.UUID) -> AssetRelease | None:
    stmt = select(AssetRelease).where(AssetRelease.release_id == release_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_document_link_model_by_id(db: AsyncSession, document_link_id: uuid.UUID) -> ValidatedDocumentLink | None:
    stmt = _document_link_query().where(ValidatedDocumentLink.document_link_id == document_link_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_active_lookup_codes(db: AsyncSession, lookup_key: str) -> set[str]:
    stmt = (
        select(LookupValue.code)
        .join(LookupMaster, LookupValue.lookup_id == LookupMaster.id)
        .where(
            LookupMaster.lookup_key == lookup_key,
            LookupMaster.is_active.is_(True),
            LookupValue.is_active.is_(True),
        )
    )
    result = await db.execute(stmt)
    return set(result.scalars().all())


async def _normalize_source_system(db: AsyncSession, value: str) -> str:
    normalized = _normalize_required(value, "source_system", 50).upper()
    active_codes = await _get_active_lookup_codes(db, OMS_SOURCE_SYSTEM_LOOKUP_KEY)
    allowed_codes = active_codes or DEFAULT_OMS_SOURCE_SYSTEM_CODES
    if normalized not in allowed_codes:
        raise ServiceValidationError(f"source_system must be one of: {_format_allowed_codes(allowed_codes)}")
    return normalized


def _normalize_document_type(value: str | None) -> str:
    if value is None:
        raise ServiceValidationError("document_type is required")
    normalized = _normalize_required(value, "document_type", 50).upper().replace(" ", "_").replace("-", "_")
    if normalized not in ALLOWED_DOCUMENT_TYPES:
        raise ServiceValidationError(f"document_type must be one of: {_format_allowed_codes(ALLOWED_DOCUMENT_TYPES)}")
    return normalized


async def _get_duplicate_asset_document(
    db: AsyncSession,
    *,
    asset_id: uuid.UUID,
    source_system: str,
    external_document_id: str,
    exclude_id: uuid.UUID | None = None,
) -> ValidatedDocumentLink | None:
    stmt = select(ValidatedDocumentLink).where(
        ValidatedDocumentLink.asset_id == asset_id,
        ValidatedDocumentLink.source_system == source_system,
        ValidatedDocumentLink.external_document_id == external_document_id,
    )
    if exclude_id is not None:
        stmt = stmt.where(ValidatedDocumentLink.document_link_id != exclude_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_duplicate_release_document(
    db: AsyncSession,
    *,
    release_id: uuid.UUID,
    source_system: str,
    external_document_id: str,
    exclude_id: uuid.UUID | None = None,
) -> ValidatedDocumentLink | None:
    stmt = select(ValidatedDocumentLink).where(
        ValidatedDocumentLink.release_id == release_id,
        ValidatedDocumentLink.source_system == source_system,
        ValidatedDocumentLink.external_document_id == external_document_id,
    )
    if exclude_id is not None:
        stmt = stmt.where(ValidatedDocumentLink.document_link_id != exclude_id)
    result = await db.execute(stmt)
    return result.scalars().first()


def _build_document_link_response(document_link: ValidatedDocumentLink) -> DocumentLinkResponse:
    release = document_link.release
    asset = document_link.asset or (release.asset if release is not None else None)
    vectorization_job = document_link.vectorization_job
    vectorization_response = None
    if vectorization_job is not None and vectorization_job.is_active:
        vectorization_response = DocumentVectorizationJobResponse(
            id=vectorization_job.id,
            rag_document_id=vectorization_job.rag_document_id,
            status=vectorization_job.status,
            metadata_json=vectorization_job.metadata_json or {},
            error_message=vectorization_job.error_message,
            requested_at=vectorization_job.requested_at,
            queued_at=vectorization_job.queued_at,
            started_at=vectorization_job.started_at,
            completed_at=vectorization_job.completed_at,
            queue_started_at=vectorization_job.queue_started_at,
            chunking_started_at=vectorization_job.chunking_started_at,
            chunking_completed_at=vectorization_job.chunking_completed_at,
            embedding_started_at=vectorization_job.embedding_started_at,
            embedding_completed_at=vectorization_job.embedding_completed_at,
            weaviate_write_started_at=vectorization_job.weaviate_write_started_at,
            weaviate_write_completed_at=vectorization_job.weaviate_write_completed_at,
            current_stage=vectorization_job.current_stage,
            process_log_json=vectorization_job.process_log_json or [],
            chunk_count=vectorization_job.chunk_count,
            weaviate_collection=vectorization_job.weaviate_collection,
            is_active=vectorization_job.is_active,
            can_reprocess=can_reprocess_vectorization_job(vectorization_job),
        )
    return DocumentLinkResponse(
        document_link_id=document_link.document_link_id,
        asset_id=document_link.asset_id,
        release_id=document_link.release_id,
        source_system=document_link.source_system,
        document_type=document_link.document_type,
        external_document_id=document_link.external_document_id,
        document_name=document_link.document_name,
        document_version=document_link.document_version,
        upload_dt=document_link.upload_dt,
        access_url=document_link.access_url,
        source_reference=document_link.source_reference,
        notes=document_link.notes,
        created_by=document_link.created_by,
        created_dt=document_link.created_dt,
        modified_by=document_link.modified_by,
        modified_dt=document_link.modified_dt,
        asset_name=asset.asset_name if asset is not None else None,
        asset_code=asset.asset_code if asset is not None else None,
        release_version=release.version if release is not None else None,
        vectorization_status=vectorization_response.status if vectorization_response is not None else None,
        vectorization_job=vectorization_response,
    )


def _conflict_message_from_integrity_error(exc: IntegrityError) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    if "uq_vdl_asset_ext_doc" in message or "uq_vdl_release_ext_doc" in message:
        return "Document link already exists for this target"
    if "chk_validated_document_link_exactly_one_target" in message:
        return "Exactly one target must be set for a document link"
    return "Operation failed due to a data conflict"


async def get_documents_by_asset(db: AsyncSession, asset_id: uuid.UUID) -> list[DocumentLinkResponse]:
    asset = await _get_asset_by_id(db, asset_id)
    if asset is None:
        raise ServiceNotFoundError("Asset not found")

    stmt = (
        _document_link_query()
        .where(ValidatedDocumentLink.asset_id == asset_id)
        .order_by(ValidatedDocumentLink.upload_dt.desc(), ValidatedDocumentLink.document_name.asc())
    )
    result = await db.execute(stmt)
    document_links = result.scalars().all()
    return [_build_document_link_response(document_link) for document_link in document_links]


async def create_document_for_asset(
    db: AsyncSession,
    asset_id: uuid.UUID,
    payload: DocumentLinkCreate,
    *,
    base_url: str | None = None,
) -> DocumentLinkResponse:
    asset = await _get_asset_by_id(db, asset_id)
    if asset is None:
        raise ServiceNotFoundError("Asset not found")

    source_system = await _normalize_source_system(db, payload.source_system)
    document_type = _normalize_document_type(payload.document_type)
    external_document_id = _normalize_required(payload.external_document_id, "external_document_id", 150)
    document_name = _normalize_required(payload.document_name, "document_name", 250)
    document_version = _normalize_required(payload.document_version, "document_version", 50)
    access_url = _normalize_required_text(payload.access_url, "access_url")
    created_by = _strip_optional(payload.created_by)

    duplicate = await _get_duplicate_asset_document(
        db,
        asset_id=asset_id,
        source_system=source_system,
        external_document_id=external_document_id,
    )
    if duplicate is not None:
        raise ServiceConflictError("Document link already exists for this asset")

    now = datetime.now(UTC)
    document_link = ValidatedDocumentLink(
        asset_id=asset_id,
        asset=asset,
        source_system=source_system,
        document_type=document_type,
        external_document_id=external_document_id,
        document_name=document_name,
        document_version=document_version,
        upload_dt=payload.upload_dt,
        access_url=access_url,
        source_reference=_strip_optional(payload.source_reference),
        notes=_strip_optional(payload.notes),
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(document_link)

    try:
        await db.flush()
        await prepare_vectorization_job_for_document_link(db, document_link, base_url=base_url)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_document_link_by_id(db, document_link.document_link_id)


async def get_documents_by_release(db: AsyncSession, release_id: uuid.UUID) -> list[DocumentLinkResponse]:
    release = await _get_release_by_id(db, release_id)
    if release is None:
        raise ServiceNotFoundError("Release not found")

    stmt = (
        _document_link_query()
        .where(ValidatedDocumentLink.release_id == release_id)
        .order_by(ValidatedDocumentLink.upload_dt.desc(), ValidatedDocumentLink.document_name.asc())
    )
    result = await db.execute(stmt)
    document_links = result.scalars().all()
    return [_build_document_link_response(document_link) for document_link in document_links]


async def create_document_for_release(
    db: AsyncSession,
    release_id: uuid.UUID,
    payload: DocumentLinkCreate,
    *,
    base_url: str | None = None,
) -> DocumentLinkResponse:
    release = await _get_release_by_id(db, release_id)
    if release is None:
        raise ServiceNotFoundError("Release not found")

    source_system = await _normalize_source_system(db, payload.source_system)
    document_type = _normalize_document_type(payload.document_type)
    external_document_id = _normalize_required(payload.external_document_id, "external_document_id", 150)
    document_name = _normalize_required(payload.document_name, "document_name", 250)
    document_version = _normalize_required(payload.document_version, "document_version", 50)
    access_url = _normalize_required_text(payload.access_url, "access_url")
    created_by = _strip_optional(payload.created_by)

    duplicate = await _get_duplicate_release_document(
        db,
        release_id=release_id,
        source_system=source_system,
        external_document_id=external_document_id,
    )
    if duplicate is not None:
        raise ServiceConflictError("Document link already exists for this release")

    now = datetime.now(UTC)
    document_link = ValidatedDocumentLink(
        release_id=release_id,
        release=release,
        source_system=source_system,
        document_type=document_type,
        external_document_id=external_document_id,
        document_name=document_name,
        document_version=document_version,
        upload_dt=payload.upload_dt,
        access_url=access_url,
        source_reference=_strip_optional(payload.source_reference),
        notes=_strip_optional(payload.notes),
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(document_link)

    try:
        await db.flush()
        await prepare_vectorization_job_for_document_link(db, document_link, base_url=base_url)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_document_link_by_id(db, document_link.document_link_id)


async def get_document_link_by_id(db: AsyncSession, document_link_id: uuid.UUID) -> DocumentLinkResponse:
    document_link = await _get_document_link_model_by_id(db, document_link_id)
    if document_link is None:
        raise ServiceNotFoundError("Document link not found")
    return _build_document_link_response(document_link)


async def update_document_link(
    db: AsyncSession,
    document_link_id: uuid.UUID,
    payload: DocumentLinkUpdate,
    *,
    base_url: str | None = None,
) -> DocumentLinkResponse:
    document_link = await _get_document_link_model_by_id(db, document_link_id)
    if document_link is None:
        raise ServiceNotFoundError("Document link not found")

    updates = payload.model_dump(exclude_unset=True)
    should_refresh_vectorization = bool(
        {
            "source_system",
            "document_type",
            "external_document_id",
            "document_name",
            "document_version",
            "upload_dt",
            "access_url",
            "source_reference",
        }.intersection(updates)
    )

    if "source_system" in updates and updates["source_system"] is not None:
        document_link.source_system = await _normalize_source_system(db, updates["source_system"])

    if "document_type" in updates:
        document_link.document_type = _normalize_document_type(updates["document_type"])

    if "external_document_id" in updates:
        if updates["external_document_id"] is None:
            raise ServiceValidationError("external_document_id cannot be null")
        document_link.external_document_id = _normalize_required(
            updates["external_document_id"],
            "external_document_id",
            150,
        )

    if "document_name" in updates:
        if updates["document_name"] is None:
            raise ServiceValidationError("document_name cannot be null")
        document_link.document_name = _normalize_required(updates["document_name"], "document_name", 250)

    if "document_version" in updates:
        if updates["document_version"] is None:
            raise ServiceValidationError("document_version cannot be null")
        document_link.document_version = _normalize_required(updates["document_version"], "document_version", 50)

    if "upload_dt" in updates:
        if updates["upload_dt"] is None:
            raise ServiceValidationError("upload_dt cannot be null")
        document_link.upload_dt = updates["upload_dt"]

    if "access_url" in updates:
        if updates["access_url"] is None:
            raise ServiceValidationError("access_url cannot be null")
        document_link.access_url = _normalize_required_text(updates["access_url"], "access_url")

    if "source_reference" in updates:
        document_link.source_reference = _strip_optional(updates["source_reference"])

    if "notes" in updates:
        document_link.notes = _strip_optional(updates["notes"])

    if "modified_by" in updates:
        document_link.modified_by = _strip_optional(updates["modified_by"])

    if document_link.asset_id is not None:
        duplicate = await _get_duplicate_asset_document(
            db,
            asset_id=document_link.asset_id,
            source_system=document_link.source_system,
            external_document_id=document_link.external_document_id,
            exclude_id=document_link.document_link_id,
        )
        if duplicate is not None:
            raise ServiceConflictError("Document link already exists for this asset")
    elif document_link.release_id is not None:
        duplicate = await _get_duplicate_release_document(
            db,
            release_id=document_link.release_id,
            source_system=document_link.source_system,
            external_document_id=document_link.external_document_id,
            exclude_id=document_link.document_link_id,
        )
        if duplicate is not None:
            raise ServiceConflictError("Document link already exists for this release")
    else:
        raise ServiceConflictError("Document link target is invalid")

    document_link.modified_dt = datetime.now(UTC)

    try:
        if should_refresh_vectorization:
            await db.flush()
            await prepare_vectorization_job_for_document_link(db, document_link, base_url=base_url)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_document_link_by_id(db, document_link.document_link_id)


async def upsert_document_link_reference(
    db: AsyncSession,
    *,
    asset_id: uuid.UUID | None,
    release_id: uuid.UUID | None,
    source_system: str,
    external_document_id: str,
    document_name: str,
    document_version: str,
    upload_dt: datetime,
    access_url: str,
    document_type: str = DOCUMENT_TYPE_URS,
    actor: str | None = None,
    source_reference: str | None = None,
    notes: str | None = None,
) -> ValidatedDocumentLink:
    if (asset_id is None and release_id is None) or (asset_id is not None and release_id is not None):
        raise ServiceValidationError("Exactly one target must be set for a document link")

    normalized_source_system = await _normalize_source_system(db, source_system)
    normalized_document_type = _normalize_document_type(document_type)
    normalized_external_document_id = _normalize_required(external_document_id, "external_document_id", 150)
    normalized_document_name = _normalize_required(document_name, "document_name", 250)
    normalized_document_version = _normalize_required(document_version, "document_version", 50)
    normalized_access_url = _normalize_required_text(access_url, "access_url")
    normalized_actor = _strip_optional(actor)
    normalized_source_reference = _strip_optional(source_reference)
    normalized_notes = _strip_optional(notes)
    now = datetime.now(UTC)

    if asset_id is not None:
        existing = await _get_duplicate_asset_document(
            db,
            asset_id=asset_id,
            source_system=normalized_source_system,
            external_document_id=normalized_external_document_id,
        )
        if existing is None:
            existing = ValidatedDocumentLink(
                asset_id=asset_id,
                source_system=normalized_source_system,
                document_type=normalized_document_type,
                external_document_id=normalized_external_document_id,
                document_name=normalized_document_name,
                document_version=normalized_document_version,
                upload_dt=upload_dt,
                access_url=normalized_access_url,
                source_reference=normalized_source_reference,
                notes=normalized_notes,
                created_by=normalized_actor,
                created_dt=now,
                modified_by=normalized_actor,
                modified_dt=now,
            )
            db.add(existing)
            return existing
    else:
        existing = await _get_duplicate_release_document(
            db,
            release_id=release_id,
            source_system=normalized_source_system,
            external_document_id=normalized_external_document_id,
        )
        if existing is None:
            existing = ValidatedDocumentLink(
                release_id=release_id,
                source_system=normalized_source_system,
                document_type=normalized_document_type,
                external_document_id=normalized_external_document_id,
                document_name=normalized_document_name,
                document_version=normalized_document_version,
                upload_dt=upload_dt,
                access_url=normalized_access_url,
                source_reference=normalized_source_reference,
                notes=normalized_notes,
                created_by=normalized_actor,
                created_dt=now,
                modified_by=normalized_actor,
                modified_dt=now,
            )
            db.add(existing)
            return existing

    existing.document_name = normalized_document_name
    existing.document_type = normalized_document_type
    existing.document_version = normalized_document_version
    existing.upload_dt = upload_dt
    existing.access_url = normalized_access_url
    existing.source_reference = normalized_source_reference
    existing.notes = normalized_notes
    existing.modified_by = normalized_actor
    existing.modified_dt = now
    return existing


async def delete_document_link(db: AsyncSession, document_link_id: uuid.UUID) -> None:
    document_link = await _get_document_link_model_by_id(db, document_link_id)
    if document_link is None:
        raise ServiceNotFoundError("Document link not found")

    try:
        await deactivate_vectorization_for_document_link(db, document_link_id)
        await db.delete(document_link)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete document link") from exc


async def reprocess_document_link_vectorization(
    db: AsyncSession,
    document_link_id: uuid.UUID,
    *,
    base_url: str | None = None,
) -> DocumentLinkResponse:
    document_link = await _get_document_link_model_by_id(db, document_link_id)
    if document_link is None:
        raise ServiceNotFoundError("Document link not found")

    try:
        await requeue_vectorization_for_document_link(db, document_link, base_url=base_url)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to reprocess document vectorization") from exc

    return await get_document_link_by_id(db, document_link.document_link_id)
