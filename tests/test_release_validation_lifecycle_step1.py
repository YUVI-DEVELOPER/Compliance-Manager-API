from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.models.asset_release import AssetRelease
from app.models.release_validation_package import ReleaseValidationPackage
from app.schemas.release_schema import (
    DOCUMENTATION_MODE_MANUAL,
    DOCUMENTATION_MODE_ONLINE_FETCH,
    ReleaseCreate,
    ReleaseResponse,
)
from app.schemas.release_validation_package_schema import ReleaseValidationPackageResponse
from app.services import release_service
from app.services.release_service import ServiceConflictError


ASSET_ID = uuid.uuid4()


def _payload_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "release_name": "LIMS 4.2 validation release",
        "previous_version": "4.1",
        "version": "4.2",
        "release_type": "MINOR",
        "planned_implementation_date": datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
        "environment": "UAT",
        "release_description": "Validated asset release metadata update.",
        "business_reason": "Adds controlled compliance lifecycle initialization.",
        "expected_validated_functionality_impact": "UNKNOWN",
        "documentation_mode": DOCUMENTATION_MODE_MANUAL,
        "documentation_text": "Release documentation baseline.",
        "created_by": "qa.user@example.com",
    }
    data.update(overrides)
    return data


def _payload(**overrides: object) -> ReleaseCreate:
    return ReleaseCreate(**_payload_data(**overrides))


def _assert_missing_field(field_name: str) -> None:
    data = _payload_data()
    data.pop(field_name)
    with pytest.raises(ValidationError) as exc_info:
        ReleaseCreate(**data)
    assert field_name in str(exc_info.value)


def test_release_create_schema_rejects_missing_release_name() -> None:
    _assert_missing_field("release_name")


def test_release_create_schema_rejects_missing_previous_version() -> None:
    _assert_missing_field("previous_version")


def test_release_create_schema_rejects_missing_release_type() -> None:
    _assert_missing_field("release_type")


def test_release_create_schema_rejects_invalid_release_type() -> None:
    with pytest.raises(ValidationError, match="release_type must be one of"):
        _payload(release_type="DATABASE_PATCH")


def test_release_create_schema_rejects_missing_planned_implementation_date() -> None:
    _assert_missing_field("planned_implementation_date")


def test_release_create_schema_rejects_missing_business_reason() -> None:
    _assert_missing_field("business_reason")


def test_release_create_schema_rejects_manual_documentation_without_text() -> None:
    with pytest.raises(ValidationError, match="documentation_text is required"):
        ReleaseCreate(**_payload_data(documentation_text=None))


def test_release_create_schema_rejects_online_fetch_without_valid_url() -> None:
    with pytest.raises(ValidationError, match="documentation_source_url must start"):
        ReleaseCreate(
            **_payload_data(
                documentation_mode=DOCUMENTATION_MODE_ONLINE_FETCH,
                documentation_text=None,
                documentation_source_url="ftp://example.com/release-notes",
            )
        )


class _FakeDb:
    def __init__(self, flush_error_on: int | None = None) -> None:
        self.added: list[object] = []
        self.flush_count = 0
        self.flush_error_on = flush_error_on
        self.commit_called = False
        self.rollback_called = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1
        if self.flush_error_on == self.flush_count:
            raise IntegrityError("INSERT", {}, Exception("uq_release_validation_package_no"))
        for obj in self.added:
            if isinstance(obj, AssetRelease) and obj.release_id is None:
                obj.release_id = uuid.uuid4()
            if isinstance(obj, ReleaseValidationPackage) and obj.package_id is None:
                obj.package_id = uuid.uuid4()

    async def commit(self) -> None:
        self.commit_called = True

    async def rollback(self) -> None:
        self.rollback_called = True


def _patch_create_dependencies(monkeypatch: pytest.MonkeyPatch, duplicate: object | None = None) -> None:
    async def fake_get_asset_by_id(db: object, asset_id: uuid.UUID) -> SimpleNamespace:
        return SimpleNamespace(asset_class="SOFTWARE")

    async def fake_is_asset_class_upgrade_supported(db: object, asset_class: str) -> bool:
        return True

    async def fake_get_release_by_asset_version(db: object, asset_id: uuid.UUID, version: str) -> object | None:
        return duplicate

    async def fake_package_no(db: object, reference_dt: datetime) -> str:
        return "VAL-PKG-2026-0001"

    monkeypatch.setattr(release_service, "_get_asset_by_id", fake_get_asset_by_id)
    monkeypatch.setattr(release_service, "is_asset_class_upgrade_supported", fake_is_asset_class_upgrade_supported)
    monkeypatch.setattr(release_service, "_get_release_by_asset_version", fake_get_release_by_asset_version)
    monkeypatch.setattr(release_service, "_generate_validation_package_no", fake_package_no)


