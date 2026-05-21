from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models.audit_review_job import AuditReviewJob
from app.models.audit_review_score import AuditReviewScore
from app.services.audit_review_checks_service import (
    CHECK_STATUS_NO_DATA,
    CHECK_STATUS_NOT_APPLICABLE,
    AuditCheckResult,
)
from app.services.audit_review_metadata import REVIEW_SCOPES, SUPPORTED_AUDIT_TRAIL_TYPES, resolve_review_scope, score_label_for_scope


OVERALL_CHECK_CODE = "OVERALL"
OVERALL_CHECK_NAME = "Overall Compliance Score"
SCORE_STATUS_SCORED = "SCORED"
SCORE_STATUS_PASS = "PASS"
SCORE_STATUS_REVIEW_REQUIRED = "REVIEW_REQUIRED"
SCORE_STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
SCORE_SCOPE_CHECKPOINT = "CHECKPOINT"
SCORE_SCOPE_AUDIT_TYPE = "AUDIT_TYPE"
SCORE_SCOPE_OVERALL = "OVERALL"


@dataclass(frozen=True)
class ScoreBreakdownItem:
    check_code: str
    check_name: str
    score_scope: str
    audit_trail_type: str
    score_label: str | None
    applicability: str | None
    finding_count: int
    penalty_per_finding: int
    penalty_cap: int
    raw_penalty: int
    applied_penalty: int
    applicable_record_count: int
    evaluated_record_count: int
    skipped_record_count: int
    no_data_count: int
    source_record_count: int
    score_status: str
    sort_order: int
    overall_score: int | None = None
    rating: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_code": self.check_code,
            "check_name": self.check_name,
            "score_scope": self.score_scope,
            "audit_trail_type": self.audit_trail_type,
            "score_label": self.score_label,
            "applicability": self.applicability,
            "finding_count": self.finding_count,
            "penalty_per_finding": self.penalty_per_finding,
            "penalty_cap": self.penalty_cap,
            "raw_penalty": self.raw_penalty,
            "applied_penalty": self.applied_penalty,
            "applicable_record_count": self.applicable_record_count,
            "evaluated_record_count": self.evaluated_record_count,
            "skipped_record_count": self.skipped_record_count,
            "no_data_count": self.no_data_count,
            "source_record_count": self.source_record_count,
            "score_status": self.score_status,
            "sort_order": self.sort_order,
            "overall_score": self.overall_score,
            "rating": self.rating,
        }


@dataclass(frozen=True)
class AuditScoringResult:
    overall_score: int
    rating: str
    score_label: str
    total_records_analyzed: int
    total_findings: int
    finding_counts_by_severity: dict[str, int]
    score_breakdown: list[ScoreBreakdownItem]
    audit_type_scores: list[ScoreBreakdownItem]
    checkpoint_scores: list[ScoreBreakdownItem]

    @property
    def total_raw_penalty(self) -> int:
        return sum(item.raw_penalty for item in self.score_breakdown)

    @property
    def total_applied_penalty(self) -> int:
        return sum(item.applied_penalty for item in self.score_breakdown)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "rating": self.rating,
            "score_label": self.score_label,
            "total_records_analyzed": self.total_records_analyzed,
            "total_findings": self.total_findings,
            "finding_counts_by_severity": self.finding_counts_by_severity,
            "score_breakdown": [item.to_dict() for item in self.score_breakdown],
            "checkpoint_scores": [item.to_dict() for item in self.checkpoint_scores],
            "audit_type_scores": [item.to_dict() for item in self.audit_type_scores],
            "total_raw_penalty": self.total_raw_penalty,
            "total_applied_penalty": self.total_applied_penalty,
        }


def rating_for_score(score: int) -> str:
    if score >= 90:
        return "COMPLIANT"
    if score >= 75:
        return "MINOR_FINDINGS"
    if score >= 60:
        return "MAJOR_FINDINGS"
    return "CRITICAL_RISK"


def _score_status_for_result(result: AuditCheckResult) -> str:
    if result.check_status:
        return result.check_status
    if result.findings:
        return SCORE_STATUS_REVIEW_REQUIRED
    if result.applicable_record_count == 0:
        return SCORE_STATUS_NOT_APPLICABLE
    return SCORE_STATUS_PASS


