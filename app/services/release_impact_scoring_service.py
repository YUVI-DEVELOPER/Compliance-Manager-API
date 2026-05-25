from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.core.release_impact_questions import ReleaseImpactQuestion


ANSWER_YES = "YES"
ANSWER_NO = "NO"
ANSWER_NOT_APPLICABLE = "NOT_APPLICABLE"
ANSWER_UNKNOWN = "UNKNOWN"
ALLOWED_IMPACT_ANSWERS = {ANSWER_YES, ANSWER_NO, ANSWER_NOT_APPLICABLE, ANSWER_UNKNOWN}

RISK_LEVEL_NOT_ASSESSED = "NOT_ASSESSED"
RISK_LEVEL_NO_IMPACT = "NO_IMPACT"
RISK_LEVEL_LOW = "LOW"
RISK_LEVEL_MEDIUM = "MEDIUM"
RISK_LEVEL_HIGH = "HIGH"

VALIDATION_SCOPE_NOT_ASSESSED = "NOT_ASSESSED"
VALIDATION_SCOPE_NO_VALIDATION_REQUIRED = "NO_VALIDATION_REQUIRED"
VALIDATION_SCOPE_LIMITED_VALIDATION = "LIMITED_VALIDATION"
VALIDATION_SCOPE_FULL_VALIDATION = "FULL_VALIDATION"


@dataclass(frozen=True, slots=True)
class ImpactResponseForScoring:
    question_code: str
    answer: str | None
    rationale: str | None = None


@dataclass(frozen=True, slots=True)
class ResponseScore:
    question_code: str
    answer: str | None
    weight: int
    critical: bool
    mandatory: bool
    score: int


@dataclass(frozen=True, slots=True)
class ScoringValidationIssue:
    question_code: str
    field: str
    message: str


@dataclass(frozen=True, slots=True)
class ImpactScoringResult:
    response_scores: list[ResponseScore]
    total_score: int
    risk_level: str
    validation_scope: str
    summary: str
    missing_answers: list[str] = field(default_factory=list)
    missing_rationale_errors: list[ScoringValidationIssue] = field(default_factory=list)
    invalid_answer_errors: list[ScoringValidationIssue] = field(default_factory=list)

    @property
    def validation_errors(self) -> list[ScoringValidationIssue]:
        return [
            *[
                ScoringValidationIssue(
                    question_code=question_code,
                    field="answer",
                    message="Mandatory question must be answered.",
                )
                for question_code in self.missing_answers
            ],
            *self.missing_rationale_errors,
            *self.invalid_answer_errors,
        ]


