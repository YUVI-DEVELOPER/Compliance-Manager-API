import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from itertools import groupby
from urllib.parse import unquote, urlparse
from zipfile import BadZipFile, ZipFile
import xml.etree.ElementTree as ET

from fastapi import HTTPException, status
from sqlalchemy import Select, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.asset import Asset
from app.models.asset_release import AssetRelease
from app.models.asset_spec import AssetSpec
from app.models.authored_document import AuthoredDocument
from app.models.authored_document_review_action import AuthoredDocumentReviewAction
from app.models.document_template import DocumentTemplate
from app.models.lookup_master import LookupMaster
from app.models.lookup_value import LookupValue
from app.schemas.authored_document_schema import (
    AuthoredDocumentAiRegenerateRequest,
    AuthoredDocumentCommentRequest,
    AuthoredDocumentCreateAiDraftRequest,
    AuthoredDocumentCreateFromTemplateRequest,
    AuthoredDocumentReviewActionResponse,
    AuthoredDocumentResponse,
    AuthoredDocumentUpdate,
    AuthoredDocumentWorkflowActionRequest,
    DocumentTemplateCreate,
    DocumentTemplateResponse,
    DocumentTemplateUpdate,
)
from app.services.urs_generation_service import (
    GENERATION_MODE_AI_ASSISTED,
    GENERATION_MODE_TEMPLATE_PREFILL,
    GENERATION_OPERATION_CREATE,
    append_generation_metadata,
    build_generation_metadata,
    carry_forward_generation_history,
    extract_generation_metadata,
    generate_ai_urs_draft,
    get_generation_inputs,
    sanitize_urs_generation_failure_reason,
    UrsGenerationError,
    UrsGenerationUnavailableError,
)

ASSET_CLASS_LOOKUP_KEY = "ASSET_CLASS"
ASSET_CATEGORY_LOOKUP_KEY = "ASSET_CATEGORY"
ASSET_SUB_CATEGORY_LOOKUP_KEY = "ASSET_SUB_CATEGORY"
ASSET_TYPE_LOOKUP_KEY = "ASSET_TYPE"
CRITICALITY_CLASS_LOOKUP_KEY = "CRITICALITY_CLASS"
LEGACY_CRITICALITY_LOOKUP_KEY = "ASSET_CRITICALITY"
ASSET_NATURE_LOOKUP_KEY = "ASSET_NATURE"
ASSET_STATUS_LOOKUP_KEY = "ASSET_STATUS"
AUTHORED_DOCUMENT_TYPE_URS = "URS"
AUTHORED_DOCUMENT_STATUS_DRAFT = "DRAFT"
AUTHORED_DOCUMENT_STATUS_IN_REVIEW = "IN_REVIEW"
AUTHORED_DOCUMENT_STATUS_CHANGES_REQUESTED = "CHANGES_REQUESTED"
AUTHORED_DOCUMENT_STATUS_APPROVED = "APPROVED"
AUTHORED_DOCUMENT_STATUS_REJECTED = "REJECTED"
AUTHORED_DOCUMENT_PUBLISH_STATUS_NOT_PUBLISHED = "NOT_PUBLISHED"
ALLOWED_AUTHORED_DOCUMENT_STATUSES = {
    AUTHORED_DOCUMENT_STATUS_DRAFT,
    AUTHORED_DOCUMENT_STATUS_IN_REVIEW,
    AUTHORED_DOCUMENT_STATUS_CHANGES_REQUESTED,
    AUTHORED_DOCUMENT_STATUS_APPROVED,
    AUTHORED_DOCUMENT_STATUS_REJECTED,
}
EDITABLE_AUTHORED_DOCUMENT_STATUSES = {
    AUTHORED_DOCUMENT_STATUS_DRAFT,
    AUTHORED_DOCUMENT_STATUS_CHANGES_REQUESTED,
}
SUBMITTABLE_AUTHORED_DOCUMENT_STATUSES = {
    AUTHORED_DOCUMENT_STATUS_DRAFT,
    AUTHORED_DOCUMENT_STATUS_CHANGES_REQUESTED,
}
REVIEWABLE_AUTHORED_DOCUMENT_STATUSES = {
    AUTHORED_DOCUMENT_STATUS_IN_REVIEW,
}
AUTHORED_DOCUMENT_ACTION_SUBMIT_FOR_REVIEW = "SUBMIT_FOR_REVIEW"
AUTHORED_DOCUMENT_ACTION_REQUEST_CHANGES = "REQUEST_CHANGES"
AUTHORED_DOCUMENT_ACTION_APPROVE = "APPROVE"
AUTHORED_DOCUMENT_ACTION_REJECT = "REJECT"
AUTHORED_DOCUMENT_ACTION_COMMENT = "COMMENT"
TEMPLATE_PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")
ADDITIONAL_NOTES_SECTION_PATTERN = re.compile(
    r"\n?##\s+Additional Notes\s*\n.*?(?=\n##\s+|\Z)",
    re.IGNORECASE | re.DOTALL,
)
SOURCE_URS_TEXT_LIMIT = 50000
SOURCE_URS_PROMPT_LIMIT = 25000
TEXT_SOURCE_DOCUMENT_EXTENSIONS = {".csv", ".json", ".md", ".rtf", ".txt", ".xml"}
DOCX_TEXT_NAMESPACES = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
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


class ServiceUnavailableError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


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


def _truncate_text(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return f"{value[:max_len].rstrip()}\n\n[Truncated to {max_len} characters for draft generation.]"


def _normalize_source_text(value: str | None) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    return _truncate_text(normalized.replace("\r\n", "\n").replace("\r", "\n"), SOURCE_URS_TEXT_LIMIT)


def _relative_upload_path_from_url(value: str | None) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None

    parsed = urlparse(normalized)
    path = unquote(parsed.path or "")
    marker = "/uploads/"
    marker_index = path.find(marker)
    if marker_index < 0:
        return None
    return path[marker_index + len(marker):].lstrip("/")


def _resolve_uploaded_document_path(relative_path: str | None, access_url: str | None) -> Path | None:
    candidate = _strip_optional(relative_path) or _relative_upload_path_from_url(access_url)
    if candidate is None:
        return None

    settings = get_settings()
    upload_root = Path(settings.FILE_UPLOAD_DIR).resolve()
    resolved = (upload_root / candidate).resolve()
    try:
        resolved.relative_to(upload_root)
    except ValueError:
        return None
    return resolved if resolved.is_file() else None


def _extract_docx_text(path: Path) -> str | None:
    try:
        with ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError, OSError):
        return None

    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError:
        return None

    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", DOCX_TEXT_NAMESPACES):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{{{DOCX_TEXT_NAMESPACES['w']}}}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{{{DOCX_TEXT_NAMESPACES['w']}}}tab":
                parts.append("\t")
            elif node.tag == f"{{{DOCX_TEXT_NAMESPACES['w']}}}br":
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)

    return "\n".join(paragraphs).strip() or None