def _is_penalized_result(result: AuditCheckResult) -> bool:
    return result.check_status not in {CHECK_STATUS_NOT_APPLICABLE, CHECK_STATUS_NO_DATA}


def _type_score_label(audit_trail_type: str) -> str:
    metadata = SUPPORTED_AUDIT_TRAIL_TYPES.get(audit_trail_type, {})
    label = str(metadata.get("label") or audit_trail_type.replace("_", " ").title())
    return f"{label} Score"


def _selected_types(review_scope: str | None, selected_audit_trail_types: list[str] | tuple[str, ...] | None) -> list[str]:
    selected = list(selected_audit_trail_types or [])
    if selected:
        return selected
    scope = resolve_review_scope(review_scope, selected, None)
    scope_types = REVIEW_SCOPES.get(scope, {}).get("audit_trail_types") or []
    return list(scope_types) or ["login_audit_trail"]


def calculate_audit_review_score(
    check_results: list[AuditCheckResult],
    *,
    total_records_analyzed: int,
    review_scope: str | None = None,
    selected_audit_trail_types: list[str] | tuple[str, ...] | None = None,
) -> AuditScoringResult:
    breakdown: list[ScoreBreakdownItem] = []
    severity_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    selected_types = _selected_types(review_scope, selected_audit_trail_types)
    resolved_scope = resolve_review_scope(review_scope, selected_types, selected_types[0] if selected_types else None)
    label = score_label_for_scope(resolved_scope, selected_types)

    for result in check_results:
        definition = result.definition
        finding_count = len(result.findings)
        raw_penalty = finding_count * definition.penalty_per_finding
        applied_penalty = min(raw_penalty, definition.penalty_cap) if _is_penalized_result(result) else 0
        breakdown.append(
            ScoreBreakdownItem(
                check_code=definition.check_code,
                check_name=definition.check_name,
                score_scope=SCORE_SCOPE_CHECKPOINT,
                audit_trail_type="ALL",
                score_label=definition.check_name,
                applicability=result.applicability,
                finding_count=finding_count,
                penalty_per_finding=definition.penalty_per_finding,
                penalty_cap=definition.penalty_cap,
                raw_penalty=raw_penalty,
                applied_penalty=applied_penalty,
                applicable_record_count=result.applicable_record_count,
                evaluated_record_count=result.evaluated_record_count,
                skipped_record_count=result.skipped_record_count,
                no_data_count=result.no_data_count,
                source_record_count=total_records_analyzed,
                score_status=_score_status_for_result(result),
                sort_order=definition.sort_order,
            )
        )

        for finding in result.findings:
            severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1

    audit_type_scores: list[ScoreBreakdownItem] = []
    for index, audit_trail_type in enumerate(selected_types):
        type_results = [result for result in check_results if audit_trail_type in result.applicable_audit_trail_types]
        type_findings = [
            finding
            for result in type_results
            for finding in result.findings
            if finding.audit_trail_type in {audit_trail_type, "MULTI", None}
        ]
        type_raw_penalty = sum(finding.score_impact for finding in type_findings)
        type_penalty_cap = sum(result.definition.penalty_cap for result in type_results)
        type_applied_penalty = min(type_raw_penalty, type_penalty_cap) if type_penalty_cap else 0
        type_score = max(0, 100 - type_applied_penalty)
        type_statuses = {result.check_status for result in type_results}
        if not type_results:
            score_status = CHECK_STATUS_NOT_APPLICABLE
            applicability = CHECK_STATUS_NOT_APPLICABLE
        elif type_statuses == {CHECK_STATUS_NO_DATA}:
            score_status = CHECK_STATUS_NO_DATA
            applicability = CHECK_STATUS_NO_DATA
        elif any(status not in {SCORE_STATUS_PASS, CHECK_STATUS_NOT_APPLICABLE, CHECK_STATUS_NO_DATA} for status in type_statuses):
            score_status = SCORE_STATUS_REVIEW_REQUIRED
            applicability = "ACTIVE"
        else:
            score_status = SCORE_STATUS_PASS
            applicability = "ACTIVE"

        audit_type_scores.append(
            ScoreBreakdownItem(
                check_code=OVERALL_CHECK_CODE,
                check_name=_type_score_label(audit_trail_type),
                score_scope=SCORE_SCOPE_AUDIT_TYPE,
                audit_trail_type=audit_trail_type,
                score_label=_type_score_label(audit_trail_type),
                applicability=applicability,
                finding_count=len(type_findings),
                penalty_per_finding=0,
                penalty_cap=type_penalty_cap,
                raw_penalty=type_raw_penalty,
                applied_penalty=type_applied_penalty,
                applicable_record_count=sum(result.applicable_record_count for result in type_results),
                evaluated_record_count=sum(result.evaluated_record_count for result in type_results),
                skipped_record_count=sum(result.skipped_record_count for result in type_results),
                no_data_count=sum(result.no_data_count for result in type_results),
                source_record_count=total_records_analyzed,
                score_status=score_status,
                sort_order=800 + index,
                overall_score=type_score,
                rating=rating_for_score(type_score),
            )
        )

    total_findings = sum(item.finding_count for item in breakdown)
    total_applied_penalty = sum(
        item.applied_penalty
        for item in breakdown
        if item.score_status not in {CHECK_STATUS_NOT_APPLICABLE, CHECK_STATUS_NO_DATA}
    )
    overall_score = max(0, 100 - total_applied_penalty)
    return AuditScoringResult(
        overall_score=overall_score,
        rating=rating_for_score(overall_score),
        score_label=label,
        total_records_analyzed=total_records_analyzed,
        total_findings=total_findings,
        finding_counts_by_severity=severity_counts,
        score_breakdown=breakdown,
        checkpoint_scores=breakdown,
        audit_type_scores=audit_type_scores,
    )


