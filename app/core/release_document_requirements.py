from __future__ import annotations

from dataclasses import dataclass


DOCUMENT_CATEGORY_RELEASE_SOURCE = "RELEASE_SOURCE"
DOCUMENT_CATEGORY_ASSESSMENT = "ASSESSMENT"
DOCUMENT_CATEGORY_SPECIFICATION = "SPECIFICATION"
DOCUMENT_CATEGORY_PROTOCOL = "PROTOCOL"
DOCUMENT_CATEGORY_EVIDENCE = "EVIDENCE"
DOCUMENT_CATEGORY_GOVERNANCE = "GOVERNANCE"
DOCUMENT_CATEGORY_TRAINING_SOP = "TRAINING_SOP"

REQUIREMENT_LEVEL_REQUIRED = "REQUIRED"
REQUIREMENT_LEVEL_CONDITIONAL = "CONDITIONAL"
REQUIREMENT_LEVEL_OPTIONAL = "OPTIONAL"
REQUIREMENT_LEVEL_NOT_REQUIRED = "NOT_REQUIRED"

DOCUMENT_STATUS_MISSING = "MISSING"
DOCUMENT_STATUS_DRAFT = "DRAFT"
DOCUMENT_STATUS_UPLOADED = "UPLOADED"
DOCUMENT_STATUS_LINKED = "LINKED"
DOCUMENT_STATUS_IN_REVIEW = "IN_REVIEW"
DOCUMENT_STATUS_APPROVED = "APPROVED"
DOCUMENT_STATUS_REJECTED = "REJECTED"
DOCUMENT_STATUS_WAIVED = "WAIVED"
DOCUMENT_STATUS_NOT_REQUIRED = "NOT_REQUIRED"
DOCUMENT_STATUS_OBSOLETE = "OBSOLETE"

VALIDATION_SCOPE_NO_VALIDATION_REQUIRED = "NO_VALIDATION_REQUIRED"
VALIDATION_SCOPE_LIMITED_VALIDATION = "LIMITED_VALIDATION"
VALIDATION_SCOPE_FULL_VALIDATION = "FULL_VALIDATION"
VALIDATION_SCOPES = (
    VALIDATION_SCOPE_NO_VALIDATION_REQUIRED,
    VALIDATION_SCOPE_LIMITED_VALIDATION,
    VALIDATION_SCOPE_FULL_VALIDATION,
)


@dataclass(frozen=True, slots=True)
class DocumentRequirementRule:
    code: str
    name: str
    category: str
    description: str | None
    base_scopes: tuple[str, ...]
    conditional_scopes: tuple[str, ...]
    trigger_questions: tuple[str, ...]
    requirement_level: str
    required_flag: bool
    waivable_flag: bool
    waiver_requires_qa_flag: bool
    owner_role: str | None
    display_order: int


def _rule(
    code: str,
    name: str,
    category: str,
    *,
    description: str | None = None,
    base_scopes: tuple[str, ...] = (),
    conditional_scopes: tuple[str, ...] = VALIDATION_SCOPES,
    trigger_questions: tuple[str, ...] = (),
    requirement_level: str = REQUIREMENT_LEVEL_REQUIRED,
    required_flag: bool = True,
    waivable_flag: bool = True,
    waiver_requires_qa_flag: bool = True,
    owner_role: str | None = "Validation Owner",
    display_order: int,
) -> DocumentRequirementRule:
    return DocumentRequirementRule(
        code=code,
        name=name,
        category=category,
        description=description,
        base_scopes=base_scopes,
        conditional_scopes=conditional_scopes,
        trigger_questions=trigger_questions,
        requirement_level=requirement_level,
        required_flag=required_flag,
        waivable_flag=waivable_flag,
        waiver_requires_qa_flag=waiver_requires_qa_flag,
        owner_role=owner_role,
        display_order=display_order,
    )


ALL_SCOPES = VALIDATION_SCOPES
LIMITED_AND_FULL = (VALIDATION_SCOPE_LIMITED_VALIDATION, VALIDATION_SCOPE_FULL_VALIDATION)
FULL_ONLY = (VALIDATION_SCOPE_FULL_VALIDATION,)
NO_VALIDATION_ONLY = (VALIDATION_SCOPE_NO_VALIDATION_REQUIRED,)

