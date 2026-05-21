from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Iterable

from app.services.audit_review_metadata import (
    AUDIT_TYPE_DOCUMENT,
    AUDIT_TYPE_DOMAIN,
    AUDIT_TYPE_LOGIN,
    AUDIT_TYPE_OBJECT,
    AUDIT_TYPE_SYSTEM,
    SUPPORTED_AUDIT_TRAIL_TYPES,
    normalize_audit_trail_type,
)


USER_IDENTITY_KEYS = (
    "user_id",
    "userId",
    "user",
    "username",
    "user_name",
    "actor",
    "performed_by",
    "created_by",
    "user__v",
    "person",
    "performedBy",
    "createdBy",
)

TIMESTAMP_KEYS = (
    "event_timestamp",
    "timestamp",
    "event_time",
    "date_time",
    "created_date",
    "createdDate",
    "datetime",
)

ACTION_KEYS = (
    "action_type",
    "action",
    "event_action",
    "event",
    "event_name",
    "eventName",
    "event_description",
    "eventDescription",
    "operation",
    "activity",
    "event_type",
    "eventType",
    "action__v",
)

ACTION_EVENT_KEY_TERMS = ("action", "event", "activity", "operation")
UNKNOWN_ACTION_CATEGORY = "UNKNOWN"
UNKNOWN_TEXT_VALUES = {"", "unknown", "none", "null", "n/a", "na", "-"}

SOURCE_KEY_KEYS = (
    "source_record_key",
    "id",
    "record_id",
    "recordId",
    "audit_id",
    "auditId",
    "event_id",
    "eventId",
)


def _first_value(raw: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = raw.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _first_text(raw: dict[str, Any], keys: Iterable[str]) -> str | None:
    value = _first_value(raw, keys)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_timestamp(value: Any) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, datetime):
        parsed = value if value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None else value.replace(tzinfo=UTC)
        parsed = parsed.astimezone(UTC)
        return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z"), parsed.tzname()

    text = str(value).strip()
    if not text:
        return None, None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text, None

    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        parsed = parsed.replace(tzinfo=UTC)
        source_timezone = None
    else:
        source_timezone = "UTC" if text.endswith("Z") else parsed.tzname()
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"), source_timezone


def _bool_from_text(value: Any, terms: tuple[str, ...]) -> bool:
    if value is None:
        return False
    lowered = str(value).strip().lower()
    return any(term in lowered for term in terms)


