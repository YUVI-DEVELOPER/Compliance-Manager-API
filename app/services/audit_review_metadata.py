from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


AUDIT_TYPE_LOGIN = "login_audit_trail"
AUDIT_TYPE_DOCUMENT = "document_audit_trail"
AUDIT_TYPE_OBJECT = "object_audit_trail"
AUDIT_TYPE_SYSTEM = "system_audit_trail"
AUDIT_TYPE_DOMAIN = "domain_audit_trail"

SUPPORTED_AUDIT_TRAIL_TYPES: dict[str, dict[str, Any]] = {
    AUDIT_TYPE_LOGIN: {
        "code": AUDIT_TYPE_LOGIN,
        "label": "Login Audit Trail",
        "description": "User login, authentication, and session activity.",
        "expected_fields": [
            "source_record_key",
            "event_timestamp",
            "user_id",
            "user_name",
            "action_type",
            "event_status",
            "ip_address",
            "session_id",
            "auth_method",
            "failure_reason",
        ],
    },
    AUDIT_TYPE_DOCUMENT: {
        "code": AUDIT_TYPE_DOCUMENT,
        "label": "Document Audit Trail",
        "description": "Document lifecycle, version, field, and content actions.",
        "expected_fields": [
            "source_record_key",
            "event_timestamp",
            "user_id",
            "action_type",
            "object_name",
            "object_id",
            "field_name",
            "old_value",
            "new_value",
            "reason",
            "change_control_id",
        ],
    },
    AUDIT_TYPE_OBJECT: {
        "code": AUDIT_TYPE_OBJECT,
        "label": "Object Audit Trail",
        "description": "Object record creation, update, deletion, and export actions.",
        "expected_fields": [
            "source_record_key",
            "event_timestamp",
            "user_id",
            "action_type",
            "object_type",
            "object_name",
            "object_id",
            "field_name",
            "old_value",
            "new_value",
            "reason",
        ],
    },
    AUDIT_TYPE_SYSTEM: {
        "code": AUDIT_TYPE_SYSTEM,
        "label": "System Audit Trail",
        "description": "System settings, security, configuration, and platform-level actions.",
        "expected_fields": [
            "source_record_key",
            "event_timestamp",
            "user_id",
            "action_type",
            "object_type",
            "object_name",
            "field_name",
            "old_value",
            "new_value",
            "reason",
            "change_control_id",
        ],
    },
    AUDIT_TYPE_DOMAIN: {
        "code": AUDIT_TYPE_DOMAIN,
        "label": "Domain Audit Trail",
        "description": "Domain-level configuration, user, security, and platform governance actions.",
        "expected_fields": [
            "source_record_key",
            "event_timestamp",
            "user_id",
            "action_type",
            "object_type",
            "object_name",
            "field_name",
            "old_value",
            "new_value",
            "reason",
            "change_control_id",
        ],
    },
}

FULL_GXP_AUDIT_TRAIL_TYPES: list[str] = [
    AUDIT_TYPE_LOGIN,
    AUDIT_TYPE_DOCUMENT,
    AUDIT_TYPE_OBJECT,
    AUDIT_TYPE_SYSTEM,
    AUDIT_TYPE_DOMAIN,
]

REVIEW_SCOPE_LOGIN_ONLY = "LOGIN_ONLY"
REVIEW_SCOPE_DOCUMENT_ONLY = "DOCUMENT_ONLY"
REVIEW_SCOPE_OBJECT_ONLY = "OBJECT_ONLY"
REVIEW_SCOPE_SYSTEM_ONLY = "SYSTEM_ONLY"
REVIEW_SCOPE_DOMAIN_ONLY = "DOMAIN_ONLY"
REVIEW_SCOPE_FULL_GXP = "FULL_GXP"
REVIEW_SCOPE_CUSTOM = "CUSTOM"

