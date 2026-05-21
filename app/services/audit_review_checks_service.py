from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.audit_trail_record import AuditTrailRecord
from app.services.audit_review_metadata import (
    CHECKPOINT_APPLICABILITY_MATRIX,
    CHECKPOINT_METADATA,
    FULL_GXP_AUDIT_TRAIL_TYPES,
)


CHECK_MISSING_TIMESTAMP = "MISSING_TIMESTAMP"
CHECK_MISSING_USER_ID = "MISSING_USER_ID"
CHECK_RECORD_ADDITION_TRACEABILITY = "RECORD_ADDITION_TRACEABILITY"
CHECK_MODIFICATION_CAPTURE_OLD_NEW_VALUES = "MODIFICATION_CAPTURE_OLD_NEW_VALUES"
CHECK_DELETE_ACTION = "DELETE_ACTION"
CHECK_OFF_HOURS_ACTIVITY = "OFF_HOURS_ACTIVITY"
CHECK_PERMISSION_ACCESS_CHANGE = "PERMISSION_ACCESS_CHANGE"
CHECK_CONFIGURATION_SYSTEM_CHANGE = "CONFIGURATION_SYSTEM_CHANGE"
CHECK_DATA_EXPORT_LOGGING = "DATA_EXPORT_LOGGING"
CHECK_AUDIT_TRAIL_COMPLETENESS = "AUDIT_TRAIL_COMPLETENESS"

CHECK_STATUS_ACTIVE = "ACTIVE"
CHECK_STATUS_PARTIAL = "PARTIAL"
CHECK_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
CHECK_STATUS_NO_DATA = "NO_DATA"
CHECK_STATUS_PASS = "PASS"
CHECK_STATUS_FAIL = "FAIL"

CHECK_NAMES = {
    CHECK_MISSING_TIMESTAMP: "Timestamp Integrity",
    CHECK_MISSING_USER_ID: "User Attribution",
    CHECK_RECORD_ADDITION_TRACEABILITY: "Record Addition Traceability",
    CHECK_MODIFICATION_CAPTURE_OLD_NEW_VALUES: "Modification Old/New Value Capture",
    CHECK_DELETE_ACTION: "Delete Actions",
    CHECK_OFF_HOURS_ACTIVITY: "Off-hours Activity",
    CHECK_PERMISSION_ACCESS_CHANGE: "Permission / Access Changes",
    CHECK_CONFIGURATION_SYSTEM_CHANGE: "Configuration / System Changes",
    CHECK_DATA_EXPORT_LOGGING: "Data Export Logging",
    CHECK_AUDIT_TRAIL_COMPLETENESS: "Audit Trail Completeness",
}

DELETE_ACTION_TERMS = ("delete", "remove", "purge")
MISSING_USER_HIGH_RISK_ACTION_TERMS = (
    "delete",
    "remove",
    "purge",
    "permission",
    "role",
    "access",
    "security",
)
PERMISSION_ACCESS_TERMS = ("role", "permission", "access", "security", "group", "profile", "user_role")
CRITICAL_DELETE_CONTEXT_TERMS = (
    "critical",
    "config",
    "configuration",
    "security",
    "user",
    "permission",
    "role",
    "access",
)
CREATION_TERMS = ("create", "created", "add", "added", "insert", "new record", "initial creation")
MODIFICATION_TERMS = ("update", "updated", "modify", "modified", "change", "changed", "edit", "edited")
CONFIGURATION_SYSTEM_TERMS = (
    "config",
    "configuration",
    "workflow",
    "lifecycle",
    "system setting",
    "setting",
    "parameter",
    "template",
    "rule",
    "security setting",
    "metadata",
    "object config",
)
CONFIGURATION_HIGH_TERMS = (
    "config",
    "configuration",
    "security setting",
    "system setting",
    "setting",
    "parameter",
    "metadata",
    "object config",
    "security",
)
EXPORT_TERMS = ("export", "download", "extract", "report export", "csv", "excel", "bulk export")
ACTION_EVENT_KEY_TERMS = ("action", "event", "activity", "operation")
CONFIGURATION_KEY_TERMS = ("action", "event", "object", "field", "type", "component", "name", "operation", "description")
VALUE_KEY_TERMS = ("new_value", "newvalue", "initial_value", "initialvalue", "value", "values")
UNKNOWN_TEXT_VALUES = {"", "unknown", "none", "null", "n/a", "na", "-"}
FIXED_TIMEZONE_FALLBACKS: dict[str, tzinfo] = {
    "Asia/Kolkata": timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata"),
    "Asia/Calcutta": timezone(timedelta(hours=5, minutes=30), "Asia/Calcutta"),
}


