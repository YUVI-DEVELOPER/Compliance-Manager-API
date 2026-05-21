from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models.audit_trail_record import AuditTrailRecord
from app.services.audit_review_metadata import (
    FULL_GXP_AUDIT_TRAIL_TYPES,
    get_applicability,
    get_selected_audit_trail_types,
    resolve_review_scope,
    score_label_for_scope,
)
from app.services.audit_review_normalizers import normalize_action_category, normalize_audit_record
from app.services.audit_review_service import _build_record_response


def test_scope_resolution_preserves_legacy_login_request() -> None:
    selected = get_selected_audit_trail_types(None, None, "login_audit_trail")

    assert selected == ["login_audit_trail"]
    assert resolve_review_scope(None, selected, "login_audit_trail") == "LOGIN_ONLY"
    assert score_label_for_scope("LOGIN_ONLY", selected) == "Login Audit Trail Score"


def test_full_gxp_scope_selects_all_supported_types() -> None:
    selected = get_selected_audit_trail_types("FULL_GXP", None, None)

    assert selected == FULL_GXP_AUDIT_TRAIL_TYPES
    assert score_label_for_scope("FULL_GXP", selected) == "Full GxP Audit Trail Score"


def test_metadata_applicability_matrix_marks_unsupported_login_check() -> None:
    assert get_applicability("RECORD_ADDITION_TRACEABILITY", "login_audit_trail") == "NOT_APPLICABLE"
    assert get_applicability("MISSING_TIMESTAMP", "login_audit_trail") == "ACTIVE"


def test_normalizer_user_and_timestamp_fallbacks() -> None:
    record = normalize_audit_record(
        "document_audit_trail",
        {
            "id": "doc-audit-1",
            "performedBy": "qa.reviewer",
            "createdDate": "2026-05-11T10:15:00Z",
            "event": "Document Updated",
            "documentName": "SOP-001",
            "fieldName": "status__v",
            "oldValue": "Draft",
            "newValue": "Approved",
        },
    )

    assert record["user_id"] == "qa.reviewer"
    assert record["event_timestamp"] == "2026-05-11T10:15:00Z"
    assert record["action_type"] == "UPDATE"
    assert record["object_type"] == "document"


def test_document_normalizer_exposes_detected_action_when_source_action_is_missing() -> None:
    record = normalize_audit_record(
        "document_audit_trail",
        {
            "id": "doc-audit-2",
            "performedBy": "qa.reviewer",
            "createdDate": "2026-05-11T22:15:00Z",
            "documentName": "SOP-001",
            "details": {
                "activity_summary": "Document rendition downloaded as CSV",
            },
        },
    )

    assert record["action_type"] == "UNKNOWN"
    assert record["is_export_action"] is True
    assert record["normalized_extra_json"]["raw_action"] is None
    assert record["normalized_extra_json"]["detected_action_category"] == "DOWNLOAD"
    assert record["normalized_extra_json"]["display_action"] == "DOWNLOAD"


def test_record_response_backfills_display_action_from_raw_payload() -> None:
    record = AuditTrailRecord(
        record_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        asset_id=uuid.uuid4(),
        source_record_key="doc-audit-3",
        audit_trail_type="document_audit_trail",
        event_timestamp=datetime(2026, 5, 11, 22, 15, tzinfo=UTC),
        user_id="qa.reviewer",
        user_name="QA Reviewer",
        action_type="UNKNOWN",
        object_type="document",
        object_name="SOP-001",
        is_delete_action=False,
        is_permission_change=False,
        is_export_action=False,
        is_configuration_change=False,
        record_quality_status="VALID",
        raw_payload_json={"details": {"operation_summary": "Document deleted"}},
        normalized_extra_json={},
        created_dt=datetime(2026, 5, 11, 22, 16, tzinfo=UTC),
    )

    payload = _build_record_response(record, include_raw=False)

    assert payload["action_type"] == "UNKNOWN"
    assert payload["detected_action_category"] == "DELETE"
    assert payload["display_action"] == "DELETE"
    assert "raw_payload_json" not in payload


def test_action_category_mapping() -> None:
    assert normalize_action_category("User Login Success", "login_audit_trail") == "LOGIN_SUCCESS"
    assert normalize_action_category("Failed Login Attempt", "login_audit_trail") == "LOGIN_FAILURE"
    assert normalize_action_category("Download Rendition", "document_audit_trail") == "DOWNLOAD"
    assert normalize_action_category("Security Role Updated", "system_audit_trail") == "PERMISSION_CHANGE"
    assert normalize_action_category("", "object_audit_trail") == "UNKNOWN"
