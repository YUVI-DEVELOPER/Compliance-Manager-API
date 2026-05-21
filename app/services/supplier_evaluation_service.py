import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.asset_release import AssetRelease
from app.models.authored_document import AuthoredDocument
from app.models.lookup_master import LookupMaster
from app.models.lookup_value import LookupValue
from app.models.supplier import Supplier
from app.models.supplier_evaluation import SupplierEvaluation
from app.models.supplier_evaluation_response import SupplierEvaluationResponse
from app.models.supplier_response_document import SupplierResponseDocument
from app.schemas.supplier_evaluation_schema import (
    SupplierEvaluationCreate,
    SupplierEvaluationDetail,
    SupplierEvaluationResponseCreate,
    SupplierEvaluationResponseCreateResult,
    SupplierEvaluationResponseDetail,
    SupplierEvaluationResponseSubmitRequest,
    SupplierEvaluationResponseSummary,
    SupplierEvaluationResponseUpdate,
    SupplierEvaluationSummary,
    SupplierEvaluationUpdate,
    SupplierEvaluationWorkflowActionRequest,
    SupplierResponseDocumentCreate,
    SupplierResponseDocumentResponse,
)

OMS_SOURCE_SYSTEM_LOOKUP_KEY = "OMS_SOURCE_SYSTEM"
DEFAULT_OMS_SOURCE_SYSTEM_CODES = {"MANUAL_URL", "OTHER", "SHAREPOINT", "VEEVA_VAULT"}

EVALUATION_STATUS_DRAFT = "DRAFT"
EVALUATION_STATUS_OPEN_FOR_RESPONSE = "OPEN_FOR_RESPONSE"
EVALUATION_STATUS_LOCKED = "LOCKED"
EVALUATION_STATUS_CLOSED = "CLOSED"
ALLOWED_EVALUATION_STATUSES = {
    EVALUATION_STATUS_DRAFT,
    EVALUATION_STATUS_OPEN_FOR_RESPONSE,
    EVALUATION_STATUS_LOCKED,
    EVALUATION_STATUS_CLOSED,
}

RESPONSE_STATUS_NOT_STARTED = "NOT_STARTED"
RESPONSE_STATUS_IN_PROGRESS = "IN_PROGRESS"
RESPONSE_STATUS_SUBMITTED = "SUBMITTED"
RESPONSE_STATUS_LOCKED = "LOCKED"
ALLOWED_RESPONSE_STATUSES = {
    RESPONSE_STATUS_NOT_STARTED,
    RESPONSE_STATUS_IN_PROGRESS,
    RESPONSE_STATUS_SUBMITTED,
    RESPONSE_STATUS_LOCKED,
}

DOCUMENT_TYPE_QUOTATION = "QUOTATION"
DOCUMENT_TYPE_TECHNICAL_RESPONSE = "TECHNICAL_RESPONSE"
DOCUMENT_TYPE_COMMERCIAL_RESPONSE = "COMMERCIAL_RESPONSE"
DOCUMENT_TYPE_SUPPORTING_DOCUMENT = "SUPPORTING_DOCUMENT"
ALLOWED_RESPONSE_DOCUMENT_TYPES = {
    DOCUMENT_TYPE_QUOTATION,
    DOCUMENT_TYPE_TECHNICAL_RESPONSE,
    DOCUMENT_TYPE_COMMERCIAL_RESPONSE,
    DOCUMENT_TYPE_SUPPORTING_DOCUMENT,
}

AUTHORED_DOCUMENT_TYPE_URS = "URS"
AUTHORED_DOCUMENT_STATUS_APPROVED = "APPROVED"


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


def _normalize_evaluation_status(value: str | None) -> str:
    normalized = _normalize_required(value, "status", 30).upper()
    if normalized not in ALLOWED_EVALUATION_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_EVALUATION_STATUSES))
        raise ServiceValidationError(f"status must be one of: {allowed}")
    return normalized


def _normalize_response_document_type(value: str | None) -> str:
    normalized = _normalize_required(value, "document_type", 30).upper()
    if normalized not in ALLOWED_RESPONSE_DOCUMENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_RESPONSE_DOCUMENT_TYPES))
        raise ServiceValidationError(f"document_type must be one of: {allowed}")
    return normalized


def _format_allowed_codes(codes: set[str]) -> str:
    return ", ".join(sorted(codes))