@dataclass(frozen=True)
class AuditAnalysisConfig:
    business_timezone: str = "Asia/Kolkata"
    business_start_hour: int = 9
    business_end_hour: int = 18
    audit_trail_type: str | None = None
    review_scope: str | None = None
    selected_audit_trail_types: tuple[str, ...] = ()

    def zone_info(self) -> tzinfo:
        try:
            return ZoneInfo(self.business_timezone)
        except ZoneInfoNotFoundError as exc:
            fallback = FIXED_TIMEZONE_FALLBACKS.get(self.business_timezone)
            if fallback is not None:
                return fallback
            raise ValueError(f"Unsupported business timezone: {self.business_timezone}") from exc


@dataclass(frozen=True)
class AuditCheckDefinition:
    check_code: str
    check_name: str
    penalty_per_finding: int
    penalty_cap: int
    sort_order: int


@dataclass(frozen=True)
class AuditFindingCandidate:
    check_code: str
    check_name: str
    audit_trail_type: str | None
    parameter_code: str | None
    checkpoint_code: str | None
    severity: str
    score_impact: int
    finding_title: str
    finding_summary: str
    evidence_json: dict[str, object | None]
    record: AuditTrailRecord | None
    source_record_count: int = 1


@dataclass(frozen=True)
class AuditCheckResult:
    definition: AuditCheckDefinition
    findings: list[AuditFindingCandidate]
    applicable_record_count: int
    evaluated_record_count: int
    skipped_record_count: int
    applicability: str
    check_status: str
    applicable_audit_trail_types: list[str]
    selected_audit_trail_types: list[str]
    no_data_count: int = 0

    def to_applicability_dict(self) -> dict[str, Any]:
        metadata = CHECKPOINT_METADATA.get(self.definition.check_code, {})
        return {
            "check_code": self.definition.check_code,
            "check_name": self.definition.check_name,
            "checkpoint_code": metadata.get("checkpoint_code"),
            "parameter_code": metadata.get("parameter_code"),
            "applicability": self.applicability,
            "check_status": self.check_status,
            "applicable_audit_trail_types": self.applicable_audit_trail_types,
            "selected_audit_trail_types": self.selected_audit_trail_types,
            "evaluated_record_count": self.evaluated_record_count,
            "skipped_record_count": self.skipped_record_count,
            "no_data_count": self.no_data_count,
        }


CHECK_DEFINITIONS = (
    AuditCheckDefinition(CHECK_MISSING_TIMESTAMP, CHECK_NAMES[CHECK_MISSING_TIMESTAMP], 10, 20, 10),
    AuditCheckDefinition(CHECK_MISSING_USER_ID, CHECK_NAMES[CHECK_MISSING_USER_ID], 5, 15, 20),
    AuditCheckDefinition(CHECK_RECORD_ADDITION_TRACEABILITY, CHECK_NAMES[CHECK_RECORD_ADDITION_TRACEABILITY], 3, 10, 30),
    AuditCheckDefinition(
        CHECK_MODIFICATION_CAPTURE_OLD_NEW_VALUES,
        CHECK_NAMES[CHECK_MODIFICATION_CAPTURE_OLD_NEW_VALUES],
        5,
        15,
        40,
    ),
    AuditCheckDefinition(CHECK_DELETE_ACTION, CHECK_NAMES[CHECK_DELETE_ACTION], 2, 20, 50),
    AuditCheckDefinition(CHECK_OFF_HOURS_ACTIVITY, CHECK_NAMES[CHECK_OFF_HOURS_ACTIVITY], 1, 10, 60),
    AuditCheckDefinition(CHECK_PERMISSION_ACCESS_CHANGE, CHECK_NAMES[CHECK_PERMISSION_ACCESS_CHANGE], 8, 25, 70),
    AuditCheckDefinition(CHECK_CONFIGURATION_SYSTEM_CHANGE, CHECK_NAMES[CHECK_CONFIGURATION_SYSTEM_CHANGE], 5, 10, 80),
    AuditCheckDefinition(CHECK_DATA_EXPORT_LOGGING, CHECK_NAMES[CHECK_DATA_EXPORT_LOGGING], 3, 10, 90),
    AuditCheckDefinition(CHECK_AUDIT_TRAIL_COMPLETENESS, CHECK_NAMES[CHECK_AUDIT_TRAIL_COMPLETENESS], 5, 5, 100),
)


