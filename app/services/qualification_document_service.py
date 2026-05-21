import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.asset_release import AssetRelease
from app.models.lookup_master import LookupMaster
from app.models.lookup_value import LookupValue
from app.models.supplier import Supplier
from app.models.supplier_qualification_document import SupplierQualificationDocument
from app.models.supplier_qualification_document_action import SupplierQualificationDocumentAction
from app.schemas.qualification_document_schema import (
    QualificationDocumentActionResponse,
    QualificationDocumentCreate,
    QualificationDocumentResponse,
    QualificationDocumentUpdate,
    QualificationDocumentWorkflowActionRequest,
)

OMS_SOURCE_SYSTEM_LOOKUP_KEY = "OMS_SOURCE_SYSTEM"
DEFAULT_OMS_SOURCE_SYSTEM_CODES = {"MANUAL_URL", "OTHER", "SHAREPOINT", "VEEVA_VAULT"}
QUALIFICATION_TYPE_IQ = "IQ"
QUALIFICATION_TYPE_OQ = "OQ"
QUALIFICATION_TYPE_PQ = "PQ"
QUALIFICATION_STATUS_SUBMITTED = "SUBMITTED"
QUALIFICATION_STATUS_IN_REVIEW = "IN_REVIEW"
QUALIFICATION_STATUS_ACCEPTED = "ACCEPTED"
QUALIFICATION_STATUS_REJECTED = "REJECTED"
QUALIFICATION_STATUS_NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
QUALIFICATION_ACTION_REGISTER = "REGISTER"
QUALIFICATION_ACTION_SUBMIT_FOR_REVIEW = "SUBMIT_FOR_REVIEW"
QUALIFICATION_ACTION_ACCEPT = "ACCEPT"
QUALIFICATION_ACTION_REJECT = "REJECT"
QUALIFICATION_ACTION_REQUEST_CLARIFICATION = "REQUEST_CLARIFICATION"
ALLOWED_QUALIFICATION_TYPES = {QUALIFICATION_TYPE_IQ, QUALIFICATION_TYPE_OQ, QUALIFICATION_TYPE_PQ}
ALLOWED_QUALIFICATION_STATUSES = {
    QUALIFICATION_STATUS_SUBMITTED,
    QUALIFICATION_STATUS_IN_REVIEW,
    QUALIFICATION_STATUS_ACCEPTED,
    QUALIFICATION_STATUS_REJECTED,
    QUALIFICATION_STATUS_NEEDS_CLARIFICATION,
}
EDITABLE_QUALIFICATION_STATUSES = {
    QUALIFICATION_STATUS_SUBMITTED,
    QUALIFICATION_STATUS_NEEDS_CLARIFICATION,
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


def _normalize_required(value: str | None, field_name: str, max_len: int) -> str:
    if value is None:
        raise ServiceValidationError(f"{field_name} is required")
    normalized = value.strip()
    if not normalized:
        raise ServiceValidationError(f"{field_name} is required")
    if len(normalized) > max_len:
        raise ServiceValidationError(f"{field_name} must not exceed {max_len} characters")
    return normalized


def _normalize_required_text(value: str | None, field_name: str) -> str:
    if value is None:
        raise ServiceValidationError(f"{field_name} is required")
    normalized = value.strip()
    if not normalized:
        raise ServiceValidationError(f"{field_name} is required")
    return normalized


def _normalize_optional_string(value: str | None, field_name: str, max_len: int) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    if len(normalized) > max_len:
        raise ServiceValidationError(f"{field_name} must not exceed {max_len} characters")
    return normalized


def _normalize_qualification_type(value: str | None) -> str:
    normalized = _normalize_required(value, "qualification_type", 10).upper()
    if normalized not in ALLOWED_QUALIFICATION_TYPES:
        allowed = ", ".join(sorted(ALLOWED_QUALIFICATION_TYPES))
        raise ServiceValidationError(f"qualification_type must be one of: {allowed}")
    return normalized


def _normalize_comment_text(value: str | None, *, required: bool = False) -> str | None:
    normalized = _normalize_optional_string(value, "comment_text", 5000)
    if required and normalized is None:
        raise ServiceValidationError("comment_text is required")
    return normalized


def _format_allowed_codes(codes: set[str]) -> str:
    return ", ".join(sorted(codes))


def _qualification_document_query() -> Select[tuple[SupplierQualificationDocument]]:
    return select(SupplierQualificationDocument).options(
        selectinload(SupplierQualificationDocument.asset),
        selectinload(SupplierQualificationDocument.release).selectinload(AssetRelease.asset),
        selectinload(SupplierQualificationDocument.supplier),
    )


def _qualification_document_action_query() -> Select[tuple[SupplierQualificationDocumentAction]]:
    return select(SupplierQualificationDocumentAction)


async def _get_asset_by_id(db: AsyncSession, asset_id: uuid.UUID) -> Asset | None:
    result = await db.execute(select(Asset).where(Asset.asset_uuid == asset_id))
    return result.scalars().first()


async def _get_release_by_id(db: AsyncSession, release_id: uuid.UUID) -> AssetRelease | None:
    stmt = (
        select(AssetRelease)
        .options(selectinload(AssetRelease.asset))
        .where(AssetRelease.release_id == release_id)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_supplier_by_id(db: AsyncSession, supplier_id: uuid.UUID) -> Supplier | None:
    result = await db.execute(select(Supplier).where(Supplier.supplier_id == supplier_id))
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


async def _normalize_source_system(db: AsyncSession, value: str | None) -> str | None:
    normalized = _normalize_optional_string(value, "source_system", 50)
    if normalized is None:
        return None
    upper_value = normalized.upper()
    active_codes = await _get_active_lookup_codes(db, OMS_SOURCE_SYSTEM_LOOKUP_KEY)
    allowed_codes = active_codes or DEFAULT_OMS_SOURCE_SYSTEM_CODES
    if upper_value not in allowed_codes:
        raise ServiceValidationError(f"source_system must be one of: {_format_allowed_codes(allowed_codes)}")
    return upper_value


async def _resolve_target_context(
    db: AsyncSession,
    *,
    asset_id: uuid.UUID | None,
    release_id: uuid.UUID | None,
) -> tuple[Asset | None, AssetRelease | None]:
    if asset_id is None and release_id is None:
        raise ServiceValidationError("At least one of asset_id or release_id must be provided")

    asset = await _get_asset_by_id(db, asset_id) if asset_id is not None else None
    if asset_id is not None and asset is None:
        raise ServiceNotFoundError("Asset not found")

    release = await _get_release_by_id(db, release_id) if release_id is not None else None
    if release_id is not None and release is None:
        raise ServiceNotFoundError("Release not found")

    if asset is not None and release is not None and release.asset_id != asset.asset_uuid:
        raise ServiceValidationError("release_id does not belong to the provided asset_id")

    return asset, release


async def _get_document_model_by_id(
    db: AsyncSession,
    qualification_document_id: uuid.UUID,
) -> SupplierQualificationDocument | None:
    result = await db.execute(
        _qualification_document_query().where(
            SupplierQualificationDocument.qualification_document_id == qualification_document_id
        )
    )
    return result.scalars().first()


def _build_response(document: SupplierQualificationDocument) -> QualificationDocumentResponse:
    release = document.release
    asset = document.asset or (release.asset if release is not None else None)
    context_scope = "RELEASE" if document.release_id is not None else "ASSET"
    return QualificationDocumentResponse(
        qualification_document_id=document.qualification_document_id,
        qualification_type=document.qualification_type,
        status=document.status,
        context_scope=context_scope,
        asset_id=document.asset_id,
        release_id=document.release_id,
        supplier_id=document.supplier_id,
        document_name=document.document_name,
        document_version=document.document_version,
        source_system=document.source_system,
        external_document_id=document.external_document_id,
        document_url=document.document_url,
        source_reference=document.source_reference,
        submission_date=document.submission_date,
        notes=document.notes,
        created_by=document.created_by,
        created_dt=document.created_dt,
        modified_by=document.modified_by,
        modified_dt=document.modified_dt,
        asset_name=asset.asset_name if asset is not None else None,
        asset_code=asset.asset_code if asset is not None else None,
        release_version=release.version if release is not None else None,
        supplier_name=document.supplier.supplier_name if document.supplier is not None else None,
    )


def _build_action_response(action: SupplierQualificationDocumentAction) -> QualificationDocumentActionResponse:
    return QualificationDocumentActionResponse(
        id=action.id,
        qualification_document_id=action.qualification_document_id,
        action_type=action.action_type,
        action_by=action.action_by,
        action_dt=action.action_dt,
        comment_text=action.comment_text,
        from_status=action.from_status,
        to_status=action.to_status,
    )


def _ensure_editable(status: str) -> None:
    if status not in EDITABLE_QUALIFICATION_STATUSES:
        raise ServiceConflictError("Only qualification documents in SUBMITTED or NEEDS_CLARIFICATION can be edited")


def _ensure_deletable(status: str) -> None:
    if status not in EDITABLE_QUALIFICATION_STATUSES:
        raise ServiceConflictError("Only qualification documents in SUBMITTED or NEEDS_CLARIFICATION can be deleted")


def _ensure_can_submit_for_review(status: str) -> None:
    if status not in EDITABLE_QUALIFICATION_STATUSES:
        raise ServiceConflictError(
            "Only qualification documents in SUBMITTED or NEEDS_CLARIFICATION can be submitted for review"
        )


def _ensure_in_review(status: str, *, action_label: str) -> None:
    if status != QUALIFICATION_STATUS_IN_REVIEW:
        raise ServiceConflictError(f"Only qualification documents in IN_REVIEW can be {action_label}")


async def _find_duplicate_document(
    db: AsyncSession,
    *,
    supplier_id: uuid.UUID,
    qualification_type: str,
    asset_id: uuid.UUID | None,
    release_id: uuid.UUID | None,
    document_name: str,
    document_version: str | None,
    exclude_id: uuid.UUID | None = None,
) -> SupplierQualificationDocument | None:
    stmt = select(SupplierQualificationDocument).where(
        SupplierQualificationDocument.supplier_id == supplier_id,
        SupplierQualificationDocument.qualification_type == qualification_type,
        func.lower(SupplierQualificationDocument.document_name) == document_name.lower(),
    )
    if asset_id is None:
        stmt = stmt.where(SupplierQualificationDocument.asset_id.is_(None))
    else:
        stmt = stmt.where(SupplierQualificationDocument.asset_id == asset_id)
    if release_id is None:
        stmt = stmt.where(SupplierQualificationDocument.release_id.is_(None))
    else:
        stmt = stmt.where(SupplierQualificationDocument.release_id == release_id)
    if document_version is None:
        stmt = stmt.where(SupplierQualificationDocument.document_version.is_(None))
    else:
        stmt = stmt.where(SupplierQualificationDocument.document_version == document_version)
    if exclude_id is not None:
        stmt = stmt.where(SupplierQualificationDocument.qualification_document_id != exclude_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _create_workflow_action(
    db: AsyncSession,
    *,
    document: SupplierQualificationDocument,
    action_type: str,
    action_by: str | None,
    comment_text: str | None,
    to_status: str,
) -> SupplierQualificationDocumentAction:
    action_dt = datetime.now(UTC)
    from_status = document.status

    if to_status != document.status:
        document.status = to_status
    if action_by is not None:
        document.modified_by = action_by
    document.modified_dt = action_dt

    action = SupplierQualificationDocumentAction(
        qualification_document_id=document.qualification_document_id,
        action_type=action_type,
        action_by=action_by,
        action_dt=action_dt,
        comment_text=comment_text,
        from_status=from_status,
        to_status=to_status,
    )
    db.add(action)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Operation failed due to a data conflict") from exc

    return action


async def get_qualification_documents(
    db: AsyncSession,
    *,
    asset_id: uuid.UUID | None = None,
    release_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    qualification_type: str | None = None,
    status_value: str | None = None,
) -> list[QualificationDocumentResponse]:
    stmt = _qualification_document_query().outerjoin(
        AssetRelease,
        SupplierQualificationDocument.release_id == AssetRelease.release_id,
    )

    if asset_id is not None:
        asset = await _get_asset_by_id(db, asset_id)
        if asset is None:
            raise ServiceNotFoundError("Asset not found")
        stmt = stmt.where(
            or_(
                SupplierQualificationDocument.asset_id == asset_id,
                AssetRelease.asset_id == asset_id,
            )
        )
    if release_id is not None:
        release = await _get_release_by_id(db, release_id)
        if release is None:
            raise ServiceNotFoundError("Release not found")
        stmt = stmt.where(SupplierQualificationDocument.release_id == release_id)
    if supplier_id is not None:
        supplier = await _get_supplier_by_id(db, supplier_id)
        if supplier is None:
            raise ServiceNotFoundError("Supplier not found")
        stmt = stmt.where(SupplierQualificationDocument.supplier_id == supplier_id)
    if qualification_type is not None:
        stmt = stmt.where(
            SupplierQualificationDocument.qualification_type == _normalize_qualification_type(qualification_type)
        )
    if status_value is not None:
        normalized_status = _normalize_required(status_value, "status", 30).upper()
        if normalized_status not in ALLOWED_QUALIFICATION_STATUSES:
            allowed = ", ".join(sorted(ALLOWED_QUALIFICATION_STATUSES))
            raise ServiceValidationError(f"status must be one of: {allowed}")
        stmt = stmt.where(SupplierQualificationDocument.status == normalized_status)

    stmt = stmt.order_by(
        SupplierQualificationDocument.modified_dt.desc(),
        SupplierQualificationDocument.submission_date.desc(),
        SupplierQualificationDocument.document_name.asc(),
    )
    result = await db.execute(stmt)
    return [_build_response(document) for document in result.scalars().unique().all()]


async def get_qualification_document_by_id(
    db: AsyncSession,
    qualification_document_id: uuid.UUID,
) -> QualificationDocumentResponse:
    document = await _get_document_model_by_id(db, qualification_document_id)
    if document is None:
        raise ServiceNotFoundError("Qualification document not found")
    return _build_response(document)


async def create_qualification_document(
    db: AsyncSession,
    payload: QualificationDocumentCreate,
) -> QualificationDocumentResponse:
    qualification_type = _normalize_qualification_type(payload.qualification_type)
    supplier = await _get_supplier_by_id(db, payload.supplier_id)
    if supplier is None:
        raise ServiceNotFoundError("Supplier not found")

    asset, release = await _resolve_target_context(db, asset_id=payload.asset_id, release_id=payload.release_id)
    document_name = _normalize_required(payload.document_name, "document_name", 250)
    document_version = _normalize_optional_string(payload.document_version, "document_version", 50)
    source_system = await _normalize_source_system(db, payload.source_system)
    external_document_id = _normalize_optional_string(payload.external_document_id, "external_document_id", 150)
    document_url = _normalize_required_text(payload.document_url, "document_url")
    source_reference = _normalize_optional_string(payload.source_reference, "source_reference", 500)
    notes = _strip_optional(payload.notes)
    created_by = _normalize_optional_string(payload.created_by, "created_by", 150)

    duplicate = await _find_duplicate_document(
        db,
        supplier_id=supplier.supplier_id,
        qualification_type=qualification_type,
        asset_id=asset.asset_uuid if asset is not None else None,
        release_id=release.release_id if release is not None else None,
        document_name=document_name,
        document_version=document_version,
    )
    if duplicate is not None:
        raise ServiceConflictError(
            "A qualification document with the same supplier, context, type, name, and version already exists"
        )

    now = datetime.now(UTC)
    document = SupplierQualificationDocument(
        qualification_type=qualification_type,
        asset_id=asset.asset_uuid if asset is not None else None,
        release_id=release.release_id if release is not None else None,
        supplier_id=supplier.supplier_id,
        document_name=document_name,
        document_version=document_version,
        source_system=source_system,
        external_document_id=external_document_id,
        document_url=document_url,
        source_reference=source_reference,
        submission_date=payload.submission_date or now,
        status=QUALIFICATION_STATUS_SUBMITTED,
        notes=notes,
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(document)

    action = SupplierQualificationDocumentAction(
        qualification_document=document,
        action_type=QUALIFICATION_ACTION_REGISTER,
        action_by=created_by,
        action_dt=now,
        comment_text=None,
        from_status=QUALIFICATION_STATUS_SUBMITTED,
        to_status=QUALIFICATION_STATUS_SUBMITTED,
    )
    db.add(action)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to create qualification document due to a data conflict") from exc

    return await get_qualification_document_by_id(db, document.qualification_document_id)


async def update_qualification_document(
    db: AsyncSession,
    qualification_document_id: uuid.UUID,
    payload: QualificationDocumentUpdate,
) -> QualificationDocumentResponse:
    document = await _get_document_model_by_id(db, qualification_document_id)
    if document is None:
        raise ServiceNotFoundError("Qualification document not found")

    _ensure_editable(document.status)
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates:
        raise ServiceValidationError("Status changes must use workflow action endpoints")

    current_asset_id = document.asset_id
    current_release_id = document.release_id
    next_asset_id = updates["asset_id"] if "asset_id" in updates else current_asset_id
    next_release_id = updates["release_id"] if "release_id" in updates else current_release_id

    asset, release = await _resolve_target_context(db, asset_id=next_asset_id, release_id=next_release_id)
    supplier_id = document.supplier_id
    if "supplier_id" in updates:
        next_supplier_id = updates["supplier_id"]
        if next_supplier_id is None:
            raise ServiceValidationError("supplier_id cannot be null")
        supplier = await _get_supplier_by_id(db, next_supplier_id)
        if supplier is None:
            raise ServiceNotFoundError("Supplier not found")
        supplier_id = supplier.supplier_id

    qualification_type = document.qualification_type
    if "qualification_type" in updates:
        qualification_type = _normalize_qualification_type(updates["qualification_type"])

    document_name = document.document_name
    if "document_name" in updates:
        if updates["document_name"] is None:
            raise ServiceValidationError("document_name cannot be null")
        document_name = _normalize_required(updates["document_name"], "document_name", 250)

    document_version = document.document_version
    if "document_version" in updates:
        document_version = _normalize_optional_string(updates["document_version"], "document_version", 50)

    duplicate = await _find_duplicate_document(
        db,
        supplier_id=supplier_id,
        qualification_type=qualification_type,
        asset_id=asset.asset_uuid if asset is not None else None,
        release_id=release.release_id if release is not None else None,
        document_name=document_name,
        document_version=document_version,
        exclude_id=document.qualification_document_id,
    )
    if duplicate is not None:
        raise ServiceConflictError(
            "A qualification document with the same supplier, context, type, name, and version already exists"
        )

    document.asset_id = asset.asset_uuid if asset is not None else None
    document.release_id = release.release_id if release is not None else None
    document.supplier_id = supplier_id
    document.qualification_type = qualification_type
    document.document_name = document_name
    document.document_version = document_version

    if "source_system" in updates:
        document.source_system = await _normalize_source_system(db, updates["source_system"])
    if "external_document_id" in updates:
        document.external_document_id = _normalize_optional_string(
            updates["external_document_id"],
            "external_document_id",
            150,
        )
    if "document_url" in updates:
        if updates["document_url"] is None:
            raise ServiceValidationError("document_url cannot be null")
        document.document_url = _normalize_required_text(updates["document_url"], "document_url")
    if "source_reference" in updates:
        document.source_reference = _normalize_optional_string(updates["source_reference"], "source_reference", 500)
    if "submission_date" in updates:
        if updates["submission_date"] is None:
            raise ServiceValidationError("submission_date cannot be null")
        document.submission_date = updates["submission_date"]
    if "notes" in updates:
        document.notes = _strip_optional(updates["notes"])
    if "modified_by" in updates:
        document.modified_by = _normalize_optional_string(updates["modified_by"], "modified_by", 150)
    document.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to update qualification document due to a data conflict") from exc

    return await get_qualification_document_by_id(db, document.qualification_document_id)


async def submit_qualification_document_for_review(
    db: AsyncSession,
    qualification_document_id: uuid.UUID,
    payload: QualificationDocumentWorkflowActionRequest,
) -> QualificationDocumentResponse:
    document = await _get_document_model_by_id(db, qualification_document_id)
    if document is None:
        raise ServiceNotFoundError("Qualification document not found")

    _ensure_can_submit_for_review(document.status)
    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    comment_text = _normalize_comment_text(payload.comment_text)

    await _create_workflow_action(
        db,
        document=document,
        action_type=QUALIFICATION_ACTION_SUBMIT_FOR_REVIEW,
        action_by=action_by,
        comment_text=comment_text,
        to_status=QUALIFICATION_STATUS_IN_REVIEW,
    )
    return await get_qualification_document_by_id(db, document.qualification_document_id)


async def accept_qualification_document(
    db: AsyncSession,
    qualification_document_id: uuid.UUID,
    payload: QualificationDocumentWorkflowActionRequest,
) -> QualificationDocumentResponse:
    document = await _get_document_model_by_id(db, qualification_document_id)
    if document is None:
        raise ServiceNotFoundError("Qualification document not found")

    _ensure_in_review(document.status, action_label="accepted")
    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    comment_text = _normalize_comment_text(payload.comment_text)

    await _create_workflow_action(
        db,
        document=document,
        action_type=QUALIFICATION_ACTION_ACCEPT,
        action_by=action_by,
        comment_text=comment_text,
        to_status=QUALIFICATION_STATUS_ACCEPTED,
    )
    return await get_qualification_document_by_id(db, document.qualification_document_id)


async def reject_qualification_document(
    db: AsyncSession,
    qualification_document_id: uuid.UUID,
    payload: QualificationDocumentWorkflowActionRequest,
) -> QualificationDocumentResponse:
    document = await _get_document_model_by_id(db, qualification_document_id)
    if document is None:
        raise ServiceNotFoundError("Qualification document not found")

    _ensure_in_review(document.status, action_label="rejected")
    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    comment_text = _normalize_comment_text(payload.comment_text, required=True)

    await _create_workflow_action(
        db,
        document=document,
        action_type=QUALIFICATION_ACTION_REJECT,
        action_by=action_by,
        comment_text=comment_text,
        to_status=QUALIFICATION_STATUS_REJECTED,
    )
    return await get_qualification_document_by_id(db, document.qualification_document_id)


async def request_qualification_document_clarification(
    db: AsyncSession,
    qualification_document_id: uuid.UUID,
    payload: QualificationDocumentWorkflowActionRequest,
) -> QualificationDocumentResponse:
    document = await _get_document_model_by_id(db, qualification_document_id)
    if document is None:
        raise ServiceNotFoundError("Qualification document not found")

    _ensure_in_review(document.status, action_label="sent back for clarification")
    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    comment_text = _normalize_comment_text(payload.comment_text, required=True)

    await _create_workflow_action(
        db,
        document=document,
        action_type=QUALIFICATION_ACTION_REQUEST_CLARIFICATION,
        action_by=action_by,
        comment_text=comment_text,
        to_status=QUALIFICATION_STATUS_NEEDS_CLARIFICATION,
    )
    return await get_qualification_document_by_id(db, document.qualification_document_id)


async def get_qualification_document_history(
    db: AsyncSession,
    qualification_document_id: uuid.UUID,
) -> list[QualificationDocumentActionResponse]:
    document = await _get_document_model_by_id(db, qualification_document_id)
    if document is None:
        raise ServiceNotFoundError("Qualification document not found")

    stmt = (
        _qualification_document_action_query()
        .where(SupplierQualificationDocumentAction.qualification_document_id == qualification_document_id)
        .order_by(SupplierQualificationDocumentAction.action_dt.desc())
    )
    result = await db.execute(stmt)
    return [_build_action_response(action) for action in result.scalars().all()]


async def delete_qualification_document(
    db: AsyncSession,
    qualification_document_id: uuid.UUID,
) -> None:
    document = await _get_document_model_by_id(db, qualification_document_id)
    if document is None:
        raise ServiceNotFoundError("Qualification document not found")

    _ensure_deletable(document.status)

    try:
        await db.delete(document)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete qualification document") from exc
