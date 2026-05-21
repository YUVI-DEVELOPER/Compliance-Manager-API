from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionSeed:
    permission_code: str
    permission_name: str
    module_name: str
    action_name: str
    description: str


@dataclass(frozen=True)
class RoleSeed:
    role_code: str
    role_name: str
    description: str
    permission_codes: tuple[str, ...]
    permission_group_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PermissionGroupSeed:
    group_code: str
    group_name: str
    module_name: str
    description: str
    display_order: int
    permission_codes: tuple[str, ...]


def _permission_name(code: str) -> str:
    return code.replace("_", " ").title()


def _permission(code: str, module: str, action: str, description: str | None = None) -> PermissionSeed:
    return PermissionSeed(
        permission_code=code,
        permission_name=_permission_name(code),
        module_name=module,
        action_name=action,
        description=description or _permission_name(code),
    )


def _group(
    code: str,
    name: str,
    module: str,
    display_order: int,
    permission_codes: tuple[str, ...],
    description: str | None = None,
) -> PermissionGroupSeed:
    return PermissionGroupSeed(
        group_code=code,
        group_name=name,
        module_name=module,
        description=description or name,
        display_order=display_order,
        permission_codes=permission_codes,
    )


PERMISSION_CATALOG: tuple[PermissionSeed, ...] = (
    _permission("DASHBOARD_VIEW", "DASHBOARD", "VIEW"),
    _permission("USER_VIEW", "USER", "VIEW"),
    _permission("USER_CREATE", "USER", "CREATE"),
    _permission("USER_UPDATE", "USER", "UPDATE"),
    _permission("USER_DELETE", "USER", "DELETE"),
    _permission("USER_ASSIGN_ROLE", "USER", "ASSIGN_ROLE"),
    _permission("ROLE_VIEW", "ROLE", "VIEW"),
    _permission("ROLE_CREATE", "ROLE", "CREATE"),
    _permission("ROLE_UPDATE", "ROLE", "UPDATE"),
    _permission("ROLE_DELETE", "ROLE", "DELETE"),
    _permission("ROLE_ASSIGN_PERMISSION", "ROLE", "ASSIGN_PERMISSION"),
    _permission("ORGANIZATION_VIEW", "ORGANIZATION", "VIEW"),
    _permission("ORGANIZATION_CREATE", "ORGANIZATION", "CREATE"),
    _permission("ORGANIZATION_UPDATE", "ORGANIZATION", "UPDATE"),
    _permission("ORGANIZATION_DELETE", "ORGANIZATION", "DELETE"),
    _permission("SUPPLIER_VIEW", "SUPPLIER", "VIEW"),
    _permission("SUPPLIER_CREATE", "SUPPLIER", "CREATE"),
    _permission("SUPPLIER_UPDATE", "SUPPLIER", "UPDATE"),
    _permission("SUPPLIER_DELETE", "SUPPLIER", "DELETE"),
    _permission("ASSET_VIEW", "ASSET", "VIEW"),
    _permission("ASSET_CREATE", "ASSET", "CREATE"),
    _permission("ASSET_UPDATE", "ASSET", "UPDATE"),
    _permission("ASSET_DELETE", "ASSET", "DELETE"),
    _permission("DOCUMENT_VIEW", "DOCUMENT", "VIEW"),
    _permission("DOCUMENT_UPLOAD", "DOCUMENT", "UPLOAD"),
    _permission("DOCUMENT_LINK", "DOCUMENT", "LINK"),
    _permission("DOCUMENT_UPDATE", "DOCUMENT", "UPDATE"),
    _permission("DOCUMENT_DELETE", "DOCUMENT", "DELETE"),
    _permission("AUDIT_REVIEW_VIEW", "AUDIT_REVIEW", "VIEW"),
    _permission("AUDIT_REVIEW_CREATE", "AUDIT_REVIEW", "CREATE"),
    _permission("AUDIT_REVIEW_EXTRACT", "AUDIT_REVIEW", "EXTRACT"),
    _permission("AUDIT_REVIEW_ANALYZE", "AUDIT_REVIEW", "ANALYZE"),
    _permission("AUDIT_RECORD_VIEW", "AUDIT_RECORD", "VIEW"),
    _permission("AUDIT_FINDING_VIEW", "AUDIT_FINDING", "VIEW"),
    _permission("AUDIT_FINDING_REVIEW", "AUDIT_FINDING", "REVIEW"),
    _permission("AUDIT_COMMENT_ADD", "AUDIT_FINDING", "COMMENT_ADD"),
    _permission("AUDIT_REPORT_VIEW", "AUDIT_REPORT", "VIEW"),
    _permission("AUDIT_REPORT_GENERATE", "AUDIT_REPORT", "GENERATE"),
    _permission("AUDIT_REPORT_SUBMIT", "AUDIT_REPORT", "SUBMIT"),
    _permission("AUDIT_REPORT_APPROVE", "AUDIT_REPORT", "APPROVE"),
    _permission("AUDIT_REPORT_REJECT", "AUDIT_REPORT", "REJECT"),
    _permission("AUDIT_REPORT_REQUEST_CHANGES", "AUDIT_REPORT", "REQUEST_CHANGES"),
    _permission("SCHEDULE_VIEW", "SCHEDULE", "VIEW"),
    _permission("SCHEDULE_CREATE", "SCHEDULE", "CREATE"),
    _permission("SCHEDULE_UPDATE", "SCHEDULE", "UPDATE"),
    _permission("SCHEDULE_RUN", "SCHEDULE", "RUN"),
    _permission("SCHEDULE_DELETE", "SCHEDULE", "DELETE"),
    _permission("NOTIFICATION_VIEW", "NOTIFICATION", "VIEW"),
    _permission("NOTIFICATION_MANAGE", "NOTIFICATION", "MANAGE"),
    _permission("LOOKUP_VIEW", "LOOKUP", "VIEW"),
    _permission("LOOKUP_MANAGE", "LOOKUP", "MANAGE"),
    _permission("REPORT_EXPORT", "REPORT", "EXPORT"),
)