def build_score_models(
    job: AuditReviewJob,
    scoring_result: AuditScoringResult,
    *,
    created_dt: datetime,
) -> list[AuditReviewScore]:
    score_rows: list[AuditReviewScore] = []
    for item in [*scoring_result.checkpoint_scores, *scoring_result.audit_type_scores]:
        score_rows.append(
            AuditReviewScore(
                job_id=job.job_id,
                asset_id=job.asset_id,
                check_code=item.check_code,
                check_name=item.check_name,
                score_scope=item.score_scope,
                audit_trail_type=item.audit_trail_type,
                score_label=item.score_label,
                applicability=item.applicability,
                evaluated_record_count=item.evaluated_record_count,
                skipped_record_count=item.skipped_record_count,
                no_data_count=item.no_data_count,
                overall_score=item.overall_score,
                rating=item.rating,
                score_status=item.score_status,
                source_record_count=item.source_record_count,
                finding_count=item.finding_count,
                penalty_per_finding=item.penalty_per_finding,
                penalty_cap=item.penalty_cap,
                raw_penalty=item.raw_penalty,
                applied_penalty=item.applied_penalty,
                sort_order=item.sort_order,
                scoring_summary_json=item.to_dict(),
                created_by=job.requested_by,
                created_dt=created_dt,
                modified_by=job.requested_by,
                modified_dt=created_dt,
            )
        )

    score_rows.append(
        AuditReviewScore(
            job_id=job.job_id,
            asset_id=job.asset_id,
            check_code=OVERALL_CHECK_CODE,
            check_name=scoring_result.score_label or OVERALL_CHECK_NAME,
            score_scope=SCORE_SCOPE_OVERALL,
            audit_trail_type="ALL",
            score_label=scoring_result.score_label,
            applicability="ACTIVE",
            evaluated_record_count=scoring_result.total_records_analyzed,
            skipped_record_count=0,
            no_data_count=sum(item.no_data_count for item in scoring_result.score_breakdown),
            overall_score=scoring_result.overall_score,
            rating=scoring_result.rating,
            score_status=SCORE_STATUS_SCORED,
            source_record_count=scoring_result.total_records_analyzed,
            finding_count=scoring_result.total_findings,
            penalty_per_finding=0,
            penalty_cap=sum(item.penalty_cap for item in scoring_result.score_breakdown),
            raw_penalty=scoring_result.total_raw_penalty,
            applied_penalty=scoring_result.total_applied_penalty,
            sort_order=1000,
            scoring_summary_json=scoring_result.summary_dict(),
            created_by=job.requested_by,
            created_dt=created_dt,
            modified_by=job.requested_by,
            modified_dt=created_dt,
        )
    )
    return score_rows
