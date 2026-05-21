import asyncio
import inspect
import uuid

from fastapi import HTTPException, status

from app.core.auth_dependencies import get_current_user, require_permission
from app.core.rbac import (
    ADMIN_PERMISSION_CODES,
    ADMIN_PERMISSION_GROUP_CODES,
    PERMISSION_GROUP_MAP,
    QA_REVIEWER_PERMISSION_CODES,
    QA_REVIEWER_PERMISSION_GROUP_CODES,
    QA_VALIDATION_MANAGER_PERMISSION_CODES,
    QA_VALIDATION_MANAGER_PERMISSION_GROUP_CODES,
)
from app.routers import audit_review_router
from app.schemas.auth_schema import CurrentUser


def test_audit_report_permission_groups_are_split_by_workflow_responsibility() -> None:
    assert set(PERMISSION_GROUP_MAP["AUDIT_DRAFT_REPORT_GENERATION"].permission_codes) == {
        "AUDIT_REPORT_GENERATE",
        "AUDIT_REPORT_VIEW",
        "REPORT_EXPORT",
    }
    assert set(PERMISSION_GROUP_MAP["AUDIT_REPORT_SUBMISSION"].permission_codes) == {
        "AUDIT_REPORT_SUBMIT",
    }
    assert set(PERMISSION_GROUP_MAP["FINAL_QA_APPROVAL"].permission_codes) == {
        "AUDIT_REPORT_APPROVE",
        "AUDIT_REPORT_REJECT",
        "AUDIT_REPORT_REQUEST_CHANGES",
    }


def test_legacy_draft_report_preparation_group_no_longer_grants_submission() -> None:
    legacy_group_permissions = set(PERMISSION_GROUP_MAP["AUDIT_DRAFT_REPORT_PREPARATION"].permission_codes)

    assert "AUDIT_REPORT_SUBMIT" not in legacy_group_permissions
    assert legacy_group_permissions == {
        "AUDIT_REPORT_GENERATE",
        "AUDIT_REPORT_VIEW",
        "REPORT_EXPORT",
    }


def test_qa_reviewer_default_role_can_run_submit_and_respond_but_not_approve() -> None:
    permissions = set(QA_REVIEWER_PERMISSION_CODES)
    groups = set(QA_REVIEWER_PERMISSION_GROUP_CODES)

    assert "AUDIT_REVIEW_EXECUTION" in groups
    assert "AUDIT_DRAFT_REPORT_GENERATION" in groups
    assert "AUDIT_REPORT_SUBMISSION" in groups
    assert "FINAL_QA_APPROVAL" not in groups
    assert "SCHEDULE_VIEW_ONLY" not in groups
    assert "SCHEDULE_MANAGEMENT" in groups
    assert "SYSTEM_ADMINISTRATION" not in groups
    assert "MASTER_DATA_MANAGEMENT" not in groups

    assert {"AUDIT_REVIEW_VIEW", "AUDIT_RECORD_VIEW", "AUDIT_FINDING_VIEW", "AUDIT_FINDING_REVIEW"}.issubset(permissions)
    assert {"AUDIT_REVIEW_CREATE", "AUDIT_REVIEW_EXTRACT", "AUDIT_REVIEW_ANALYZE"}.issubset(permissions)
    assert {"AUDIT_REPORT_VIEW", "AUDIT_REPORT_GENERATE", "REPORT_EXPORT"}.issubset(permissions)
    assert "AUDIT_REPORT_SUBMIT" in permissions
    assert "AUDIT_REPORT_APPROVE" not in permissions
    assert "AUDIT_REPORT_REJECT" not in permissions
    assert "AUDIT_REPORT_REQUEST_CHANGES" not in permissions
    assert {"SCHEDULE_VIEW", "SCHEDULE_CREATE", "SCHEDULE_UPDATE", "SCHEDULE_RUN", "SCHEDULE_DELETE"}.issubset(permissions)