PERMISSION_CODES: tuple[str, ...] = tuple(permission.permission_code for permission in PERMISSION_CATALOG)

PERMISSION_GROUP_CATALOG: tuple[PermissionGroupSeed, ...] = (
    _group(
        "SYSTEM_ADMINISTRATION",
        "System Administration",
        "SYSTEM",
        10,
        (
            "USER_VIEW",
            "USER_CREATE",
            "USER_UPDATE",
            "USER_DELETE",
            "USER_ASSIGN_ROLE",
            "ROLE_VIEW",
            "ROLE_CREATE",
            "ROLE_UPDATE",
            "ROLE_DELETE",
            "ROLE_ASSIGN_PERMISSION",
        ),
    ),
    _group(
        "MASTER_DATA_MANAGEMENT",
        "Master Data Management",
        "MASTER_DATA",
        20,
        (
            "ORGANIZATION_VIEW",
            "ORGANIZATION_CREATE",
            "ORGANIZATION_UPDATE",
            "ORGANIZATION_DELETE",
            "SUPPLIER_VIEW",
            "SUPPLIER_CREATE",
            "SUPPLIER_UPDATE",
            "SUPPLIER_DELETE",
            "ASSET_VIEW",
            "ASSET_CREATE",
            "ASSET_UPDATE",
            "ASSET_DELETE",
        ),
    ),
    _group(
        "DOCUMENT_MANAGEMENT",
        "Document Management",
        "DOCUMENT",
        30,
        (
            "DOCUMENT_VIEW",
            "DOCUMENT_UPLOAD",
            "DOCUMENT_LINK",
            "DOCUMENT_UPDATE",
            "DOCUMENT_DELETE",
        ),
    ),
    _group(
        "AUDIT_REVIEW_VIEW",
        "Audit Review View",
        "AUDIT_REVIEW",
        40,
        (
            "AUDIT_REVIEW_VIEW",
            "AUDIT_RECORD_VIEW",
            "AUDIT_FINDING_VIEW",
            "AUDIT_REPORT_VIEW",
        ),
    ),
    _group(
        "AUDIT_REVIEW_EXECUTION",
        "Audit Review Execution",
        "AUDIT_REVIEW",
        50,
        (
            "AUDIT_REVIEW_CREATE",
            "AUDIT_REVIEW_EXTRACT",
            "AUDIT_REVIEW_ANALYZE",
        ),
    ),
    _group(
        "AUDIT_FINDING_REVIEW",
        "Finding Review and Comments",
        "AUDIT_FINDING",
        60,
        (
            "AUDIT_FINDING_REVIEW",
            "AUDIT_COMMENT_ADD",
        ),
    ),
    _group(
        "AUDIT_DRAFT_REPORT_GENERATION",
        "Draft Report Generation",
        "AUDIT_REPORT",
        70,
        (
            "AUDIT_REPORT_GENERATE",
            "AUDIT_REPORT_VIEW",
            "REPORT_EXPORT",
        ),
    ),
    _group(
        "AUDIT_DRAFT_REPORT_PREPARATION",
        "Draft Report Preparation",
        "AUDIT_REPORT",
        71,
        (
            "AUDIT_REPORT_GENERATE",
            "AUDIT_REPORT_VIEW",
            "REPORT_EXPORT",
        ),
        description="Compatibility group for draft report generation without submission rights.",
    ),
    _group(
        "AUDIT_REPORT_SUBMISSION",
        "Audit Report Submission",
        "AUDIT_REPORT",
        75,
        ("AUDIT_REPORT_SUBMIT",),
    ),
    _group(
        "FINAL_QA_APPROVAL",
        "Final QA Approval",
        "AUDIT_REPORT",
        80,
        (
            "AUDIT_REPORT_APPROVE",
            "AUDIT_REPORT_REJECT",
            "AUDIT_REPORT_REQUEST_CHANGES",
        ),
    ),
    _group(
        "SCHEDULE_VIEW_ONLY",
        "Schedule View Only",
        "SCHEDULE",
        90,
        ("SCHEDULE_VIEW",),
    ),
    _group(
        "SCHEDULE_MANAGEMENT",
        "Schedule Management",
        "SCHEDULE",
        100,
        (
            "SCHEDULE_VIEW",
            "SCHEDULE_CREATE",
            "SCHEDULE_UPDATE",
            "SCHEDULE_RUN",
            "SCHEDULE_DELETE",
        ),
    ),
    _group(
        "NOTIFICATION_VIEW_ONLY",
        "Notification View Only",
        "NOTIFICATION",
        110,
        ("NOTIFICATION_VIEW",),
    ),
    _group(
        "NOTIFICATION_MANAGEMENT",
        "Notification Management",
        "NOTIFICATION",
        120,
        (
            "NOTIFICATION_VIEW",
            "NOTIFICATION_MANAGE",
        ),
    ),
    _group(
        "LOOKUP_CONFIGURATION",
        "Lookup Configuration",
        "LOOKUP",
        130,
        (
            "LOOKUP_VIEW",
            "LOOKUP_MANAGE",
        ),
    ),
    _group(
        "DASHBOARD_AND_REPORTS",
        "Dashboard and Reports",
        "REPORT",
        140,
        (
            "DASHBOARD_VIEW",
            "REPORT_EXPORT",
        ),
    ),
)

