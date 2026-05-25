from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReleaseImpactQuestion:
    question_code: str
    category: str
    question_text: str
    weight: int
    critical: bool
    mandatory: bool


RELEASE_IMPACT_QUESTIONS: tuple[ReleaseImpactQuestion, ...] = (
    ReleaseImpactQuestion(
        question_code="GXP_IMPACT",
        category="GxP Impact",
        question_text="Does this release impact any GxP-regulated process or validated business process?",
        weight=5,
        critical=True,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="DATA_INTEGRITY",
        category="Data Integrity",
        question_text="Does this release affect data creation, modification, deletion, retention, or reporting?",
        weight=5,
        critical=True,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="AUDIT_TRAIL",
        category="Audit Trail",
        question_text="Does this release affect audit trail generation, review, export, filtering, retention, or visibility?",
        weight=5,
        critical=True,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="E_SIGNATURE",
        category="Electronic Signature",
        question_text="Does this release affect electronic signature, approval, certification, or review workflow?",
        weight=5,
        critical=True,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="SECURITY_ACCESS",
        category="Security / Access",
        question_text="Does this release affect roles, permissions, authentication, MFA, SSO, or access control?",
        weight=4,
        critical=False,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="CONFIGURATION",
        category="Configuration",
        question_text="Does this release introduce or modify configuration, feature flags, workflows, rules, or admin settings?",
        weight=3,
        critical=False,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="WORKFLOW",
        category="Workflow",
        question_text="Does this release modify business workflow, approval routing, state transition, or user task flow?",
        weight=4,
        critical=False,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="REPORTS_CALCULATIONS",
        category="Reports / Calculations",
        question_text="Does this release affect reports, dashboards, calculations, exports, labels, or generated outputs?",
        weight=5,
        critical=True,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="INTEGRATION_API",
        category="Integration / API",
        question_text="Does this release affect inbound/outbound integrations, API contracts, imports, exports, jobs, or connectors?",
        weight=4,
        critical=False,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="DATA_MIGRATION",
        category="Data Migration",
        question_text="Does this release require data migration, transformation, backfill, or database schema changes?",
        weight=5,
        critical=True,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="INFRASTRUCTURE",
        category="Infrastructure",
        question_text="Does this release affect browser, OS, database, server, deployment, network, or hosting configuration?",
        weight=3,
        critical=False,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="SOP_TRAINING",
        category="SOP / Training",
        question_text="Does this release require SOP, work instruction, user guide, or training update?",
        weight=2,
        critical=False,
        mandatory=True,
    ),
    ReleaseImpactQuestion(
        question_code="REGRESSION_IMPACT",
        category="Regression Impact",
        question_text="Can this release impact previously validated functionality?",
        weight=4,
        critical=False,
        mandatory=True,
    ),
)


def get_release_impact_questions() -> tuple[ReleaseImpactQuestion, ...]:
    return RELEASE_IMPACT_QUESTIONS


def get_release_impact_question_map() -> dict[str, ReleaseImpactQuestion]:
    return {question.question_code: question for question in RELEASE_IMPACT_QUESTIONS}
