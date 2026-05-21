from __future__ import annotations

from datetime import UTC, datetime

from app.models.audit_trail_record import AuditTrailRecord
from app.services.audit_review_checks_service import (
    AuditAnalysisConfig,
    CHECK_RECORD_ADDITION_TRACEABILITY,
    CHECK_MISSING_TIMESTAMP,
    run_deterministic_audit_checks,
)
from app.services.audit_review_scoring_service import calculate_audit_review_score


def _record(
    audit_trail_type: str,
    *,
    event_timestamp: datetime | None = None,
    action_type: str = "LOGIN_SUCCESS",
) -> AuditTrailRecord:
    return AuditTrailRecord(
        audit_trail_type=audit_trail_type,
        source_record_key=f"{audit_trail_type}:1",
        event_timestamp=event_timestamp,
        user_id="qa.user",
        user_name="QA User",
        action_type=action_type,
        object_type="document" if audit_trail_type == "document_audit_trail" else None,
        record_quality_status="VALID",
        raw_payload_json={},
        normalized_extra_json={},
        is_delete_action=False,
        is_permission_change=False,
        is_export_action=False,
        is_configuration_change=False,
    )


def test_login_only_unsupported_check_is_not_applicable() -> None:
    results = run_deterministic_audit_checks(
        [_record("login_audit_trail", event_timestamp=datetime(2026, 5, 11, 10, 0, tzinfo=UTC))],
        AuditAnalysisConfig(audit_trail_type="login_audit_trail", selected_audit_trail_types=("login_audit_trail",)),
    )
    addition = next(result for result in results if result.definition.check_code == CHECK_RECORD_ADDITION_TRACEABILITY)

    assert addition.check_status == "NOT_APPLICABLE"
    assert addition.applicability == "NOT_APPLICABLE"
    assert addition.evaluated_record_count == 0


def test_applicable_check_with_zero_records_is_no_data() -> None:
    results = run_deterministic_audit_checks(
        [],
        AuditAnalysisConfig(audit_trail_type="document_audit_trail", selected_audit_trail_types=("document_audit_trail",)),
    )
    timestamp = next(result for result in results if result.definition.check_code == CHECK_MISSING_TIMESTAMP)

    assert timestamp.check_status == "NO_DATA"
    assert timestamp.applicability == "NO_DATA"


def test_no_data_does_not_become_pass_in_scoring() -> None:
    results = run_deterministic_audit_checks(
        [],
        AuditAnalysisConfig(audit_trail_type="document_audit_trail", selected_audit_trail_types=("document_audit_trail",)),
    )
    scoring = calculate_audit_review_score(
        results,
        total_records_analyzed=0,
        review_scope="DOCUMENT_ONLY",
        selected_audit_trail_types=["document_audit_trail"],
    )

    assert any(item.score_status == "NO_DATA" for item in scoring.score_breakdown)
    assert not any(item.score_status == "PASS" for item in scoring.score_breakdown if item.no_data_count > 0)


def test_score_label_full_gxp_only_for_all_types() -> None:
    login_scoring = calculate_audit_review_score(
        [],
        total_records_analyzed=0,
        review_scope="LOGIN_ONLY",
        selected_audit_trail_types=["login_audit_trail"],
    )
    full_scoring = calculate_audit_review_score(
        [],
        total_records_analyzed=0,
        review_scope="FULL_GXP",
        selected_audit_trail_types=[
            "login_audit_trail",
            "document_audit_trail",
            "object_audit_trail",
            "system_audit_trail",
            "domain_audit_trail",
        ],
    )

    assert login_scoring.score_label == "Login Audit Trail Score"
    assert full_scoring.score_label == "Full GxP Audit Trail Score"