def test_admin_default_role_can_submit_but_not_make_final_qa_decisions() -> None:
    permissions = set(ADMIN_PERMISSION_CODES)
    groups = set(ADMIN_PERMISSION_GROUP_CODES)

    assert "AUDIT_DRAFT_REPORT_GENERATION" in groups
    assert "AUDIT_REPORT_SUBMISSION" in groups
    assert "FINAL_QA_APPROVAL" not in groups

    assert "AUDIT_REPORT_SUBMIT" in permissions
    assert "AUDIT_REPORT_APPROVE" not in permissions
    assert "AUDIT_REPORT_REJECT" not in permissions
    assert "AUDIT_REPORT_REQUEST_CHANGES" not in permissions


def test_qa_validation_manager_default_role_can_decide_but_not_generate_or_submit() -> None:
    permissions = set(QA_VALIDATION_MANAGER_PERMISSION_CODES)
    groups = set(QA_VALIDATION_MANAGER_PERMISSION_GROUP_CODES)

    assert "FINAL_QA_APPROVAL" in groups
    assert "AUDIT_REPORT_SUBMISSION" not in groups
    assert "AUDIT_DRAFT_REPORT_GENERATION" not in groups
    assert "AUDIT_REVIEW_EXECUTION" not in groups
    assert "SCHEDULE_MANAGEMENT" not in groups

    assert {"AUDIT_REPORT_APPROVE", "AUDIT_REPORT_REJECT", "AUDIT_REPORT_REQUEST_CHANGES"}.issubset(permissions)
    assert "AUDIT_REPORT_SUBMIT" not in permissions
    assert "AUDIT_REPORT_GENERATE" not in permissions
    assert "AUDIT_REVIEW_CREATE" not in permissions
    assert "AUDIT_REVIEW_EXTRACT" not in permissions
    assert "AUDIT_REVIEW_ANALYZE" not in permissions


def test_audit_review_workflow_endpoints_require_exact_permissions() -> None:
    expected_endpoint_permissions = {
        "audit_review_report_submit_review": "AUDIT_REPORT_SUBMIT",
        "audit_review_report_approve": "AUDIT_REPORT_APPROVE",
        "audit_review_report_reject": "AUDIT_REPORT_REJECT",
        "audit_review_report_request_changes": "AUDIT_REPORT_REQUEST_CHANGES",
        "audit_review_schedule_create_or_update": "SCHEDULE_CREATE",
        "audit_review_schedule_update": "SCHEDULE_UPDATE",
        "audit_review_schedule_run_now": "SCHEDULE_RUN",
        "audit_review_scheduler_run_due": "SCHEDULE_RUN",
    }

    for endpoint_name, permission_code in expected_endpoint_permissions.items():
        endpoint = getattr(audit_review_router, endpoint_name)
        current_user_dependency = inspect.signature(endpoint).parameters["current_user"].default.dependency
        closure_values = [cell.cell_contents for cell in (current_user_dependency.__closure__ or ())]

        assert permission_code in closure_values


def test_auth_dependencies_return_401_for_missing_token_and_403_for_missing_permission() -> None:
    async def exercise_dependencies() -> None:
        try:
            await get_current_user(credentials=None, db=None)
        except HTTPException as exc:
            assert exc.status_code == status.HTTP_401_UNAUTHORIZED
        else:
            raise AssertionError("Missing token should raise HTTP 401")

        dependency = require_permission("AUDIT_REPORT_SUBMIT")
        current_user = CurrentUser(
            id=uuid.uuid4(),
            full_name="QA Reviewer",
            email="qa.reviewer@example.com",
            roles=["QA_REVIEWER"],
            permissions=["AUDIT_REPORT_VIEW"],
        )

        try:
            await dependency(current_user=current_user)
        except HTTPException as exc:
            assert exc.status_code == status.HTTP_403_FORBIDDEN
        else:
            raise AssertionError("Missing permission should raise HTTP 403")

    asyncio.run(exercise_dependencies())