def _normalize_answer(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    return normalized or None


def _has_rationale(value: str | None) -> bool:
    return bool(value and value.strip())


def _score_for_answer(answer: str | None, weight: int) -> int:
    if answer in {ANSWER_YES, ANSWER_UNKNOWN}:
        return weight
    return 0


def _scope_for_risk(risk_level: str) -> str:
    if risk_level == RISK_LEVEL_NO_IMPACT:
        return VALIDATION_SCOPE_NO_VALIDATION_REQUIRED
    if risk_level in {RISK_LEVEL_LOW, RISK_LEVEL_MEDIUM}:
        return VALIDATION_SCOPE_LIMITED_VALIDATION
    if risk_level == RISK_LEVEL_HIGH:
        return VALIDATION_SCOPE_FULL_VALIDATION
    return VALIDATION_SCOPE_NOT_ASSESSED


def _risk_for_score(total_score: int, has_critical_risk: bool, answered_values: Iterable[str]) -> str:
    answers = list(answered_values)
    if has_critical_risk:
        return RISK_LEVEL_HIGH
    if total_score == 0 and answers and all(answer in {ANSWER_NO, ANSWER_NOT_APPLICABLE} for answer in answers):
        return RISK_LEVEL_NO_IMPACT
    if 1 <= total_score <= 5:
        return RISK_LEVEL_LOW
    if 6 <= total_score <= 14:
        return RISK_LEVEL_MEDIUM
    if total_score >= 15:
        return RISK_LEVEL_HIGH
    return RISK_LEVEL_NOT_ASSESSED


def _summary_for_result(risk_level: str, missing_answers: list[str]) -> str:
    if missing_answers:
        return "Impact assessment is in progress. Complete all mandatory answers before final scoring."
    if risk_level == RISK_LEVEL_NO_IMPACT:
        return "No validation impact identified. No validation is required."
    if risk_level == RISK_LEVEL_LOW:
        return "Low impact identified. Limited validation is required."
    if risk_level == RISK_LEVEL_MEDIUM:
        return "Medium impact identified. Limited validation is required."
    if risk_level == RISK_LEVEL_HIGH:
        return "Critical impacts identified. Full validation is required."
    return "Impact assessment has not been scored."


def calculate_impact_assessment_score(
    questions: Iterable[ReleaseImpactQuestion],
    responses: Iterable[ImpactResponseForScoring],
) -> ImpactScoringResult:
    question_list = list(questions)
    response_by_code = {response.question_code: response for response in responses}

    response_scores: list[ResponseScore] = []
    missing_answers: list[str] = []
    missing_rationale_errors: list[ScoringValidationIssue] = []
    invalid_answer_errors: list[ScoringValidationIssue] = []
    answered_values: list[str] = []
    has_critical_risk = False
    total_score = 0

    for question in question_list:
        response = response_by_code.get(question.question_code)
        answer = _normalize_answer(response.answer if response is not None else None)
        rationale = response.rationale if response is not None else None

        if question.mandatory and answer is None:
            missing_answers.append(question.question_code)
            response_scores.append(
                ResponseScore(
                    question_code=question.question_code,
                    answer=None,
                    weight=question.weight,
                    critical=question.critical,
                    mandatory=question.mandatory,
                    score=0,
                )
            )
            continue

        if answer is not None and answer not in ALLOWED_IMPACT_ANSWERS:
            invalid_answer_errors.append(
                ScoringValidationIssue(
                    question_code=question.question_code,
                    field="answer",
                    message="Answer must be YES, NO, NOT_APPLICABLE, or UNKNOWN.",
                )
            )
            score = 0
        else:
            score = _score_for_answer(answer, question.weight)
            if answer is not None:
                answered_values.append(answer)

        if answer in {ANSWER_YES, ANSWER_UNKNOWN} and not _has_rationale(rationale):
            missing_rationale_errors.append(
                ScoringValidationIssue(
                    question_code=question.question_code,
                    field="rationale",
                    message=f"{answer} requires rationale.",
                )
            )
        if answer == ANSWER_NOT_APPLICABLE and question.critical and not _has_rationale(rationale):
            missing_rationale_errors.append(
                ScoringValidationIssue(
                    question_code=question.question_code,
                    field="rationale",
                    message="NOT_APPLICABLE requires rationale for critical questions.",
                )
            )

        if question.critical and answer in {ANSWER_YES, ANSWER_UNKNOWN}:
            has_critical_risk = True

        total_score += score
        response_scores.append(
            ResponseScore(
                question_code=question.question_code,
                answer=answer,
                weight=question.weight,
                critical=question.critical,
                mandatory=question.mandatory,
                score=score,
            )
        )

    risk_level = _risk_for_score(total_score, has_critical_risk, answered_values)
    validation_scope = _scope_for_risk(risk_level)
    summary = _summary_for_result(risk_level, missing_answers)

    return ImpactScoringResult(
        response_scores=response_scores,
        total_score=total_score,
        risk_level=risk_level,
        validation_scope=validation_scope,
        summary=summary,
        missing_answers=missing_answers,
        missing_rationale_errors=missing_rationale_errors,
        invalid_answer_errors=invalid_answer_errors,
    )