def _extract_plain_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None

    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        normalized = decoded.strip()
        if normalized:
            return normalized
    return None


def _extract_source_document_text(relative_path: str | None, access_url: str | None) -> tuple[str | None, str]:
    path = _resolve_uploaded_document_path(relative_path, access_url)
    if path is None:
        return None, "not_available"

    suffix = path.suffix.lower()
    if suffix == ".docx":
        extracted = _extract_docx_text(path)
        return _normalize_source_text(extracted), "extracted_docx" if extracted else "docx_extract_failed"

    if suffix in TEXT_SOURCE_DOCUMENT_EXTENSIONS:
        extracted = _extract_plain_text(path)
        return _normalize_source_text(extracted), "extracted_text" if extracted else "text_extract_failed"

    return None, f"unsupported_{suffix.lstrip('.') or 'file'}"


def _append_source_urs_section(
    content: str,
    *,
    source_text: str | None,
    source_document_name: str | None,
    source_document_url: str | None,
) -> str:
    normalized_text = _normalize_source_text(source_text)
    if normalized_text is None:
        return content

    source_label = source_document_name or source_document_url or "Attached URS source"
    section = "\n\n".join(
        [
            "## Source URS Requirements",
            f"Source: {source_label}",
            "The following content was supplied from an attached or pasted asset URS and should be reviewed before approval.",
            normalized_text,
        ]
    )
    return f"{content.rstrip()}\n\n{section}".strip()


def _get_source_urs_context(source_context: dict | None) -> dict[str, str | None]:
    source_urs = source_context.get("source_urs") if isinstance(source_context, dict) else None
    source_map = source_urs if isinstance(source_urs, dict) else {}

    def read_string(key: str) -> str | None:
        value = source_map.get(key)
        return _strip_optional(value) if isinstance(value, str) else None

    return {
        "source_document_url": read_string("document_url"),
        "source_document_name": read_string("document_name"),
        "source_document_relative_path": read_string("relative_path"),
        "source_urs_text": read_string("text"),
    }


def _normalize_document_type(value: str | None, field_name: str = "document_type") -> str:
    return _normalize_required(value, field_name, 50).upper()


def _normalize_status(value: str | None) -> str:
    normalized = _normalize_document_type(value, "status")
    if normalized not in ALLOWED_AUTHORED_DOCUMENT_STATUSES:
        allowed = ", ".join(sorted(ALLOWED_AUTHORED_DOCUMENT_STATUSES))
        raise ServiceValidationError(f"status must be one of: {allowed}")
    return normalized


def _normalize_comment_text(value: str | None, *, required: bool = False) -> str | None:
    normalized = _normalize_optional_string(value, "comment_text", 5000)
    if required and normalized is None:
        raise ServiceValidationError("comment_text is required")
    return normalized


def _document_template_query() -> Select[tuple[DocumentTemplate]]:
    return select(DocumentTemplate)


def _authored_document_query() -> Select[tuple[AuthoredDocument]]:
    return select(AuthoredDocument).options(
        selectinload(AuthoredDocument.template),
        selectinload(AuthoredDocument.asset).selectinload(Asset.org_node),
        selectinload(AuthoredDocument.asset).selectinload(Asset.supplier),
        selectinload(AuthoredDocument.release)
        .selectinload(AssetRelease.asset)
        .selectinload(Asset.org_node),
        selectinload(AuthoredDocument.release)
        .selectinload(AssetRelease.asset)
        .selectinload(Asset.supplier),
    )


def _authored_document_review_action_query() -> Select[tuple[AuthoredDocumentReviewAction]]:
    return select(AuthoredDocumentReviewAction)


async def _get_document_template_model_by_id(
    db: AsyncSession,
    template_id: uuid.UUID,
) -> DocumentTemplate | None:
    result = await db.execute(_document_template_query().where(DocumentTemplate.template_id == template_id))
    return result.scalars().first()


async def _get_document_template_model_by_code(
    db: AsyncSession,
    template_code: str,
) -> DocumentTemplate | None:
    normalized_code = template_code.strip().upper()
    result = await db.execute(_document_template_query().where(DocumentTemplate.template_code == normalized_code))
    return result.scalars().first()


async def _get_authored_document_model_by_id(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
) -> AuthoredDocument | None:
    result = await db.execute(
        _authored_document_query().where(AuthoredDocument.authored_document_id == authored_document_id)
    )
    return result.scalars().first()