def _dedupe_uuid_list(values: list[uuid.UUID]) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    ordered: list[uuid.UUID] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _evaluation_query() -> Select[tuple[SupplierEvaluation]]:
    return select(SupplierEvaluation).options(
        selectinload(SupplierEvaluation.asset),
        selectinload(SupplierEvaluation.urs_document).selectinload(AuthoredDocument.release),
        selectinload(SupplierEvaluation.responses).selectinload(SupplierEvaluationResponse.supplier),
    )


def _response_query() -> Select[tuple[SupplierEvaluationResponse]]:
    return select(SupplierEvaluationResponse).options(
        selectinload(SupplierEvaluationResponse.supplier),
        selectinload(SupplierEvaluationResponse.documents),
        selectinload(SupplierEvaluationResponse.evaluation),
    )


def _document_query() -> Select[tuple[SupplierResponseDocument]]:
    return select(SupplierResponseDocument).options(
        selectinload(SupplierResponseDocument.response).selectinload(SupplierEvaluationResponse.evaluation),
        selectinload(SupplierResponseDocument.response).selectinload(SupplierEvaluationResponse.supplier),
    )


async def _get_asset_by_id(db: AsyncSession, asset_uuid: uuid.UUID) -> Asset | None:
    stmt = select(Asset).where(Asset.asset_uuid == asset_uuid)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_supplier_by_id(db: AsyncSession, supplier_id: uuid.UUID) -> Supplier | None:
    stmt = select(Supplier).where(Supplier.supplier_id == supplier_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_suppliers_by_ids(db: AsyncSession, supplier_ids: list[uuid.UUID]) -> dict[uuid.UUID, Supplier]:
    if not supplier_ids:
        return {}
    stmt = select(Supplier).where(Supplier.supplier_id.in_(supplier_ids))
    result = await db.execute(stmt)
    suppliers = result.scalars().all()
    return {supplier.supplier_id: supplier for supplier in suppliers}


async def _get_authored_document_by_id(db: AsyncSession, authored_document_id: uuid.UUID) -> AuthoredDocument | None:
    stmt = (
        select(AuthoredDocument)
        .options(
            selectinload(AuthoredDocument.asset),
            selectinload(AuthoredDocument.release).selectinload(AssetRelease.asset),
        )
        .where(AuthoredDocument.authored_document_id == authored_document_id)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_evaluation_model_by_id(db: AsyncSession, evaluation_id: uuid.UUID) -> SupplierEvaluation | None:
    stmt = _evaluation_query().where(SupplierEvaluation.evaluation_id == evaluation_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_response_model_by_id(db: AsyncSession, response_id: uuid.UUID) -> SupplierEvaluationResponse | None:
    stmt = _response_query().where(SupplierEvaluationResponse.response_id == response_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_document_model_by_id(db: AsyncSession, document_id: uuid.UUID) -> SupplierResponseDocument | None:
    stmt = _document_query().where(SupplierResponseDocument.document_id == document_id)
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


def _build_document_response(document: SupplierResponseDocument) -> SupplierResponseDocumentResponse:
    return SupplierResponseDocumentResponse(
        document_id=document.document_id,
        response_id=document.response_id,
        document_type=document.document_type,
        source_system=document.source_system,
        external_document_id=document.external_document_id,
        document_name=document.document_name,
        document_version=document.document_version,
        upload_dt=document.upload_dt,
        access_url=document.access_url,
        source_reference=document.source_reference,
        notes=document.notes,
        created_by=document.created_by,
        created_dt=document.created_dt,
        modified_by=document.modified_by,
        modified_dt=document.modified_dt,
    )


def _build_response_summary(response: SupplierEvaluationResponse) -> SupplierEvaluationResponseSummary:
    return SupplierEvaluationResponseSummary(
        response_id=response.response_id,
        evaluation_id=response.evaluation_id,
        supplier_id=response.supplier_id,
        supplier_name=response.supplier.supplier_name if response.supplier is not None else None,
        supplier_type=response.supplier.supplier_type if response.supplier is not None else None,
        submission_status=response.submission_status,
        quotation_reference=response.quotation_reference,
        submitted_at=response.submitted_at,
        submitted_by=response.submitted_by,
        notes=response.notes,
        created_by=response.created_by,
        created_dt=response.created_dt,
        modified_by=response.modified_by,
        modified_dt=response.modified_dt,
        document_count=len(response.documents or []),
    )


def _build_response_detail(response: SupplierEvaluationResponse) -> SupplierEvaluationResponseDetail:
    ordered_documents = sorted(
        response.documents or [],
        key=lambda item: (item.upload_dt, item.document_name.lower()),
        reverse=True,
    )
    return SupplierEvaluationResponseDetail(
        **_build_response_summary(response).model_dump(),
        evaluation_status=response.evaluation.status,
        documents=[_build_document_response(document) for document in ordered_documents],
    )


def _count_submitted_responses(responses: list[SupplierEvaluationResponse]) -> int:
    return sum(
        response.submission_status in {RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_LOCKED}
        for response in responses
    )


def _count_locked_responses(responses: list[SupplierEvaluationResponse]) -> int:
    return sum(response.submission_status == RESPONSE_STATUS_LOCKED for response in responses)


def _build_evaluation_summary(evaluation: SupplierEvaluation) -> SupplierEvaluationSummary:
    responses = evaluation.responses or []
    urs_document = evaluation.urs_document
    urs_release = urs_document.release if urs_document is not None else None

    return SupplierEvaluationSummary(
        evaluation_id=evaluation.evaluation_id,
        evaluation_name=evaluation.evaluation_name,
        asset_uuid=evaluation.asset_uuid,
        asset_name=evaluation.asset.asset_name if evaluation.asset is not None else None,
        asset_code=evaluation.asset.asset_code if evaluation.asset is not None else None,
        urs_document_id=evaluation.urs_document_id,
        urs_title=urs_document.title if urs_document is not None else None,
        urs_status=urs_document.status if urs_document is not None else None,
        urs_release_id=urs_document.release_id if urs_document is not None else None,
        urs_release_version=urs_release.version if urs_release is not None else None,
        status=evaluation.status,
        opened_at=evaluation.opened_at,
        locked_at=evaluation.locked_at,
        created_by=evaluation.created_by,
        created_dt=evaluation.created_dt,
        modified_by=evaluation.modified_by,
        modified_dt=evaluation.modified_dt,
        response_count=len(responses),
        submitted_response_count=_count_submitted_responses(responses),
        locked_response_count=_count_locked_responses(responses),
    )


def _build_evaluation_detail(evaluation: SupplierEvaluation) -> SupplierEvaluationDetail:
    return SupplierEvaluationDetail(**_build_evaluation_summary(evaluation).model_dump())


def _ensure_urs_document_matches_asset(asset: Asset, urs_document: AuthoredDocument) -> None:
    if urs_document.document_type != AUTHORED_DOCUMENT_TYPE_URS:
        raise ServiceValidationError("urs_document_id must reference a URS authored document")
    if urs_document.status != AUTHORED_DOCUMENT_STATUS_APPROVED:
        raise ServiceConflictError("Selected URS must be in APPROVED status for supplier evaluation")

    if urs_document.asset_id is not None:
        if urs_document.asset_id != asset.asset_uuid:
            raise ServiceValidationError("urs_document_id does not belong to the provided asset_uuid")
        return

    if urs_document.release is None:
        raise ServiceConflictError("Selected URS is missing its asset context")
    if urs_document.release.asset_id != asset.asset_uuid:
        raise ServiceValidationError("urs_document_id does not belong to the provided asset_uuid")


def _ensure_evaluation_allows_response_changes(evaluation: SupplierEvaluation) -> None:
    if evaluation.status in {EVALUATION_STATUS_LOCKED, EVALUATION_STATUS_CLOSED}:
        raise ServiceConflictError("Locked or closed evaluations cannot be modified")


def _ensure_response_is_editable(response: SupplierEvaluationResponse) -> None:
    _ensure_evaluation_allows_response_changes(response.evaluation)
    if response.submission_status in {RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_LOCKED}:
        raise ServiceConflictError("Submitted or locked supplier responses are read-only")


def _ensure_response_can_be_submitted(response: SupplierEvaluationResponse) -> None:
    if response.evaluation.status not in {EVALUATION_STATUS_DRAFT, EVALUATION_STATUS_OPEN_FOR_RESPONSE}:
        raise ServiceConflictError("Supplier responses can only be submitted while the evaluation is open for work")
    if response.submission_status in {RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_LOCKED}:
        raise ServiceConflictError("This supplier response has already been submitted")
    if len(response.documents or []) == 0:
        raise ServiceConflictError("Attach at least one response document before submitting")


def _ensure_evaluation_can_be_opened(evaluation: SupplierEvaluation) -> None:
    if evaluation.status != EVALUATION_STATUS_DRAFT:
        raise ServiceConflictError("Only draft evaluations can be opened for supplier response")
    if len(evaluation.responses or []) == 0:
        raise ServiceConflictError("Add at least one supplier response before opening the evaluation")


def _ensure_evaluation_can_be_locked(evaluation: SupplierEvaluation) -> None:
    if evaluation.status != EVALUATION_STATUS_OPEN_FOR_RESPONSE:
        raise ServiceConflictError("Only evaluations in OPEN_FOR_RESPONSE can be locked")
    if len(evaluation.responses or []) == 0:
        raise ServiceConflictError("Add at least one supplier response before locking the evaluation")

    pending_supplier_names = [
        response.supplier.supplier_name or str(response.supplier_id)
        for response in evaluation.responses
        if response.submission_status not in {RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_LOCKED}
    ]
    if pending_supplier_names:
        supplier_list = ", ".join(pending_supplier_names)
        raise ServiceConflictError(
            f"All supplier responses must be submitted before locking. Pending suppliers: {supplier_list}"
        )


def _maybe_mark_response_in_progress(response: SupplierEvaluationResponse) -> None:
    if response.submission_status != RESPONSE_STATUS_NOT_STARTED:
        return
    has_content = bool(_strip_optional(response.quotation_reference) or _strip_optional(response.notes))
    has_documents = len(response.documents or []) > 0
    if has_content or has_documents:
        response.submission_status = RESPONSE_STATUS_IN_PROGRESS


def _conflict_message_from_integrity_error(exc: IntegrityError) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    if "uq_supplier_evaluation_response_evaluation_supplier" in message:
        return "A supplier can only have one response in the same evaluation"
    if "chk_supplier_evaluation_status" in message:
        allowed = ", ".join(sorted(ALLOWED_EVALUATION_STATUSES))
        return f"status must be one of: {allowed}"
    if "chk_supplier_evaluation_response_submission_status" in message:
        allowed = ", ".join(sorted(ALLOWED_RESPONSE_STATUSES))
        return f"submission_status must be one of: {allowed}"
    if "chk_supplier_response_document_type" in message:
        allowed = ", ".join(sorted(ALLOWED_RESPONSE_DOCUMENT_TYPES))
        return f"document_type must be one of: {allowed}"
    return "Operation failed due to a data conflict"


async def get_supplier_evaluations(
    db: AsyncSession,
    *,
    asset_uuid: uuid.UUID | None = None,
    status_value: str | None = None,
) -> list[SupplierEvaluationSummary]:
    stmt = _evaluation_query()

    if asset_uuid is not None:
        asset = await _get_asset_by_id(db, asset_uuid)
        if asset is None:
            raise ServiceNotFoundError("Asset not found")
        stmt = stmt.where(SupplierEvaluation.asset_uuid == asset_uuid)

    if status_value is not None:
        stmt = stmt.where(SupplierEvaluation.status == _normalize_evaluation_status(status_value))

    stmt = stmt.order_by(SupplierEvaluation.modified_dt.desc(), SupplierEvaluation.created_dt.desc())
    result = await db.execute(stmt)
    evaluations = result.scalars().unique().all()
    return [_build_evaluation_summary(evaluation) for evaluation in evaluations]


async def get_supplier_evaluation_by_id(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
) -> SupplierEvaluationDetail:
    evaluation = await _get_evaluation_model_by_id(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")
    return _build_evaluation_detail(evaluation)


async def create_supplier_evaluation(
    db: AsyncSession,
    payload: SupplierEvaluationCreate,
) -> SupplierEvaluationDetail:
    evaluation_name = _normalize_required(payload.evaluation_name, "evaluation_name", 250)
    created_by = _normalize_optional_string(payload.created_by, "created_by", 150)

    asset = await _get_asset_by_id(db, payload.asset_uuid)
    if asset is None:
        raise ServiceNotFoundError("Asset not found")

    urs_document = await _get_authored_document_by_id(db, payload.urs_document_id)
    if urs_document is None:
        raise ServiceNotFoundError("URS authored document not found")
    _ensure_urs_document_matches_asset(asset, urs_document)

    supplier_ids = _dedupe_uuid_list(payload.supplier_ids)
    supplier_map = await _get_suppliers_by_ids(db, supplier_ids)
    missing_supplier_ids = [supplier_id for supplier_id in supplier_ids if supplier_id not in supplier_map]
    if missing_supplier_ids:
        raise ServiceNotFoundError("One or more suppliers were not found")

    now = datetime.now(UTC)
    evaluation = SupplierEvaluation(
        evaluation_name=evaluation_name,
        asset_uuid=asset.asset_uuid,
        urs_document_id=urs_document.authored_document_id,
        status=EVALUATION_STATUS_DRAFT,
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(evaluation)

    for supplier_id in supplier_ids:
        db.add(
            SupplierEvaluationResponse(
                evaluation=evaluation,
                supplier_id=supplier_id,
                submission_status=RESPONSE_STATUS_NOT_STARTED,
                created_by=created_by,
                created_dt=now,
                modified_by=created_by,
                modified_dt=now,
            )
        )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_supplier_evaluation_by_id(db, evaluation.evaluation_id)


async def update_supplier_evaluation(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
    payload: SupplierEvaluationUpdate,
) -> SupplierEvaluationDetail:
    evaluation = await _get_evaluation_model_by_id(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")

    updates = payload.model_dump(exclude_unset=True)
    modified_by = _normalize_optional_string(updates.get("modified_by"), "modified_by", 150)
    changed = False

    if "status" in updates:
        if updates["status"] is None:
            raise ServiceValidationError("status cannot be null")
        next_status = _normalize_evaluation_status(updates["status"])
        if next_status != EVALUATION_STATUS_CLOSED:
            raise ServiceValidationError("Status updates must use the open/lock endpoints; only CLOSED is supported here")
        if evaluation.status != EVALUATION_STATUS_LOCKED:
            raise ServiceConflictError("Only locked evaluations can be moved to CLOSED")
        if evaluation.status != next_status:
            evaluation.status = next_status
            changed = True

    if "evaluation_name" in updates:
        if evaluation.status in {EVALUATION_STATUS_LOCKED, EVALUATION_STATUS_CLOSED}:
            raise ServiceConflictError("Locked or closed evaluations cannot be modified")
        if updates["evaluation_name"] is None:
            raise ServiceValidationError("evaluation_name cannot be null")
        next_name = _normalize_required(updates["evaluation_name"], "evaluation_name", 250)
        if next_name != evaluation.evaluation_name:
            evaluation.evaluation_name = next_name
            changed = True

    if "urs_document_id" in updates:
        if evaluation.status != EVALUATION_STATUS_DRAFT:
            raise ServiceConflictError("URS linkage can only be changed while the evaluation is in DRAFT")
        if updates["urs_document_id"] is None:
            raise ServiceValidationError("urs_document_id cannot be null")
        urs_document = await _get_authored_document_by_id(db, updates["urs_document_id"])
        if urs_document is None:
            raise ServiceNotFoundError("URS authored document not found")
        if evaluation.asset is None:
            asset = await _get_asset_by_id(db, evaluation.asset_uuid)
            if asset is None:
                raise ServiceNotFoundError("Asset not found")
            evaluation.asset = asset
        _ensure_urs_document_matches_asset(evaluation.asset, urs_document)
        if urs_document.authored_document_id != evaluation.urs_document_id:
            evaluation.urs_document_id = urs_document.authored_document_id
            changed = True

    if not changed:
        return _build_evaluation_detail(evaluation)

    evaluation.modified_by = modified_by
    evaluation.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_supplier_evaluation_by_id(db, evaluation.evaluation_id)


async def open_supplier_evaluation(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
    payload: SupplierEvaluationWorkflowActionRequest,
) -> SupplierEvaluationDetail:
    evaluation = await _get_evaluation_model_by_id(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")

    _ensure_evaluation_can_be_opened(evaluation)

    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    now = datetime.now(UTC)
    evaluation.status = EVALUATION_STATUS_OPEN_FOR_RESPONSE
    evaluation.opened_at = now
    evaluation.modified_by = action_by
    evaluation.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_supplier_evaluation_by_id(db, evaluation.evaluation_id)


async def lock_supplier_evaluation(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
    payload: SupplierEvaluationWorkflowActionRequest,
) -> SupplierEvaluationDetail:
    evaluation = await _get_evaluation_model_by_id(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")

    _ensure_evaluation_can_be_locked(evaluation)

    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    now = datetime.now(UTC)
    evaluation.status = EVALUATION_STATUS_LOCKED
    evaluation.locked_at = now
    evaluation.modified_by = action_by
    evaluation.modified_dt = now

    for response in evaluation.responses:
        response.submission_status = RESPONSE_STATUS_LOCKED
        response.modified_by = action_by
        response.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_supplier_evaluation_by_id(db, evaluation.evaluation_id)


async def get_supplier_evaluation_responses(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
) -> list[SupplierEvaluationResponseSummary]:
    evaluation = await _get_evaluation_model_by_id(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")

    stmt = (
        _response_query()
        .where(SupplierEvaluationResponse.evaluation_id == evaluation_id)
        .join(Supplier, SupplierEvaluationResponse.supplier_id == Supplier.supplier_id)
        .order_by(Supplier.supplier_name.asc())
    )
    result = await db.execute(stmt)
    responses = result.scalars().unique().all()
    return [_build_response_summary(response) for response in responses]


async def add_supplier_evaluation_responses(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
    payload: SupplierEvaluationResponseCreate,
) -> SupplierEvaluationResponseCreateResult:
    evaluation = await _get_evaluation_model_by_id(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")

    _ensure_evaluation_allows_response_changes(evaluation)

    supplier_ids = _dedupe_uuid_list(payload.supplier_ids)
    if not supplier_ids:
        raise ServiceValidationError("supplier_ids must contain at least one supplier")

    duplicate_supplier_names = [
        response.supplier.supplier_name or str(response.supplier_id)
        for response in evaluation.responses
        if response.supplier_id in supplier_ids
    ]
    if duplicate_supplier_names:
        raise ServiceConflictError(
            f"Supplier responses already exist for: {', '.join(duplicate_supplier_names)}"
        )

    supplier_map = await _get_suppliers_by_ids(db, supplier_ids)
    missing_supplier_ids = [supplier_id for supplier_id in supplier_ids if supplier_id not in supplier_map]
    if missing_supplier_ids:
        raise ServiceNotFoundError("One or more suppliers were not found")

    created_by = _normalize_optional_string(payload.created_by, "created_by", 150)
    now = datetime.now(UTC)
    created_responses: list[SupplierEvaluationResponse] = []

    for supplier_id in supplier_ids:
        response = SupplierEvaluationResponse(
            evaluation_id=evaluation.evaluation_id,
            supplier_id=supplier_id,
            submission_status=RESPONSE_STATUS_NOT_STARTED,
            created_by=created_by,
            created_dt=now,
            modified_by=created_by,
            modified_dt=now,
        )
        db.add(response)
        created_responses.append(response)

    evaluation.modified_by = created_by
    evaluation.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    if not created_responses:
        return SupplierEvaluationResponseCreateResult(created_count=0, responses=[])

    created_response_ids = [response.response_id for response in created_responses]
    stmt = (
        _response_query()
        .where(SupplierEvaluationResponse.response_id.in_(created_response_ids))
        .join(Supplier, SupplierEvaluationResponse.supplier_id == Supplier.supplier_id)
        .order_by(Supplier.supplier_name.asc())
    )
    result = await db.execute(stmt)
    stored_responses = result.scalars().unique().all()
    return SupplierEvaluationResponseCreateResult(
        created_count=len(stored_responses),
        responses=[_build_response_summary(response) for response in stored_responses],
    )


async def get_supplier_evaluation_response_by_id(
    db: AsyncSession,
    response_id: uuid.UUID,
) -> SupplierEvaluationResponseDetail:
    response = await _get_response_model_by_id(db, response_id)
    if response is None:
        raise ServiceNotFoundError("Supplier response not found")
    return _build_response_detail(response)


async def update_supplier_evaluation_response(
    db: AsyncSession,
    response_id: uuid.UUID,
    payload: SupplierEvaluationResponseUpdate,
) -> SupplierEvaluationResponseDetail:
    response = await _get_response_model_by_id(db, response_id)
    if response is None:
        raise ServiceNotFoundError("Supplier response not found")

    _ensure_response_is_editable(response)
    updates = payload.model_dump(exclude_unset=True)
    changed = False

    if "quotation_reference" in updates:
        next_reference = _normalize_optional_string(updates["quotation_reference"], "quotation_reference", 250)
        if next_reference != response.quotation_reference:
            response.quotation_reference = next_reference
            changed = True

    if "notes" in updates:
        next_notes = _strip_optional(updates["notes"])
        if next_notes != response.notes:
            response.notes = next_notes
            changed = True

    if not changed:
        return _build_response_detail(response)

    response.modified_by = _normalize_optional_string(updates.get("modified_by"), "modified_by", 150)
    response.modified_dt = datetime.now(UTC)
    _maybe_mark_response_in_progress(response)
    response.evaluation.modified_dt = response.modified_dt
    response.evaluation.modified_by = response.modified_by

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_supplier_evaluation_response_by_id(db, response.response_id)


async def submit_supplier_evaluation_response(
    db: AsyncSession,
    response_id: uuid.UUID,
    payload: SupplierEvaluationResponseSubmitRequest,
) -> SupplierEvaluationResponseDetail:
    response = await _get_response_model_by_id(db, response_id)
    if response is None:
        raise ServiceNotFoundError("Supplier response not found")

    _ensure_response_can_be_submitted(response)

    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    now = datetime.now(UTC)
    response.submission_status = RESPONSE_STATUS_SUBMITTED
    response.submitted_at = now
    response.submitted_by = action_by
    response.modified_by = action_by
    response.modified_dt = now
    response.evaluation.modified_by = action_by
    response.evaluation.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_supplier_evaluation_response_by_id(db, response.response_id)


async def get_supplier_response_documents(
    db: AsyncSession,
    response_id: uuid.UUID,
) -> list[SupplierResponseDocumentResponse]:
    response = await _get_response_model_by_id(db, response_id)
    if response is None:
        raise ServiceNotFoundError("Supplier response not found")

    ordered_documents = sorted(
        response.documents or [],
        key=lambda item: (item.upload_dt, item.document_name.lower()),
        reverse=True,
    )
    return [_build_document_response(document) for document in ordered_documents]


async def create_supplier_response_document(
    db: AsyncSession,
    response_id: uuid.UUID,
    payload: SupplierResponseDocumentCreate,
) -> SupplierResponseDocumentResponse:
    response = await _get_response_model_by_id(db, response_id)
    if response is None:
        raise ServiceNotFoundError("Supplier response not found")

    _ensure_response_is_editable(response)

    document_type = _normalize_response_document_type(payload.document_type)
    source_system = await _normalize_source_system(db, payload.source_system)
    external_document_id = _normalize_optional_string(payload.external_document_id, "external_document_id", 150)
    document_name = _normalize_required(payload.document_name, "document_name", 250)
    document_version = _normalize_optional_string(payload.document_version, "document_version", 50)
    access_url = _normalize_required_text(payload.access_url, "access_url")
    created_by = _normalize_optional_string(payload.created_by, "created_by", 150)
    now = datetime.now(UTC)

    document = SupplierResponseDocument(
        response_id=response.response_id,
        document_type=document_type,
        source_system=source_system,
        external_document_id=external_document_id,
        document_name=document_name,
        document_version=document_version,
        upload_dt=payload.upload_dt,
        access_url=access_url,
        source_reference=_normalize_optional_string(payload.source_reference, "source_reference", 500),
        notes=_strip_optional(payload.notes),
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(document)

    response.modified_by = created_by
    response.modified_dt = now
    if response.submission_status == RESPONSE_STATUS_NOT_STARTED:
        response.submission_status = RESPONSE_STATUS_IN_PROGRESS
    response.evaluation.modified_by = created_by
    response.evaluation.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    stored_document = await _get_document_model_by_id(db, document.document_id)
    if stored_document is None:
        raise ServiceConflictError("Supplier response document could not be loaded after creation")
    return _build_document_response(stored_document)


async def delete_supplier_response_document(
    db: AsyncSession,
    document_id: uuid.UUID,
) -> None:
    document = await _get_document_model_by_id(db, document_id)
    if document is None:
        raise ServiceNotFoundError("Supplier response document not found")

    _ensure_response_is_editable(document.response)
    now = datetime.now(UTC)
    document.response.modified_dt = now
    document.response.evaluation.modified_dt = now

    try:
        await db.delete(document)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete supplier response document") from exc