REVIEW_SCOPES: dict[str, dict[str, Any]] = {
    REVIEW_SCOPE_LOGIN_ONLY: {
        "code": REVIEW_SCOPE_LOGIN_ONLY,
        "label": "Login Audit Trail Review",
        "score_label": "Login Audit Trail Score",
        "audit_trail_types": [AUDIT_TYPE_LOGIN],
    },
    REVIEW_SCOPE_DOCUMENT_ONLY: {
        "code": REVIEW_SCOPE_DOCUMENT_ONLY,
        "label": "Document Audit Trail Review",
        "score_label": "Document Audit Trail Score",
        "audit_trail_types": [AUDIT_TYPE_DOCUMENT],
    },
    REVIEW_SCOPE_OBJECT_ONLY: {
        "code": REVIEW_SCOPE_OBJECT_ONLY,
        "label": "Object Audit Trail Review",
        "score_label": "Object Audit Trail Score",
        "audit_trail_types": [AUDIT_TYPE_OBJECT],
    },
    REVIEW_SCOPE_SYSTEM_ONLY: {
        "code": REVIEW_SCOPE_SYSTEM_ONLY,
        "label": "System Audit Trail Review",
        "score_label": "System Audit Trail Score",
        "audit_trail_types": [AUDIT_TYPE_SYSTEM],
    },
    REVIEW_SCOPE_DOMAIN_ONLY: {
        "code": REVIEW_SCOPE_DOMAIN_ONLY,
        "label": "Domain Audit Trail Review",
        "score_label": "Domain Audit Trail Score",
        "audit_trail_types": [AUDIT_TYPE_DOMAIN],
    },
    REVIEW_SCOPE_FULL_GXP: {
        "code": REVIEW_SCOPE_FULL_GXP,
        "label": "Full GxP Audit Trail Review",
        "score_label": "Full GxP Audit Trail Score",
        "audit_trail_types": FULL_GXP_AUDIT_TRAIL_TYPES,
    },
    REVIEW_SCOPE_CUSTOM: {
        "code": REVIEW_SCOPE_CUSTOM,
        "label": "Custom Audit Trail Review",
        "score_label": "Custom Audit Trail Review Score",
        "audit_trail_types": [],
    },
}

CHECKPOINT_METADATA: dict[str, dict[str, Any]] = {
    "MISSING_TIMESTAMP": {
        "check_code": "MISSING_TIMESTAMP",
        "checkpoint_code": "TIMESTAMP_INTEGRITY",
        "parameter_code": "DATA_INTEGRITY",
        "label": "Timestamp Integrity",
        "description": "Each applicable record should include a usable event timestamp.",
        "sort_order": 10,
    },
    "MISSING_USER_ID": {
        "check_code": "MISSING_USER_ID",
        "checkpoint_code": "USER_ATTRIBUTION",
        "parameter_code": "DATA_INTEGRITY",
        "label": "User Attribution",
        "description": "Each applicable record should identify the responsible user or actor.",
        "sort_order": 20,
    },
    "RECORD_ADDITION_TRACEABILITY": {
        "check_code": "RECORD_ADDITION_TRACEABILITY",
        "checkpoint_code": "CREATION_TRACEABILITY",
        "parameter_code": "RECORD_CHANGES",
        "label": "Record Addition Traceability",
        "description": "Creation events should show who created what, when, and initial value context.",
        "sort_order": 30,
    },
    "MODIFICATION_CAPTURE_OLD_NEW_VALUES": {
        "check_code": "MODIFICATION_CAPTURE_OLD_NEW_VALUES",
        "checkpoint_code": "OLD_NEW_VALUE_CAPTURE",
        "parameter_code": "RECORD_CHANGES",
        "label": "Modification Old/New Value Capture",
        "description": "Modification events should preserve field, old value, and new value evidence.",
        "sort_order": 40,
    },
    "DELETE_ACTION": {
        "check_code": "DELETE_ACTION",
        "checkpoint_code": "DELETE_TRACEABILITY",
        "parameter_code": "RECORD_CHANGES",
        "label": "Delete Actions",
        "description": "Delete, remove, and purge actions should be surfaced for QA review.",
        "sort_order": 50,
    },
    "OFF_HOURS_ACTIVITY": {
        "check_code": "OFF_HOURS_ACTIVITY",
        "checkpoint_code": "BUSINESS_HOURS_REVIEW",
        "parameter_code": "USER_ACTIVITY",
        "label": "Off-hours Activity",
        "description": "Applicable activity outside configured business hours should be reviewed.",
        "sort_order": 60,
    },
    "PERMISSION_ACCESS_CHANGE": {
        "check_code": "PERMISSION_ACCESS_CHANGE",
        "checkpoint_code": "PERMISSION_CHANGE_REVIEW",
        "parameter_code": "SECURITY_CONFIGURATION",
        "label": "Permission / Access Changes",
        "description": "Permission, role, group, profile, and security changes should be flagged.",
        "sort_order": 70,
    },
    "CONFIGURATION_SYSTEM_CHANGE": {
        "check_code": "CONFIGURATION_SYSTEM_CHANGE",
        "checkpoint_code": "CONFIGURATION_CHANGE_REVIEW",
        "parameter_code": "SECURITY_CONFIGURATION",
        "label": "Configuration / System Changes",
        "description": "System, workflow, lifecycle, metadata, and configuration changes require review.",
        "sort_order": 80,
    },
    "DATA_EXPORT_LOGGING": {
        "check_code": "DATA_EXPORT_LOGGING",
        "checkpoint_code": "EXPORT_TRACEABILITY",
        "parameter_code": "DATA_MOVEMENT",
        "label": "Data Export Logging",
        "description": "Export and download events should retain user, timestamp, and object/report context.",
        "sort_order": 90,
    },
    "AUDIT_TRAIL_COMPLETENESS": {
        "check_code": "AUDIT_TRAIL_COMPLETENESS",
        "checkpoint_code": "EXTRACTION_COMPLETENESS",
        "parameter_code": "DATA_INTEGRITY",
        "label": "Audit Trail Completeness",
        "description": "Extracted records should preserve source keys and core timeline evidence.",
        "sort_order": 100,
    },
}