DEFINITION_BY_CODE = {definition.check_code: definition for definition in CHECK_DEFINITIONS}


def _contains_any(value: str | None, terms: Iterable[str]) -> bool:
    if value is None:
        return False
    lowered = str(value).lower()
    return any(term in lowered for term in terms)


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![a-z0-9_]){escaped}(?![a-z0-9_])")


def _contains_term(value: str | None, terms: Iterable[str]) -> bool:
    if value is None:
        return False
    lowered = str(value).lower()
    return any(_term_pattern(term).search(lowered) for term in terms)


def _record_contains_any(record: AuditTrailRecord, fields: tuple[str, ...], terms: Iterable[str]) -> bool:
    return any(_contains_any(getattr(record, field, None), terms) for field in fields)


def _record_contains_term(record: AuditTrailRecord, fields: tuple[str, ...], terms: Iterable[str]) -> bool:
    return any(_contains_term(getattr(record, field, None), terms) for field in fields)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in UNKNOWN_TEXT_VALUES


def _has_user_identity(record: AuditTrailRecord) -> bool:
    return not _is_blank(record.user_id) or not _is_blank(record.user_name)


def _has_object_context(record: AuditTrailRecord) -> bool:
    return not (_is_blank(record.object_type) and _is_blank(record.object_name) and _is_blank(record.object_id))


def _has_field_context(record: AuditTrailRecord) -> bool:
    return not _is_blank(record.field_name)


def _has_old_value(record: AuditTrailRecord) -> bool:
    return not _is_blank(record.old_value)


def _has_new_value(record: AuditTrailRecord) -> bool:
    return not _is_blank(record.new_value)


def _raw_payload(record: AuditTrailRecord) -> dict[str, Any]:
    payload = record.raw_payload_json
    return payload if isinstance(payload, dict) else {}


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


def _action_event_text(record: AuditTrailRecord) -> str:
    parts = [record.action_type]
    parts.extend(_flatten_json_values(_raw_payload(record), key_filter=ACTION_EVENT_KEY_TERMS))
    return " ".join(str(part) for part in parts if not _is_blank(part))


def _raw_normalized_text(record: AuditTrailRecord) -> str:
    safe_parts = [
        record.action_type,
        record.object_type,
        record.object_name,
        record.object_id,
        record.field_name,
        record.old_value,
        record.new_value,
    ]
    raw_parts = _flatten_json_values(_raw_payload(record))
    return " ".join(str(part) for part in [*safe_parts, *raw_parts] if not _is_blank(part))


def _configuration_detection_text(record: AuditTrailRecord) -> str:
    safe_parts = [
        record.action_type,
        record.object_type,
        record.object_name,
        record.object_id,
        record.field_name,
    ]
    raw_parts = _flatten_json_values(_raw_payload(record), key_filter=CONFIGURATION_KEY_TERMS)
    return " ".join(str(part) for part in [*safe_parts, *raw_parts] if not _is_blank(part))


def _has_raw_value_context(record: AuditTrailRecord) -> bool:
    for value in _flatten_json_values(_raw_payload(record), key_filter=VALUE_KEY_TERMS):
        if not _is_blank(value):
            return True
    return False


def _has_new_or_initial_value_context(record: AuditTrailRecord) -> bool:
    return _has_new_value(record) or _has_raw_value_context(record)


def _is_missing_user_id(record: AuditTrailRecord) -> bool:
    user_id = str(record.user_id or "").strip().lower()
    return user_id in {"", "unknown"}


def _is_delete_action(record: AuditTrailRecord) -> bool:
    return bool(record.is_delete_action) or _contains_any(record.action_type, DELETE_ACTION_TERMS)


def _is_permission_access_change(record: AuditTrailRecord) -> bool:
    return bool(record.is_permission_change) or _record_contains_any(
        record,
        ("action_type", "object_type", "field_name"),
        PERMISSION_ACCESS_TERMS,
    )


def _is_critical_delete_context(record: AuditTrailRecord) -> bool:
    return _record_contains_any(record, ("action_type", "object_type"), CRITICAL_DELETE_CONTEXT_TERMS)


