import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.evaluation_requirement_item import EvaluationRequirementItem
from app.models.supplier_comparison_summary import SupplierComparisonSummary
from app.models.supplier_evaluation import SupplierEvaluation
from app.models.supplier_evaluation_analysis import SupplierEvaluationAnalysis
from app.models.supplier_evaluation_response import SupplierEvaluationResponse
from app.models.supplier_requirement_analysis import SupplierRequirementAnalysis
from app.models.supplier_requirement_response import SupplierRequirementResponse
from app.schemas.supplier_evaluation_schema import (
    SupplierComparisonSummaryResponse,
    SupplierEvaluationAnalysisListResponse,
    SupplierEvaluationAnalysisResponse,
    SupplierEvaluationAnalysisRunRequest,
    SupplierEvaluationComparisonResponse,
    SupplierRequirementAnalysisResponse,
)
from app.services.supplier_evaluation_service import (
    EVALUATION_STATUS_LOCKED,
    RESPONSE_STATUS_LOCKED,
    RESPONSE_STATUS_SUBMITTED,
    ServiceConflictError,
    ServiceNotFoundError,
    ServiceValidationError,
)
from app.services.urs_generation_service import (
    _build_llm_headers,
    _extract_chat_completion_output_text,
    _infer_provider_name,
)

ANALYSIS_STATUS_NOT_STARTED = "NOT_STARTED"
ANALYSIS_STATUS_RUNNING = "RUNNING"
ANALYSIS_STATUS_COMPLETED = "COMPLETED"
ANALYSIS_STATUS_FAILED = "FAILED"

FIT_STATUS_MEETS = "MEETS"
FIT_STATUS_PARTIALLY_MEETS = "PARTIALLY_MEETS"
FIT_STATUS_NOT_MEETS = "NOT_MEETS"
ALLOWED_FIT_STATUSES = {FIT_STATUS_MEETS, FIT_STATUS_PARTIALLY_MEETS, FIT_STATUS_NOT_MEETS}

SUPPLIER_ANALYSIS_PROMPT_VERSION = "supplier-evaluation-analysis-v1"
DETERMINISTIC_PROVIDER = "deterministic"
DETERMINISTIC_MODEL = "structured-response-rules-v1"

FIT_WEIGHTS = {
    FIT_STATUS_MEETS: 1.0,
    FIT_STATUS_PARTIALLY_MEETS: 0.5,
    FIT_STATUS_NOT_MEETS: 0.0,
}

CRITICAL_RISK_HINTS = (
    "critical",
    "security",
    "compliance",
    "validation",
    "audit",
    "data integrity",
    "access",
    "regulatory",
    "gxp",
)


@dataclass(slots=True)
class RequirementAnalysisDraft:
    supplier_response_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str | None
    requirement_id: uuid.UUID
    requirement_key: str | None
    requirement_section: str | None
    requirement_text: str
    structured_fit: str | None
    evaluated_fit: str
    confidence_score: float
    reasoning_text: str
    evidence_reference: str | None


@dataclass(slots=True)
class SupplierSummaryDraft:
    supplier_id: uuid.UUID
    supplier_name: str | None
    supplier_type: str | None
    supplier_response_id: uuid.UUID
    overall_score: float
    meets_count: int
    partially_meets_count: int
    not_meets_count: int
    total_requirements: int
    strengths: list[str]
    weaknesses: list[str]
    risk_flags: list[str]
    recommendation_rank: int


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _clamp_confidence(value: Any) -> float:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return 0.35
    return max(0.0, min(1.0, numeric_value))


def _normalize_fit(value: str | None) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    upper_value = normalized.upper()
    return upper_value if upper_value in ALLOWED_FIT_STATUSES else None