async def _get_asset_model_by_id(db: AsyncSession, asset_id: uuid.UUID) -> Asset | None:
    stmt = (
        select(Asset)
        .options(selectinload(Asset.org_node), selectinload(Asset.supplier))
        .where(Asset.asset_uuid == asset_id)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_release_model_by_id(db: AsyncSession, release_id: uuid.UUID) -> AssetRelease | None:
    stmt = (
        select(AssetRelease)
        .options(
            selectinload(AssetRelease.asset).selectinload(Asset.org_node),
            selectinload(AssetRelease.asset).selectinload(Asset.supplier),
        )
        .where(AssetRelease.release_id == release_id)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_asset_sub_category_lookup(db: AsyncSession, sub_category_code: str | None) -> LookupValue | None:
    normalized_code = _strip_optional(sub_category_code)
    if normalized_code is None:
        return None

    stmt = (
        select(LookupValue)
        .join(LookupMaster, LookupValue.lookup_id == LookupMaster.id)
        .where(
            LookupMaster.lookup_key == ASSET_SUB_CATEGORY_LOOKUP_KEY,
            LookupValue.code == normalized_code.upper(),
        )
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_asset_specs_for_sub_category_id(
    db: AsyncSession,
    asset_sub_category_id: int,
) -> list[AssetSpec]:
    stmt = (
        select(AssetSpec)
        .where(
            AssetSpec.asset_sub_category_id == asset_sub_category_id,
            AssetSpec.is_active.is_(True),
        )
        .order_by(AssetSpec.parameter_grouping.asc(), AssetSpec.parameter_seq.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _get_lookup_display_names(
    db: AsyncSession,
    lookup_pairs: set[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    if not lookup_pairs:
        return {}

    stmt = (
        select(LookupMaster.lookup_key, LookupValue.code, LookupValue.display_name)
        .join(LookupValue, LookupValue.lookup_id == LookupMaster.id)
        .where(tuple_(LookupMaster.lookup_key, LookupValue.code).in_(lookup_pairs))
    )
    result = await db.execute(stmt)
    return {(lookup_key, code): display_name for lookup_key, code, display_name in result.all()}


def _build_document_template_response(template: DocumentTemplate) -> DocumentTemplateResponse:
    return DocumentTemplateResponse(
        template_id=template.template_id,
        template_code=template.template_code,
        template_name=template.template_name,
        document_type=template.document_type,
        template_content=_strip_additional_notes_section(template.template_content),
        is_active=template.is_active,
        created_by=template.created_by,
        created_dt=template.created_dt,
        modified_by=template.modified_by,
        modified_dt=template.modified_dt,
    )


def _build_authored_document_response(document: AuthoredDocument) -> AuthoredDocumentResponse:
    release = document.release
    asset = document.asset or (release.asset if release is not None else None)
    generation_metadata = extract_generation_metadata(document.source_context_json)

    return AuthoredDocumentResponse(
        authored_document_id=document.authored_document_id,
        document_type=document.document_type,
        title=document.title,
        status=document.status,
        asset_id=document.asset_id,
        release_id=document.release_id,
        template_id=document.template_id,
        template_code=document.template.template_code if document.template is not None else None,
        template_name=document.template.template_name if document.template is not None else None,
        content=document.content,
        source_context_json=document.source_context_json,
        created_by=document.created_by,
        created_dt=document.created_dt,
        modified_by=document.modified_by,
        modified_dt=document.modified_dt,
        reviewer_name=document.reviewer_name,
        approver_name=document.approver_name,
        publish_status=document.publish_status,
        last_publish_attempt_at=document.last_publish_attempt_at,
        last_publish_attempt_by=document.last_publish_attempt_by,
        published_at=document.published_at,
        published_by=document.published_by,
        external_system=document.external_system,
        external_document_id=document.external_document_id,
        external_document_name=document.external_document_name,
        external_document_version=document.external_document_version,
        external_document_url=document.external_document_url,
        external_source_reference=document.external_source_reference,
        publish_error_message=document.publish_error_message,
        asset_name=asset.asset_name if asset is not None else None,
        asset_code=asset.asset_id if asset is not None else None,
        release_version=release.version if release is not None else None,
        generation_mode=generation_metadata["generation_mode"],
        generation_requested_mode=generation_metadata["generation_requested_mode"],
        generation_status=generation_metadata["generation_status"],
        generation_operation=generation_metadata["generation_operation"],
        generation_provider=generation_metadata["generation_provider"],
        generation_model=generation_metadata["generation_model"],
        generation_fallback_reason=generation_metadata["generation_fallback_reason"],
        last_generated_at=generation_metadata["last_generated_at"],
    )


def _build_authored_document_review_action_response(
    action: AuthoredDocumentReviewAction,
) -> AuthoredDocumentReviewActionResponse:
    return AuthoredDocumentReviewActionResponse(
        id=action.id,
        authored_document_id=action.authored_document_id,
        action_type=action.action_type,
        action_by=action.action_by,
        action_dt=action.action_dt,
        comment_text=action.comment_text,
        from_status=action.from_status,
        to_status=action.to_status,
    )


def _conflict_message_from_template_integrity_error(exc: IntegrityError) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    if "uq_document_template_code" in message or "template_code" in message:
        return "template_code already exists"
    if "fk_authored_document_template" in message:
        return "Template is in use by authored documents and cannot be deleted"
    return "Operation failed due to a data conflict"


def _conflict_message_from_authored_document_integrity_error(exc: IntegrityError) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    if "chk_authored_document_exactly_one_target" in message:
        return "Exactly one target must be set for an authored document"
    if "chk_authored_document_status" in message:
        allowed = ", ".join(sorted(ALLOWED_AUTHORED_DOCUMENT_STATUSES))
        return f"status must be one of: {allowed}"
    if "chk_authored_document_publish_status" in message:
        return "publish_status must be one of: NOT_PUBLISHED, PUBLISH_PENDING, PUBLISHED, PUBLISH_FAILED"
    if "fk_authored_document_template" in message:
        return "template_id references an unknown template"
    return "Operation failed due to a data conflict"


def _ensure_document_is_editable(status: str) -> None:
    if status == AUTHORED_DOCUMENT_STATUS_APPROVED:
        raise ServiceConflictError("Approved documents are read-only and cannot be edited")
    if status not in EDITABLE_AUTHORED_DOCUMENT_STATUSES:
        raise ServiceConflictError("Only documents in DRAFT or CHANGES_REQUESTED can be edited")


def _ensure_document_can_be_submitted(status: str) -> None:
    if status not in SUBMITTABLE_AUTHORED_DOCUMENT_STATUSES:
        raise ServiceConflictError("Only documents in DRAFT or CHANGES_REQUESTED can be submitted for review")


def _ensure_document_is_in_review(status: str, *, action_label: str) -> None:
    if status not in REVIEWABLE_AUTHORED_DOCUMENT_STATUSES:
        raise ServiceConflictError(f"Only documents in IN_REVIEW can be {action_label}")


async def _create_authored_document_review_action(
    db: AsyncSession,
    *,
    document: AuthoredDocument,
    action_type: str,
    action_by: str | None,
    comment_text: str | None,
    to_status: str,
    reviewer_name: str | None = None,
    approver_name: str | None = None,
) -> AuthoredDocumentReviewAction:
    action_dt = datetime.now(UTC)
    from_status = document.status

    if reviewer_name is not None:
        document.reviewer_name = reviewer_name
    if approver_name is not None:
        document.approver_name = approver_name
    if to_status != document.status:
        document.status = to_status
    if action_by is not None:
        document.modified_by = action_by
    document.modified_dt = action_dt

    action = AuthoredDocumentReviewAction(
        authored_document_id=document.authored_document_id,
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
        raise ServiceConflictError(_conflict_message_from_authored_document_integrity_error(exc)) from exc

    return action


def _lookup_label(
    labels: dict[tuple[str, str], str],
    code: str | None,
    *lookup_keys: str,
) -> str:
    normalized_code = _strip_optional(code)
    if normalized_code is None:
        return ""

    upper_code = normalized_code.upper()
    for lookup_key in lookup_keys:
        label = labels.get((lookup_key, upper_code))
        if label:
            return label
    return normalized_code


def _format_release_context(release: AssetRelease | None) -> str:
    if release is None:
        return "This URS draft is linked at the asset level and is not scoped to a specific release."

    lines = [
        f"- Release Version: {release.version}",
        f"- Release Created Date: {release.created_dt.date().isoformat() if release.created_dt else 'Not specified'}",
        f"- Release End Date: {release.end_dt.date().isoformat() if release.end_dt else 'Open'}",
    ]
    documentation_mode = _strip_optional(release.documentation_mode)
    if documentation_mode:
        lines.append(f"- Documentation Mode: {documentation_mode}")
    return "\n".join(lines)


def _format_asset_specs_summary(specs: list[AssetSpec]) -> str:
    if not specs:
        return "No active asset specifications are configured for this asset sub-category."

    lines: list[str] = []
    for grouping, group_specs in groupby(specs, key=lambda spec: spec.parameter_grouping):
        lines.append(f"### {grouping}")
        for spec in group_specs:
            line = f"- {spec.parameter_name}: {spec.parameter_value}"
            if spec.guidelines:
                line = f"{line} (Guidance: {spec.guidelines})"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip()


def _build_default_purpose(asset: Asset, release: AssetRelease | None) -> str:
    asset_reference = asset.asset_name or asset.asset_id
    if release is None:
        return f"Define the user requirements for {asset_reference} using current asset master and specification data."
    return (
        f"Define the user requirements for {asset_reference} in the context of release {release.version}, "
        "using current asset master and specification data."
    )


def _build_default_scope(asset: Asset, release: AssetRelease | None) -> str:
    asset_reference = asset.asset_name or asset.asset_id
    if release is None:
        return f"This URS applies to the lifecycle, controls, and supporting specifications for {asset_reference}."
    return (
        f"This URS applies to {asset_reference} and the release-scoped changes for version {release.version}, "
        "including applicable configuration and specification expectations."
    )


def _generate_document_title(
    document_type: str,
    asset: Asset,
    release: AssetRelease | None,
) -> str:
    asset_reference = asset.asset_name or asset.asset_id
    if release is None:
        return f"{document_type} - {asset_reference}"
    return f"{document_type} - {asset_reference} - Release {release.version}"


def _strip_additional_notes_section(template_content: str) -> str:
    normalized_template = template_content.replace("\r\n", "\n").replace("\r", "\n")
    return ADDITIONAL_NOTES_SECTION_PATTERN.sub("\n", normalized_template).strip()


def _merge_template_content(template_content: str, context: dict[str, str]) -> str:
    normalized_template = _strip_additional_notes_section(template_content)

    def replace_match(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "additional_notes":
            return ""
        return context.get(key, "")

    return TEMPLATE_PLACEHOLDER_PATTERN.sub(replace_match, normalized_template).strip()


async def _build_prefill_payload(
    db: AsyncSession,
    *,
    document_type: str,
    template: DocumentTemplate,
    asset: Asset,
    release: AssetRelease | None,
    title: str | None,
    purpose_notes: str | None,
    special_instructions: str | None,
    additional_notes: str | None,
    source_document_url: str | None = None,
    source_document_name: str | None = None,
    source_document_relative_path: str | None = None,
    source_urs_text: str | None = None,
) -> tuple[str, str, dict, list[AssetSpec]]:
    lookup_pairs: set[tuple[str, str]] = set()
    for lookup_key, code in (
        (ASSET_CLASS_LOOKUP_KEY, asset.asset_class),
        (ASSET_CATEGORY_LOOKUP_KEY, asset.asset_category),
        (ASSET_SUB_CATEGORY_LOOKUP_KEY, asset.asset_sub_category),
        (ASSET_TYPE_LOOKUP_KEY, asset.asset_type),
        (ASSET_NATURE_LOOKUP_KEY, asset.asset_nature),
        (ASSET_STATUS_LOOKUP_KEY, asset.asset_status),
        (CRITICALITY_CLASS_LOOKUP_KEY, asset.criticality_class),
        (LEGACY_CRITICALITY_LOOKUP_KEY, asset.criticality_class),
    ):
        normalized_code = _strip_optional(code)
        if normalized_code is not None:
            lookup_pairs.add((lookup_key, normalized_code.upper()))

    lookup_labels = await _get_lookup_display_names(db, lookup_pairs)
    asset_sub_category_lookup = await _get_asset_sub_category_lookup(db, asset.asset_sub_category)
    specs = (
        await _get_asset_specs_for_sub_category_id(db, asset_sub_category_lookup.id)
        if asset_sub_category_lookup is not None
        else []
    )

    resolved_title = _normalize_optional_string(title, "title", 250) or _generate_document_title(
        document_type,
        asset,
        release,
    )
    resolved_purpose = _strip_optional(purpose_notes) or _build_default_purpose(asset, release)
    resolved_scope = _build_default_scope(asset, release)
    generated_on = datetime.now(UTC)
    asset_specs_summary = _format_asset_specs_summary(specs)
    normalized_source_document_url = _strip_optional(source_document_url)
    normalized_source_document_name = _normalize_optional_string(source_document_name, "source_document_name", 250)
    normalized_source_relative_path = _normalize_optional_string(
        source_document_relative_path,
        "source_document_relative_path",
        1000,
    )
    normalized_source_text = _normalize_source_text(source_urs_text)
    extraction_status = "pasted" if normalized_source_text is not None else "none"
    if normalized_source_text is None and (
        normalized_source_relative_path is not None or normalized_source_document_url is not None
    ):
        normalized_source_text, extraction_status = _extract_source_document_text(
            normalized_source_relative_path,
            normalized_source_document_url,
        )
    source_context_text = (
        _truncate_text(normalized_source_text, SOURCE_URS_PROMPT_LIMIT)
        if normalized_source_text is not None
        else ""
    )

    template_context = {
        "document_title": resolved_title,
        "document_type": document_type,
        "status": AUTHORED_DOCUMENT_STATUS_DRAFT,
        "template_name": template.template_name,
        "template_code": template.template_code,
        "generated_on": generated_on.strftime("%Y-%m-%d %H:%M UTC"),
        "purpose": resolved_purpose,
        "scope": resolved_scope,
        "asset_name": asset.asset_name or "",
        "asset_id": asset.asset_id,
        "asset_code": asset.asset_id,
        "asset_description": asset.asset_description or "",
        "short_description": asset.short_description or "",
        "asset_owner": asset.asset_owner or "",
        "organization_name": asset.org_node.name if asset.org_node is not None else "",
        "supplier_name": asset.supplier.supplier_name if asset.supplier is not None else "",
        "manufacturer": asset.manufacturer or "",
        "model": asset.model or "",
        "asset_version": asset.asset_version or "",
        "asset_class": _lookup_label(lookup_labels, asset.asset_class, ASSET_CLASS_LOOKUP_KEY),
        "asset_category": _lookup_label(lookup_labels, asset.asset_category, ASSET_CATEGORY_LOOKUP_KEY),
        "asset_sub_category": _lookup_label(lookup_labels, asset.asset_sub_category, ASSET_SUB_CATEGORY_LOOKUP_KEY),
        "asset_type": _lookup_label(lookup_labels, asset.asset_type, ASSET_TYPE_LOOKUP_KEY),
        "criticality_class": _lookup_label(
            lookup_labels,
            asset.criticality_class,
            CRITICALITY_CLASS_LOOKUP_KEY,
            LEGACY_CRITICALITY_LOOKUP_KEY,
        ),
        "asset_nature": _lookup_label(lookup_labels, asset.asset_nature, ASSET_NATURE_LOOKUP_KEY),
        "asset_status": _lookup_label(lookup_labels, asset.asset_status, ASSET_STATUS_LOOKUP_KEY),
        "release_context": _format_release_context(release),
        "release_version": release.version if release is not None else "",
        "asset_specs_summary": asset_specs_summary,
        "source_urs_text": source_context_text,
        "source_urs_reference": normalized_source_document_name or normalized_source_document_url or "",
    }
    content = _merge_template_content(template.template_content, template_context)
    content = _append_source_urs_section(
        content,
        source_text=normalized_source_text,
        source_document_name=normalized_source_document_name,
        source_document_url=normalized_source_document_url,
    )

    source_context = {
        "template": {
            "template_id": str(template.template_id),
            "template_code": template.template_code,
            "template_name": template.template_name,
            "document_type": template.document_type,
        },
        "target": {
            "type": "release" if release is not None else "asset",
            "asset_id": str(asset.asset_uuid),
            "release_id": str(release.release_id) if release is not None else None,
        },
        "merge_inputs": {
            "title": resolved_title,
            "purpose_notes": _strip_optional(purpose_notes),
            "special_instructions": _strip_optional(special_instructions),
            "source_document_url": normalized_source_document_url,
            "source_document_name": normalized_source_document_name,
            "source_document_relative_path": normalized_source_relative_path,
            "source_urs_text_present": normalized_source_text is not None,
            "source_urs_extraction_status": extraction_status,
            "generated_on": generated_on.isoformat(),
        },
        "source_urs": {
            "document_url": normalized_source_document_url,
            "document_name": normalized_source_document_name,
            "relative_path": normalized_source_relative_path,
            "text": normalized_source_text,
            "text_present": normalized_source_text is not None,
            "extraction_status": extraction_status,
        },
        "asset": {
            "asset_uuid": str(asset.asset_uuid),
            "asset_id": asset.asset_id,
            "asset_name": asset.asset_name,
            "asset_description": asset.asset_description,
            "short_description": asset.short_description,
            "asset_owner": asset.asset_owner,
            "manufacturer": asset.manufacturer,
            "model": asset.model,
            "asset_version": asset.asset_version,
            "asset_class": template_context["asset_class"],
            "asset_category": template_context["asset_category"],
            "asset_sub_category": template_context["asset_sub_category"],
            "asset_type": template_context["asset_type"],
            "criticality_class": template_context["criticality_class"],
            "asset_nature": template_context["asset_nature"],
            "asset_status": template_context["asset_status"],
            "organization_name": template_context["organization_name"],
            "supplier_name": template_context["supplier_name"],
        },
        "release": (
            {
                "release_id": str(release.release_id),
                "version": release.version,
                "created_dt": release.created_dt.isoformat() if release.created_dt is not None else None,
                "end_dt": release.end_dt.isoformat() if release.end_dt is not None else None,
                "documentation_mode": release.documentation_mode,
                "system_config_report_present": bool(_strip_optional(release.system_config_report)),
                "documentation_text_present": bool(_strip_optional(release.documentation_text)),
            }
            if release is not None
            else None
        ),
        "asset_specs": [
            {
                "asset_spec_id": str(spec.asset_spec_id),
                "parameter_seq": spec.parameter_seq,
                "parameter_grouping": spec.parameter_grouping,
                "parameter_name": spec.parameter_name,
                "parameter_value": spec.parameter_value,
                "guidelines": spec.guidelines,
            }
            for spec in specs
        ],
    }

    return resolved_title, content, source_context, specs


async def _resolve_target_context(
    db: AsyncSession,
    *,
    asset_id: uuid.UUID | None,
    release_id: uuid.UUID | None,
) -> tuple[Asset, AssetRelease | None]:
    if asset_id is not None:
        asset = await _get_asset_model_by_id(db, asset_id)
        if asset is None:
            raise ServiceNotFoundError("Asset not found")
        return asset, None

    if release_id is not None:
        release = await _get_release_model_by_id(db, release_id)
        if release is None:
            raise ServiceNotFoundError("Release not found")
        if release.asset is None:
            raise ServiceConflictError("Release is not linked to a valid asset")
        return release.asset, release

    raise ServiceValidationError("Exactly one target must be provided")


async def get_document_templates(
    db: AsyncSession,
    *,
    document_type: str | None = None,
    active_only: bool = True,
) -> list[DocumentTemplateResponse]:
    stmt = _document_template_query()
    if active_only:
        stmt = stmt.where(DocumentTemplate.is_active.is_(True))
    if document_type is not None:
        stmt = stmt.where(DocumentTemplate.document_type == _normalize_document_type(document_type))
    stmt = stmt.order_by(DocumentTemplate.document_type.asc(), DocumentTemplate.template_name.asc())

    result = await db.execute(stmt)
    return [_build_document_template_response(template) for template in result.scalars().all()]


async def get_document_template_by_id(db: AsyncSession, template_id: uuid.UUID) -> DocumentTemplateResponse:
    template = await _get_document_template_model_by_id(db, template_id)
    if template is None:
        raise ServiceNotFoundError("Document template not found")
    return _build_document_template_response(template)


async def get_document_template_by_code(db: AsyncSession, template_code: str) -> DocumentTemplateResponse:
    template = await _get_document_template_model_by_code(db, template_code)
    if template is None:
        raise ServiceNotFoundError("Document template not found")
    return _build_document_template_response(template)


async def create_document_template(
    db: AsyncSession,
    payload: DocumentTemplateCreate,
) -> DocumentTemplateResponse:
    now = datetime.now(UTC)
    template = DocumentTemplate(
        template_code=_normalize_required(payload.template_code, "template_code", 100).upper(),
        template_name=_normalize_required(payload.template_name, "template_name", 150),
        document_type=_normalize_document_type(payload.document_type),
        template_content=_normalize_required_text(payload.template_content, "template_content"),
        is_active=payload.is_active,
        created_by=_strip_optional(payload.created_by),
        created_dt=now,
        modified_by=_strip_optional(payload.created_by),
        modified_dt=now,
    )
    db.add(template)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_template_integrity_error(exc)) from exc

    return await get_document_template_by_id(db, template.template_id)


async def update_document_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    payload: DocumentTemplateUpdate,
) -> DocumentTemplateResponse:
    template = await _get_document_template_model_by_id(db, template_id)
    if template is None:
        raise ServiceNotFoundError("Document template not found")

    updates = payload.model_dump(exclude_unset=True)
    if "template_code" in updates and updates["template_code"] is not None:
        template.template_code = _normalize_required(updates["template_code"], "template_code", 100).upper()
    if "template_name" in updates and updates["template_name"] is not None:
        template.template_name = _normalize_required(updates["template_name"], "template_name", 150)
    if "document_type" in updates and updates["document_type"] is not None:
        template.document_type = _normalize_document_type(updates["document_type"])
    if "template_content" in updates and updates["template_content"] is not None:
        template.template_content = _normalize_required_text(updates["template_content"], "template_content")
    if "is_active" in updates and updates["is_active"] is not None:
        template.is_active = updates["is_active"]
    if "modified_by" in updates:
        template.modified_by = _normalize_optional_string(updates["modified_by"], "modified_by", 150)

    template.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_template_integrity_error(exc)) from exc

    return await get_document_template_by_id(db, template.template_id)


async def delete_document_template(db: AsyncSession, template_id: uuid.UUID) -> None:
    template = await _get_document_template_model_by_id(db, template_id)
    if template is None:
        raise ServiceNotFoundError("Document template not found")

    try:
        await db.delete(template)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_template_integrity_error(exc)) from exc


async def get_authored_documents_by_asset(
    db: AsyncSession,
    asset_id: uuid.UUID,
) -> list[AuthoredDocumentResponse]:
    asset = await _get_asset_model_by_id(db, asset_id)
    if asset is None:
        raise ServiceNotFoundError("Asset not found")

    stmt = (
        _authored_document_query()
        .where(AuthoredDocument.asset_id == asset_id)
        .order_by(AuthoredDocument.modified_dt.desc(), AuthoredDocument.created_dt.desc(), AuthoredDocument.title.asc())
    )
    result = await db.execute(stmt)
    return [_build_authored_document_response(document) for document in result.scalars().all()]


async def get_authored_documents_by_release(
    db: AsyncSession,
    release_id: uuid.UUID,
) -> list[AuthoredDocumentResponse]:
    release = await _get_release_model_by_id(db, release_id)
    if release is None:
        raise ServiceNotFoundError("Release not found")

    stmt = (
        _authored_document_query()
        .where(AuthoredDocument.release_id == release_id)
        .order_by(AuthoredDocument.modified_dt.desc(), AuthoredDocument.created_dt.desc(), AuthoredDocument.title.asc())
    )
    result = await db.execute(stmt)
    return [_build_authored_document_response(document) for document in result.scalars().all()]


async def get_authored_document_by_id(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
) -> AuthoredDocumentResponse:
    document = await _get_authored_document_model_by_id(db, authored_document_id)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")
    return _build_authored_document_response(document)


async def _resolve_template_for_document_request(
    db: AsyncSession,
    *,
    document_type: str,
    template_id: uuid.UUID | None,
    template_code: str | None,
) -> tuple[str, DocumentTemplate]:
    normalized_document_type = _normalize_document_type(document_type)
    if normalized_document_type != AUTHORED_DOCUMENT_TYPE_URS:
        raise ServiceValidationError("Only URS authored documents are supported in this phase")

    template = (
        await _get_document_template_model_by_id(db, template_id)
        if template_id is not None
        else await _get_document_template_model_by_code(db, template_code or "")
    )
    if template is None:
        raise ServiceNotFoundError("Document template not found")
    if not template.is_active:
        raise ServiceValidationError("Template must be active to create a draft")
    if _normalize_document_type(template.document_type) != normalized_document_type:
        raise ServiceValidationError("Selected template does not match the requested document_type")

    return normalized_document_type, template


def _build_template_prefill_generation_event(
    *,
    requested_mode: str,
    operation: str,
    purpose_notes: str | None,
    special_instructions: str | None,
    additional_notes: str | None,
    fallback_reason: str | None = None,
) -> dict:
    actual_mode = (
        GENERATION_MODE_TEMPLATE_PREFILL
        if requested_mode == GENERATION_MODE_AI_ASSISTED
        else GENERATION_MODE_TEMPLATE_PREFILL
    )
    status = "FALLBACK" if requested_mode == GENERATION_MODE_AI_ASSISTED and fallback_reason else "COMPLETED"
    return build_generation_metadata(
        requested_mode=requested_mode,
        actual_mode=actual_mode,
        status=status,
        operation=operation,
        purpose_notes=purpose_notes,
        special_instructions=special_instructions,
        additional_notes=additional_notes,
        fallback_reason=fallback_reason,
    )


async def create_authored_document_from_template(
    db: AsyncSession,
    payload: AuthoredDocumentCreateFromTemplateRequest,
) -> AuthoredDocumentResponse:
    document_type, template = await _resolve_template_for_document_request(
        db,
        document_type=payload.document_type,
        template_id=payload.template_id,
        template_code=payload.template_code,
    )

    asset, release = await _resolve_target_context(db, asset_id=payload.asset_id, release_id=payload.release_id)
    additional_notes = None
    title, content, source_context, _specs = await _build_prefill_payload(
        db,
        document_type=document_type,
        template=template,
        asset=asset,
        release=release,
        title=payload.title,
        purpose_notes=payload.purpose_notes,
        special_instructions=payload.special_instructions,
        additional_notes=additional_notes,
        source_document_url=payload.source_document_url,
        source_document_name=payload.source_document_name,
        source_document_relative_path=payload.source_document_relative_path,
        source_urs_text=payload.source_urs_text,
    )
    source_context = append_generation_metadata(
        source_context,
        _build_template_prefill_generation_event(
            requested_mode=GENERATION_MODE_TEMPLATE_PREFILL,
            operation=GENERATION_OPERATION_CREATE,
            purpose_notes=payload.purpose_notes,
            special_instructions=payload.special_instructions,
            additional_notes=additional_notes,
        ),
    )

    created_by = _strip_optional(payload.created_by)
    now = datetime.now(UTC)
    document = AuthoredDocument(
        document_type=document_type,
        title=title,
        status=AUTHORED_DOCUMENT_STATUS_DRAFT,
        publish_status=AUTHORED_DOCUMENT_PUBLISH_STATUS_NOT_PUBLISHED,
        asset_id=asset.asset_uuid if release is None else None,
        release_id=release.release_id if release is not None else None,
        template_id=template.template_id,
        content=content,
        source_context_json=source_context,
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(document)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_authored_document_integrity_error(exc)) from exc

    return await get_authored_document_by_id(db, document.authored_document_id)


async def create_authored_document_ai_draft(
    db: AsyncSession,
    payload: AuthoredDocumentCreateAiDraftRequest,
) -> AuthoredDocumentResponse:
    document_type, template = await _resolve_template_for_document_request(
        db,
        document_type=payload.document_type,
        template_id=payload.template_id,
        template_code=payload.template_code,
    )
    asset, release = await _resolve_target_context(db, asset_id=payload.asset_id, release_id=payload.release_id)
    additional_notes = None
    title, deterministic_content, source_context, specs = await _build_prefill_payload(
        db,
        document_type=document_type,
        template=template,
        asset=asset,
        release=release,
        title=payload.title,
        purpose_notes=payload.purpose_notes,
        special_instructions=payload.special_instructions,
        additional_notes=additional_notes,
        source_document_url=payload.source_document_url,
        source_document_name=payload.source_document_name,
        source_document_relative_path=payload.source_document_relative_path,
        source_urs_text=payload.source_urs_text,
    )

    content = deterministic_content
    try:
        ai_draft = await generate_ai_urs_draft(
            title=title,
            template=template,
            asset=asset,
            release=release,
            specs=specs,
            deterministic_content=deterministic_content,
            source_context=source_context,
            purpose_notes=payload.purpose_notes,
            special_instructions=payload.special_instructions,
            additional_notes=additional_notes,
            operation=GENERATION_OPERATION_CREATE,
        )
        content = ai_draft.content
        generation_event = ai_draft.generation_metadata
    except (UrsGenerationUnavailableError, UrsGenerationError) as exc:
        safe_reason = sanitize_urs_generation_failure_reason(str(exc))
        if not payload.fallback_to_template_prefill:
            raise ServiceUnavailableError(safe_reason or "AI-assisted generation could not be completed") from exc
        generation_event = _build_template_prefill_generation_event(
            requested_mode=GENERATION_MODE_AI_ASSISTED,
            operation=GENERATION_OPERATION_CREATE,
            purpose_notes=payload.purpose_notes,
            special_instructions=payload.special_instructions,
            additional_notes=additional_notes,
            fallback_reason=safe_reason,
        )

    source_context = append_generation_metadata(source_context, generation_event)

    created_by = _strip_optional(payload.created_by)
    now = datetime.now(UTC)
    document = AuthoredDocument(
        document_type=document_type,
        title=title,
        status=AUTHORED_DOCUMENT_STATUS_DRAFT,
        publish_status=AUTHORED_DOCUMENT_PUBLISH_STATUS_NOT_PUBLISHED,
        asset_id=asset.asset_uuid if release is None else None,
        release_id=release.release_id if release is not None else None,
        template_id=template.template_id,
        content=content,
        source_context_json=source_context,
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
    )
    db.add(document)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_authored_document_integrity_error(exc)) from exc

    return await get_authored_document_by_id(db, document.authored_document_id)


async def regenerate_authored_document_ai_content(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentAiRegenerateRequest,
) -> AuthoredDocumentResponse:
    document = await _get_authored_document_model_by_id(db, authored_document_id)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")

    _ensure_document_is_editable(document.status)

    template = document.template
    if template is None:
        raise ServiceConflictError("Authored document is missing its template context")

    release = document.release
    asset = document.asset or (release.asset if release is not None else None)
    if asset is None:
        raise ServiceConflictError("Authored document is not linked to a valid asset")

    existing_inputs = get_generation_inputs(document.source_context_json)
    source_urs_inputs = _get_source_urs_context(document.source_context_json)
    purpose_notes = _strip_optional(payload.purpose_notes) or existing_inputs["purpose_notes"]
    special_instructions = _strip_optional(payload.special_instructions) or existing_inputs["special_instructions"]
    additional_notes = None
    title_override = payload.title if payload.title is not None else document.title

    title, deterministic_content, source_context, specs = await _build_prefill_payload(
        db,
        document_type=document.document_type,
        template=template,
        asset=asset,
        release=release,
        title=title_override,
        purpose_notes=purpose_notes,
        special_instructions=special_instructions,
        additional_notes=additional_notes,
        source_document_url=source_urs_inputs["source_document_url"],
        source_document_name=source_urs_inputs["source_document_name"],
        source_document_relative_path=source_urs_inputs["source_document_relative_path"],
        source_urs_text=source_urs_inputs["source_urs_text"],
    )
    source_context = carry_forward_generation_history(source_context, document.source_context_json)

    existing_content = (
        _normalize_required_text(payload.existing_content, "existing_content")
        if payload.operation == "IMPROVE" and payload.existing_content is not None
        else document.content
    )
    if payload.operation == "IMPROVE" and not _strip_optional(existing_content):
        raise ServiceValidationError("existing_content is required when improving a draft")

    try:
        ai_draft = await generate_ai_urs_draft(
            title=title,
            template=template,
            asset=asset,
            release=release,
            specs=specs,
            deterministic_content=deterministic_content,
            source_context=source_context,
            purpose_notes=purpose_notes,
            special_instructions=special_instructions,
            additional_notes=additional_notes,
            operation=payload.operation,
            existing_content=existing_content if payload.operation == "IMPROVE" else None,
        )
    except (UrsGenerationUnavailableError, UrsGenerationError) as exc:
        safe_reason = sanitize_urs_generation_failure_reason(str(exc))
        raise ServiceUnavailableError(safe_reason or "AI-assisted generation could not be completed") from exc

    document.title = title
    document.content = ai_draft.content
    document.source_context_json = append_generation_metadata(source_context, ai_draft.generation_metadata)
    document.modified_by = _normalize_optional_string(payload.modified_by, "modified_by", 150)
    document.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_authored_document_integrity_error(exc)) from exc

    return await get_authored_document_by_id(db, document.authored_document_id)


async def update_authored_document(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentUpdate,
) -> AuthoredDocumentResponse:
    document = await _get_authored_document_model_by_id(db, authored_document_id)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")

    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates:
        raise ServiceValidationError("Status changes must use workflow action endpoints")

    has_editable_updates = any(key in updates for key in ("title", "content"))
    if has_editable_updates:
        _ensure_document_is_editable(document.status)

    changed = False
    if "title" in updates:
        if updates["title"] is None:
            raise ServiceValidationError("title cannot be null")
        next_title = _normalize_required(updates["title"], "title", 250)
        if next_title != document.title:
            document.title = next_title
            changed = True
    if "content" in updates:
        if updates["content"] is None:
            raise ServiceValidationError("content cannot be null")
        next_content = _normalize_required_text(updates["content"], "content")
        if next_content != document.content:
            document.content = next_content
            changed = True

    if not changed:
        return _build_authored_document_response(document)

    if "modified_by" in updates:
        document.modified_by = _normalize_optional_string(updates["modified_by"], "modified_by", 150)
    document.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_authored_document_integrity_error(exc)) from exc

    return await get_authored_document_by_id(db, document.authored_document_id)


async def submit_authored_document_for_review(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentWorkflowActionRequest,
) -> AuthoredDocumentResponse:
    document = await _get_authored_document_model_by_id(db, authored_document_id)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")

    _ensure_document_can_be_submitted(document.status)
    _normalize_required(document.title, "title", 250)
    _normalize_required_text(document.content, "content")

    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    comment_text = _normalize_comment_text(payload.comment_text)
    reviewer_name = _normalize_optional_string(payload.reviewer_name, "reviewer_name", 150) or document.reviewer_name

    await _create_authored_document_review_action(
        db,
        document=document,
        action_type=AUTHORED_DOCUMENT_ACTION_SUBMIT_FOR_REVIEW,
        action_by=action_by,
        comment_text=comment_text,
        to_status=AUTHORED_DOCUMENT_STATUS_IN_REVIEW,
        reviewer_name=reviewer_name,
    )
    return await get_authored_document_by_id(db, document.authored_document_id)


async def request_authored_document_changes(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentWorkflowActionRequest,
) -> AuthoredDocumentResponse:
    document = await _get_authored_document_model_by_id(db, authored_document_id)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")

    _ensure_document_is_in_review(document.status, action_label="sent back for changes")

    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    comment_text = _normalize_comment_text(payload.comment_text, required=True)
    reviewer_name = (
        _normalize_optional_string(payload.reviewer_name, "reviewer_name", 150)
        or document.reviewer_name
        or action_by
    )

    await _create_authored_document_review_action(
        db,
        document=document,
        action_type=AUTHORED_DOCUMENT_ACTION_REQUEST_CHANGES,
        action_by=action_by,
        comment_text=comment_text,
        to_status=AUTHORED_DOCUMENT_STATUS_CHANGES_REQUESTED,
        reviewer_name=reviewer_name,
    )
    return await get_authored_document_by_id(db, document.authored_document_id)


async def approve_authored_document(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentWorkflowActionRequest,
) -> AuthoredDocumentResponse:
    document = await _get_authored_document_model_by_id(db, authored_document_id)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")

    _ensure_document_is_in_review(document.status, action_label="approved")

    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    comment_text = _normalize_comment_text(payload.comment_text)
    reviewer_name = (
        _normalize_optional_string(payload.reviewer_name, "reviewer_name", 150)
        or document.reviewer_name
        or action_by
    )
    approver_name = (
        _normalize_optional_string(payload.approver_name, "approver_name", 150)
        or action_by
        or document.approver_name
    )

    await _create_authored_document_review_action(
        db,
        document=document,
        action_type=AUTHORED_DOCUMENT_ACTION_APPROVE,
        action_by=action_by,
        comment_text=comment_text,
        to_status=AUTHORED_DOCUMENT_STATUS_APPROVED,
        reviewer_name=reviewer_name,
        approver_name=approver_name,
    )
    return await get_authored_document_by_id(db, document.authored_document_id)


async def reject_authored_document(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentWorkflowActionRequest,
) -> AuthoredDocumentResponse:
    document = await _get_authored_document_model_by_id(db, authored_document_id)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")

    _ensure_document_is_in_review(document.status, action_label="rejected")

    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    comment_text = _normalize_comment_text(payload.comment_text, required=True)
    reviewer_name = (
        _normalize_optional_string(payload.reviewer_name, "reviewer_name", 150)
        or document.reviewer_name
        or action_by
    )

    await _create_authored_document_review_action(
        db,
        document=document,
        action_type=AUTHORED_DOCUMENT_ACTION_REJECT,
        action_by=action_by,
        comment_text=comment_text,
        to_status=AUTHORED_DOCUMENT_STATUS_REJECTED,
        reviewer_name=reviewer_name,
    )
    return await get_authored_document_by_id(db, document.authored_document_id)


async def comment_on_authored_document(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentCommentRequest,
) -> AuthoredDocumentReviewActionResponse:
    document = await _get_authored_document_model_by_id(db, authored_document_id)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")

    action_by = _normalize_optional_string(payload.action_by, "action_by", 150)
    comment_text = _normalize_comment_text(payload.comment_text, required=True)
    reviewer_name = document.reviewer_name or (action_by if document.status == AUTHORED_DOCUMENT_STATUS_IN_REVIEW else None)

    action = await _create_authored_document_review_action(
        db,
        document=document,
        action_type=AUTHORED_DOCUMENT_ACTION_COMMENT,
        action_by=action_by,
        comment_text=comment_text,
        to_status=document.status,
        reviewer_name=reviewer_name,
    )
    return _build_authored_document_review_action_response(action)


async def get_authored_document_history(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
) -> list[AuthoredDocumentReviewActionResponse]:
    document = await _get_authored_document_model_by_id(db, authored_document_id)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")

    stmt = (
        _authored_document_review_action_query()
        .where(AuthoredDocumentReviewAction.authored_document_id == authored_document_id)
        .order_by(AuthoredDocumentReviewAction.action_dt.desc())
    )
    result = await db.execute(stmt)
    return [_build_authored_document_review_action_response(action) for action in result.scalars().all()]


async def delete_authored_document(db: AsyncSession, authored_document_id: uuid.UUID) -> None:
    document = await _get_authored_document_model_by_id(db, authored_document_id)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")
    if document.status not in EDITABLE_AUTHORED_DOCUMENT_STATUSES:
        raise ServiceConflictError("Only documents in DRAFT or CHANGES_REQUESTED can be deleted")

    try:
        await db.delete(document)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete authored document") from exc