def resolve_business_hours(record: AuditTrailRecord | None, config: AuditAnalysisConfig | None) -> tuple[str, int, int]:
    # Future site/asset-specific calendar logic can branch from the record context here.
    if config is None:
        return "Asia/Kolkata", 9, 18
    return (
        config.business_timezone or "Asia/Kolkata",
        config.business_start_hour if config.business_start_hour is not None else 9,
        config.business_end_hour if config.business_end_hour is not None else 18,
    )


def _zone_info_for_name(timezone_name: str) -> tzinfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        fallback = FIXED_TIMEZONE_FALLBACKS.get(timezone_name)
        if fallback is not None:
            return fallback
        return ZoneInfo("UTC")


def _is_within_business_hours(record: AuditTrailRecord, config: AuditAnalysisConfig | None) -> bool:
    if record.event_timestamp is None:
        return True
    timestamp = record.event_timestamp
    if timestamp.tzinfo is None or timestamp.tzinfo.utcoffset(timestamp) is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timezone_name, start_hour, end_hour = resolve_business_hours(record, config)
    local_timestamp = timestamp.astimezone(_zone_info_for_name(timezone_name))
    return start_hour <= local_timestamp.hour < end_hour


def _is_off_hours(record: AuditTrailRecord, config: AuditAnalysisConfig) -> bool:
    return not _is_within_business_hours(record, config)


def _local_timestamp_text(record: AuditTrailRecord, config: AuditAnalysisConfig) -> str:
    if record.event_timestamp is None:
        return "unknown local time"
    timestamp = record.event_timestamp
    if timestamp.tzinfo is None or timestamp.tzinfo.utcoffset(timestamp) is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timezone_name, _, _ = resolve_business_hours(record, config)
    return timestamp.astimezone(_zone_info_for_name(timezone_name)).isoformat()


def _is_creation_event(record: AuditTrailRecord) -> bool:
    return _contains_term(_action_event_text(record), CREATION_TERMS)


def _is_modification_event(record: AuditTrailRecord, config: AuditAnalysisConfig) -> bool:
    if not _contains_term(_action_event_text(record), MODIFICATION_TERMS):
        return False

    audit_trail_type = (config.audit_trail_type or "").strip().lower()
    if audit_trail_type == "login_audit_trail":
        return _has_object_context(record) or _has_field_context(record) or _has_old_value(record) or _has_new_value(record)

    return True


def _is_configuration_system_change(record: AuditTrailRecord) -> bool:
    return bool(getattr(record, "is_configuration_change", False)) or _record_contains_term(
        record,
        ("action_type", "object_type", "object_name", "field_name"),
        CONFIGURATION_SYSTEM_TERMS,
    ) or _contains_term(_configuration_detection_text(record), CONFIGURATION_SYSTEM_TERMS)


def _configuration_severity(record: AuditTrailRecord) -> str:
    text = _configuration_detection_text(record)
    if _contains_term(text, CONFIGURATION_HIGH_TERMS):
        return "HIGH"
    return "MEDIUM"


def _is_export_event(record: AuditTrailRecord) -> bool:
    return bool(getattr(record, "is_export_action", False)) or _record_contains_term(
        record,
        ("action_type", "object_type", "object_name"),
        EXPORT_TERMS,
    )


def _iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_safe_evidence(record: AuditTrailRecord) -> dict[str, object | None]:
    return {
        "record_id": str(record.record_id),
        "source_record_key": record.source_record_key,
        "audit_trail_type": record.audit_trail_type,
        "event_timestamp": _iso_datetime(record.event_timestamp),
        "user_id": record.user_id,
        "user_name": record.user_name,
        "action_type": record.action_type,
        "object_type": record.object_type,
        "object_id": record.object_id,
        "object_name": record.object_name,
        "field_name": record.field_name,
    }


def _record_label(record: AuditTrailRecord) -> str:
    return record.source_record_key or str(record.record_id)


def _finding(
    definition: AuditCheckDefinition,
    record: AuditTrailRecord,
    *,
    severity: str,
    title: str,
    summary: str,
) -> AuditFindingCandidate:
    metadata = CHECKPOINT_METADATA.get(definition.check_code, {})
    return AuditFindingCandidate(
        check_code=definition.check_code,
        check_name=definition.check_name,
        audit_trail_type=record.audit_trail_type,
        parameter_code=metadata.get("parameter_code"),
        checkpoint_code=metadata.get("checkpoint_code"),
        severity=severity,
        score_impact=definition.penalty_per_finding,
        finding_title=title,
        finding_summary=summary,
        evidence_json=build_safe_evidence(record),
        record=record,
    )


