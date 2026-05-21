import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.authored_document import AuthoredDocument
from app.schemas.authored_document_schema import (
    AuthoredDocumentPublishRequest,
    AuthoredDocumentPublishStatusResponse,
    AuthoredDocumentResponse,
)
from app.services.authored_document_service import (
    AUTHORED_DOCUMENT_STATUS_APPROVED,
    AUTHORED_DOCUMENT_TYPE_URS,
    ServiceConflictError,
    ServiceNotFoundError,
    ServiceUnavailableError,
    ServiceValidationError,
    _authored_document_query,
    get_authored_document_by_id,
)
from app.services.document_link_service import SOURCE_SYSTEM_VEEVA_VAULT, upsert_document_link_reference

AUTHORED_DOCUMENT_PUBLISH_STATUS_NOT_PUBLISHED = "NOT_PUBLISHED"
AUTHORED_DOCUMENT_PUBLISH_STATUS_PENDING = "PUBLISH_PENDING"
AUTHORED_DOCUMENT_PUBLISH_STATUS_PUBLISHED = "PUBLISHED"
AUTHORED_DOCUMENT_PUBLISH_STATUS_FAILED = "PUBLISH_FAILED"
SUPPORTED_VEEVA_AUTH_METHODS = {"basic", "bearer", "token", "none"}

logger = logging.getLogger("app.veeva_publish")


@dataclass(slots=True)
class VeevaPublishResult:
    external_document_id: str
    external_document_name: str
    external_document_version: str | None
    external_document_url: str | None
    external_source_reference: str | None


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_actor(value: str | None) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    if len(normalized) > 150:
        raise ServiceValidationError("action_by must not exceed 150 characters")
    return normalized


def _build_publish_status_response(document: AuthoredDocument) -> AuthoredDocumentPublishStatusResponse:
    return AuthoredDocumentPublishStatusResponse(
        authored_document_id=document.authored_document_id,
        document_type=document.document_type,
        document_status=document.status,
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
    )