def _truncate(value: str | None, limit: int = 1200) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None or len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _list_value(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _evaluation_query() -> Select[tuple[SupplierEvaluation]]:
    return select(SupplierEvaluation).options(
        selectinload(SupplierEvaluation.asset),
        selectinload(SupplierEvaluation.urs_document),
        selectinload(SupplierEvaluation.requirement_items),
        selectinload(SupplierEvaluation.responses).selectinload(SupplierEvaluationResponse.supplier),
        selectinload(SupplierEvaluation.responses).selectinload(SupplierEvaluationResponse.documents),
        selectinload(SupplierEvaluation.responses)
        .selectinload(SupplierEvaluationResponse.requirement_responses)
        .selectinload(SupplierRequirementResponse.requirement_item),
    )


def _analysis_query() -> Select[tuple[SupplierEvaluationAnalysis]]:
    return select(SupplierEvaluationAnalysis).options(
        selectinload(SupplierEvaluationAnalysis.requirement_analyses),
        selectinload(SupplierEvaluationAnalysis.comparison_summaries),
    )


async def _get_evaluation_model_by_id(db: AsyncSession, evaluation_id: uuid.UUID) -> SupplierEvaluation | None:
    result = await db.execute(_evaluation_query().where(SupplierEvaluation.evaluation_id == evaluation_id))
    return result.scalars().unique().first()


async def _get_analysis_model_by_id(db: AsyncSession, analysis_id: uuid.UUID) -> SupplierEvaluationAnalysis | None:
    result = await db.execute(_analysis_query().where(SupplierEvaluationAnalysis.analysis_id == analysis_id))
    return result.scalars().unique().first()


async def _get_latest_analysis_model(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
) -> SupplierEvaluationAnalysis | None:
    stmt = (
        _analysis_query()
        .where(SupplierEvaluationAnalysis.evaluation_id == evaluation_id)
        .order_by(SupplierEvaluationAnalysis.created_at.desc(), SupplierEvaluationAnalysis.analysis_id.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().unique().first()


async def _get_analysis_history_models(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
) -> list[SupplierEvaluationAnalysis]:
    stmt = (
        _analysis_query()
        .where(SupplierEvaluationAnalysis.evaluation_id == evaluation_id)
        .order_by(SupplierEvaluationAnalysis.created_at.desc(), SupplierEvaluationAnalysis.analysis_id.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().unique().all())


def _ordered_requirements(evaluation: SupplierEvaluation) -> list[EvaluationRequirementItem]:
    return sorted(
        evaluation.requirement_items or [],
        key=lambda item: (
            item.requirement_order if item.requirement_order is not None else 999999,
            item.created_dt or datetime.min.replace(tzinfo=UTC),
        ),
    )


def _ordered_responses(evaluation: SupplierEvaluation) -> list[SupplierEvaluationResponse]:
    return sorted(
        evaluation.responses or [],
        key=lambda response: ((response.supplier.supplier_name or "").lower() if response.supplier else ""),
    )


def _ensure_analysis_allowed(evaluation: SupplierEvaluation) -> None:
    if evaluation.status != EVALUATION_STATUS_LOCKED:
        raise ServiceConflictError("AI supplier evaluation analysis can only run after the evaluation is LOCKED")
    if not evaluation.responses:
        raise ServiceConflictError("Add supplier responses before running AI supplier evaluation analysis")
    if not evaluation.requirement_items:
        raise ServiceConflictError("Seed or add evaluation requirement rows before running analysis")

    pending = [
        response.supplier.supplier_name or str(response.supplier_id)
        for response in evaluation.responses
        if response.submission_status not in {RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_LOCKED}
    ]
    if pending:
        raise ServiceConflictError(
            f"All supplier responses must be submitted before analysis. Pending suppliers: {', '.join(pending)}"
        )


def _document_evidence(response: SupplierEvaluationResponse) -> list[str]:
    evidence: list[str] = []
    for document in sorted(response.documents or [], key=lambda item: item.document_name.lower()):
        parts = [document.document_name]
        if document.document_type:
            parts.append(document.document_type)
        if document.document_version:
            parts.append(f"v{document.document_version}")
        if document.source_reference:
            parts.append(document.source_reference)
        evidence.append(" | ".join(parts))
    return evidence


def _build_input_snapshot(evaluation: SupplierEvaluation) -> dict[str, Any]:
    return {
        "snapshot_at": datetime.now(UTC).isoformat(),
        "evaluation": {
            "evaluation_id": str(evaluation.evaluation_id),
            "evaluation_name": evaluation.evaluation_name,
            "status": evaluation.status,
            "asset_uuid": str(evaluation.asset_uuid),
            "asset_name": evaluation.asset.asset_name if evaluation.asset else None,
            "asset_code": evaluation.asset.asset_code if evaluation.asset else None,
            "urs_document_id": str(evaluation.urs_document_id),
            "urs_title": evaluation.urs_document.title if evaluation.urs_document else None,
            "urs_status": evaluation.urs_document.status if evaluation.urs_document else None,
        },
        "urs": {
            "title": evaluation.urs_document.title if evaluation.urs_document else None,
            "content": _truncate(evaluation.urs_document.content if evaluation.urs_document else None, 8000),
        },
        "requirements": [
            {
                "requirement_id": str(item.requirement_item_id),
                "requirement_key": item.requirement_key,
                "requirement_section": item.requirement_section,
                "requirement_text": item.requirement_text,
                "requirement_order": item.requirement_order,
                "source_reference": item.source_reference,
            }
            for item in _ordered_requirements(evaluation)
        ],
        "supplier_responses": [
            {
                "supplier_response_id": str(response.response_id),
                "supplier_id": str(response.supplier_id),
                "supplier_name": response.supplier.supplier_name if response.supplier else None,
                "supplier_type": response.supplier.supplier_type if response.supplier else None,
                "submission_status": response.submission_status,
                "quotation_reference": response.quotation_reference,
                "notes": _truncate(response.notes, 1200),
                "documents": [
                    {
                        "document_id": str(document.document_id),
                        "document_type": document.document_type,
                        "document_name": document.document_name,
                        "document_version": document.document_version,
                        "source_system": document.source_system,
                        "external_document_id": document.external_document_id,
                        "source_reference": document.source_reference,
                        "notes": _truncate(document.notes, 800),
                    }
                    for document in response.documents or []
                ],
                "requirement_responses": [
                    {
                        "requirement_response_id": str(row.requirement_response_id),
                        "requirement_id": str(row.requirement_item_id),
                        "fit_status": row.fit_status,
                        "supplier_response_text": _truncate(row.supplier_response_text, 1200),
                        "evidence_reference": row.evidence_reference,
                        "notes": _truncate(row.notes, 800),
                    }
                    for row in response.requirement_responses or []
                ],
            }
            for response in _ordered_responses(evaluation)
        ],
    }


def _base_confidence(structured_response: SupplierRequirementResponse | None, response: SupplierEvaluationResponse) -> float:
    if structured_response is None:
        return 0.3

    confidence = 0.72 if structured_response.fit_status == FIT_STATUS_PARTIALLY_MEETS else 0.78
    if _strip_optional(structured_response.supplier_response_text):
        confidence += 0.08
    if _strip_optional(structured_response.evidence_reference):
        confidence += 0.05
    if response.documents:
        confidence += 0.04
    return min(confidence, 0.95)


def _combine_evidence(
    structured_response: SupplierRequirementResponse | None,
    response: SupplierEvaluationResponse,
) -> str | None:
    evidence: list[str] = []
    if structured_response is not None and _strip_optional(structured_response.evidence_reference):
        evidence.append(f"Structured evidence: {structured_response.evidence_reference}")
    document_evidence = _document_evidence(response)
    if document_evidence:
        evidence.append(f"Attached documents: {'; '.join(document_evidence[:5])}")
    return "; ".join(evidence) if evidence else None


def _build_reasoning(
    *,
    requirement: EvaluationRequirementItem,
    response: SupplierEvaluationResponse,
    structured_response: SupplierRequirementResponse | None,
    evaluated_fit: str,
    confidence: float,
) -> str:
    supplier_name = response.supplier.supplier_name if response.supplier else "Supplier"
    requirement_label = requirement.requirement_key or requirement.requirement_section or "requirement"
    if structured_response is None:
        return (
            f"{supplier_name} did not provide a structured answer for {requirement_label}. "
            "The analysis defaults to PARTIALLY_MEETS with low confidence because there is not enough evidence to validate full compliance or non-compliance."
        )

    details: list[str] = [
        f"{supplier_name} declared {structured_response.fit_status} for {requirement_label}.",
    ]
    response_text = _strip_optional(structured_response.supplier_response_text)
    if response_text:
        details.append(f"Supplier response text: {_truncate(response_text, 500)}")
    else:
        details.append("No supplier explanation was provided in the structured matrix.")

    evidence = _combine_evidence(structured_response, response)
    if evidence:
        details.append(f"Evidence considered: {_truncate(evidence, 600)}")
    else:
        details.append("No supporting evidence reference or response document metadata was available.")

    details.append(
        f"Validated fit remains {evaluated_fit} with confidence {confidence:.2f}; no unsupported assumptions were added."
    )
    return " ".join(details)


def _build_deterministic_requirement_drafts(
    evaluation: SupplierEvaluation,
) -> list[RequirementAnalysisDraft]:
    drafts: list[RequirementAnalysisDraft] = []
    requirements = _ordered_requirements(evaluation)
    for response in _ordered_responses(evaluation):
        structured_map = {
            row.requirement_item_id: row for row in response.requirement_responses or []
        }
        for requirement in requirements:
            structured_response = structured_map.get(requirement.requirement_item_id)
            structured_fit = _normalize_fit(structured_response.fit_status if structured_response else None)
            evaluated_fit = structured_fit or FIT_STATUS_PARTIALLY_MEETS
            confidence = _base_confidence(structured_response, response)
            reasoning = _build_reasoning(
                requirement=requirement,
                response=response,
                structured_response=structured_response,
                evaluated_fit=evaluated_fit,
                confidence=confidence,
            )
            drafts.append(
                RequirementAnalysisDraft(
                    supplier_response_id=response.response_id,
                    supplier_id=response.supplier_id,
                    supplier_name=response.supplier.supplier_name if response.supplier else None,
                    requirement_id=requirement.requirement_item_id,
                    requirement_key=requirement.requirement_key,
                    requirement_section=requirement.requirement_section,
                    requirement_text=requirement.requirement_text,
                    structured_fit=structured_fit,
                    evaluated_fit=evaluated_fit,
                    confidence_score=confidence,
                    reasoning_text=reasoning,
                    evidence_reference=_combine_evidence(structured_response, response),
                )
            )
    return drafts


def _analysis_key(supplier_response_id: uuid.UUID, requirement_id: uuid.UUID) -> str:
    return f"{supplier_response_id}:{requirement_id}"


def _drafts_for_prompt(drafts: list[RequirementAnalysisDraft]) -> list[dict[str, Any]]:
    return [
        {
            "supplier_response_id": str(draft.supplier_response_id),
            "supplier_id": str(draft.supplier_id),
            "supplier_name": draft.supplier_name,
            "requirement_id": str(draft.requirement_id),
            "requirement_key": draft.requirement_key,
            "requirement_section": draft.requirement_section,
            "requirement_text": _truncate(draft.requirement_text, 800),
            "structured_fit": draft.structured_fit,
            "deterministic_fit": draft.evaluated_fit,
            "deterministic_confidence": draft.confidence_score,
            "deterministic_reasoning": _truncate(draft.reasoning_text, 800),
            "evidence_reference": _truncate(draft.evidence_reference, 800),
        }
        for draft in drafts
    ]


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()

    try:
        payload = json.loads(stripped)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(stripped[start : end + 1])
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            return None


def _build_ai_prompt(snapshot: dict[str, Any], drafts: list[RequirementAnalysisDraft]) -> tuple[str, str]:
    instructions = (
        "You are an enterprise supplier evaluation analyst. Review supplier responses against URS requirements.\n"
        "Return JSON only. Do not include markdown.\n"
        "Use only the supplied structured response matrix and document metadata. Do not invent facts or infer capabilities from missing evidence.\n"
        "If a supplier answer is unclear or missing, use PARTIALLY_MEETS with low confidence.\n"
        "Keep evaluated_fit to MEETS, PARTIALLY_MEETS, or NOT_MEETS. Confidence must be between 0 and 1.\n"
        "Do not modify source data. Your output is an auditable recommendation layer."
    )
    prompt_payload = {
        "schema": {
            "requirement_analyses": [
                {
                    "supplier_response_id": "uuid",
                    "requirement_id": "uuid",
                    "evaluated_fit": "MEETS|PARTIALLY_MEETS|NOT_MEETS",
                    "confidence_score": 0.0,
                    "reasoning_text": "grounded explanation",
                    "evidence_reference": "optional evidence used",
                }
            ],
            "evaluation_summary": {
                "overall_comparison_insight": "short grounded comparison",
                "recommendation_explanation": "why top supplier is recommended and trade-offs",
                "key_differentiators": ["grounded differentiator"],
            },
        },
        "input_snapshot": {
            "evaluation": snapshot.get("evaluation"),
            "requirements": snapshot.get("requirements"),
            "supplier_responses": snapshot.get("supplier_responses"),
        },
        "deterministic_baseline": _drafts_for_prompt(drafts),
    }
    return instructions, json.dumps(prompt_payload, ensure_ascii=True, indent=2)


async def _request_ai_analysis(
    snapshot: dict[str, Any],
    drafts: list[RequirementAnalysisDraft],
) -> tuple[dict[str, Any] | None, str | None, str | None, str | None]:
    settings = get_settings()
    if not settings.LLM_ENABLED:
        return None, DETERMINISTIC_PROVIDER, DETERMINISTIC_MODEL, "LLM_ENABLED is false; deterministic analysis was used"

    api_key = _strip_optional(settings.LLM_API_KEY)
    model = _strip_optional(settings.LLM_MODEL)
    if api_key is None or model is None:
        return None, DETERMINISTIC_PROVIDER, DETERMINISTIC_MODEL, "LLM API key or model is not configured; deterministic analysis was used"

    provider = _infer_provider_name()
    instructions, prompt_input = _build_ai_prompt(snapshot, drafts)
    request_id = str(uuid.uuid4())
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": prompt_input},
        ],
        "response_format": {"type": "json_object"},
    }
    max_attempts = max(1, settings.LLM_MAX_RETRIES + 1)

    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
                    headers=_build_llm_headers(api_key, request_id),
                    json=payload,
                )
                response.raise_for_status()

            response_payload = response.json()
            if not isinstance(response_payload, dict):
                return None, provider, model, "AI provider returned an unexpected payload; deterministic analysis was used"
            output_text = _extract_chat_completion_output_text(response_payload)
            ai_payload = _extract_json_object(output_text)
            if ai_payload is None:
                return None, provider, model, "AI provider did not return parseable JSON; deterministic analysis was used"
            return ai_payload, provider, model, None
        except (httpx.HTTPError, ValueError) as exc:
            if attempt >= max_attempts:
                return None, provider, model, f"AI provider call failed: {exc}; deterministic analysis was used"
            await asyncio.sleep(min(1.5 * attempt, 3.0))

    return None, provider, model, "AI provider call failed; deterministic analysis was used"


def _apply_ai_payload(
    drafts: list[RequirementAnalysisDraft],
    ai_payload: dict[str, Any] | None,
) -> list[RequirementAnalysisDraft]:
    if ai_payload is None:
        return drafts

    ai_rows = ai_payload.get("requirement_analyses")
    if not isinstance(ai_rows, list):
        return drafts

    draft_map = {
        _analysis_key(draft.supplier_response_id, draft.requirement_id): draft
        for draft in drafts
    }
    for row in ai_rows:
        if not isinstance(row, dict):
            continue
        try:
            supplier_response_id = uuid.UUID(str(row.get("supplier_response_id")))
            requirement_id = uuid.UUID(str(row.get("requirement_id")))
        except (TypeError, ValueError):
            continue

        key = _analysis_key(supplier_response_id, requirement_id)
        draft = draft_map.get(key)
        if draft is None:
            continue

        evaluated_fit = _normalize_fit(row.get("evaluated_fit"))
        if evaluated_fit is None:
            continue

        # Guardrail: missing supplier matrix answers cannot be upgraded to full compliance.
        if draft.structured_fit is None and evaluated_fit == FIT_STATUS_MEETS:
            evaluated_fit = FIT_STATUS_PARTIALLY_MEETS

        # Guardrail: an explicit supplier NOT_MEETS answer should not become MEETS without source changes.
        if draft.structured_fit == FIT_STATUS_NOT_MEETS and evaluated_fit == FIT_STATUS_MEETS:
            evaluated_fit = FIT_STATUS_PARTIALLY_MEETS

        confidence = _clamp_confidence(row.get("confidence_score"))
        if draft.structured_fit is None:
            confidence = min(confidence, 0.45)

        reasoning_text = _strip_optional(row.get("reasoning_text")) or draft.reasoning_text
        evidence_reference = _strip_optional(row.get("evidence_reference")) or draft.evidence_reference
        draft.evaluated_fit = evaluated_fit
        draft.confidence_score = confidence
        draft.reasoning_text = reasoning_text
        draft.evidence_reference = evidence_reference

    return drafts


def _is_critical_requirement(draft: RequirementAnalysisDraft) -> bool:
    searchable = " ".join(
        [
            draft.requirement_key or "",
            draft.requirement_section or "",
            draft.requirement_text or "",
        ]
    ).lower()
    return any(hint in searchable for hint in CRITICAL_RISK_HINTS)


def _requirement_label(draft: RequirementAnalysisDraft) -> str:
    label = draft.requirement_key or draft.requirement_section or "Requirement"
    text = _truncate(draft.requirement_text, 180) or ""
    return f"{label}: {text}"


def _build_supplier_summary_drafts(
    evaluation: SupplierEvaluation,
    drafts: list[RequirementAnalysisDraft],
) -> list[SupplierSummaryDraft]:
    by_response_id: dict[uuid.UUID, list[RequirementAnalysisDraft]] = {}
    for draft in drafts:
        by_response_id.setdefault(draft.supplier_response_id, []).append(draft)

    summaries: list[SupplierSummaryDraft] = []
    response_map = {response.response_id: response for response in _ordered_responses(evaluation)}
    for response_id, response_drafts in by_response_id.items():
        total = len(response_drafts)
        meets = sum(draft.evaluated_fit == FIT_STATUS_MEETS for draft in response_drafts)
        partial = sum(draft.evaluated_fit == FIT_STATUS_PARTIALLY_MEETS for draft in response_drafts)
        not_meets = sum(draft.evaluated_fit == FIT_STATUS_NOT_MEETS for draft in response_drafts)
        weighted = sum(FIT_WEIGHTS[draft.evaluated_fit] for draft in response_drafts)
        score = round((weighted / total) * 100, 2) if total else 0.0

        strengths = [_requirement_label(draft) for draft in response_drafts if draft.evaluated_fit == FIT_STATUS_MEETS][:5]
        weaknesses = [_requirement_label(draft) for draft in response_drafts if draft.evaluated_fit == FIT_STATUS_NOT_MEETS][:5]
        risk_flags = [
            f"Critical gap: {_requirement_label(draft)}"
            for draft in response_drafts
            if draft.evaluated_fit == FIT_STATUS_NOT_MEETS and _is_critical_requirement(draft)
        ][:5]

        response = response_map.get(response_id)
        summaries.append(
            SupplierSummaryDraft(
                supplier_id=response.supplier_id if response is not None else response_drafts[0].supplier_id,
                supplier_name=response.supplier.supplier_name if response is not None and response.supplier else response_drafts[0].supplier_name,
                supplier_type=response.supplier.supplier_type if response is not None and response.supplier else None,
                supplier_response_id=response_id,
                overall_score=score,
                meets_count=meets,
                partially_meets_count=partial,
                not_meets_count=not_meets,
                total_requirements=total,
                strengths=strengths,
                weaknesses=weaknesses,
                risk_flags=risk_flags,
                recommendation_rank=0,
            )
        )

    summaries.sort(
        key=lambda item: (
            -item.overall_score,
            -item.meets_count,
            item.not_meets_count,
            item.supplier_name or "",
        )
    )
    for index, summary in enumerate(summaries, start=1):
        summary.recommendation_rank = index
    return summaries


def _build_summary_json(
    *,
    evaluation: SupplierEvaluation,
    requirement_drafts: list[RequirementAnalysisDraft],
    supplier_summaries: list[SupplierSummaryDraft],
    ai_payload: dict[str, Any] | None,
    provider: str | None,
    model: str | None,
    fallback_reason: str | None,
) -> dict[str, Any]:
    top_supplier = supplier_summaries[0] if supplier_summaries else None
    total_suppliers = len(supplier_summaries)
    total_requirements = len(_ordered_requirements(evaluation))

    differentiators: list[str] = []
    if len(supplier_summaries) > 1:
        top_score = supplier_summaries[0].overall_score
        for summary in supplier_summaries[1:]:
            delta = round(top_score - summary.overall_score, 2)
            differentiators.append(
                f"{supplier_summaries[0].supplier_name or 'Top supplier'} leads {summary.supplier_name or 'supplier'} by {delta} points."
            )

    ai_summary = ai_payload.get("evaluation_summary") if isinstance(ai_payload, dict) else None
    ai_key_differentiators = _list_value(ai_summary.get("key_differentiators")) if isinstance(ai_summary, dict) else []

    recommendation_reason = (
        ai_summary.get("recommendation_explanation")
        if isinstance(ai_summary, dict) and _strip_optional(ai_summary.get("recommendation_explanation"))
        else None
    )
    if recommendation_reason is None and top_supplier is not None:
        recommendation_reason = (
            f"{top_supplier.supplier_name or 'The top-ranked supplier'} is recommended based on the highest weighted URS compliance score "
            f"({top_supplier.overall_score:.2f}/100), with {top_supplier.meets_count} requirements meeting expectations."
        )

    overall_insight = (
        ai_summary.get("overall_comparison_insight")
        if isinstance(ai_summary, dict) and _strip_optional(ai_summary.get("overall_comparison_insight"))
        else None
    )
    if overall_insight is None:
        overall_insight = (
            "Supplier ranking is based on structured requirement fit using MEETS=1, PARTIALLY_MEETS=0.5, NOT_MEETS=0. "
            "Attached document metadata is used only as supporting evidence."
        )

    return {
        "analysis_method": {
            "provider": provider or DETERMINISTIC_PROVIDER,
            "model": model or DETERMINISTIC_MODEL,
            "prompt_version": SUPPLIER_ANALYSIS_PROMPT_VERSION,
            "fallback_reason": fallback_reason,
            "scoring": {
                "MEETS": 1,
                "PARTIALLY_MEETS": 0.5,
                "NOT_MEETS": 0,
            },
        },
        "evaluation_summary": {
            "evaluation_id": str(evaluation.evaluation_id),
            "evaluation_name": evaluation.evaluation_name,
            "total_suppliers": total_suppliers,
            "total_requirements": total_requirements,
            "best_performing_supplier": top_supplier.supplier_name if top_supplier is not None else None,
            "best_supplier_id": str(top_supplier.supplier_id) if top_supplier is not None else None,
            "overall_comparison_insight": overall_insight,
        },
        "supplier_wise_summary": [
            {
                "supplier_id": str(summary.supplier_id),
                "supplier_name": summary.supplier_name,
                "rank": summary.recommendation_rank,
                "overall_score": summary.overall_score,
                "strengths": summary.strengths,
                "weaknesses": summary.weaknesses,
                "risk_flags": summary.risk_flags,
            }
            for summary in supplier_summaries
        ],
        "recommendation": {
            "recommended_supplier_id": str(top_supplier.supplier_id) if top_supplier is not None else None,
            "recommended_supplier_name": top_supplier.supplier_name if top_supplier is not None else None,
            "explanation": recommendation_reason,
            "trade_offs": ai_key_differentiators or differentiators,
        },
        "requirement_fit_totals": {
            "MEETS": sum(draft.evaluated_fit == FIT_STATUS_MEETS for draft in requirement_drafts),
            "PARTIALLY_MEETS": sum(draft.evaluated_fit == FIT_STATUS_PARTIALLY_MEETS for draft in requirement_drafts),
            "NOT_MEETS": sum(draft.evaluated_fit == FIT_STATUS_NOT_MEETS for draft in requirement_drafts),
        },
    }