def _aggregate_finding(
    definition: AuditCheckDefinition,
    *,
    severity: str,
    title: str,
    summary: str,
    evidence_json: dict[str, object | None],
    source_record_count: int,
) -> AuditFindingCandidate:
    metadata = CHECKPOINT_METADATA.get(definition.check_code, {})
    audit_trail_type = None
    evidence_type = evidence_json.get("audit_trail_type")
    if isinstance(evidence_type, str):
        audit_trail_type = evidence_type
    return AuditFindingCandidate(
        check_code=definition.check_code,
        check_name=definition.check_name,
        audit_trail_type=audit_trail_type,
        parameter_code=metadata.get("parameter_code"),
        checkpoint_code=metadata.get("checkpoint_code"),
        severity=severity,
        score_impact=definition.penalty_per_finding,
        finding_title=title,
        finding_summary=summary,
        evidence_json=evidence_json,
        record=None,
        source_record_count=source_record_count,
    )


def _missing_user_id_findings(records: list[AuditTrailRecord], definition: AuditCheckDefinition) -> list[AuditFindingCandidate]:
    findings: list[AuditFindingCandidate] = []
    for record in records:
        if not _is_missing_user_id(record):
            continue
        severity = "HIGH" if _contains_any(record.action_type, MISSING_USER_HIGH_RISK_ACTION_TERMS) else "MEDIUM"
        findings.append(
            _finding(
                definition,
                record,
                severity=severity,
                title="Audit record is missing user identity",
                summary=(
                    f"Audit record {_record_label(record)} does not include a usable user_id for "
                    f"action {record.action_type or 'unspecified'}."
                ),
            )
        )
    return findings


def _missing_timestamp_findings(
    records: list[AuditTrailRecord],
    definition: AuditCheckDefinition,
) -> list[AuditFindingCandidate]:
    findings: list[AuditFindingCandidate] = []
    for record in records:
        if record.event_timestamp is not None:
            continue
        findings.append(
            _finding(
                definition,
                record,
                severity="HIGH",
                title="Audit record is missing event timestamp",
                summary=(
                    f"Audit record {_record_label(record)} cannot be placed on the review timeline because "
                    "event_timestamp is missing."
                ),
            )
        )
    return findings


def _record_addition_traceability_findings(
    records: list[AuditTrailRecord],
    definition: AuditCheckDefinition,
) -> list[AuditFindingCandidate]:
    findings: list[AuditFindingCandidate] = []
    for record in records:
        if not _is_creation_event(record):
            continue

        missing_critical = []
        if not _has_user_identity(record):
            missing_critical.append("creator identity")
        if record.event_timestamp is None:
            missing_critical.append("event timestamp")

        missing_context = []
        if not _has_object_context(record):
            missing_context.append("object/module context")
        if not _has_new_or_initial_value_context(record):
            missing_context.append("initial/new value context")

        if not missing_critical and not missing_context:
            continue

        severity = "MEDIUM" if missing_critical else "LOW"
        missing_parts = [*missing_critical, *missing_context]
        findings.append(
            _finding(
                definition,
                record,
                severity=severity,
                title="Record creation traceability is incomplete",
                summary=(
                    f"Audit record {_record_label(record)} indicates record creation/addition but is missing "
                    f"{', '.join(missing_parts)}."
                ),
            )
        )
    return findings


def _modification_capture_findings(
    records: list[AuditTrailRecord],
    definition: AuditCheckDefinition,
    config: AuditAnalysisConfig,
) -> list[AuditFindingCandidate]:
    findings: list[AuditFindingCandidate] = []
    for record in records:
        if not _is_modification_event(record, config):
            continue

        has_old_value = _has_old_value(record)
        has_new_value = _has_new_value(record)
        has_field_name = _has_field_context(record)
        if has_old_value and has_new_value and has_field_name:
            continue

        if not has_old_value and not has_new_value:
            severity = "HIGH"
            missing_summary = "both old_value and new_value"
        elif not has_old_value:
            severity = "MEDIUM"
            missing_summary = "old_value"
        elif not has_new_value:
            severity = "MEDIUM"
            missing_summary = "new_value"
        else:
            severity = "LOW"
            missing_summary = "field_name"

        findings.append(
            _finding(
                definition,
                record,
                severity=severity,
                title="Modification record is missing old/new value traceability",
                summary=(
                    f"Audit record {_record_label(record)} indicates update/change activity but is missing "
                    f"{missing_summary}."
                ),
            )
        )
    return findings