DOCUMENT_REQUIREMENT_RULES: tuple[DocumentRequirementRule, ...] = (
    _rule(
        "RELEASE_NOTES",
        "Release Notes / Release Source Documentation",
        DOCUMENT_CATEGORY_RELEASE_SOURCE,
        description="Release source information used to assess the validation impact.",
        base_scopes=ALL_SCOPES,
        waivable_flag=False,
        owner_role="System Owner",
        display_order=10,
    ),
    _rule(
        "IMPACT_ASSESSMENT",
        "Impact Assessment Record",
        DOCUMENT_CATEGORY_ASSESSMENT,
        description="Completed Step 2 impact assessment and scoring conclusion.",
        base_scopes=ALL_SCOPES,
        waivable_flag=False,
        owner_role="Validation Owner",
        display_order=20,
    ),
    _rule(
        "RISK_ASSESSMENT",
        "Risk Assessment / Risk Conclusion",
        DOCUMENT_CATEGORY_ASSESSMENT,
        description="Documented risk conclusion supporting the validation scope.",
        base_scopes=ALL_SCOPES,
        trigger_questions=("GXP_IMPACT",),
        waivable_flag=False,
        owner_role="Quality Assurance",
        display_order=30,
    ),
    _rule(
        "NO_VALIDATION_JUSTIFICATION",
        "No Validation Required Justification",
        DOCUMENT_CATEGORY_ASSESSMENT,
        description="Justification for no validation required based on assessed impact.",
        base_scopes=NO_VALIDATION_ONLY,
        waivable_flag=False,
        owner_role="Validation Owner",
        display_order=40,
    ),
    _rule(
        "QA_APPROVAL_PLACEHOLDER",
        "QA Approval Placeholder",
        DOCUMENT_CATEGORY_GOVERNANCE,
        description="QA approval placeholder for no-validation-required release closure.",
        base_scopes=NO_VALIDATION_ONLY,
        waivable_flag=False,
        owner_role="Quality Assurance",
        display_order=50,
    ),
    _rule(
        "CHANGE_CONTROL",
        "Change Control Record",
        DOCUMENT_CATEGORY_GOVERNANCE,
        description="Approved or referenced change control for the release.",
        base_scopes=LIMITED_AND_FULL,
        trigger_questions=("GXP_IMPACT",),
        owner_role="Quality Assurance",
        display_order=60,
    ),
    _rule(
        "VALIDATION_PLAN",
        "Validation Plan",
        DOCUMENT_CATEGORY_GOVERNANCE,
        description="Plan defining validation approach, responsibilities, and deliverables.",
        base_scopes=FULL_ONLY,
        owner_role="Validation Owner",
        display_order=70,
    ),
    _rule(
        "URS",
        "User Requirements Specification",
        DOCUMENT_CATEGORY_SPECIFICATION,
        base_scopes=FULL_ONLY,
        owner_role="Business Owner",
        display_order=80,
    ),
    _rule(
        "FRS",
        "Functional Requirements Specification",
        DOCUMENT_CATEGORY_SPECIFICATION,
        base_scopes=FULL_ONLY,
        trigger_questions=("WORKFLOW",),
        owner_role="System Owner",
        display_order=90,
    ),
    _rule(
        "CONFIGURATION_SPECIFICATION",
        "Configuration Specification",
        DOCUMENT_CATEGORY_SPECIFICATION,
        base_scopes=FULL_ONLY,
        trigger_questions=("CONFIGURATION",),
        owner_role="System Owner",
        display_order=100,
    ),
    _rule(
        "DESIGN_SPECIFICATION",
        "Design Specification",
        DOCUMENT_CATEGORY_SPECIFICATION,
        base_scopes=FULL_ONLY,
        owner_role="System Owner",
        display_order=110,
    ),
    _rule(
        "IQ_PROTOCOL",
        "IQ Protocol",
        DOCUMENT_CATEGORY_PROTOCOL,
        base_scopes=FULL_ONLY,
        trigger_questions=("INFRASTRUCTURE",),
        owner_role="Validation Owner",
        display_order=120,
    ),
    _rule(
        "IQ_EVIDENCE",
        "IQ Evidence",
        DOCUMENT_CATEGORY_EVIDENCE,
        base_scopes=FULL_ONLY,
        trigger_questions=("INFRASTRUCTURE",),
        owner_role="Validation Owner",
        display_order=130,
    ),
    _rule(
        "OQ_PROTOCOL",
        "OQ Protocol",
        DOCUMENT_CATEGORY_PROTOCOL,
        base_scopes=FULL_ONLY,
        trigger_questions=("CONFIGURATION", "WORKFLOW"),
        owner_role="Validation Owner",
        display_order=140,
    ),
    _rule(
        "OQ_EVIDENCE",
        "OQ Evidence",
        DOCUMENT_CATEGORY_EVIDENCE,
        base_scopes=FULL_ONLY,
        trigger_questions=("CONFIGURATION", "REPORTS_CALCULATIONS"),
        owner_role="Validation Owner",
        display_order=150,
    ),
    _rule(
        "PQ_UAT_PROTOCOL",
        "PQ / UAT Protocol",
        DOCUMENT_CATEGORY_PROTOCOL,
        base_scopes=FULL_ONLY,
        trigger_questions=("WORKFLOW",),
        owner_role="Business Owner",
        display_order=160,
    ),
    _rule(
        "PQ_UAT_EVIDENCE",
        "PQ / UAT Evidence",
        DOCUMENT_CATEGORY_EVIDENCE,
        base_scopes=FULL_ONLY,
        trigger_questions=("REPORTS_CALCULATIONS",),
        owner_role="Business Owner",
        display_order=170,
    ),
    _rule(
        "REGRESSION_PROTOCOL",
        "Regression Test Protocol",
        DOCUMENT_CATEGORY_PROTOCOL,
        base_scopes=LIMITED_AND_FULL,
        trigger_questions=("REGRESSION_IMPACT",),
        owner_role="Validation Owner",
        display_order=180,
    ),
    _rule(
        "REGRESSION_EVIDENCE",
        "Regression Test Evidence",
        DOCUMENT_CATEGORY_EVIDENCE,
        base_scopes=LIMITED_AND_FULL,
        trigger_questions=("CONFIGURATION", "AUDIT_TRAIL", "REGRESSION_IMPACT"),
        owner_role="Validation Owner",
        display_order=190,
    ),
    _rule(
        "RTM",
        "Requirements Traceability Matrix",
        DOCUMENT_CATEGORY_GOVERNANCE,
        base_scopes=FULL_ONLY,
        owner_role="Validation Owner",
        display_order=200,
    ),
    _rule(
        "VALIDATION_SUMMARY_REPORT",
        "Validation Summary Report",
        DOCUMENT_CATEGORY_GOVERNANCE,
        base_scopes=LIMITED_AND_FULL,
        trigger_questions=("GXP_IMPACT",),
        waivable_flag=False,
        owner_role="Validation Owner",
        display_order=210,
    ),
    _rule(
        "QA_APPROVAL",
        "QA Approval",
        DOCUMENT_CATEGORY_GOVERNANCE,
        base_scopes=LIMITED_AND_FULL,
        trigger_questions=("GXP_IMPACT",),
        waivable_flag=False,
        owner_role="Quality Assurance",
        display_order=220,
    ),
    _rule(
        "GO_LIVE_APPROVAL",
        "Go-Live Approval",
        DOCUMENT_CATEGORY_GOVERNANCE,
        base_scopes=FULL_ONLY,
        owner_role="Quality Assurance",
        display_order=230,
    ),
    _rule(
        "ROLLBACK_PLAN",
        "Rollback Plan",
        DOCUMENT_CATEGORY_GOVERNANCE,
        base_scopes=FULL_ONLY,
        owner_role="System Owner",
        display_order=240,
    ),
    _rule(
        "SOP_TRAINING_REVIEW",
        "SOP / Training Impact Review",
        DOCUMENT_CATEGORY_TRAINING_SOP,
        trigger_questions=("WORKFLOW",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Training Owner",
        display_order=250,
    ),
    _rule(
        "AUDIT_TRAIL_OQ",
        "Audit Trail OQ",
        DOCUMENT_CATEGORY_PROTOCOL,
        trigger_questions=("AUDIT_TRAIL",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Validation Owner",
        display_order=260,
    ),
    _rule(
        "PART11_ANNEX11_ASSESSMENT",
        "Part 11 / Annex 11 Assessment",
        DOCUMENT_CATEGORY_ASSESSMENT,
        trigger_questions=("AUDIT_TRAIL", "E_SIGNATURE"),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Quality Assurance",
        display_order=270,
    ),
    _rule(
        "ESIGNATURE_OQ",
        "E-Signature OQ",
        DOCUMENT_CATEGORY_PROTOCOL,
        trigger_questions=("E_SIGNATURE",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Validation Owner",
        display_order=280,
    ),
    _rule(
        "APPROVAL_WORKFLOW_EVIDENCE",
        "Approval Workflow Evidence",
        DOCUMENT_CATEGORY_EVIDENCE,
        trigger_questions=("E_SIGNATURE",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Quality Assurance",
        display_order=290,
    ),
    _rule(
        "SECURITY_ASSESSMENT",
        "Security Assessment",
        DOCUMENT_CATEGORY_ASSESSMENT,
        trigger_questions=("SECURITY_ACCESS",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Security Owner",
        display_order=300,
    ),
    _rule(
        "ROLE_PERMISSION_TEST_EVIDENCE",
        "Role / Permission Test Evidence",
        DOCUMENT_CATEGORY_EVIDENCE,
        trigger_questions=("SECURITY_ACCESS",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Security Owner",
        display_order=310,
    ),
    _rule(
        "REPORT_SPECIFICATION",
        "Report Specification",
        DOCUMENT_CATEGORY_SPECIFICATION,
        trigger_questions=("REPORTS_CALCULATIONS",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Business Owner",
        display_order=320,
    ),
    _rule(
        "CALCULATION_VERIFICATION_EVIDENCE",
        "Calculation Verification Evidence",
        DOCUMENT_CATEGORY_EVIDENCE,
        trigger_questions=("REPORTS_CALCULATIONS",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Validation Owner",
        display_order=330,
    ),
    _rule(
        "INTERFACE_SPECIFICATION",
        "Interface Specification",
        DOCUMENT_CATEGORY_SPECIFICATION,
        trigger_questions=("INTEGRATION_API",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="System Owner",
        display_order=340,
    ),
    _rule(
        "INTEGRATION_TEST_PROTOCOL",
        "Integration Test Protocol",
        DOCUMENT_CATEGORY_PROTOCOL,
        trigger_questions=("INTEGRATION_API",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Validation Owner",
        display_order=350,
    ),
    _rule(
        "INTEGRATION_EVIDENCE",
        "Integration Evidence",
        DOCUMENT_CATEGORY_EVIDENCE,
        trigger_questions=("INTEGRATION_API",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Validation Owner",
        display_order=360,
    ),
    _rule(
        "DATA_MIGRATION_PLAN",
        "Data Migration Plan",
        DOCUMENT_CATEGORY_GOVERNANCE,
        trigger_questions=("DATA_MIGRATION",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Data Owner",
        display_order=370,
    ),
    _rule(
        "MIGRATION_PROTOCOL",
        "Migration Protocol",
        DOCUMENT_CATEGORY_PROTOCOL,
        trigger_questions=("DATA_MIGRATION",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Validation Owner",
        display_order=380,
    ),
    _rule(
        "RECONCILIATION_EVIDENCE",
        "Reconciliation Evidence",
        DOCUMENT_CATEGORY_EVIDENCE,
        trigger_questions=("DATA_MIGRATION",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Data Owner",
        display_order=390,
    ),
    _rule(
        "COMPATIBILITY_MATRIX",
        "Compatibility Matrix",
        DOCUMENT_CATEGORY_SPECIFICATION,
        trigger_questions=("INFRASTRUCTURE",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="System Owner",
        display_order=400,
    ),
    _rule(
        "SOP_UPDATE",
        "SOP Update",
        DOCUMENT_CATEGORY_TRAINING_SOP,
        trigger_questions=("SOP_TRAINING",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Training Owner",
        display_order=410,
    ),
    _rule(
        "TRAINING_RECORD",
        "Training Record",
        DOCUMENT_CATEGORY_TRAINING_SOP,
        trigger_questions=("SOP_TRAINING",),
        requirement_level=REQUIREMENT_LEVEL_CONDITIONAL,
        owner_role="Training Owner",
        display_order=420,
    ),
)


def get_document_requirement_rules() -> tuple[DocumentRequirementRule, ...]:
    return DOCUMENT_REQUIREMENT_RULES