CHECKPOINT_APPLICABILITY_MATRIX: dict[str, list[str]] = {
    "MISSING_TIMESTAMP": FULL_GXP_AUDIT_TRAIL_TYPES,
    "MISSING_USER_ID": FULL_GXP_AUDIT_TRAIL_TYPES,
    "RECORD_ADDITION_TRACEABILITY": [AUDIT_TYPE_DOCUMENT, AUDIT_TYPE_OBJECT, AUDIT_TYPE_DOMAIN],
    "MODIFICATION_CAPTURE_OLD_NEW_VALUES": [
        AUDIT_TYPE_DOCUMENT,
        AUDIT_TYPE_OBJECT,
        AUDIT_TYPE_SYSTEM,
        AUDIT_TYPE_DOMAIN,
    ],
    "DELETE_ACTION": [AUDIT_TYPE_DOCUMENT, AUDIT_TYPE_OBJECT, AUDIT_TYPE_DOMAIN],
    "OFF_HOURS_ACTIVITY": FULL_GXP_AUDIT_TRAIL_TYPES,
    "PERMISSION_ACCESS_CHANGE": [AUDIT_TYPE_OBJECT, AUDIT_TYPE_SYSTEM, AUDIT_TYPE_DOMAIN],
    "CONFIGURATION_SYSTEM_CHANGE": [AUDIT_TYPE_SYSTEM, AUDIT_TYPE_DOMAIN],
    "DATA_EXPORT_LOGGING": [AUDIT_TYPE_DOCUMENT, AUDIT_TYPE_OBJECT, AUDIT_TYPE_SYSTEM, AUDIT_TYPE_DOMAIN],
    "AUDIT_TRAIL_COMPLETENESS": FULL_GXP_AUDIT_TRAIL_TYPES,
}

PARAMETER_CARD_METADATA: dict[str, dict[str, Any]] = {
    "DATA_INTEGRITY": {
        "parameter_code": "DATA_INTEGRITY",
        "label": "Data Integrity",
        "description": "Completeness, timestamp, and user attribution controls.",
        "check_codes": ["MISSING_TIMESTAMP", "MISSING_USER_ID", "AUDIT_TRAIL_COMPLETENESS"],
        "sort_order": 10,
    },
    "RECORD_CHANGES": {
        "parameter_code": "RECORD_CHANGES",
        "label": "Record Changes",
        "description": "Creation, modification, and deletion traceability.",
        "check_codes": [
            "RECORD_ADDITION_TRACEABILITY",
            "MODIFICATION_CAPTURE_OLD_NEW_VALUES",
            "DELETE_ACTION",
        ],
        "sort_order": 20,
    },
    "USER_ACTIVITY": {
        "parameter_code": "USER_ACTIVITY",
        "label": "User Activity",
        "description": "Business-hours and user behavior review.",
        "check_codes": ["OFF_HOURS_ACTIVITY"],
        "sort_order": 30,
    },
    "SECURITY_CONFIGURATION": {
        "parameter_code": "SECURITY_CONFIGURATION",
        "label": "Security & Configuration",
        "description": "Access, permission, system, and domain configuration review.",
        "check_codes": ["PERMISSION_ACCESS_CHANGE", "CONFIGURATION_SYSTEM_CHANGE"],
        "sort_order": 40,
    },
    "DATA_MOVEMENT": {
        "parameter_code": "DATA_MOVEMENT",
        "label": "Data Movement",
        "description": "Export, download, and extraction review.",
        "check_codes": ["DATA_EXPORT_LOGGING"],
        "sort_order": 50,
    },
}

_SINGLE_TYPE_SCOPE_BY_AUDIT_TYPE = {
    AUDIT_TYPE_LOGIN: REVIEW_SCOPE_LOGIN_ONLY,
    AUDIT_TYPE_DOCUMENT: REVIEW_SCOPE_DOCUMENT_ONLY,
    AUDIT_TYPE_OBJECT: REVIEW_SCOPE_OBJECT_ONLY,
    AUDIT_TYPE_SYSTEM: REVIEW_SCOPE_SYSTEM_ONLY,
    AUDIT_TYPE_DOMAIN: REVIEW_SCOPE_DOMAIN_ONLY,
}