PERMISSION_GROUP_CODES: tuple[str, ...] = tuple(group.group_code for group in PERMISSION_GROUP_CATALOG)
PERMISSION_GROUP_MAP: dict[str, PermissionGroupSeed] = {
    group.group_code: group for group in PERMISSION_GROUP_CATALOG
}


def _permissions_from_groups(group_codes: tuple[str, ...]) -> tuple[str, ...]:
    permission_codes: list[str] = []
    for group_code in group_codes:
        group = PERMISSION_GROUP_MAP[group_code]
        for permission_code in group.permission_codes:
            if permission_code not in permission_codes:
                permission_codes.append(permission_code)
    return tuple(permission_codes)


ADMIN_PERMISSION_GROUP_CODES: tuple[str, ...] = (
    "SYSTEM_ADMINISTRATION",
    "MASTER_DATA_MANAGEMENT",
    "DOCUMENT_MANAGEMENT",
    "AUDIT_REVIEW_VIEW",
    "AUDIT_REVIEW_EXECUTION",
    "AUDIT_FINDING_REVIEW",
    "AUDIT_DRAFT_REPORT_GENERATION",
    "AUDIT_REPORT_SUBMISSION",
    "SCHEDULE_MANAGEMENT",
    "NOTIFICATION_MANAGEMENT",
    "LOOKUP_CONFIGURATION",
    "DASHBOARD_AND_REPORTS",
)

QA_REVIEWER_PERMISSION_GROUP_CODES: tuple[str, ...] = (
    "DASHBOARD_AND_REPORTS",
    "AUDIT_REVIEW_VIEW",
    "AUDIT_REVIEW_EXECUTION",
    "AUDIT_FINDING_REVIEW",
    "AUDIT_DRAFT_REPORT_GENERATION",
    "AUDIT_REPORT_SUBMISSION",
    "SCHEDULE_MANAGEMENT",
)

QA_VALIDATION_MANAGER_PERMISSION_GROUP_CODES: tuple[str, ...] = (
    "DASHBOARD_AND_REPORTS",
    "AUDIT_REVIEW_VIEW",
    "AUDIT_FINDING_REVIEW",
    "FINAL_QA_APPROVAL",
    "SCHEDULE_VIEW_ONLY",
    "NOTIFICATION_VIEW_ONLY",
)

ADMIN_PERMISSION_CODES: tuple[str, ...] = _permissions_from_groups(ADMIN_PERMISSION_GROUP_CODES)

QA_REVIEWER_PERMISSION_CODES: tuple[str, ...] = _permissions_from_groups(QA_REVIEWER_PERMISSION_GROUP_CODES)

QA_VALIDATION_MANAGER_PERMISSION_CODES: tuple[str, ...] = _permissions_from_groups(
    QA_VALIDATION_MANAGER_PERMISSION_GROUP_CODES
)

ROLE_CATALOG: tuple[RoleSeed, ...] = (
    RoleSeed(
        role_code="ADMIN",
        role_name="Administrator",
        description="System configuration and operational administration without final audit report approval by default.",
        permission_codes=ADMIN_PERMISSION_CODES,
        permission_group_codes=ADMIN_PERMISSION_GROUP_CODES,
    ),
    RoleSeed(
        role_code="QA_REVIEWER",
        role_name="QA Reviewer",
        description="Reviews audit findings, comments, records, and draft audit review report content.",
        permission_codes=QA_REVIEWER_PERMISSION_CODES,
        permission_group_codes=QA_REVIEWER_PERMISSION_GROUP_CODES,
    ),
    RoleSeed(
        role_code="QA_VALIDATION_MANAGER",
        role_name="QA Validation Manager",
        description="Provides final QA validation decisions for submitted audit review reports.",
        permission_codes=QA_VALIDATION_MANAGER_PERMISSION_CODES,
        permission_group_codes=QA_VALIDATION_MANAGER_PERMISSION_GROUP_CODES,
    ),
)