def _delete_action_findings(records: list[AuditTrailRecord], definition: AuditCheckDefinition) -> list[AuditFindingCandidate]:
    findings: list[AuditFindingCandidate] = []
    for record in records:
        if not _is_delete_action(record):
            continue
        severity = "HIGH" if _is_critical_delete_context(record) else "MEDIUM"
        findings.append(
            _finding(
                definition,
                record,
                severity=severity,
                title="Delete or removal action detected",
                summary=(
                    f"Audit record {_record_label(record)} indicates delete/remove/purge activity for "
                    f"{record.object_type or 'an unspecified object type'}."
                ),
            )
        )
    return findings


def _permission_access_findings(
    records: list[AuditTrailRecord],
    definition: AuditCheckDefinition,
) -> list[AuditFindingCandidate]:
    findings: list[AuditFindingCandidate] = []
    for record in records:
        if not _is_permission_access_change(record):
            continue
        findings.append(
            _finding(
                definition,
                record,
                severity="HIGH",
                title="Permission or access-related change detected",
                summary=(
                    f"Audit record {_record_label(record)} indicates a role, permission, access, security, "
                    "group, profile, or user-role change."
                ),
            )
        )
    return findings


def _off_hours_findings(
    records: list[AuditTrailRecord],
    definition: AuditCheckDefinition,
    config: AuditAnalysisConfig,
) -> list[AuditFindingCandidate]:
    findings: list[AuditFindingCandidate] = []
    for record in records:
        if record.event_timestamp is None or not _is_off_hours(record, config):
            continue
        severity = "MEDIUM" if _is_delete_action(record) or _is_permission_access_change(record) else "LOW"
        findings.append(
            _finding(
                definition,
                record,
                severity=severity,
                title="Audit activity occurred outside business hours",
                summary=(
                    f"Audit record {_record_label(record)} occurred at {_local_timestamp_text(record, config)} outside "
                    f"{config.business_start_hour}:00-{config.business_end_hour}:00 "
                    f"{config.business_timezone} business hours."
                ),
            )
        )
    return findings


def _configuration_system_change_findings(
    records: list[AuditTrailRecord],
    definition: AuditCheckDefinition,
) -> list[AuditFindingCandidate]:
    findings: list[AuditFindingCandidate] = []
    for record in records:
        if not _is_configuration_system_change(record):
            continue
        findings.append(
            _finding(
                definition,
                record,
                severity=_configuration_severity(record),
                title="Configuration or system-level change detected",
                summary=(
                    f"Audit record {_record_label(record)} indicates configuration, workflow, lifecycle, "
                    "security setting, metadata, template, rule, or system parameter activity that may require "
                    "change-control evidence."
                ),
            )
        )
    return findings


def _data_export_logging_findings(
    records: list[AuditTrailRecord],
    definition: AuditCheckDefinition,
    config: AuditAnalysisConfig,
) -> list[AuditFindingCandidate]:
    findings: list[AuditFindingCandidate] = []
    for record in records:
        if not _is_export_event(record):
            continue

        missing_traceability = []
        if not _has_user_identity(record):
            missing_traceability.append("user identity")
        if record.event_timestamp is None:
            missing_traceability.append("event timestamp")
        if not _has_object_context(record):
            missing_traceability.append("object/report name")

        severity = "HIGH" if _is_off_hours(record, config) else "MEDIUM"
        if missing_traceability:
            traceability_summary = f" Missing minimum traceability: {', '.join(missing_traceability)}."
        else:
            traceability_summary = " Minimum user, timestamp, and object/report traceability is present."

        findings.append(
            _finding(
                definition,
                record,
                severity=severity,
                title="Export, download, or extraction activity requires review",
                summary=(
                    f"Audit record {_record_label(record)} indicates export/download/report extraction activity."
                    f"{traceability_summary} Recipient or purpose should be reviewed if available in the source system."
                ),
            )
        )
    return findings


