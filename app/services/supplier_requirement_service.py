import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.authored_document import AuthoredDocument
from app.models.evaluation_requirement_item import EvaluationRequirementItem
from app.models.supplier_evaluation import SupplierEvaluation
from app.models.supplier_evaluation_response import SupplierEvaluationResponse
from app.models.supplier_requirement_response import SupplierRequirementResponse
from app.schemas.supplier_evaluation_schema import (
    EvaluationRequirementItemCreate,
    EvaluationRequirementItemResponse,
    EvaluationRequirementItemUpdate,
    EvaluationRequirementSeedRequest,
    EvaluationRequirementSeedResult,
    SupplierRequirementResponseBulkSaveItem,
    SupplierRequirementResponseBulkSaveRequest,
    SupplierRequirementResponseCreate,
    SupplierRequirementResponseMatrixRow,
    SupplierRequirementResponseUpdate,
)
from app.services.supplier_evaluation_service import (
    EVALUATION_STATUS_CLOSED,
    EVALUATION_STATUS_DRAFT,
    EVALUATION_STATUS_LOCKED,
    RESPONSE_STATUS_IN_PROGRESS,
    RESPONSE_STATUS_LOCKED,
    RESPONSE_STATUS_NOT_STARTED,
    RESPONSE_STATUS_SUBMITTED,
    ServiceConflictError,
    ServiceNotFoundError,
    ServiceValidationError,
)

FIT_STATUS_MEETS = "MEETS"
FIT_STATUS_PARTIALLY_MEETS = "PARTIALLY_MEETS"
FIT_STATUS_NOT_MEETS = "NOT_MEETS"
ALLOWED_FIT_STATUSES = {
    FIT_STATUS_MEETS,
    FIT_STATUS_PARTIALLY_MEETS,
    FIT_STATUS_NOT_MEETS,
}

SEED_STRATEGY = "DETERMINISTIC_URS_MARKDOWN_PARSE"

HEADING_PATTERN = re.compile(r"^\s*#{1,6}\s+(?P<title>.+?)\s*$")
LIST_ITEM_PATTERN = re.compile(
    r"^\s*(?:(?P<number>\d+(?:\.\d+)*[.)])|(?P<alpha>[A-Za-z][.)])|(?P<bullet>[-*+]))\s+(?P<body>.+?)\s*$"
)
INLINE_REQUIREMENT_KEY_PATTERN = re.compile(
    r"^(?P<key>(?:[A-Z]{2,10}[-_ ]?\d+(?:\.\d+)*|\d+(?:\.\d+)*))[:.)-]\s*(?P<body>.+)$"
)
METADATA_LINE_PATTERN = re.compile(r"^(document type|status|template|generated on)\s*:", re.IGNORECASE)
WHITESPACE_PATTERN = re.compile(r"\s+")

RELEVANT_SECTION_HINTS = (
    "requirement",
    "functional",
    "feature",
    "capability",
    "user need",
    "user requirement",
    "performance",
    "security",
    "access",
    "audit",
    "alarm",
    "interface",
    "integration",
    "data",
    "report",
    "compliance",
    "validation",
)
IGNORED_SECTION_HINTS = (
    "purpose",
    "scope",
    "asset summary",
    "asset classification",
    "release context",
    "asset specifications summary",
    "authoring notes",
)
REQUIREMENT_TEXT_HINTS = (
    " shall ",
    " must ",
    " should ",
    " required ",
    " need to ",
    " needs to ",
    " capable of ",
    " ability to ",
    " support ",
    " supports ",
    " provide ",
    " provides ",
    " include ",
    " includes ",
)


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


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


def _normalize_fit_status(value: str | None, *, required: bool) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        if required:
            raise ServiceValidationError("fit_status is required")
        return None
    upper_value = normalized.upper()
    if upper_value not in ALLOWED_FIT_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_FIT_STATUSES))
        raise ServiceValidationError(f"fit_status must be one of: {allowed}")
    return upper_value


def _normalize_requirement_order(value: int | None) -> int | None:
    if value is None:
        return None
    if value < 0:
        raise ServiceValidationError("requirement_order must be zero or greater")
    return value