async def _get_authored_document_for_publish(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> AuthoredDocument | None:
    stmt = _authored_document_query().where(AuthoredDocument.authored_document_id == authored_document_id)
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalars().first()


def _ensure_document_is_publishable(document: AuthoredDocument, *, retry: bool) -> None:
    if document.document_type != AUTHORED_DOCUMENT_TYPE_URS:
        raise ServiceValidationError("Only URS authored documents can be published to Veeva")
    if document.status != AUTHORED_DOCUMENT_STATUS_APPROVED:
        raise ServiceConflictError("Only APPROVED authored documents can be published to Veeva")

    publish_status = document.publish_status or AUTHORED_DOCUMENT_PUBLISH_STATUS_NOT_PUBLISHED
    if retry:
        if publish_status == AUTHORED_DOCUMENT_PUBLISH_STATUS_FAILED:
            return
        if publish_status == AUTHORED_DOCUMENT_PUBLISH_STATUS_PUBLISHED:
            raise ServiceConflictError("This authored document is already published to Veeva")
        if publish_status == AUTHORED_DOCUMENT_PUBLISH_STATUS_PENDING:
            raise ServiceConflictError("This authored document already has a publish attempt in progress")
        raise ServiceConflictError("Retry publish is only available after a failed Veeva publish attempt")

    if publish_status == AUTHORED_DOCUMENT_PUBLISH_STATUS_PUBLISHED:
        raise ServiceConflictError("This authored document is already published to Veeva")
    if publish_status == AUTHORED_DOCUMENT_PUBLISH_STATUS_PENDING:
        raise ServiceConflictError("This authored document already has a publish attempt in progress")
    if publish_status == AUTHORED_DOCUMENT_PUBLISH_STATUS_FAILED:
        raise ServiceConflictError("The last Veeva publish attempt failed. Use retry-publish instead")


def _mark_publish_pending(document: AuthoredDocument, *, action_by: str | None, attempted_at: datetime) -> None:
    document.publish_status = AUTHORED_DOCUMENT_PUBLISH_STATUS_PENDING
    document.last_publish_attempt_at = attempted_at
    document.last_publish_attempt_by = action_by
    document.external_system = SOURCE_SYSTEM_VEEVA_VAULT
    document.external_document_id = None
    document.external_document_name = None
    document.external_document_version = None
    document.external_document_url = None
    document.external_source_reference = None
    document.publish_error_message = None
    document.published_at = None
    document.published_by = None
    if action_by is not None:
        document.modified_by = action_by
    document.modified_dt = attempted_at


def _mark_publish_failed(
    document: AuthoredDocument,
    *,
    action_by: str | None,
    attempted_at: datetime,
    error_message: str,
) -> None:
    document.publish_status = AUTHORED_DOCUMENT_PUBLISH_STATUS_FAILED
    document.last_publish_attempt_at = attempted_at
    document.last_publish_attempt_by = action_by
    document.external_system = SOURCE_SYSTEM_VEEVA_VAULT
    document.external_document_id = None
    document.external_document_name = None
    document.external_document_version = None
    document.external_document_url = None
    document.external_source_reference = None
    document.publish_error_message = error_message.strip()
    document.published_at = None
    document.published_by = None
    if action_by is not None:
        document.modified_by = action_by
    document.modified_dt = datetime.now(UTC)


def _mark_publish_success(
    document: AuthoredDocument,
    *,
    action_by: str | None,
    published_at: datetime,
    publish_result: VeevaPublishResult,
) -> None:
    document.publish_status = AUTHORED_DOCUMENT_PUBLISH_STATUS_PUBLISHED
    document.last_publish_attempt_at = published_at
    document.last_publish_attempt_by = action_by
    document.published_at = published_at
    document.published_by = action_by
    document.external_system = SOURCE_SYSTEM_VEEVA_VAULT
    document.external_document_id = publish_result.external_document_id
    document.external_document_name = publish_result.external_document_name
    document.external_document_version = publish_result.external_document_version
    document.external_document_url = publish_result.external_document_url
    document.external_source_reference = publish_result.external_source_reference
    document.publish_error_message = None
    if action_by is not None:
        document.modified_by = action_by
    document.modified_dt = published_at


def _extract_nested_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _extract_string_candidate(payload: dict[str, Any], *paths: tuple[str, ...]) -> str | None:
    for path in paths:
        value = _extract_nested_value(payload, path)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _coerce_publish_error_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text or None

    if not isinstance(payload, dict):
        return None

    candidates = (
        ("error", "message"),
        ("error_message",),
        ("message",),
        ("detail",),
    )
    return _extract_string_candidate(payload, *candidates)


def _safe_url(value: str | None) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    parsed = urlparse(normalized)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return normalized
    return None


def _parse_publish_response(payload: dict[str, Any], *, fallback_title: str) -> VeevaPublishResult:
    external_document_id = _extract_string_candidate(
        payload,
        ("external_document_id",),
        ("document_id",),
        ("id",),
        ("data", "external_document_id"),
        ("data", "document_id"),
        ("data", "id"),
        ("document", "external_document_id"),
        ("document", "document_id"),
        ("document", "id"),
    )
    if external_document_id is None:
        raise ServiceUnavailableError("Veeva publish response did not include an external document identifier")

    external_document_name = (
        _extract_string_candidate(
            payload,
            ("external_document_name",),
            ("document_name",),
            ("name",),
            ("title",),
            ("data", "external_document_name"),
            ("data", "document_name"),
            ("data", "name"),
            ("data", "title"),
            ("document", "external_document_name"),
            ("document", "document_name"),
            ("document", "name"),
            ("document", "title"),
        )
        or fallback_title
    )
    external_document_version = _extract_string_candidate(
        payload,
        ("external_document_version",),
        ("document_version",),
        ("version",),
        ("major_version",),
        ("data", "external_document_version"),
        ("data", "document_version"),
        ("data", "version"),
        ("data", "major_version"),
        ("document", "external_document_version"),
        ("document", "document_version"),
        ("document", "version"),
    )
    external_source_reference = _extract_string_candidate(
        payload,
        ("source_reference",),
        ("reference",),
        ("document_number",),
        ("permalink",),
        ("data", "source_reference"),
        ("data", "reference"),
        ("data", "document_number"),
        ("data", "permalink"),
        ("document", "source_reference"),
        ("document", "reference"),
    )
    external_document_url = _safe_url(
        _extract_string_candidate(
            payload,
            ("external_document_url",),
            ("document_url",),
            ("access_url",),
            ("url",),
            ("permalink",),
            ("data", "external_document_url"),
            ("data", "document_url"),
            ("data", "access_url"),
            ("data", "url"),
            ("data", "permalink"),
            ("document", "external_document_url"),
            ("document", "document_url"),
            ("document", "access_url"),
            ("document", "url"),
        )
    ) or _safe_url(external_source_reference)

    return VeevaPublishResult(
        external_document_id=external_document_id,
        external_document_name=external_document_name,
        external_document_version=external_document_version,
        external_document_url=external_document_url,
        external_source_reference=external_source_reference,
    )


def _build_publish_payload(document: AuthoredDocument) -> dict[str, Any]:
    settings = get_settings()
    release = document.release
    asset = document.asset or (release.asset if release is not None else None)

    return {
        "source_application": "ValidateNow",
        "veeva_mapping": {
            "document_type": settings.VEEVA_URS_DOCUMENT_TYPE,
            "document_class": settings.VEEVA_URS_DOCUMENT_CLASS,
        },
        "document": {
            "authored_document_id": str(document.authored_document_id),
            "document_type": document.document_type,
            "title": document.title,
            "status": document.status,
            "content_markdown": document.content,
            "template": {
                "template_id": str(document.template_id),
                "template_code": document.template.template_code if document.template is not None else None,
                "template_name": document.template.template_name if document.template is not None else None,
            },
            "approval": {
                "reviewer_name": document.reviewer_name,
                "approver_name": document.approver_name,
                "approved_at": document.modified_dt.isoformat() if document.modified_dt is not None else None,
            },
            "asset": {
                "asset_uuid": str(asset.asset_uuid) if asset is not None else None,
                "asset_code": asset.asset_id if asset is not None else None,
                "asset_name": asset.asset_name if asset is not None else None,
                "asset_version": asset.asset_version if asset is not None else None,
            },
            "release": {
                "release_id": str(release.release_id) if release is not None else None,
                "release_version": release.version if release is not None else None,
            },
            "source_context": document.source_context_json,
        },
    }


class VeevaPublishClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _ensure_configured(self) -> None:
        if not self.settings.VEEVA_PUBLISH_ENABLED:
            raise ServiceUnavailableError(
                "Veeva publishing is disabled. Set VEEVA_PUBLISH_ENABLED=true and configure the Veeva endpoint."
            )
        if not _strip_optional(self.settings.VEEVA_BASE_URL):
            raise ServiceUnavailableError("Veeva publishing is not configured: VEEVA_BASE_URL is required")
        if not _strip_optional(self.settings.VEEVA_PUBLISH_ENDPOINT):
            raise ServiceUnavailableError("Veeva publishing is not configured: VEEVA_PUBLISH_ENDPOINT is required")

        auth_method = _strip_optional(self.settings.VEEVA_AUTH_METHOD)
        normalized_auth_method = auth_method.lower() if auth_method is not None else "basic"
        if normalized_auth_method not in SUPPORTED_VEEVA_AUTH_METHODS:
            allowed = ", ".join(sorted(SUPPORTED_VEEVA_AUTH_METHODS))
            raise ServiceUnavailableError(f"Unsupported VEEVA_AUTH_METHOD. Expected one of: {allowed}")
        if normalized_auth_method == "basic":
            if not _strip_optional(self.settings.VEEVA_USERNAME) or not _strip_optional(self.settings.VEEVA_PASSWORD):
                raise ServiceUnavailableError(
                    "Veeva publishing is not configured: VEEVA_USERNAME and VEEVA_PASSWORD are required for basic auth"
                )
        if normalized_auth_method in {"bearer", "token"} and not _strip_optional(self.settings.VEEVA_API_TOKEN):
            raise ServiceUnavailableError(
                "Veeva publishing is not configured: VEEVA_API_TOKEN is required for bearer auth"
            )

    def _build_request_parts(self) -> tuple[str, dict[str, str], httpx.BasicAuth | None]:
        base_url = self.settings.VEEVA_BASE_URL.rstrip("/")
        endpoint = self.settings.VEEVA_PUBLISH_ENDPOINT.lstrip("/")
        url = f"{base_url}/{endpoint}"
        auth_method = self.settings.VEEVA_AUTH_METHOD.strip().lower()

        headers = {
            "Accept": "application/json",
            "X-Source-System": "ValidateNow",
        }
        auth: httpx.BasicAuth | None = None

        if auth_method == "basic":
            auth = httpx.BasicAuth(self.settings.VEEVA_USERNAME, self.settings.VEEVA_PASSWORD)
        elif auth_method in {"bearer", "token"}:
            headers["Authorization"] = f"Bearer {self.settings.VEEVA_API_TOKEN}"

        return url, headers, auth

    async def publish_document(self, payload: dict[str, Any]) -> VeevaPublishResult:
        self._ensure_configured()
        url, headers, auth = self._build_request_parts()
        timeout = httpx.Timeout(self.settings.VEEVA_TIMEOUT_SECONDS)

        try:
            async with httpx.AsyncClient(timeout=timeout, verify=self.settings.VEEVA_VERIFY_SSL) as client:
                response = await client.post(url, headers=headers, auth=auth, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ServiceUnavailableError("Veeva publish request timed out") from exc
        except httpx.HTTPStatusError as exc:
            detail = _coerce_publish_error_detail(exc.response)
            message = f"Veeva publish failed with HTTP {exc.response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise ServiceUnavailableError(message) from exc
        except httpx.HTTPError as exc:
            raise ServiceUnavailableError(f"Veeva publish request failed: {exc}") from exc

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise ServiceUnavailableError("Veeva publish response was not valid JSON") from exc
        if not isinstance(response_payload, dict):
            raise ServiceUnavailableError("Veeva publish response had an unexpected structure")

        return _parse_publish_response(
            response_payload,
            fallback_title=str(payload.get("document", {}).get("title") or "Authored URS"),
        )


async def _persist_publish_state(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to persist authored document publish state") from exc


async def _run_publish_flow(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentPublishRequest,
    *,
    retry: bool,
) -> AuthoredDocumentResponse:
    document = await _get_authored_document_for_publish(db, authored_document_id, for_update=True)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")

    _ensure_document_is_publishable(document, retry=retry)

    action_by = _normalize_actor(payload.action_by)
    attempted_at = datetime.now(UTC)
    _mark_publish_pending(document, action_by=action_by, attempted_at=attempted_at)
    await _persist_publish_state(db)

    client = VeevaPublishClient()
    publish_payload = _build_publish_payload(document)

    try:
        publish_result = await client.publish_document(publish_payload)
    except HTTPException as exc:
        _mark_publish_failed(
            document,
            action_by=action_by,
            attempted_at=attempted_at,
            error_message=str(exc.detail),
        )
        await _persist_publish_state(db)
        raise
    except Exception as exc:
        logger.exception("veeva_publish_unhandled_error authored_document_id=%s", authored_document_id)
        _mark_publish_failed(
            document,
            action_by=action_by,
            attempted_at=attempted_at,
            error_message="Veeva publish failed unexpectedly",
        )
        await _persist_publish_state(db)
        raise ServiceUnavailableError("Veeva publish failed unexpectedly") from exc

    published_at = datetime.now(UTC)
    _mark_publish_success(
        document,
        action_by=action_by,
        published_at=published_at,
        publish_result=publish_result,
    )

    if publish_result.external_document_version and publish_result.external_document_url:
        await upsert_document_link_reference(
            db,
            asset_id=document.asset_id,
            release_id=document.release_id,
            source_system=SOURCE_SYSTEM_VEEVA_VAULT,
            external_document_id=publish_result.external_document_id,
            document_name=publish_result.external_document_name,
            document_version=publish_result.external_document_version,
            upload_dt=published_at,
            access_url=publish_result.external_document_url,
            document_type=document.document_type,
            actor=action_by,
            source_reference=publish_result.external_source_reference,
            notes=f"Published from authored URS {document.authored_document_id}",
        )
    else:
        logger.warning(
            "veeva_publish_link_skipped authored_document_id=%s external_document_id=%s missing_version_or_url=true",
            authored_document_id,
            publish_result.external_document_id,
        )

    await _persist_publish_state(db)
    return await get_authored_document_by_id(db, authored_document_id)


async def publish_authored_document_to_veeva(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentPublishRequest,
) -> AuthoredDocumentResponse:
    return await _run_publish_flow(db, authored_document_id, payload, retry=False)


async def retry_authored_document_publish_to_veeva(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
    payload: AuthoredDocumentPublishRequest,
) -> AuthoredDocumentResponse:
    return await _run_publish_flow(db, authored_document_id, payload, retry=True)


async def get_authored_document_publish_status(
    db: AsyncSession,
    authored_document_id: uuid.UUID,
) -> AuthoredDocumentPublishStatusResponse:
    document = await _get_authored_document_for_publish(db, authored_document_id)
    if document is None:
        raise ServiceNotFoundError("Authored document not found")
    return _build_publish_status_response(document)