def _audit_trail_completeness_findings(
    records: list[AuditTrailRecord],
    definition: AuditCheckDefinition,
) -> list[AuditFindingCandidate]:
    total_records = len(records)
    missing_source_record_key_count = sum(1 for record in records if _is_blank(record.source_record_key))
    missing_timestamp_count = sum(1 for record in records if record.event_timestamp is None)
    source_keys = [str(record.source_record_key).strip() for record in records if not _is_blank(record.source_record_key)]
    duplicate_source_record_key_count = sum(count - 1 for count in Counter(source_keys).values() if count > 1)

    missing_source_record_key_percentage = (
        round((missing_source_record_key_count / total_records) * 100, 2) if total_records else 0
    )
    missing_timestamp_percentage = round((missing_timestamp_count / total_records) * 100, 2) if total_records else 0
    duplicate_source_record_key_percentage = (
        round((duplicate_source_record_key_count / total_records) * 100, 2) if total_records else 0
    )
    evidence = {
        "total_records": total_records,
        "audit_trail_type": "MULTI" if len({record.audit_trail_type for record in records}) > 1 else (records[0].audit_trail_type if records else None),
        "missing_source_record_key_count": missing_source_record_key_count,
        "missing_timestamp_count": missing_timestamp_count,
        "duplicate_source_record_key_count": duplicate_source_record_key_count,
        "missing_source_record_key_percentage": missing_source_record_key_percentage,
        "missing_timestamp_percentage": missing_timestamp_percentage,
    }

    issues = []
    if total_records == 0:
        issues.append("zero records were extracted")
    if missing_source_record_key_percentage > 5:
        issues.append("more than 5% of records are missing source_record_key")
    elif missing_source_record_key_count > 0:
        issues.append("some records are missing source_record_key")
    if missing_timestamp_percentage > 5:
        issues.append("more than 5% of records are missing event_timestamp")
    elif missing_timestamp_count > 0:
        issues.append("some records are missing event_timestamp")
    if duplicate_source_record_key_count > 0:
        issues.append("duplicate source_record_key values were detected")

    if not issues:
        return []

    if total_records == 0:
        severity = "HIGH"
    elif (
        missing_source_record_key_percentage > 5
        or missing_timestamp_percentage > 5
        or duplicate_source_record_key_percentage > 5
    ):
        severity = "MEDIUM"
    else:
        severity = "LOW"

    return [
        _aggregate_finding(
            definition,
            severity=severity,
            title="Extracted audit trail completeness issue detected",
            summary=f"Aggregate completeness review found that {', '.join(issues)}.",
            evidence_json=evidence,
            source_record_count=total_records,
        )
    ]


def _selected_types_for_run(records: list[AuditTrailRecord], config: AuditAnalysisConfig) -> list[str]:
    selected = [item for item in config.selected_audit_trail_types if item]
    if selected:
        return list(dict.fromkeys(selected))
    if config.audit_trail_type:
        return [config.audit_trail_type]
    record_types = [record.audit_trail_type for record in records if record.audit_trail_type]
    return list(dict.fromkeys(record_types)) or list(FULL_GXP_AUDIT_TRAIL_TYPES)


def _record_type(record: AuditTrailRecord) -> str:
    return record.audit_trail_type or "login_audit_trail"


def _applicable_types_for_check(check_code: str, selected_types: list[str]) -> list[str]:
    supported = CHECKPOINT_APPLICABILITY_MATRIX.get(check_code, [])
    return [audit_trail_type for audit_trail_type in selected_types if audit_trail_type in supported]


def _status_for_check(
    *,
    findings: list[AuditFindingCandidate],
    evaluated_count: int,
    no_data_count: int,
) -> str:
    if evaluated_count == 0:
        return CHECK_STATUS_NO_DATA
    if not findings:
        return CHECK_STATUS_PASS

    impacted_records = sum(max(finding.source_record_count, 1) for finding in findings)
    if no_data_count > 0 or impacted_records < evaluated_count:
        return CHECK_STATUS_PARTIAL
    return CHECK_STATUS_FAIL


def _applicability_for_check(status: str) -> str:
    if status in {CHECK_STATUS_NOT_APPLICABLE, CHECK_STATUS_NO_DATA, CHECK_STATUS_PARTIAL}:
        return status
    return CHECK_STATUS_ACTIVE