def _is_unknown_text(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in UNKNOWN_TEXT_VALUES


def _first_known_text(*values: Any) -> str | None:
    for value in values:
        if not _is_unknown_text(value):
            return str(value).strip()
    return None


def _flatten_json_values(value: Any, *, key_filter: tuple[str, ...] | None = None) -> list[str]:
    values: list[str] = []

    def visit(item: Any, key_path: str = "") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                child_key_path = f"{key_path}.{key}" if key_path else str(key)
                visit(child, child_key_path)
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{key_path}[{index}]")
            return
        if item is None:
            return
        if key_filter is not None and not any(term in key_path.lower() for term in key_filter):
            return
        text = str(item).strip()
        if text:
            values.append(text)

    visit(value)
    return values


def infer_action_category_from_payload(raw: dict[str, Any] | None, audit_trail_type: str | None = None) -> str | None:
    if not isinstance(raw, dict):
        return None
    for value in _flatten_json_values(raw, key_filter=ACTION_EVENT_KEY_TERMS):
        category = normalize_action_category(value, audit_trail_type)
        if category != UNKNOWN_ACTION_CATEGORY:
            return category
    return None


def best_action_label(*values: Any) -> str:
    return _first_known_text(*values) or UNKNOWN_ACTION_CATEGORY


def _stable_source_key(raw: dict[str, Any], audit_trail_type: str) -> str:
    raw_key = _first_text(raw, SOURCE_KEY_KEYS)
    if raw_key:
        return raw_key
    digest_source = repr(sorted(raw.items(), key=lambda item: str(item[0]))).encode("utf-8", errors="ignore")
    digest = hashlib.sha256(digest_source).hexdigest()[:24]
    return f"{audit_trail_type}:{digest}"


def _base_normalize(audit_trail_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    raw_action = _first_text(raw, ACTION_KEYS)
    event_timestamp, event_timezone = _parse_timestamp(_first_value(raw, TIMESTAMP_KEYS))
    action_category = normalize_action_category(raw_action, audit_trail_type)
    detected_action_category = None
    if action_category == UNKNOWN_ACTION_CATEGORY:
        detected_action_category = infer_action_category_from_payload(raw, audit_trail_type)
    object_type = _first_text(raw, ("object_type", "objectType", "object", "component_type", "componentType", "type"))
    object_name = _first_text(raw, ("object_name", "objectName", "document_name", "documentName", "name", "label", "component_name"))
    field_name = _first_text(raw, ("field_name", "fieldName", "field", "property", "attribute", "column"))
    old_value = _first_text(raw, ("old_value", "oldValue", "previous_value", "previousValue", "old", "before"))
    new_value = _first_text(raw, ("new_value", "newValue", "current_value", "currentValue", "new", "after", "value"))

    normalized = {
        "audit_trail_type": audit_trail_type,
        "source_record_key": _stable_source_key(raw, audit_trail_type),
        "event_timestamp": event_timestamp,
        "event_timezone": _first_text(raw, ("event_timezone", "timezone", "time_zone")) or event_timezone,
        "user_id": _first_text(raw, USER_IDENTITY_KEYS),
        "user_name": _first_text(raw, ("user_name", "userName", "username", "user", "actor_name", "actorName", "display_name")),
        "action_type": action_category,
        "object_type": object_type,
        "object_name": object_name,
        "object_id": _first_text(raw, ("object_id", "objectId", "document_id", "documentId", "record_id", "recordId")),
        "field_name": field_name,
        "old_value": old_value,
        "new_value": new_value,
        "event_status": _first_text(raw, ("event_status", "eventStatus", "status", "result", "login_status")),
        "reason": _first_text(raw, ("reason", "comment", "comments", "justification", "change_reason")),
        "change_control_id": _first_text(raw, ("change_control_id", "changeControlId", "change_control", "changeControl", "change_request")),
        "ip_address": _first_text(raw, ("ip_address", "ipAddress", "client_ip", "clientIp", "remote_address")),
        "session_id": _first_text(raw, ("session_id", "sessionId", "session", "login_session_id")),
        "auth_method": _first_text(raw, ("auth_method", "authMethod", "authentication_method", "authenticationMethod", "mfa_method")),
        "failure_reason": _first_text(raw, ("failure_reason", "failureReason", "error", "error_message", "reason_failed")),
        "is_delete_action": action_category == "DELETE" or detected_action_category == "DELETE" or bool(raw.get("is_delete_action")),
        "is_permission_change": action_category == "PERMISSION_CHANGE"
        or detected_action_category == "PERMISSION_CHANGE"
        or bool(raw.get("is_permission_change")),
        "is_export_action": action_category in {"EXPORT", "DOWNLOAD"}
        or detected_action_category in {"EXPORT", "DOWNLOAD"}
        or bool(raw.get("is_export_action")),
        "is_configuration_change": action_category == "CONFIG_CHANGE"
        or detected_action_category == "CONFIG_CHANGE"
        or bool(raw.get("is_configuration_change")),
        "raw_payload": raw,
        "normalized_extra_json": {
            "raw_action": raw_action,
            "action_category": action_category,
            "detected_action_category": detected_action_category,
            "display_action": best_action_label(action_category, detected_action_category, raw_action),
            "normalizer": audit_trail_type,
            "source_fields": {
                "user_identity_keys": list(USER_IDENTITY_KEYS),
                "timestamp_keys": list(TIMESTAMP_KEYS),
                "action_keys": list(ACTION_KEYS),
            },
        },
    }
    return normalized


def _sync_action_metadata(normalized: dict[str, Any]) -> dict[str, Any]:
    extra = normalized.get("normalized_extra_json")
    if not isinstance(extra, dict):
        extra = {}
        normalized["normalized_extra_json"] = extra
    raw_action = extra.get("raw_action")
    detected_action_category = extra.get("detected_action_category")
    action_category = normalized.get("action_type")
    extra["action_category"] = action_category
    extra["display_action"] = best_action_label(action_category, detected_action_category, raw_action)
    normalized["is_delete_action"] = bool(normalized.get("is_delete_action")) or action_category == "DELETE" or detected_action_category == "DELETE"
    normalized["is_permission_change"] = (
        bool(normalized.get("is_permission_change"))
        or action_category == "PERMISSION_CHANGE"
        or detected_action_category == "PERMISSION_CHANGE"
    )
    normalized["is_export_action"] = (
        bool(normalized.get("is_export_action"))
        or action_category in {"EXPORT", "DOWNLOAD"}
        or detected_action_category in {"EXPORT", "DOWNLOAD"}
    )
    normalized["is_configuration_change"] = (
        bool(normalized.get("is_configuration_change"))
        or action_category == "CONFIG_CHANGE"
        or detected_action_category == "CONFIG_CHANGE"
    )
    return normalized


def normalize_action_category(raw_action: Any, audit_trail_type: str | None = None) -> str:
    text = str(raw_action or "").strip().lower()
    normalized_type = normalize_audit_trail_type(audit_trail_type)

    if not text:
        return "UNKNOWN"
    if any(term in text for term in ("login failed", "failed login", "login failure", "auth failure", "authentication failed")):
        return "LOGIN_FAILURE"
    if any(term in text for term in ("login success", "successful login", "logged in", "login")) and not any(
        term in text for term in ("logout", "failed", "failure")
    ):
        return "LOGIN_SUCCESS"
    if "approve" in text or "approved" in text:
        return "APPROVE"
    if "reject" in text or "rejected" in text:
        return "REJECT"
    if any(term in text for term in ("permission", "role", "access", "security", "group", "profile", "user role")):
        return "PERMISSION_CHANGE"
    if any(term in text for term in ("config", "configuration", "workflow", "lifecycle", "metadata", "setting", "template", "rule")):
        return "CONFIG_CHANGE"
    if "download" in text:
        return "DOWNLOAD"
    if any(term in text for term in ("export", "extract", "csv", "excel")):
        return "EXPORT"
    if any(term in text for term in ("delete", "remove", "purge", "destroy")):
        return "DELETE"
    if any(term in text for term in ("create", "created", "add", "added", "insert", "new record")):
        return "CREATE"
    if any(term in text for term in ("update", "updated", "modify", "modified", "change", "changed", "edit", "edited")):
        return "UPDATE"
    if normalized_type == AUDIT_TYPE_LOGIN and _bool_from_text(text, ("success", "passed", "succeeded")):
        return "LOGIN_SUCCESS"
    if normalized_type == AUDIT_TYPE_LOGIN and _bool_from_text(text, ("fail", "denied", "locked")):
        return "LOGIN_FAILURE"
    return "UNKNOWN"


def normalize_login_audit_record(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = _base_normalize(AUDIT_TYPE_LOGIN, raw)
    status_text = " ".join(
        str(value)
        for value in (
            normalized.get("event_status"),
            normalized.get("failure_reason"),
            raw.get("success"),
            raw.get("login_status"),
        )
        if value is not None
    ).lower()
    if normalized["action_type"] == "UNKNOWN":
        if any(term in status_text for term in ("false", "fail", "failure", "denied", "locked")):
            normalized["action_type"] = "LOGIN_FAILURE"
        elif any(term in status_text for term in ("true", "success", "succeeded", "passed")):
            normalized["action_type"] = "LOGIN_SUCCESS"
    return _sync_action_metadata(normalized)


def normalize_document_audit_record(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = _base_normalize(AUDIT_TYPE_DOCUMENT, raw)
    normalized["object_type"] = normalized.get("object_type") or "document"
    return _sync_action_metadata(normalized)


def normalize_object_audit_record(raw: dict[str, Any]) -> dict[str, Any]:
    return _sync_action_metadata(_base_normalize(AUDIT_TYPE_OBJECT, raw))


def normalize_system_audit_record(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = _base_normalize(AUDIT_TYPE_SYSTEM, raw)
    if normalized["action_type"] == "UNKNOWN" and normalized.get("object_type"):
        normalized["action_type"] = normalize_action_category(normalized["object_type"], AUDIT_TYPE_SYSTEM)
    return _sync_action_metadata(normalized)


def normalize_domain_audit_record(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = _base_normalize(AUDIT_TYPE_DOMAIN, raw)
    if normalized["action_type"] == "UNKNOWN" and normalized.get("object_type"):
        normalized["action_type"] = normalize_action_category(normalized["object_type"], AUDIT_TYPE_DOMAIN)
    return _sync_action_metadata(normalized)


_NORMALIZER_BY_AUDIT_TYPE = {
    AUDIT_TYPE_LOGIN: normalize_login_audit_record,
    AUDIT_TYPE_DOCUMENT: normalize_document_audit_record,
    AUDIT_TYPE_OBJECT: normalize_object_audit_record,
    AUDIT_TYPE_SYSTEM: normalize_system_audit_record,
    AUDIT_TYPE_DOMAIN: normalize_domain_audit_record,
}


def normalize_audit_record(audit_trail_type: str, raw: dict[str, Any]) -> dict[str, Any]:
    normalized_type = normalize_audit_trail_type(audit_trail_type)
    if normalized_type not in SUPPORTED_AUDIT_TRAIL_TYPES:
        raise ValueError(f"Unsupported audit trail type: {audit_trail_type}")
    return _NORMALIZER_BY_AUDIT_TYPE[normalized_type](raw)