def _normalize_seed_text(value: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", value).strip()


def _normalize_text_key(value: str | None) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    return WHITESPACE_PATTERN.sub(" ", normalized).strip().lower()


def _is_relevant_section(section: str | None) -> bool:
    normalized = _normalize_text_key(section)
    if normalized is None:
        return False
    if any(hint in normalized for hint in IGNORED_SECTION_HINTS):
        return False
    return any(hint in normalized for hint in RELEVANT_SECTION_HINTS)


def _contains_requirement_hint(text: str) -> bool:
    normalized = f" {_normalize_seed_text(text).lower()} "
    return any(hint in normalized for hint in REQUIREMENT_TEXT_HINTS)


def _extract_inline_requirement_key(text: str) -> tuple[str | None, str]:
    match = INLINE_REQUIREMENT_KEY_PATTERN.match(text)
    if match is None:
        return None, text
    return match.group("key").strip(), match.group("body").strip()


def _build_seed_candidate(
    raw_text: str,
    *,
    requirement_key: str | None,
    section: str | None,
    line_number: int,
) -> dict[str, object] | None:
    text = _normalize_seed_text(raw_text)
    if not text:
        return None
    if METADATA_LINE_PATTERN.match(text):
        return None

    inline_key, body = _extract_inline_requirement_key(text)
    final_key = requirement_key or inline_key
    requirement_text = body if inline_key is not None else text
    if len(requirement_text) < 12:
        return None

    if not _contains_requirement_hint(requirement_text) and not _is_relevant_section(section):
        return None

    source_reference = section or f"Line {line_number}"
    if section is not None:
        source_reference = f"{section} / line {line_number}"

    return {
        "requirement_key": _normalize_optional_string(final_key, "requirement_key", 100),
        "requirement_section": _normalize_optional_string(section, "requirement_section", 250),
        "requirement_text": requirement_text,
        "source_reference": _normalize_optional_string(source_reference, "source_reference", 500),
    }


def _extract_requirement_seed_candidates(document: AuthoredDocument) -> list[dict[str, object]]:
    content = _strip_optional(document.content)
    if content is None:
        return []

    normalized_content = content.replace("\r\n", "\n").replace("\r", "\n")
    current_section: str | None = None
    paragraph_lines: list[str] = []
    paragraph_start_line: int | None = None
    candidates: list[dict[str, object]] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_lines, paragraph_start_line
        if not paragraph_lines:
            return
        candidate = _build_seed_candidate(
            " ".join(paragraph_lines),
            requirement_key=None,
            section=current_section,
            line_number=paragraph_start_line or 0,
        )
        if candidate is not None:
            candidates.append(candidate)
        paragraph_lines = []
        paragraph_start_line = None

    for line_number, raw_line in enumerate(normalized_content.split("\n"), start=1):
        stripped_line = raw_line.strip()
        if not stripped_line:
            flush_paragraph()
            continue

        heading_match = HEADING_PATTERN.match(raw_line)
        if heading_match is not None:
            flush_paragraph()
            current_section = heading_match.group("title").strip()
            continue

        if METADATA_LINE_PATTERN.match(stripped_line) or stripped_line.startswith("|"):
            flush_paragraph()
            continue

        list_match = LIST_ITEM_PATTERN.match(raw_line)
        if list_match is not None:
            flush_paragraph()
            raw_key = list_match.group("number") or list_match.group("alpha")
            requirement_key = raw_key.rstrip(".)") if raw_key is not None else None
            candidate = _build_seed_candidate(
                list_match.group("body"),
                requirement_key=requirement_key,
                section=current_section,
                line_number=line_number,
            )
            if candidate is not None:
                candidates.append(candidate)
            continue

        if paragraph_start_line is None:
            paragraph_start_line = line_number
        paragraph_lines.append(stripped_line)

    flush_paragraph()

    deduped: list[dict[str, object]] = []
    seen_keys: set[tuple[str | None, str]] = set()
    for candidate in candidates:
        section_key = _normalize_text_key(candidate.get("requirement_section"))  # type: ignore[arg-type]
        text_key = _normalize_text_key(candidate.get("requirement_text"))  # type: ignore[arg-type]
        if text_key is None:
            continue
        dedupe_key = (section_key, text_key)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        deduped.append(candidate)

    return deduped


def _evaluation_query() -> Select[tuple[SupplierEvaluation]]:
    return select(SupplierEvaluation).options(
        selectinload(SupplierEvaluation.responses).selectinload(SupplierEvaluationResponse.supplier),
        selectinload(SupplierEvaluation.requirement_items),
        selectinload(SupplierEvaluation.urs_document),
    )


def _response_query() -> Select[tuple[SupplierEvaluationResponse]]:
    return select(SupplierEvaluationResponse).options(
        selectinload(SupplierEvaluationResponse.evaluation).selectinload(SupplierEvaluation.responses).selectinload(
            SupplierEvaluationResponse.supplier
        ),
        selectinload(SupplierEvaluationResponse.requirement_responses),
    )


def _requirement_item_query() -> Select[tuple[EvaluationRequirementItem]]:
    return select(EvaluationRequirementItem).options(
        selectinload(EvaluationRequirementItem.evaluation).selectinload(SupplierEvaluation.responses).selectinload(
            SupplierEvaluationResponse.supplier
        )
    )


def _requirement_response_query() -> Select[tuple[SupplierRequirementResponse]]:
    return select(SupplierRequirementResponse).options(
        selectinload(SupplierRequirementResponse.response).selectinload(SupplierEvaluationResponse.evaluation),
        selectinload(SupplierRequirementResponse.requirement_item),
    )


async def _get_evaluation_model_by_id(db: AsyncSession, evaluation_id: uuid.UUID) -> SupplierEvaluation | None:
    result = await db.execute(_evaluation_query().where(SupplierEvaluation.evaluation_id == evaluation_id))
    return result.scalars().first()


async def _get_response_model_by_id(db: AsyncSession, response_id: uuid.UUID) -> SupplierEvaluationResponse | None:
    result = await db.execute(_response_query().where(SupplierEvaluationResponse.response_id == response_id))
    return result.scalars().first()


async def _get_requirement_item_model_by_id(
    db: AsyncSession, requirement_item_id: uuid.UUID
) -> EvaluationRequirementItem | None:
    result = await db.execute(
        _requirement_item_query().where(EvaluationRequirementItem.requirement_item_id == requirement_item_id)
    )
    return result.scalars().first()


async def _get_requirement_response_model_by_id(
    db: AsyncSession, requirement_response_id: uuid.UUID
) -> SupplierRequirementResponse | None:
    result = await db.execute(
        _requirement_response_query().where(
            SupplierRequirementResponse.requirement_response_id == requirement_response_id
        )
    )
    return result.scalars().first()


async def _get_existing_requirement_response(
    db: AsyncSession,
    *,
    response_id: uuid.UUID,
    requirement_item_id: uuid.UUID,
) -> SupplierRequirementResponse | None:
    stmt = _requirement_response_query().where(
        SupplierRequirementResponse.response_id == response_id,
        SupplierRequirementResponse.requirement_item_id == requirement_item_id,
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_next_requirement_order(db: AsyncSession, evaluation_id: uuid.UUID) -> int:
    stmt = select(func.max(EvaluationRequirementItem.requirement_order)).where(
        EvaluationRequirementItem.evaluation_id == evaluation_id
    )
    result = await db.execute(stmt)
    current_max = result.scalar_one_or_none()
    return (current_max or 0) + 1


def _build_requirement_item_response(
    requirement_item: EvaluationRequirementItem,
) -> EvaluationRequirementItemResponse:
    return EvaluationRequirementItemResponse(
        requirement_item_id=requirement_item.requirement_item_id,
        evaluation_id=requirement_item.evaluation_id,
        urs_document_id=requirement_item.urs_document_id,
        requirement_key=requirement_item.requirement_key,
        requirement_section=requirement_item.requirement_section,
        requirement_text=requirement_item.requirement_text,
        requirement_order=requirement_item.requirement_order,
        source_reference=requirement_item.source_reference,
        created_by=requirement_item.created_by,
        created_dt=requirement_item.created_dt,
        modified_by=requirement_item.modified_by,
        modified_dt=requirement_item.modified_dt,
    )


def _build_requirement_matrix_row(
    requirement_item: EvaluationRequirementItem,
    *,
    response_id: uuid.UUID,
    requirement_response: SupplierRequirementResponse | None,
) -> SupplierRequirementResponseMatrixRow:
    return SupplierRequirementResponseMatrixRow(
        requirement_item_id=requirement_item.requirement_item_id,
        requirement_response_id=(
            requirement_response.requirement_response_id if requirement_response is not None else None
        ),
        response_id=response_id,
        requirement_key=requirement_item.requirement_key,
        requirement_section=requirement_item.requirement_section,
        requirement_text=requirement_item.requirement_text,
        requirement_order=requirement_item.requirement_order,
        source_reference=requirement_item.source_reference,
        fit_status=requirement_response.fit_status if requirement_response is not None else None,
        supplier_response_text=(
            requirement_response.supplier_response_text if requirement_response is not None else None
        ),
        evidence_reference=requirement_response.evidence_reference if requirement_response is not None else None,
        notes=requirement_response.notes if requirement_response is not None else None,
        created_by=requirement_response.created_by if requirement_response is not None else None,
        created_dt=requirement_response.created_dt if requirement_response is not None else None,
        modified_by=requirement_response.modified_by if requirement_response is not None else None,
        modified_dt=requirement_response.modified_dt if requirement_response is not None else None,
    )


def _ensure_response_is_editable(response: SupplierEvaluationResponse) -> None:
    if response.evaluation.status in {EVALUATION_STATUS_LOCKED, EVALUATION_STATUS_CLOSED}:
        raise ServiceConflictError("Locked or closed evaluations cannot be modified")
    if response.submission_status in {RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_LOCKED}:
        raise ServiceConflictError("Submitted or locked supplier responses are read-only")


def _ensure_evaluation_allows_requirement_definition(evaluation: SupplierEvaluation) -> None:
    if evaluation.status != EVALUATION_STATUS_DRAFT:
        raise ServiceConflictError("Requirement baseline can only be managed while the evaluation is in DRAFT")

    started_responses = [
        response.supplier.supplier_name or str(response.supplier_id)
        for response in evaluation.responses or []
        if response.submission_status != RESPONSE_STATUS_NOT_STARTED
    ]
    if started_responses:
        supplier_list = ", ".join(started_responses)
        raise ServiceConflictError(
            f"Requirement baseline is frozen once supplier response work starts. Started suppliers: {supplier_list}"
        )


def _ensure_requirement_item_belongs_to_response(
    requirement_item: EvaluationRequirementItem,
    response: SupplierEvaluationResponse,
) -> None:
    if requirement_item.evaluation_id != response.evaluation_id:
        raise ServiceValidationError("requirement_item_id does not belong to this supplier response's evaluation")


def _apply_requirement_response_fields(
    requirement_response: SupplierRequirementResponse,
    *,
    fit_status: str,
    supplier_response_text: str | None,
    evidence_reference: str | None,
    notes: str | None,
    actor: str | None,
    now: datetime,
) -> bool:
    changed = False
    if requirement_response.fit_status != fit_status:
        requirement_response.fit_status = fit_status
        changed = True
    if requirement_response.supplier_response_text != supplier_response_text:
        requirement_response.supplier_response_text = supplier_response_text
        changed = True
    if requirement_response.evidence_reference != evidence_reference:
        requirement_response.evidence_reference = evidence_reference
        changed = True
    if requirement_response.notes != notes:
        requirement_response.notes = notes
        changed = True

    if changed:
        requirement_response.modified_by = actor
        requirement_response.modified_dt = now
    return changed


def _conflict_message_from_integrity_error(exc: IntegrityError) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    if "uq_supplier_requirement_response_response_requirement" in message:
        return "A supplier can only have one structured response per requirement item"
    if "chk_supplier_requirement_response_fit_status" in message:
        allowed = ", ".join(sorted(ALLOWED_FIT_STATUSES))
        return f"fit_status must be one of: {allowed}"
    return "Operation failed due to a data conflict"


async def get_supplier_evaluation_requirements(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
) -> list[EvaluationRequirementItemResponse]:
    evaluation = await _get_evaluation_model_by_id(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")

    stmt = (
        select(EvaluationRequirementItem)
        .where(EvaluationRequirementItem.evaluation_id == evaluation_id)
        .order_by(EvaluationRequirementItem.requirement_order.asc().nulls_last(), EvaluationRequirementItem.created_dt.asc())
    )
    result = await db.execute(stmt)
    items = result.scalars().all()
    return [_build_requirement_item_response(item) for item in items]


async def seed_supplier_evaluation_requirements(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
    payload: EvaluationRequirementSeedRequest,
) -> EvaluationRequirementSeedResult:
    evaluation = await _get_evaluation_model_by_id(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")

    _ensure_evaluation_allows_requirement_definition(evaluation)
    if evaluation.urs_document is None:
        raise ServiceConflictError("Selected URS could not be loaded for requirement seeding")

    candidates = _extract_requirement_seed_candidates(evaluation.urs_document)
    existing_texts = {
        _normalize_text_key(item.requirement_text)
        for item in evaluation.requirement_items or []
        if _normalize_text_key(item.requirement_text) is not None
    }

    created_by = _normalize_optional_string(payload.created_by, "created_by", 150)
    created_count = 0
    skipped_count = 0
    next_order = await _get_next_requirement_order(db, evaluation.evaluation_id)
    now = datetime.now(UTC)

    for candidate in candidates:
        text_key = _normalize_text_key(candidate["requirement_text"])  # type: ignore[index]
        if text_key is None or text_key in existing_texts:
            skipped_count += 1
            continue

        requirement_item = EvaluationRequirementItem(
            evaluation_id=evaluation.evaluation_id,
            urs_document_id=evaluation.urs_document_id,
            requirement_key=candidate["requirement_key"],  # type: ignore[index]
            requirement_section=candidate["requirement_section"],  # type: ignore[index]
            requirement_text=candidate["requirement_text"],  # type: ignore[index]
            requirement_order=next_order,
            source_reference=candidate["source_reference"],  # type: ignore[index]
            created_by=created_by,
            created_dt=now,
            modified_by=created_by,
            modified_dt=now,
        )
        db.add(requirement_item)
        existing_texts.add(text_key)
        next_order += 1
        created_count += 1

    if created_count > 0:
        evaluation.modified_by = created_by
        evaluation.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    requirements = await get_supplier_evaluation_requirements(db, evaluation.evaluation_id)
    return EvaluationRequirementSeedResult(
        created_count=created_count,
        skipped_count=skipped_count,
        strategy=SEED_STRATEGY,
        requirements=requirements,
    )


async def create_evaluation_requirement_item(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
    payload: EvaluationRequirementItemCreate,
) -> EvaluationRequirementItemResponse:
    evaluation = await _get_evaluation_model_by_id(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")

    _ensure_evaluation_allows_requirement_definition(evaluation)
    created_by = _normalize_optional_string(payload.created_by, "created_by", 150)
    requirement_order = _normalize_requirement_order(payload.requirement_order)
    if requirement_order is None:
        requirement_order = await _get_next_requirement_order(db, evaluation.evaluation_id)

    now = datetime.now(UTC)
    requirement_item = EvaluationRequirementItem(
        evaluation_id=evaluation.evaluation_id,
        urs_document_id=evaluation.urs_document_id,
        requirement_key=_normalize_optional_string(payload.requirement_key, "requirement_key", 100),
        requirement_section=_normalize_optional_string(payload.requirement_section, "requirement_section", 250),
        requirement_text=_normalize_required_text(payload.requirement_text, "requirement_text"),
        requirement_order=requirement_order,
        source_reference=_normalize_optional_string(payload.source_reference, "source_reference", 500),
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(requirement_item)
    evaluation.modified_by = created_by
    evaluation.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    stored_item = await _get_requirement_item_model_by_id(db, requirement_item.requirement_item_id)
    if stored_item is None:
        raise ServiceConflictError("Evaluation requirement item could not be loaded after creation")
    return _build_requirement_item_response(stored_item)


async def update_evaluation_requirement_item(
    db: AsyncSession,
    requirement_item_id: uuid.UUID,
    payload: EvaluationRequirementItemUpdate,
) -> EvaluationRequirementItemResponse:
    requirement_item = await _get_requirement_item_model_by_id(db, requirement_item_id)
    if requirement_item is None:
        raise ServiceNotFoundError("Evaluation requirement item not found")

    _ensure_evaluation_allows_requirement_definition(requirement_item.evaluation)
    updates = payload.model_dump(exclude_unset=True)
    changed = False

    if "requirement_key" in updates:
        next_key = _normalize_optional_string(updates["requirement_key"], "requirement_key", 100)
        if next_key != requirement_item.requirement_key:
            requirement_item.requirement_key = next_key
            changed = True

    if "requirement_section" in updates:
        next_section = _normalize_optional_string(updates["requirement_section"], "requirement_section", 250)
        if next_section != requirement_item.requirement_section:
            requirement_item.requirement_section = next_section
            changed = True

    if "requirement_text" in updates:
        if updates["requirement_text"] is None:
            raise ServiceValidationError("requirement_text cannot be null")
        next_text = _normalize_required_text(updates["requirement_text"], "requirement_text")
        if next_text != requirement_item.requirement_text:
            requirement_item.requirement_text = next_text
            changed = True

    if "requirement_order" in updates:
        next_order = _normalize_requirement_order(updates["requirement_order"])
        if next_order != requirement_item.requirement_order:
            requirement_item.requirement_order = next_order
            changed = True

    if "source_reference" in updates:
        next_source_reference = _normalize_optional_string(updates["source_reference"], "source_reference", 500)
        if next_source_reference != requirement_item.source_reference:
            requirement_item.source_reference = next_source_reference
            changed = True

    if not changed:
        return _build_requirement_item_response(requirement_item)

    modified_by = _normalize_optional_string(updates.get("modified_by"), "modified_by", 150)
    now = datetime.now(UTC)
    requirement_item.modified_by = modified_by
    requirement_item.modified_dt = now
    requirement_item.evaluation.modified_by = modified_by
    requirement_item.evaluation.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return _build_requirement_item_response(requirement_item)


async def delete_evaluation_requirement_item(
    db: AsyncSession,
    requirement_item_id: uuid.UUID,
) -> None:
    requirement_item = await _get_requirement_item_model_by_id(db, requirement_item_id)
    if requirement_item is None:
        raise ServiceNotFoundError("Evaluation requirement item not found")

    _ensure_evaluation_allows_requirement_definition(requirement_item.evaluation)
    requirement_item.evaluation.modified_dt = datetime.now(UTC)

    try:
        await db.delete(requirement_item)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete evaluation requirement item") from exc


async def get_supplier_response_requirement_matrix(
    db: AsyncSession,
    response_id: uuid.UUID,
) -> list[SupplierRequirementResponseMatrixRow]:
    response = await _get_response_model_by_id(db, response_id)
    if response is None:
        raise ServiceNotFoundError("Supplier response not found")

    stmt = (
        select(EvaluationRequirementItem, SupplierRequirementResponse)
        .outerjoin(
            SupplierRequirementResponse,
            and_(
                SupplierRequirementResponse.requirement_item_id == EvaluationRequirementItem.requirement_item_id,
                SupplierRequirementResponse.response_id == response.response_id,
            ),
        )
        .where(EvaluationRequirementItem.evaluation_id == response.evaluation_id)
        .order_by(EvaluationRequirementItem.requirement_order.asc().nulls_last(), EvaluationRequirementItem.created_dt.asc())
    )
    result = await db.execute(stmt)
    return [
        _build_requirement_matrix_row(
            requirement_item,
            response_id=response.response_id,
            requirement_response=requirement_response,
        )
        for requirement_item, requirement_response in result.all()
    ]


async def create_supplier_requirement_response(
    db: AsyncSession,
    response_id: uuid.UUID,
    payload: SupplierRequirementResponseCreate,
) -> SupplierRequirementResponseMatrixRow:
    response = await _get_response_model_by_id(db, response_id)
    if response is None:
        raise ServiceNotFoundError("Supplier response not found")

    _ensure_response_is_editable(response)
    requirement_item = await _get_requirement_item_model_by_id(db, payload.requirement_item_id)
    if requirement_item is None:
        raise ServiceNotFoundError("Evaluation requirement item not found")
    _ensure_requirement_item_belongs_to_response(requirement_item, response)

    existing = await _get_existing_requirement_response(
        db,
        response_id=response.response_id,
        requirement_item_id=requirement_item.requirement_item_id,
    )
    if existing is not None:
        raise ServiceConflictError("A structured response already exists for this requirement item")

    created_by = _normalize_optional_string(payload.created_by, "created_by", 150)
    fit_status = _normalize_fit_status(payload.fit_status, required=True)
    now = datetime.now(UTC)
    requirement_response = SupplierRequirementResponse(
        response_id=response.response_id,
        requirement_item_id=requirement_item.requirement_item_id,
        fit_status=fit_status or FIT_STATUS_MEETS,
        supplier_response_text=_strip_optional(payload.supplier_response_text),
        evidence_reference=_normalize_optional_string(payload.evidence_reference, "evidence_reference", 1000),
        notes=_strip_optional(payload.notes),
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(requirement_response)

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

    stored_response = await _get_requirement_response_model_by_id(db, requirement_response.requirement_response_id)
    if stored_response is None:
        raise ServiceConflictError("Supplier requirement response could not be loaded after creation")
    return _build_requirement_matrix_row(
        stored_response.requirement_item,
        response_id=stored_response.response_id,
        requirement_response=stored_response,
    )


async def update_supplier_requirement_response(
    db: AsyncSession,
    requirement_response_id: uuid.UUID,
    payload: SupplierRequirementResponseUpdate,
) -> SupplierRequirementResponseMatrixRow:
    requirement_response = await _get_requirement_response_model_by_id(db, requirement_response_id)
    if requirement_response is None:
        raise ServiceNotFoundError("Supplier requirement response not found")

    _ensure_response_is_editable(requirement_response.response)
    updates = payload.model_dump(exclude_unset=True)

    fit_status = requirement_response.fit_status
    if "fit_status" in updates:
        if updates["fit_status"] is None:
            raise ServiceValidationError("fit_status cannot be null")
        fit_status = _normalize_fit_status(updates["fit_status"], required=True) or requirement_response.fit_status

    supplier_response_text = (
        _strip_optional(updates["supplier_response_text"])
        if "supplier_response_text" in updates
        else requirement_response.supplier_response_text
    )
    evidence_reference = (
        _normalize_optional_string(updates["evidence_reference"], "evidence_reference", 1000)
        if "evidence_reference" in updates
        else requirement_response.evidence_reference
    )
    notes = _strip_optional(updates["notes"]) if "notes" in updates else requirement_response.notes

    modified_by = _normalize_optional_string(updates.get("modified_by"), "modified_by", 150)
    now = datetime.now(UTC)
    changed = _apply_requirement_response_fields(
        requirement_response,
        fit_status=fit_status,
        supplier_response_text=supplier_response_text,
        evidence_reference=evidence_reference,
        notes=notes,
        actor=modified_by,
        now=now,
    )

    if not changed:
        return _build_requirement_matrix_row(
            requirement_response.requirement_item,
            response_id=requirement_response.response_id,
            requirement_response=requirement_response,
        )

    requirement_response.response.modified_by = modified_by
    requirement_response.response.modified_dt = now
    if requirement_response.response.submission_status == RESPONSE_STATUS_NOT_STARTED:
        requirement_response.response.submission_status = RESPONSE_STATUS_IN_PROGRESS
    requirement_response.response.evaluation.modified_by = modified_by
    requirement_response.response.evaluation.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return _build_requirement_matrix_row(
        requirement_response.requirement_item,
        response_id=requirement_response.response_id,
        requirement_response=requirement_response,
    )


async def delete_supplier_requirement_response(
    db: AsyncSession,
    requirement_response_id: uuid.UUID,
) -> None:
    requirement_response = await _get_requirement_response_model_by_id(db, requirement_response_id)
    if requirement_response is None:
        raise ServiceNotFoundError("Supplier requirement response not found")

    _ensure_response_is_editable(requirement_response.response)
    now = datetime.now(UTC)
    requirement_response.response.modified_dt = now
    requirement_response.response.evaluation.modified_dt = now

    try:
        await db.delete(requirement_response)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete supplier requirement response") from exc


async def bulk_save_supplier_requirement_responses(
    db: AsyncSession,
    response_id: uuid.UUID,
    payload: SupplierRequirementResponseBulkSaveRequest,
) -> list[SupplierRequirementResponseMatrixRow]:
    response = await _get_response_model_by_id(db, response_id)
    if response is None:
        raise ServiceNotFoundError("Supplier response not found")

    _ensure_response_is_editable(response)
    if not payload.items:
        raise ServiceValidationError("items must contain at least one row")

    deduped_items: dict[uuid.UUID, SupplierRequirementResponseBulkSaveItem] = {}
    for item in payload.items:
        if item.requirement_item_id in deduped_items:
            raise ServiceValidationError("Duplicate requirement_item_id values are not allowed in bulk-save")
        deduped_items[item.requirement_item_id] = item

    requirement_item_ids = list(deduped_items.keys())
    stmt = select(EvaluationRequirementItem).where(
        EvaluationRequirementItem.evaluation_id == response.evaluation_id,
        EvaluationRequirementItem.requirement_item_id.in_(requirement_item_ids),
    )
    result = await db.execute(stmt)
    requirement_items = result.scalars().all()
    requirement_item_map = {
        requirement_item.requirement_item_id: requirement_item for requirement_item in requirement_items
    }
    missing_requirement_ids = [item_id for item_id in requirement_item_ids if item_id not in requirement_item_map]
    if missing_requirement_ids:
        raise ServiceValidationError("One or more requirement items do not belong to this supplier response")

    existing_stmt = select(SupplierRequirementResponse).where(
        SupplierRequirementResponse.response_id == response.response_id,
        SupplierRequirementResponse.requirement_item_id.in_(requirement_item_ids),
    )
    existing_result = await db.execute(existing_stmt)
    existing_map = {
        row.requirement_item_id: row for row in existing_result.scalars().all()
    }

    modified_by = _normalize_optional_string(payload.modified_by, "modified_by", 150)
    now = datetime.now(UTC)
    changed = False

    for requirement_item_id, item in deduped_items.items():
        fit_status = _normalize_fit_status(item.fit_status, required=False)
        supplier_response_text = _strip_optional(item.supplier_response_text)
        evidence_reference = _normalize_optional_string(item.evidence_reference, "evidence_reference", 1000)
        notes = _strip_optional(item.notes)
        has_any_value = any([fit_status, supplier_response_text, evidence_reference, notes])

        existing = existing_map.get(requirement_item_id)
        if not has_any_value:
            if existing is not None:
                await db.delete(existing)
                changed = True
            continue

        if fit_status is None:
            raise ServiceValidationError("fit_status is required when saving a structured requirement response")

        if existing is None:
            db.add(
                SupplierRequirementResponse(
                    response_id=response.response_id,
                    requirement_item_id=requirement_item_id,
                    fit_status=fit_status,
                    supplier_response_text=supplier_response_text,
                    evidence_reference=evidence_reference,
                    notes=notes,
                    created_by=modified_by,
                    created_dt=now,
                    modified_by=modified_by,
                    modified_dt=now,
                )
            )
            changed = True
            continue

        changed = (
            _apply_requirement_response_fields(
                existing,
                fit_status=fit_status,
                supplier_response_text=supplier_response_text,
                evidence_reference=evidence_reference,
                notes=notes,
                actor=modified_by,
                now=now,
            )
            or changed
        )

    if changed:
        response.modified_by = modified_by
        response.modified_dt = now
        if response.submission_status == RESPONSE_STATUS_NOT_STARTED:
            response.submission_status = RESPONSE_STATUS_IN_PROGRESS
        response.evaluation.modified_by = modified_by
        response.evaluation.modified_dt = now

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_supplier_response_requirement_matrix(db, response.response_id)