class AuditReviewMetadataError(ValueError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.data = data or {}


def normalize_audit_trail_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _dedupe_supported(values: Iterable[str | None]) -> list[str]:
    selected: list[str] = []
    unsupported: list[str] = []
    for raw_value in values:
        audit_trail_type = normalize_audit_trail_type(raw_value)
        if audit_trail_type is None:
            continue
        if audit_trail_type not in SUPPORTED_AUDIT_TRAIL_TYPES:
            unsupported.append(audit_trail_type)
            continue
        if audit_trail_type not in selected:
            selected.append(audit_trail_type)

    if unsupported:
        raise AuditReviewMetadataError(
            "Unsupported audit trail type selected.",
            data={"unsupported_audit_trail_types": unsupported},
        )
    return selected


def resolve_review_scope(
    review_scope: str | None = None,
    selected_audit_trail_types: Iterable[str | None] | None = None,
    audit_trail_type: str | None = None,
) -> str:
    selected = _dedupe_supported(selected_audit_trail_types or [])
    legacy_type = normalize_audit_trail_type(audit_trail_type)
    normalized_scope = (review_scope or "").strip().upper() or None

    if normalized_scope is not None and normalized_scope not in REVIEW_SCOPES:
        raise AuditReviewMetadataError("Unsupported audit review scope.", data={"review_scope": normalized_scope})

    if normalized_scope == REVIEW_SCOPE_FULL_GXP:
        return REVIEW_SCOPE_FULL_GXP

    if normalized_scope in REVIEW_SCOPES and normalized_scope != REVIEW_SCOPE_CUSTOM:
        return normalized_scope

    if normalized_scope == REVIEW_SCOPE_CUSTOM:
        return REVIEW_SCOPE_CUSTOM

    if selected:
        if selected == FULL_GXP_AUDIT_TRAIL_TYPES:
            return REVIEW_SCOPE_FULL_GXP
        if len(selected) == 1:
            return _SINGLE_TYPE_SCOPE_BY_AUDIT_TYPE[selected[0]]
        return REVIEW_SCOPE_CUSTOM

    if legacy_type in _SINGLE_TYPE_SCOPE_BY_AUDIT_TYPE:
        return _SINGLE_TYPE_SCOPE_BY_AUDIT_TYPE[legacy_type]

    return REVIEW_SCOPE_LOGIN_ONLY


def get_selected_audit_trail_types(
    review_scope: str | None = None,
    selected_audit_trail_types: Iterable[str | None] | None = None,
    audit_trail_type: str | None = None,
) -> list[str]:
    scope = resolve_review_scope(review_scope, selected_audit_trail_types, audit_trail_type)
    selected = _dedupe_supported(selected_audit_trail_types or [])

    if scope == REVIEW_SCOPE_FULL_GXP:
        return list(FULL_GXP_AUDIT_TRAIL_TYPES)

    if scope == REVIEW_SCOPE_CUSTOM:
        if selected:
            return selected
        legacy_type = normalize_audit_trail_type(audit_trail_type)
        if legacy_type in SUPPORTED_AUDIT_TRAIL_TYPES:
            return [legacy_type]
        return [AUDIT_TYPE_LOGIN]

    scope_types = REVIEW_SCOPES[scope]["audit_trail_types"]
    return list(scope_types)


def get_applicability(check_code: str, audit_trail_type: str) -> str:
    normalized_check = check_code.strip().upper()
    normalized_type = normalize_audit_trail_type(audit_trail_type)
    applicable_types = CHECKPOINT_APPLICABILITY_MATRIX.get(normalized_check, [])
    return "ACTIVE" if normalized_type in applicable_types else "NOT_APPLICABLE"


def score_label_for_scope(review_scope: str | None, selected_audit_trail_types: Iterable[str | None] | None = None) -> str:
    selected = _dedupe_supported(selected_audit_trail_types or [])
    scope = resolve_review_scope(review_scope, selected, selected[0] if selected else None)
    if scope == REVIEW_SCOPE_FULL_GXP and selected and set(selected) != set(FULL_GXP_AUDIT_TRAIL_TYPES):
        return REVIEW_SCOPES[REVIEW_SCOPE_CUSTOM]["score_label"]
    return str(REVIEW_SCOPES.get(scope, REVIEW_SCOPES[REVIEW_SCOPE_CUSTOM])["score_label"])


def get_metadata_response() -> dict[str, Any]:
    return {
        "supported_audit_trail_types": list(deepcopy(SUPPORTED_AUDIT_TRAIL_TYPES).values()),
        "review_scopes": list(deepcopy(REVIEW_SCOPES).values()),
        "full_gxp_audit_trail_types": list(FULL_GXP_AUDIT_TRAIL_TYPES),
        "checkpoint_metadata": list(deepcopy(CHECKPOINT_METADATA).values()),
        "checkpoint_applicability_matrix": deepcopy(CHECKPOINT_APPLICABILITY_MATRIX),
        "parameter_card_metadata": list(deepcopy(PARAMETER_CARD_METADATA).values()),
    }