def run_deterministic_audit_checks(
    records: list[AuditTrailRecord],
    config: AuditAnalysisConfig,
) -> list[AuditCheckResult]:
    selected_types = _selected_types_for_run(records, config)
    total_record_count = len(records)
    results: list[AuditCheckResult] = []

    for definition in CHECK_DEFINITIONS:
        applicable_types = _applicable_types_for_check(definition.check_code, selected_types)
        if not applicable_types:
            results.append(
                AuditCheckResult(
                    definition=definition,
                    findings=[],
                    applicable_record_count=0,
                    evaluated_record_count=0,
                    skipped_record_count=total_record_count,
                    applicability=CHECK_STATUS_NOT_APPLICABLE,
                    check_status=CHECK_STATUS_NOT_APPLICABLE,
                    applicable_audit_trail_types=[],
                    selected_audit_trail_types=selected_types,
                    no_data_count=0,
                )
            )
            continue

        applicable_records = [record for record in records if _record_type(record) in applicable_types]
        skipped_record_count = total_record_count - len(applicable_records)
        types_with_records = {_record_type(record) for record in applicable_records}
        no_data_count = len([audit_type for audit_type in applicable_types if audit_type not in types_with_records])

        if not applicable_records:
            results.append(
                AuditCheckResult(
                    definition=definition,
                    findings=[],
                    applicable_record_count=0,
                    evaluated_record_count=0,
                    skipped_record_count=skipped_record_count,
                    applicability=CHECK_STATUS_NO_DATA,
                    check_status=CHECK_STATUS_NO_DATA,
                    applicable_audit_trail_types=applicable_types,
                    selected_audit_trail_types=selected_types,
                    no_data_count=no_data_count or len(applicable_types),
                )
            )
            continue

        creation_events = [record for record in applicable_records if _is_creation_event(record)]
        modification_events = [record for record in applicable_records if _is_modification_event(record, config)]
        configuration_events = [record for record in applicable_records if _is_configuration_system_change(record)]
        export_events = [record for record in applicable_records if _is_export_event(record)]

        result_by_code = {
            CHECK_MISSING_TIMESTAMP: (
                _missing_timestamp_findings(applicable_records, definition),
                len(applicable_records),
            ),
            CHECK_MISSING_USER_ID: (
                _missing_user_id_findings(applicable_records, definition),
                len(applicable_records),
            ),
            CHECK_RECORD_ADDITION_TRACEABILITY: (
                _record_addition_traceability_findings(applicable_records, definition),
                len(creation_events),
            ),
            CHECK_MODIFICATION_CAPTURE_OLD_NEW_VALUES: (
                _modification_capture_findings(applicable_records, definition, config),
                len(modification_events),
            ),
            CHECK_DELETE_ACTION: (
                _delete_action_findings(applicable_records, definition),
                len(applicable_records),
            ),
            CHECK_OFF_HOURS_ACTIVITY: (
                _off_hours_findings(applicable_records, definition, config),
                len([record for record in applicable_records if record.event_timestamp is not None]),
            ),
            CHECK_PERMISSION_ACCESS_CHANGE: (
                _permission_access_findings(applicable_records, definition),
                len(applicable_records),
            ),
            CHECK_CONFIGURATION_SYSTEM_CHANGE: (
                _configuration_system_change_findings(applicable_records, definition),
                len(configuration_events),
            ),
            CHECK_DATA_EXPORT_LOGGING: (
                _data_export_logging_findings(applicable_records, definition, config),
                len(export_events),
            ),
            CHECK_AUDIT_TRAIL_COMPLETENESS: (
                _audit_trail_completeness_findings(applicable_records, definition),
                len(applicable_records),
            ),
        }
        findings, applicable_record_count = result_by_code[definition.check_code]
        check_status = _status_for_check(
            findings=findings,
            evaluated_count=applicable_record_count,
            no_data_count=no_data_count,
        )
        if no_data_count and check_status == CHECK_STATUS_PASS:
            check_status = CHECK_STATUS_PARTIAL

        results.append(
            AuditCheckResult(
                definition=definition,
                findings=findings,
                applicable_record_count=applicable_record_count,
                evaluated_record_count=applicable_record_count,
                skipped_record_count=skipped_record_count,
                applicability=_applicability_for_check(check_status),
                check_status=check_status,
                applicable_audit_trail_types=applicable_types,
                selected_audit_trail_types=selected_types,
                no_data_count=no_data_count,
            )
        )

    return results
