import re
import uuid
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, status
from sqlalchemy import Select, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.asset_release import AssetRelease
from app.models.release_validation_package import ReleaseValidationPackage
from app.schemas.release_schema import (
    ALLOWED_EXPECTED_VALIDATED_FUNCTIONALITY_IMPACTS,
    ALLOWED_RELEASE_ENVIRONMENTS,
    ALLOWED_RELEASE_TYPES,
    DOCUMENTATION_MODE_MANUAL,
    DOCUMENTATION_MODE_ONLINE_FETCH,
    ReleaseCreate,
    ReleaseCreateResult,
    ReleaseResponse,
    ReleaseUpdate,
    RELEASE_STATUS_IMPACT_ASSESSMENT_PENDING,
)
from app.schemas.release_validation_package_schema import ReleaseValidationPackageResponse
from app.services.asset_service import is_asset_class_upgrade_supported

DOCUMENTATION_FETCH_TIMEOUT_SECONDS = 20.0
MAX_FETCHED_DOCUMENT_SIZE = 2_000_000
PACKAGE_STATUS_DRAFT = "DRAFT"
VALIDATION_SCOPE_NOT_ASSESSED = "NOT_ASSESSED"
RISK_LEVEL_NOT_ASSESSED = "NOT_ASSESSED"
IMPACT_ASSESSMENT_STATUS_PENDING = "PENDING"
DOCUMENT_CHECKLIST_STATUS_NOT_GENERATED = "NOT_GENERATED"
TESTING_STATUS_NOT_STARTED = "NOT_STARTED"
APPROVAL_STATUS_NOT_STARTED = "NOT_STARTED"
NEXT_STEP_IMPACT_ASSESSMENT = "IMPACT_ASSESSMENT"