def test_successful_release_creation_initializes_validation_package(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeDb()
    _patch_create_dependencies(monkeypatch)

    async def fake_get_release_by_id(db: _FakeDb, release_id: uuid.UUID) -> ReleaseResponse:
        release = next(obj for obj in db.added if isinstance(obj, AssetRelease))
        package = next(obj for obj in db.added if isinstance(obj, ReleaseValidationPackage))
        package_response = ReleaseValidationPackageResponse(
            package_id=package.package_id,
            release_id=release_id,
            package_no=package.package_no,
            package_status=package.package_status,
            validation_scope=package.validation_scope,
            risk_level=package.risk_level,
            impact_assessment_status=package.impact_assessment_status,
            document_checklist_status=package.document_checklist_status,
            testing_status=package.testing_status,
            approval_status=package.approval_status,
            final_decision=package.final_decision,
            created_by=package.created_by,
            created_dt=package.created_dt,
            modified_by=package.modified_by,
            modified_dt=package.modified_dt,
        )
        return ReleaseResponse(
            release_id=release_id,
            asset_id=release.asset_id,
            release_name=release.release_name,
            previous_version=release.previous_version,
            version=release.version,
            release_type=release.release_type,
            planned_implementation_date=release.planned_implementation_date,
            environment=release.environment,
            release_description=release.release_description,
            business_reason=release.business_reason,
            expected_validated_functionality_impact=release.expected_validated_functionality_impact,
            release_status=release.release_status,
            documentation_mode=release.documentation_mode,
            documentation_text=release.documentation_text,
            validation_package=package_response,
        )

    monkeypatch.setattr(release_service, "get_release_by_id", fake_get_release_by_id)

    result = asyncio.run(release_service.create_release(fake_db, ASSET_ID, _payload()))

    assert fake_db.commit_called is True
    assert fake_db.rollback_called is False
    assert result.release.release_status == "IMPACT_ASSESSMENT_PENDING"
    assert result.validation_package.package_no == "VAL-PKG-2026-0001"
    assert result.validation_package.package_status == "DRAFT"
    assert result.validation_package.validation_scope == "NOT_ASSESSED"
    assert result.validation_package.risk_level == "NOT_ASSESSED"
    assert result.validation_package.impact_assessment_status == "PENDING"
    assert result.nextStep == "IMPACT_ASSESSMENT"


def test_duplicate_release_version_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeDb()
    _patch_create_dependencies(monkeypatch, duplicate=SimpleNamespace(release_id=uuid.uuid4()))

    with pytest.raises(ServiceConflictError, match="Release version already exists"):
        asyncio.run(release_service.create_release(fake_db, ASSET_ID, _payload()))

    assert fake_db.added == []
    assert fake_db.commit_called is False


def test_package_creation_failure_rolls_back_release(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeDb(flush_error_on=2)
    _patch_create_dependencies(monkeypatch)

    with pytest.raises(ServiceConflictError, match="Validation package number already exists"):
        asyncio.run(release_service.create_release(fake_db, ASSET_ID, _payload()))

    assert any(isinstance(obj, AssetRelease) for obj in fake_db.added)
    assert any(isinstance(obj, ReleaseValidationPackage) for obj in fake_db.added)
    assert fake_db.rollback_called is True
    assert fake_db.commit_called is False


def test_old_release_without_validation_package_loads_safely() -> None:
    release = SimpleNamespace(
        release_id=uuid.uuid4(),
        asset_id=ASSET_ID,
        version="3.0",
        release_name="Legacy release",
        previous_version=None,
        release_type="PATCH",
        vendor_name=None,
        planned_implementation_date=None,
        environment="MULTI_ENV",
        release_description=None,
        business_reason=None,
        change_control_no=None,
        expected_validated_functionality_impact=None,
        release_status="IMPACT_ASSESSMENT_PENDING",
        system_config_report=None,
        documentation_mode=DOCUMENTATION_MODE_MANUAL,
        documentation_text="Legacy documentation.",
        documentation_source_url=None,
        documentation_fetched_at=None,
        created_by=None,
        created_dt=datetime(2026, 5, 1, tzinfo=UTC),
        modified_by=None,
        modified_dt=datetime(2026, 5, 1, tzinfo=UTC),
        end_dt=None,
        asset=None,
        validation_package=None,
    )

    response = release_service._build_release_response(release)

    assert response.release_id == release.release_id
    assert response.validation_package is None