class ServiceValidationError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class ServiceNotFoundError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ServiceConflictError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class _DocumentationHTMLParser(HTMLParser):
    _BLOCK_TAGS = {
        "article",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
    _IGNORED_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag in self._IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._IGNORED_TAGS and self._ignored_depth > 0:
            self._ignored_depth -= 1
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth > 0:
            return
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


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


def _normalize_required_text(value: str | None, field_name: str) -> str:
    if value is None:
        raise ServiceValidationError(f"{field_name} is required")
    normalized = value.strip()
    if not normalized:
        raise ServiceValidationError(f"{field_name} is required")
    return normalized


def _normalize_allowed(value: str | None, field_name: str, allowed_values: set[str], max_len: int) -> str:
    normalized = _normalize_required(value or "", field_name, max_len).upper()
    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ServiceValidationError(f"{field_name} must be one of: {allowed}")
    return normalized


def _normalize_required_datetime(value: datetime | None, field_name: str) -> datetime:
    if value is None:
        raise ServiceValidationError(f"{field_name} is required")
    return value


def _normalize_documentation_mode(value: str | None) -> str:
    normalized = _normalize_required_text(value, "documentation_mode").upper()
    if normalized not in {DOCUMENTATION_MODE_MANUAL, DOCUMENTATION_MODE_ONLINE_FETCH}:
        raise ServiceValidationError("documentation_mode must be one of: MANUAL, ONLINE_FETCH")
    return normalized


def _normalize_source_url(value: str | None) -> str:
    normalized = _normalize_required_text(value, "documentation_source_url")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ServiceValidationError("documentation_source_url must be a valid http or https URL")
    return normalized


def _normalize_documentation_content(value: str | None) -> str:
    normalized = _normalize_required_text(value, "documentation_text")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")

    normalized_lines: list[str] = []
    previous_blank = False
    for line in normalized.split("\n"):
        cleaned_line = re.sub(r"\s+", " ", line).strip()
        if not cleaned_line:
            if normalized_lines and not previous_blank:
                normalized_lines.append("")
            previous_blank = True
            continue
        normalized_lines.append(cleaned_line)
        previous_blank = False

    normalized_text = "\n".join(normalized_lines).strip()
    if not normalized_text:
        raise ServiceValidationError("documentation_text is required")
    return normalized_text


def _validate_end_dt(end_dt: datetime | None, created_dt: datetime) -> None:
    if end_dt is not None and end_dt < created_dt:
        raise ServiceValidationError("end_dt cannot be earlier than created_dt")


def _normalize_release_create_details(payload: ReleaseCreate) -> dict[str, object]:
    return {
        "release_name": _normalize_required(payload.release_name, "release_name", 200),
        "previous_version": _normalize_required(payload.previous_version, "previous_version", 50),
        "version": _normalize_required(payload.version, "version", 50),
        "release_type": _normalize_allowed(payload.release_type, "release_type", ALLOWED_RELEASE_TYPES, 40),
        "vendor_name": _strip_optional(payload.vendor_name),
        "planned_implementation_date": _normalize_required_datetime(
            payload.planned_implementation_date,
            "planned_implementation_date",
        ),
        "environment": _normalize_allowed(payload.environment, "environment", ALLOWED_RELEASE_ENVIRONMENTS, 30),
        "release_description": _normalize_required_text(payload.release_description, "release_description"),
        "business_reason": _normalize_required_text(payload.business_reason, "business_reason"),
        "change_control_no": _strip_optional(payload.change_control_no),
        "expected_validated_functionality_impact": _normalize_allowed(
            payload.expected_validated_functionality_impact,
            "expected_validated_functionality_impact",
            ALLOWED_EXPECTED_VALIDATED_FUNCTIONALITY_IMPACTS,
            20,
        ),
        "release_status": RELEASE_STATUS_IMPACT_ASSESSMENT_PENDING,
    }


def _release_query() -> Select[tuple[AssetRelease]]:
    return select(AssetRelease).options(
        selectinload(AssetRelease.asset).selectinload(Asset.supplier),
        selectinload(AssetRelease.validation_package),
    )


async def _get_asset_by_id(db: AsyncSession, asset_id: uuid.UUID) -> Asset | None:
    stmt = select(Asset).options(selectinload(Asset.supplier)).where(Asset.asset_uuid == asset_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_release_model_by_id(db: AsyncSession, release_id: uuid.UUID) -> AssetRelease | None:
    stmt = _release_query().where(AssetRelease.release_id == release_id)
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_release_by_asset_version(db: AsyncSession, asset_id: uuid.UUID, version: str) -> AssetRelease | None:
    stmt = select(AssetRelease).where(
        AssetRelease.asset_id == asset_id,
        AssetRelease.version == version,
    )
    result = await db.execute(stmt)
    return result.scalars().first()


def _conflict_message_from_integrity_error(exc: IntegrityError) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    if "uq_asset_release_asset_version" in message or "asset_id, version" in message:
        return "Release version already exists for this asset"
    if "uq_release_validation_package_release" in message:
        return "Validation package already exists for this release"
    if "uq_release_validation_package_no" in message:
        return "Validation package number already exists; retry release creation"
    if "chk_asset_release_end_dt" in message:
        return "end_dt cannot be earlier than created_dt"
    if "chk_asset_release_documentation_mode" in message:
        return "documentation_mode must be one of: MANUAL, ONLINE_FETCH"
    if "chk_asset_release_documentation_payload" in message:
        return "Release documentation fields are inconsistent with documentation_mode"
    return "Operation failed due to a data conflict"


def _build_validation_package_response(
    validation_package: ReleaseValidationPackage | None,
) -> ReleaseValidationPackageResponse | None:
    if validation_package is None:
        return None
    return ReleaseValidationPackageResponse.model_validate(validation_package)


def _build_release_response(release: AssetRelease) -> ReleaseResponse:
    asset = release.asset
    supplier = asset.supplier if asset is not None else None
    return ReleaseResponse(
        release_id=release.release_id,
        asset_id=release.asset_id,
        version=release.version,
        release_name=release.release_name,
        previous_version=release.previous_version,
        release_type=release.release_type,
        vendor_name=release.vendor_name,
        planned_implementation_date=release.planned_implementation_date,
        environment=release.environment,
        release_description=release.release_description,
        business_reason=release.business_reason,
        change_control_no=release.change_control_no,
        expected_validated_functionality_impact=release.expected_validated_functionality_impact,
        release_status=release.release_status,
        system_config_report=release.system_config_report,
        documentation_mode=release.documentation_mode,
        documentation_text=release.documentation_text,
        documentation_source_url=release.documentation_source_url,
        documentation_fetched_at=release.documentation_fetched_at,
        created_by=release.created_by,
        created_dt=release.created_dt,
        modified_by=release.modified_by,
        modified_dt=release.modified_dt,
        end_dt=release.end_dt,
        asset_name=asset.asset_name if asset is not None else None,
        asset_type=asset.asset_type if asset is not None else None,
        manufacturer=asset.manufacturer if asset is not None else None,
        model=asset.model if asset is not None else None,
        supplier_name=supplier.supplier_name if supplier is not None else None,
        validation_package=_build_validation_package_response(release.validation_package),
    )


def _extract_documentation_text(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "").lower()
    response_text = response.text
    if len(response_text) > MAX_FETCHED_DOCUMENT_SIZE:
        raise ServiceValidationError("Fetched documentation exceeds the maximum supported size")

    if "html" in content_type or "<html" in response_text.lower() or "<body" in response_text.lower():
        parser = _DocumentationHTMLParser()
        parser.feed(response_text)
        parser.close()
        extracted_text = parser.get_text()
    else:
        is_text_like = (
            content_type.startswith("text/")
            or "json" in content_type
            or "xml" in content_type
            or not content_type
        )
        if not is_text_like:
            raise ServiceValidationError(
                "documentation_source_url must return HTML, text, JSON, or XML content"
            )
        extracted_text = response_text

    normalized_text = _normalize_documentation_content(unescape(extracted_text))
    if not normalized_text:
        raise ServiceValidationError("Fetched documentation is empty")
    return normalized_text


async def _fetch_documentation_from_source(source_url: str) -> tuple[str, datetime]:
    timeout = httpx.Timeout(DOCUMENTATION_FETCH_TIMEOUT_SECONDS)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(
                source_url,
                headers={
                    "Accept": "text/html, text/plain, application/json;q=0.9, */*;q=0.8",
                    "User-Agent": "ValidateNow/1.0",
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ServiceValidationError(
            f"Failed to fetch documentation from documentation_source_url: received HTTP {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ServiceValidationError(f"Failed to fetch documentation from documentation_source_url: {exc}") from exc

    return _extract_documentation_text(response), datetime.now(UTC)


async def _generate_validation_package_no(db: AsyncSession, reference_dt: datetime) -> str:
    year = reference_dt.year
    prefix = f"VAL-PKG-{year}-"
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
        {"lock_name": f"release_validation_package:{year}"},
    )
    result = await db.execute(
        text(
            """
            SELECT COALESCE(MAX(CAST(SUBSTRING(package_no FROM :pattern) AS INTEGER)), 0)
            FROM public.release_validation_package
            WHERE package_no LIKE :like_pattern
            """
        ),
        {
            "pattern": f"^{prefix}([0-9]+)$",
            "like_pattern": f"{prefix}%",
        },
    )
    latest_sequence = result.scalar_one_or_none() or 0
    return f"{prefix}{int(latest_sequence) + 1:04d}"


async def _resolve_documentation_on_create(payload: ReleaseCreate) -> tuple[str, str, str | None, datetime | None]:
    documentation_mode = _normalize_documentation_mode(payload.documentation_mode)

    if documentation_mode == DOCUMENTATION_MODE_MANUAL:
        documentation_text = _normalize_documentation_content(payload.documentation_text)
        return documentation_mode, documentation_text, None, None

    documentation_source_url = _normalize_source_url(payload.documentation_source_url)
    documentation_text, documentation_fetched_at = await _fetch_documentation_from_source(documentation_source_url)
    return documentation_mode, documentation_text, documentation_source_url, documentation_fetched_at


async def _apply_documentation_updates(release: AssetRelease, updates: dict[str, object]) -> None:
    documentation_mode = release.documentation_mode
    if "documentation_mode" in updates:
        if updates["documentation_mode"] is None:
            raise ServiceValidationError("documentation_mode cannot be null")
        documentation_mode = _normalize_documentation_mode(str(updates["documentation_mode"]))

    if documentation_mode == DOCUMENTATION_MODE_MANUAL:
        if "documentation_text" in updates:
            release.documentation_text = _normalize_documentation_content(updates["documentation_text"])
        else:
            release.documentation_text = _normalize_documentation_content(release.documentation_text)

        release.documentation_mode = documentation_mode
        release.documentation_source_url = None
        release.documentation_fetched_at = None
        return

    if "documentation_source_url" in updates or "documentation_mode" in updates:
        source_url = _normalize_source_url(updates.get("documentation_source_url", release.documentation_source_url))
        documentation_text, documentation_fetched_at = await _fetch_documentation_from_source(source_url)
        release.documentation_source_url = source_url
        release.documentation_text = documentation_text
        release.documentation_fetched_at = documentation_fetched_at
    else:
        source_url = _normalize_source_url(release.documentation_source_url)
        release.documentation_source_url = source_url
        if not release.documentation_text:
            documentation_text, documentation_fetched_at = await _fetch_documentation_from_source(source_url)
            release.documentation_text = documentation_text
            release.documentation_fetched_at = documentation_fetched_at

    release.documentation_mode = documentation_mode


async def get_releases_by_asset(db: AsyncSession, asset_id: uuid.UUID) -> list[ReleaseResponse]:
    asset = await _get_asset_by_id(db, asset_id)
    if asset is None:
        raise ServiceNotFoundError("Asset not found")

    stmt = (
        _release_query()
        .where(AssetRelease.asset_id == asset_id)
        .order_by(AssetRelease.created_dt.desc(), AssetRelease.version.desc())
    )
    result = await db.execute(stmt)
    releases = result.scalars().all()
    return [_build_release_response(release) for release in releases]


async def get_release_by_id(db: AsyncSession, release_id: uuid.UUID) -> ReleaseResponse:
    release = await _get_release_model_by_id(db, release_id)
    if release is None:
        raise ServiceNotFoundError("Release not found")
    return _build_release_response(release)


async def get_validation_package_by_release(
    db: AsyncSession,
    release_id: uuid.UUID,
) -> ReleaseValidationPackageResponse:
    release = await _get_release_model_by_id(db, release_id)
    if release is None:
        raise ServiceNotFoundError("Release not found")
    validation_package = _build_validation_package_response(release.validation_package)
    if validation_package is None:
        raise ServiceNotFoundError("Validation package not found for release")
    return validation_package


async def create_release(db: AsyncSession, asset_id: uuid.UUID, payload: ReleaseCreate) -> ReleaseCreateResult:
    asset = await _get_asset_by_id(db, asset_id)
    if asset is None:
        raise ServiceNotFoundError("Asset not found")
    if not await is_asset_class_upgrade_supported(db, asset.asset_class):
        raise ServiceValidationError(
            "Releases can only be created for assets whose asset class is marked as upgrade-supported"
        )

    release_details = _normalize_release_create_details(payload)
    version = str(release_details["version"])
    created_by = _strip_optional(payload.created_by)
    documentation_mode, documentation_text, documentation_source_url, documentation_fetched_at = (
        await _resolve_documentation_on_create(payload)
    )
    now = datetime.now(UTC)
    _validate_end_dt(payload.end_dt, now)

    duplicate = await _get_release_by_asset_version(db, asset_id, version)
    if duplicate is not None:
        raise ServiceConflictError("Release version already exists for this asset")

    release = AssetRelease(
        asset_id=asset_id,
        version=version,
        release_name=release_details["release_name"],
        previous_version=release_details["previous_version"],
        release_type=release_details["release_type"],
        vendor_name=release_details["vendor_name"],
        planned_implementation_date=release_details["planned_implementation_date"],
        environment=release_details["environment"],
        release_description=release_details["release_description"],
        business_reason=release_details["business_reason"],
        change_control_no=release_details["change_control_no"],
        expected_validated_functionality_impact=release_details["expected_validated_functionality_impact"],
        release_status=RELEASE_STATUS_IMPACT_ASSESSMENT_PENDING,
        system_config_report=_strip_optional(payload.system_config_report),
        documentation_mode=documentation_mode,
        documentation_text=documentation_text,
        documentation_source_url=documentation_source_url,
        documentation_fetched_at=documentation_fetched_at,
        created_by=created_by,
        created_dt=now,
        modified_by=created_by,
        modified_dt=now,
        end_dt=payload.end_dt,
    )
    db.add(release)

    try:
        await db.flush()

        package_no = await _generate_validation_package_no(db, now)
        validation_package = ReleaseValidationPackage(
            release_id=release.release_id,
            package_no=package_no,
            package_status=PACKAGE_STATUS_DRAFT,
            validation_scope=VALIDATION_SCOPE_NOT_ASSESSED,
            risk_level=RISK_LEVEL_NOT_ASSESSED,
            impact_assessment_status=IMPACT_ASSESSMENT_STATUS_PENDING,
            document_checklist_status=DOCUMENT_CHECKLIST_STATUS_NOT_GENERATED,
            testing_status=TESTING_STATUS_NOT_STARTED,
            approval_status=APPROVAL_STATUS_NOT_STARTED,
            created_by=created_by,
            created_dt=now,
            modified_by=created_by,
            modified_dt=now,
        )
        db.add(validation_package)
        await db.flush()
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc
    except HTTPException:
        await db.rollback()
        raise

    created_release = await get_release_by_id(db, release.release_id)
    if created_release.validation_package is None:
        raise ServiceConflictError("Validation package initialization failed")
    return ReleaseCreateResult(
        release=created_release,
        validation_package=created_release.validation_package,
        nextStep=NEXT_STEP_IMPACT_ASSESSMENT,
    )


async def update_release(db: AsyncSession, release_id: uuid.UUID, payload: ReleaseUpdate) -> ReleaseResponse:
    release = await _get_release_model_by_id(db, release_id)
    if release is None:
        raise ServiceNotFoundError("Release not found")

    updates = payload.model_dump(exclude_unset=True)

    if "version" in updates and updates["version"] is None:
        raise ServiceValidationError("version cannot be null")

    required_text_updates = {
        "release_name": ("release_name", 200),
        "previous_version": ("previous_version", 50),
        "release_description": ("release_description", None),
        "business_reason": ("business_reason", None),
    }
    for field_name, (error_name, max_len) in required_text_updates.items():
        if field_name in updates:
            if updates[field_name] is None:
                raise ServiceValidationError(f"{error_name} cannot be null")
            if max_len is None:
                setattr(release, field_name, _normalize_required_text(str(updates[field_name]), error_name))
            else:
                setattr(release, field_name, _normalize_required(str(updates[field_name]), error_name, max_len))

    if "release_type" in updates:
        release.release_type = _normalize_allowed(updates["release_type"], "release_type", ALLOWED_RELEASE_TYPES, 40)

    if "environment" in updates:
        release.environment = _normalize_allowed(updates["environment"], "environment", ALLOWED_RELEASE_ENVIRONMENTS, 30)

    if "expected_validated_functionality_impact" in updates:
        release.expected_validated_functionality_impact = _normalize_allowed(
            updates["expected_validated_functionality_impact"],
            "expected_validated_functionality_impact",
            ALLOWED_EXPECTED_VALIDATED_FUNCTIONALITY_IMPACTS,
            20,
        )

    if "planned_implementation_date" in updates:
        release.planned_implementation_date = _normalize_required_datetime(
            updates["planned_implementation_date"],
            "planned_implementation_date",
        )

    if "vendor_name" in updates:
        release.vendor_name = _strip_optional(updates["vendor_name"])

    if "change_control_no" in updates:
        release.change_control_no = _strip_optional(updates["change_control_no"])

    if "release_status" in updates:
        release.release_status = _normalize_required(str(updates["release_status"]), "release_status", 50)

    if "version" in updates and updates["version"] is not None:
        version = _normalize_required(str(updates["version"]), "version", 50)
        if version != release.version:
            duplicate = await _get_release_by_asset_version(db, release.asset_id, version)
            if duplicate is not None and duplicate.release_id != release.release_id:
                raise ServiceConflictError("Release version already exists for this asset")
        release.version = version

    if "system_config_report" in updates:
        release.system_config_report = _strip_optional(updates["system_config_report"])

    documentation_updates = {"documentation_mode", "documentation_text", "documentation_source_url"}
    if documentation_updates.intersection(updates):
        await _apply_documentation_updates(release, updates)

    if "end_dt" in updates:
        _validate_end_dt(updates["end_dt"], release.created_dt)
        release.end_dt = updates["end_dt"]

    if "modified_by" in updates:
        release.modified_by = _strip_optional(updates["modified_by"])

    release.modified_dt = datetime.now(UTC)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError(_conflict_message_from_integrity_error(exc)) from exc

    return await get_release_by_id(db, release.release_id)


async def delete_release(db: AsyncSession, release_id: uuid.UUID) -> None:
    release = await _get_release_model_by_id(db, release_id)
    if release is None:
        raise ServiceNotFoundError("Release not found")

    try:
        await db.delete(release)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ServiceConflictError("Failed to delete release") from exc
