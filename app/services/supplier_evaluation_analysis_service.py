import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.authored_document import AuthoredDocument
from app.models.evaluation_requirement_item import EvaluationRequirementItem
from app.models.supplier_comparison_summary import SupplierComparisonSummary
from app.models.supplier_evaluation import SupplierEvaluation
from app.models.supplier_evaluation_analysis import SupplierEvaluationAnalysis
from app.models.supplier_evaluation_response import SupplierEvaluationResponse
from app.models.supplier_requirement_analysis import SupplierRequirementAnalysis
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
)
from app.services.supplier_requirement_service import (
    FIT_STATUS_MEETS,
    FIT_STATUS_NOT_MEETS,
    FIT_STATUS_PARTIALLY_MEETS,
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

PROMPT_VERSION = "supplier-evaluation-analysis-v1"
RULE_ENGINE_MODEL = "supplier-evaluation-rule-engine-v1"
RULE_ENGINE_PROVIDER = "deterministic-rules"

ALLOWED_ANALYSIS_FIT_STATUSES = {
    FIT_STATUS_MEETS,
    FIT_STATUS_PARTIALLY_MEETS,
    FIT_STATUS_NOT_MEETS,
}
FIT_SCORE = {
    FIT_STATUS_MEETS: 1.0,
    FIT_STATUS_PARTIALLY_MEETS: 0.5,
    FIT_STATUS_NOT_MEETS: 0.0,
}
FIT_RANK = {
    FIT_STATUS_NOT_MEETS: 0,
    FIT_STATUS_PARTIALLY_MEETS: 1,
    FIT_STATUS_MEETS: 2,
}
CRITICAL_REQUIREMENT_HINTS = (
    "21 cfr",
    "audit",
    "backup",
    "compliance",
    "critical",
    "data integrity",
    "disaster",
    "gamp",
    "gmp",
    "gxp",
    "must",
    "part 11",
    "regulatory",
    "security",
    "shall",
    "safety",
    "validation",
)


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _truncate(value: str | None, max_length: int) -> str | None:
    normalized = _strip_optional(value)
    if normalized is None:
        return None
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3].rstrip()}..."


def _iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _ordered_requirements(items: list[EvaluationRequirementItem]) -> list[EvaluationRequirementItem]:
    return sorted(
        items,
        key=lambda item: (
            item.requirement_order if item.requirement_order is not None else 999_999,
            item.created_dt or datetime.min.replace(tzinfo=UTC),
            str(item.requirement_item_id),
        ),
    )


def _ordered_responses(responses: list[SupplierEvaluationResponse]) -> list[SupplierEvaluationResponse]:
    return sorted(
        responses,
        key=lambda response: (
            (response.supplier.supplier_name if response.supplier is not None else "") or "",
            str(response.response_id),
        ),
    )


def _requirement_label(requirement: dict[str, Any]) -> str:
    key = _strip_optional(requirement.get("requirement_key"))
    section = _strip_optional(requirement.get("requirement_section"))
    if key and section:
        return f"{key} ({section})"
    if key:
        return key
    if section:
        return section
    order = requirement.get("requirement_order")
    return f"Requirement {order}" if order is not None else "Requirement"


def _format_fit_status(value: str | None) -> str:
    if value == FIT_STATUS_MEETS:
        return "MEETS"
    if value == FIT_STATUS_PARTIALLY_MEETS:
        return "PARTIALLY_MEETS"
    if value == FIT_STATUS_NOT_MEETS:
        return "NOT_MEETS"
    return "UNANSWERED"


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("label") or item.get("summary") or "").strip()
        else:
            text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def _analysis_query() -> Select[tuple[SupplierEvaluationAnalysis]]:
    return select(SupplierEvaluationAnalysis).options(
        selectinload(SupplierEvaluationAnalysis.requirement_analyses),
        selectinload(SupplierEvaluationAnalysis.comparison_summaries),
    )


def _evaluation_analysis_input_query() -> Select[tuple[SupplierEvaluation]]:
    return select(SupplierEvaluation).options(
        selectinload(SupplierEvaluation.asset),
        selectinload(SupplierEvaluation.urs_document).selectinload(AuthoredDocument.release),
        selectinload(SupplierEvaluation.requirement_items),
        selectinload(SupplierEvaluation.responses).selectinload(SupplierEvaluationResponse.supplier),
        selectinload(SupplierEvaluation.responses).selectinload(SupplierEvaluationResponse.documents),
        selectinload(SupplierEvaluation.responses).selectinload(SupplierEvaluationResponse.requirement_responses),
    )


async def _get_evaluation_for_analysis(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
) -> SupplierEvaluation | None:
    result = await db.execute(
        _evaluation_analysis_input_query().where(SupplierEvaluation.evaluation_id == evaluation_id)
    )
    return result.scalars().first()


async def _get_analysis_by_id(
    db: AsyncSession,
    analysis_id: uuid.UUID,
) -> SupplierEvaluationAnalysis | None:
    result = await db.execute(_analysis_query().where(SupplierEvaluationAnalysis.analysis_id == analysis_id))
    return result.scalars().first()


async def _get_latest_analysis(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
) -> SupplierEvaluationAnalysis | None:
    result = await db.execute(
        _analysis_query()
        .where(SupplierEvaluationAnalysis.evaluation_id == evaluation_id)
        .order_by(SupplierEvaluationAnalysis.created_at.desc(), SupplierEvaluationAnalysis.analysis_id.desc())
        .limit(1)
    )
    return result.scalars().first()


def _ensure_evaluation_can_run_analysis(evaluation: SupplierEvaluation) -> None:
    if evaluation.status != EVALUATION_STATUS_LOCKED:
        raise ServiceConflictError("AI analysis can only be run after the supplier evaluation is LOCKED")

    responses = list(evaluation.responses or [])
    if not responses:
        raise ServiceConflictError("AI analysis requires at least one supplier response")

    requirements = list(evaluation.requirement_items or [])
    if not requirements:
        raise ServiceConflictError("AI analysis requires a seeded requirement baseline")

    pending = [
        response.supplier.supplier_name if response.supplier is not None else str(response.supplier_id)
        for response in responses
        if response.submission_status not in {RESPONSE_STATUS_SUBMITTED, RESPONSE_STATUS_LOCKED}
    ]
    if pending:
        supplier_list = ", ".join(pending)
        raise ServiceConflictError(
            "AI analysis requires all supplier responses to be submitted or locked. "
            f"Pending suppliers: {supplier_list}"
        )


def _build_input_snapshot(evaluation: SupplierEvaluation) -> dict[str, Any]:
    requirements = _ordered_requirements(list(evaluation.requirement_items or []))
    responses = _ordered_responses(list(evaluation.responses or []))
    snapshot_dt = datetime.now(UTC)

    return {
        "snapshot_created_at": snapshot_dt.isoformat(),
        "evaluation": {
            "evaluation_id": str(evaluation.evaluation_id),
            "evaluation_name": evaluation.evaluation_name,
            "status": evaluation.status,
            "asset_uuid": str(evaluation.asset_uuid),
            "asset_name": evaluation.asset.asset_name if evaluation.asset is not None else None,
            "asset_code": evaluation.asset.asset_code if evaluation.asset is not None else None,
            "urs_document_id": str(evaluation.urs_document_id),
            "locked_at": _iso_datetime(evaluation.locked_at),
        },
        "urs": {
            "authored_document_id": (
                str(evaluation.urs_document.authored_document_id)
                if evaluation.urs_document is not None
                else str(evaluation.urs_document_id)
            ),
            "title": evaluation.urs_document.title if evaluation.urs_document is not None else None,
            "status": evaluation.urs_document.status if evaluation.urs_document is not None else None,
            "document_type": evaluation.urs_document.document_type if evaluation.urs_document is not None else None,
            "release_id": (
                str(evaluation.urs_document.release_id)
                if evaluation.urs_document is not None and evaluation.urs_document.release_id is not None
                else None
            ),
            "release_version": (
                evaluation.urs_document.release.version
                if evaluation.urs_document is not None and evaluation.urs_document.release is not None
                else None
            ),
            "content_excerpt": _truncate(
                evaluation.urs_document.content if evaluation.urs_document is not None else None,
                20_000,
            ),
            "source_context_json": evaluation.urs_document.source_context_json
            if evaluation.urs_document is not None
            else None,
        },
        "requirements": [
            {
                "requirement_item_id": str(requirement.requirement_item_id),
                "requirement_key": requirement.requirement_key,
                "requirement_section": requirement.requirement_section,
                "requirement_text": requirement.requirement_text,
                "requirement_order": requirement.requirement_order,
                "source_reference": requirement.source_reference,
            }
            for requirement in requirements
        ],
        "supplier_responses": [
            {
                "response_id": str(response.response_id),
                "supplier_id": str(response.supplier_id),
                "supplier_name": response.supplier.supplier_name if response.supplier is not None else None,
                "supplier_type": response.supplier.supplier_type if response.supplier is not None else None,
                "submission_status": response.submission_status,
                "quotation_reference": response.quotation_reference,
                "notes": response.notes,
                "submitted_at": _iso_datetime(response.submitted_at),
                "documents": [
                    {
                        "document_id": str(document.document_id),
                        "document_type": document.document_type,
                        "document_name": document.document_name,
                        "document_version": document.document_version,
                        "source_system": document.source_system,
                        "external_document_id": document.external_document_id,
                        "source_reference": document.source_reference,
                        "notes": document.notes,
                    }
                    for document in sorted(
                        response.documents or [],
                        key=lambda item: (item.document_name or "", str(item.document_id)),
                    )
                ],
                "structured_requirement_responses": [
                    {
                        "requirement_response_id": str(requirement_response.requirement_response_id),
                        "requirement_item_id": str(requirement_response.requirement_item_id),
                        "fit_status": requirement_response.fit_status,
                        "supplier_response_text": requirement_response.supplier_response_text,
                        "evidence_reference": requirement_response.evidence_reference,
                        "notes": requirement_response.notes,
                    }
                    for requirement_response in sorted(
                        response.requirement_responses or [],
                        key=lambda item: str(item.requirement_item_id),
                    )
                ],
            }
            for response in responses
        ],
    }


def _document_evidence_summary(response: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for document in response.get("documents") or []:
        if not isinstance(document, dict):
            continue
        label = _strip_optional(document.get("document_name"))
        if not label:
            continue
        version = _strip_optional(document.get("document_version"))
        doc_type = _strip_optional(document.get("document_type"))
        source_reference = _strip_optional(document.get("source_reference"))
        if version:
            label = f"{label} v{version}"
        if doc_type:
            label = f"{doc_type}: {label}"
        if source_reference:
            label = f"{label} ({source_reference})"
        parts.append(label)
    return "; ".join(parts[:8]) or None


def _structured_response_map(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = response.get("structured_requirement_responses") or []
    return {
        str(row.get("requirement_item_id")): row
        for row in rows
        if isinstance(row, dict) and row.get("requirement_item_id")
    }


def _build_deterministic_requirement_results(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    requirements = [item for item in snapshot.get("requirements") or [] if isinstance(item, dict)]
    supplier_responses = [item for item in snapshot.get("supplier_responses") or [] if isinstance(item, dict)]
    results: list[dict[str, Any]] = []

    for response in supplier_responses:
        response_id = str(response.get("response_id"))
        supplier_id = str(response.get("supplier_id"))
        structured_rows = _structured_response_map(response)
        document_evidence = _document_evidence_summary(response)
        has_documents = bool(document_evidence)

        for requirement in requirements:
            requirement_id = str(requirement.get("requirement_item_id"))
            structured = structured_rows.get(requirement_id)
            structured_fit = _strip_optional(structured.get("fit_status")) if structured is not None else None
            structured_text = _strip_optional(structured.get("supplier_response_text")) if structured is not None else None
            structured_evidence = _strip_optional(structured.get("evidence_reference")) if structured is not None else None
            structured_notes = _strip_optional(structured.get("notes")) if structured is not None else None

            if structured_fit not in ALLOWED_ANALYSIS_FIT_STATUSES:
                evaluated_fit = FIT_STATUS_PARTIALLY_MEETS
                confidence_score = 0.35 if has_documents else 0.25
                reasoning = (
                    "No structured requirement response was captured for this supplier. "
                    "The requirement is treated as PARTIALLY_MEETS with low confidence rather than inferring compliance."
                )
            else:
                evaluated_fit = structured_fit
                confidence_score = 0.65 if structured_fit == FIT_STATUS_PARTIALLY_MEETS else 0.8
                if structured_text:
                    confidence_score += 0.1
                if structured_evidence:
                    confidence_score += 0.05
                if has_documents:
                    confidence_score += 0.03
                confidence_score = min(confidence_score, 0.95)

                reasoning_parts = [
                    f"Supplier declared {_format_fit_status(structured_fit)} in the structured response matrix."
                ]
                if structured_text:
                    reasoning_parts.append(f"Supplier response: {_truncate(structured_text, 700)}")
                if structured_notes:
                    reasoning_parts.append(f"Notes: {_truncate(structured_notes, 450)}")
                if structured_fit == FIT_STATUS_PARTIALLY_MEETS:
                    reasoning_parts.append("Partial fit is retained unless later evidence clearly resolves the gap.")
                if structured_fit == FIT_STATUS_NOT_MEETS:
                    reasoning_parts.append("The supplier-declared gap is preserved as a requirement-level weakness.")
                reasoning = " ".join(reasoning_parts)

            evidence_parts = [item for item in (structured_evidence, document_evidence) if item]
            results.append(
                {
                    "supplier_response_id": response_id,
                    "supplier_id": supplier_id,
                    "supplier_name": response.get("supplier_name"),
                    "supplier_type": response.get("supplier_type"),
                    "requirement_id": requirement_id,
                    "requirement_key": requirement.get("requirement_key"),
                    "requirement_section": requirement.get("requirement_section"),
                    "requirement_text": requirement.get("requirement_text"),
                    "requirement_order": requirement.get("requirement_order"),
                    "structured_fit": structured_fit,
                    "evaluated_fit": evaluated_fit,
                    "confidence_score": round(confidence_score, 2),
                    "reasoning_text": reasoning,
                    "evidence_reference": "; ".join(evidence_parts) or None,
                }
            )

    return results


def _is_critical_requirement(result: dict[str, Any]) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            result.get("requirement_key"),
            result.get("requirement_section"),
            result.get("requirement_text"),
        )
    ).lower()
    return any(hint in text for hint in CRITICAL_REQUIREMENT_HINTS)


def _build_supplier_summaries(
    results: list[dict[str, Any]],
    snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    supplier_metadata = {
        str(response.get("supplier_id")): {
            "supplier_id": str(response.get("supplier_id")),
            "supplier_name": response.get("supplier_name"),
            "supplier_type": response.get("supplier_type"),
            "supplier_response_id": str(response.get("response_id")),
        }
        for response in snapshot.get("supplier_responses") or []
        if isinstance(response, dict) and response.get("supplier_id")
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(str(result.get("supplier_id")), []).append(result)

    summaries: list[dict[str, Any]] = []
    for supplier_id, supplier_results in grouped.items():
        total = len(supplier_results)
        meets_count = sum(1 for item in supplier_results if item.get("evaluated_fit") == FIT_STATUS_MEETS)
        partial_count = sum(1 for item in supplier_results if item.get("evaluated_fit") == FIT_STATUS_PARTIALLY_MEETS)
        not_count = sum(1 for item in supplier_results if item.get("evaluated_fit") == FIT_STATUS_NOT_MEETS)
        weighted_score = sum(FIT_SCORE.get(str(item.get("evaluated_fit")), 0.0) for item in supplier_results)
        overall_score = round((weighted_score / total) * 100, 2) if total else 0.0

        strengths = [
            _requirement_label(item)
            for item in sorted(
                (row for row in supplier_results if row.get("evaluated_fit") == FIT_STATUS_MEETS),
                key=lambda row: (-float(row.get("confidence_score") or 0), row.get("requirement_order") or 999_999),
            )[:5]
        ]
        weaknesses = [
            _requirement_label(item)
            for item in sorted(
                (row for row in supplier_results if row.get("evaluated_fit") == FIT_STATUS_NOT_MEETS),
                key=lambda row: (row.get("requirement_order") or 999_999, _requirement_label(row)),
            )[:5]
        ]
        if not weaknesses:
            weaknesses = [
                _requirement_label(item)
                for item in sorted(
                    (row for row in supplier_results if row.get("evaluated_fit") == FIT_STATUS_PARTIALLY_MEETS),
                    key=lambda row: (float(row.get("confidence_score") or 0), row.get("requirement_order") or 999_999),
                )[:3]
            ]

        risk_flags = [
            f"Critical gap: {_requirement_label(item)}"
            for item in sorted(
                (
                    row
                    for row in supplier_results
                    if row.get("evaluated_fit") == FIT_STATUS_NOT_MEETS and _is_critical_requirement(row)
                ),
                key=lambda row: (row.get("requirement_order") or 999_999, _requirement_label(row)),
            )[:5]
        ]
        if not risk_flags and not_count > 0:
            risk_flags.append(f"{not_count} requirement(s) evaluated as NOT_MEETS require remediation review")

        metadata = supplier_metadata.get(supplier_id, {"supplier_id": supplier_id})
        summaries.append(
            {
                **metadata,
                "overall_score": overall_score,
                "meets_count": meets_count,
                "partially_meets_count": partial_count,
                "not_meets_count": not_count,
                "total_requirements": total,
                "meets_percent": round((meets_count / total) * 100, 2) if total else 0.0,
                "partially_meets_percent": round((partial_count / total) * 100, 2) if total else 0.0,
                "not_meets_percent": round((not_count / total) * 100, 2) if total else 0.0,
                "strengths": strengths,
                "weaknesses": weaknesses,
                "risk_flags": risk_flags,
                "recommendation_rank": 0,
            }
        )

    summaries.sort(
        key=lambda item: (
            -float(item.get("overall_score") or 0),
            -int(item.get("meets_count") or 0),
            int(item.get("not_meets_count") or 0),
            str(item.get("supplier_name") or ""),
        )
    )
    for rank, summary in enumerate(summaries, start=1):
        summary["recommendation_rank"] = rank
    return summaries


def _build_supplier_differentiators(summary: dict[str, Any], summaries: list[dict[str, Any]]) -> list[str]:
    differentiators: list[str] = []
    score = float(summary.get("overall_score") or 0)
    rank = int(summary.get("recommendation_rank") or 0)
    if rank == 1 and len(summaries) > 1:
        next_score = float(summaries[1].get("overall_score") or 0)
        differentiators.append(f"Leads the next supplier by {round(score - next_score, 2)} score points")
    if summary.get("not_meets_count") == 0:
        differentiators.append("No requirements evaluated as NOT_MEETS")
    if summary.get("risk_flags"):
        differentiators.append("Has critical or high-priority risk flags to review")
    return differentiators


def _build_top_supplier_rationale(best_supplier: dict[str, Any] | None) -> str | None:
    if best_supplier is None:
        return None
    supplier_name = best_supplier.get("supplier_name") or best_supplier.get("supplier_id")
    score = best_supplier.get("overall_score")
    meets_percent = best_supplier.get("meets_percent")
    not_meets_percent = best_supplier.get("not_meets_percent")
    return (
        f"{supplier_name} is recommended as the leading compliance fit with score {score}, "
        f"{meets_percent}% MEETS, and {not_meets_percent}% NOT_MEETS."
    )


def _build_summary_json(
    snapshot: dict[str, Any],
    results: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    ai_generation: dict[str, Any],
) -> dict[str, Any]:
    best_supplier = summaries[0] if summaries else None
    total_requirements = len(snapshot.get("requirements") or [])
    total_suppliers = len(snapshot.get("supplier_responses") or [])
    if best_supplier:
        overall_insight = (
            f"{best_supplier.get('supplier_name') or best_supplier.get('supplier_id')} ranks first "
            f"with a compliance score of {best_supplier.get('overall_score')}."
        )
    else:
        overall_insight = "No supplier responses were available for comparison."

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "prompt_version": PROMPT_VERSION,
        "ai_generation": ai_generation,
        "scoring_model": {
            "MEETS": 1.0,
            "PARTIALLY_MEETS": 0.5,
            "NOT_MEETS": 0.0,
            "overall_score": "weighted average converted to 0-100",
        },
        "evaluation_summary": {
            "total_suppliers": total_suppliers,
            "total_requirements": total_requirements,
            "best_performing_supplier": best_supplier.get("supplier_name") if best_supplier else None,
            "overall_comparison_insight": overall_insight,
        },
        "supplier_wise_summary": [
            {
                "supplier_id": summary.get("supplier_id"),
                "supplier_name": summary.get("supplier_name"),
                "overall_score": summary.get("overall_score"),
                "recommendation_rank": summary.get("recommendation_rank"),
                "strengths": summary.get("strengths") or [],
                "weaknesses": summary.get("weaknesses") or [],
                "risk_flags": summary.get("risk_flags") or [],
                "differentiators": _build_supplier_differentiators(summary, summaries),
            }
            for summary in summaries
        ],
        "recommendation": {
            "ranked_suppliers": [
                {
                    "rank": summary.get("recommendation_rank"),
                    "supplier_id": summary.get("supplier_id"),
                    "supplier_name": summary.get("supplier_name"),
                    "overall_score": summary.get("overall_score"),
                    "meets_percent": summary.get("meets_percent"),
                    "not_meets_percent": summary.get("not_meets_percent"),
                }
                for summary in summaries
            ],
            "top_supplier_rationale": _build_top_supplier_rationale(best_supplier),
            "trade_offs": [
                "This Phase 3 score evaluates URS compliance and structured response evidence only.",
                "Commercial price, delivery commitments, and contractual risk should be reviewed alongside this recommendation.",
                "The report is advisory and does not auto-submit, auto-approve, or modify supplier responses.",
            ],
        },
        "traceability": {
            "input_snapshot_created_at": snapshot.get("snapshot_created_at"),
            "requirement_analysis_count": len(results),
            "source_data": [
                "evaluation_requirement_item",
                "supplier_requirement_response",
                "supplier_response_document metadata",
                "authored_document URS snapshot",
                "supplier metadata",
            ],
        },
    }


def _initial_ai_metadata() -> dict[str, Any]:
    settings = get_settings()
    if not settings.LLM_ENABLED:
        return {
            "status": "DISABLED",
            "provider": RULE_ENGINE_PROVIDER,
            "model": RULE_ENGINE_MODEL,
            "message": "LLM_ENABLED is false; deterministic explainable scoring was used.",
        }
    return {
        "status": "CONFIGURED",
        "provider": _infer_provider_name(),
        "model": _strip_optional(settings.LLM_MODEL) or "not-configured",
        "message": "OpenAI-compatible LLM configuration detected.",
    }


def _build_llm_prompt_payload(
    snapshot: dict[str, Any],
    deterministic_results: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
) -> str:
    compact_payload = {
        "task": (
            "Validate supplier fit per URS requirement using structured supplier responses as the primary signal. "
            "Do not invent evidence. If evidence is unclear or missing, use PARTIALLY_MEETS with low confidence."
        ),
        "required_json_shape": {
            "requirement_analyses": [
                {
                    "supplier_response_id": "uuid",
                    "requirement_id": "uuid",
                    "evaluated_fit": "MEETS | PARTIALLY_MEETS | NOT_MEETS",
                    "confidence_score": "number from 0 to 1",
                    "reasoning_text": "brief auditable reasoning",
                    "evidence_reference": "optional evidence reference",
                }
            ],
            "summary_json": "optional narrative summary object",
        },
        "evaluation": snapshot.get("evaluation"),
        "requirements": [
            {
                "requirement_item_id": item.get("requirement_item_id"),
                "requirement_key": item.get("requirement_key"),
                "requirement_section": item.get("requirement_section"),
                "requirement_text": _truncate(item.get("requirement_text"), 900),
                "requirement_order": item.get("requirement_order"),
            }
            for item in snapshot.get("requirements") or []
            if isinstance(item, dict)
        ],
        "supplier_responses": [
            {
                "response_id": response.get("response_id"),
                "supplier_id": response.get("supplier_id"),
                "supplier_name": response.get("supplier_name"),
                "supplier_type": response.get("supplier_type"),
                "documents": [
                    {
                        "document_type": document.get("document_type"),
                        "document_name": document.get("document_name"),
                        "source_reference": document.get("source_reference"),
                    }
                    for document in response.get("documents") or []
                    if isinstance(document, dict)
                ],
                "structured_requirement_responses": [
                    {
                        "requirement_item_id": item.get("requirement_item_id"),
                        "fit_status": item.get("fit_status"),
                        "supplier_response_text": _truncate(item.get("supplier_response_text"), 900),
                        "evidence_reference": item.get("evidence_reference"),
                        "notes": _truncate(item.get("notes"), 500),
                    }
                    for item in response.get("structured_requirement_responses") or []
                    if isinstance(item, dict)
                ],
            }
            for response in snapshot.get("supplier_responses") or []
            if isinstance(response, dict)
        ],
        "deterministic_baseline": [
            {
                "supplier_response_id": item.get("supplier_response_id"),
                "requirement_id": item.get("requirement_id"),
                "structured_fit": item.get("structured_fit"),
                "evaluated_fit": item.get("evaluated_fit"),
                "confidence_score": item.get("confidence_score"),
            }
            for item in deterministic_results
        ],
        "deterministic_supplier_scores": summaries,
    }
    return json.dumps(compact_payload, ensure_ascii=True, default=str)


def _extract_json_payload(raw_text: str) -> dict[str, Any] | None:
    stripped = raw_text.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        payload = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def _generate_ai_enhancements(
    snapshot: dict[str, Any],
    deterministic_results: list[dict[str, Any]],
    deterministic_summaries: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    settings = get_settings()
    initial_metadata = _initial_ai_metadata()
    if not settings.LLM_ENABLED:
        return None, initial_metadata

    api_key = _strip_optional(settings.LLM_API_KEY)
    model = _strip_optional(settings.LLM_MODEL)
    if api_key is None or model is None:
        return None, {
            **initial_metadata,
            "status": "MISCONFIGURED",
            "message": "LLM_ENABLED is true, but LLM_API_KEY or LLM_MODEL is not configured.",
        }

    prompt_input = _build_llm_prompt_payload(snapshot, deterministic_results, deterministic_summaries)
    if len(prompt_input) > 120_000:
        return None, {
            **initial_metadata,
            "status": "SKIPPED",
            "message": "Analysis input exceeded the safe prompt size; deterministic scoring was used.",
        }

    request_id = str(uuid.uuid4())
    request_payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a GxP supplier evaluation assistant. Return valid JSON only. "
                    "Use structured supplier responses as primary evidence, do not hallucinate missing evidence, "
                    "and keep every requirement-level reasoning traceable and concise."
                ),
            },
            {"role": "user", "content": prompt_input},
        ],
        "temperature": 0,
    }
    max_attempts = max(1, settings.LLM_MAX_RETRIES + 1)
    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
                    headers=_build_llm_headers(api_key, request_id),
                    json=request_payload,
                )
                response.raise_for_status()
            response_payload = response.json()
            if not isinstance(response_payload, dict):
                raise ValueError("LLM provider returned a non-object payload")
            content = _extract_chat_completion_output_text(response_payload)
            ai_payload = _extract_json_payload(content)
            if ai_payload is None:
                raise ValueError("LLM provider did not return parseable JSON")
            return ai_payload, {
                **initial_metadata,
                "status": "COMPLETED",
                "request_id": request_id,
                "message": "LLM validation completed successfully.",
            }
        except (httpx.HTTPError, ValueError) as exc:
            if attempt >= max_attempts:
                return None, {
                    **initial_metadata,
                    "status": "FALLBACK",
                    "request_id": request_id,
                    "message": f"LLM validation failed; deterministic scoring was used. {exc}",
                }
            await asyncio.sleep(min(1.5 * attempt, 3.0))

    return None, {
        **initial_metadata,
        "status": "FALLBACK",
        "request_id": request_id,
        "message": "LLM validation failed; deterministic scoring was used.",
    }


def _normalize_ai_fit(value: Any) -> str | None:
    normalized = _strip_optional(str(value)) if value is not None else None
    if normalized is None:
        return None
    upper_value = normalized.upper()
    return upper_value if upper_value in ALLOWED_ANALYSIS_FIT_STATUSES else None


def _clamp_confidence(value: Any, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return round(min(max(numeric, 0.0), 1.0), 2)


def _apply_ai_enhancements(
    deterministic_results: list[dict[str, Any]],
    ai_payload: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if ai_payload is None:
        return deterministic_results, None

    ai_rows = ai_payload.get("requirement_analyses")
    if not isinstance(ai_rows, list):
        ai_summary = ai_payload.get("summary_json")
        return deterministic_results, ai_summary if isinstance(ai_summary, dict) else None

    ai_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in ai_rows:
        if not isinstance(row, dict):
            continue
        supplier_response_id = _strip_optional(str(row.get("supplier_response_id") or ""))
        requirement_id = _strip_optional(str(row.get("requirement_id") or ""))
        if supplier_response_id and requirement_id:
            ai_by_key[(supplier_response_id, requirement_id)] = row

    merged: list[dict[str, Any]] = []
    for deterministic in deterministic_results:
        next_result = dict(deterministic)
        key = (str(deterministic.get("supplier_response_id")), str(deterministic.get("requirement_id")))
        ai_row = ai_by_key.get(key)
        if ai_row is None:
            merged.append(next_result)
            continue

        structured_fit = _normalize_ai_fit(deterministic.get("structured_fit"))
        ai_fit = _normalize_ai_fit(ai_row.get("evaluated_fit"))
        current_fit = _normalize_ai_fit(deterministic.get("evaluated_fit")) or FIT_STATUS_PARTIALLY_MEETS
        if structured_fit is None:
            next_fit = FIT_STATUS_PARTIALLY_MEETS
            confidence = min(_clamp_confidence(ai_row.get("confidence_score"), 0.35), 0.45)
        elif ai_fit is not None and FIT_RANK[ai_fit] <= FIT_RANK[structured_fit]:
            next_fit = ai_fit
            confidence = _clamp_confidence(
                ai_row.get("confidence_score"),
                float(deterministic.get("confidence_score") or 0.65),
            )
        else:
            next_fit = current_fit
            confidence = float(deterministic.get("confidence_score") or 0.65)

        ai_reasoning = _strip_optional(ai_row.get("reasoning_text"))
        if ai_reasoning:
            next_result["reasoning_text"] = f"AI validation: {_truncate(ai_reasoning, 1800)}"
        next_result["evaluated_fit"] = next_fit
        next_result["confidence_score"] = round(confidence, 2)
        ai_evidence = _strip_optional(ai_row.get("evidence_reference"))
        if ai_evidence:
            next_result["evidence_reference"] = _truncate(ai_evidence, 1200)
        merged.append(next_result)

    ai_summary = ai_payload.get("summary_json")
    return merged, ai_summary if isinstance(ai_summary, dict) else None


def _calculate_counts_by_supplier(
    rows: list[SupplierRequirementAnalysisResponse],
) -> dict[uuid.UUID, dict[str, int | float]]:
    counts: dict[uuid.UUID, dict[str, int | float]] = {}
    for row in rows:
        supplier_counts = counts.setdefault(
            row.supplier_id,
            {
                "meets_count": 0,
                "partially_meets_count": 0,
                "not_meets_count": 0,
                "total_requirements": 0,
            },
        )
        supplier_counts["total_requirements"] = int(supplier_counts["total_requirements"]) + 1
        if row.evaluated_fit == FIT_STATUS_MEETS:
            supplier_counts["meets_count"] = int(supplier_counts["meets_count"]) + 1
        elif row.evaluated_fit == FIT_STATUS_PARTIALLY_MEETS:
            supplier_counts["partially_meets_count"] = int(supplier_counts["partially_meets_count"]) + 1
        elif row.evaluated_fit == FIT_STATUS_NOT_MEETS:
            supplier_counts["not_meets_count"] = int(supplier_counts["not_meets_count"]) + 1

    for supplier_counts in counts.values():
        total = int(supplier_counts["total_requirements"])
        supplier_counts["meets_percent"] = (
            round((int(supplier_counts["meets_count"]) / total) * 100, 2) if total else 0
        )
        supplier_counts["partially_meets_percent"] = (
            round((int(supplier_counts["partially_meets_count"]) / total) * 100, 2) if total else 0
        )
        supplier_counts["not_meets_percent"] = (
            round((int(supplier_counts["not_meets_count"]) / total) * 100, 2) if total else 0
        )
    return counts


async def _build_analysis_response(
    db: AsyncSession,
    analysis: SupplierEvaluationAnalysis,
) -> SupplierEvaluationAnalysisResponse:
    stored_analysis = await _get_analysis_by_id(db, analysis.analysis_id)
    if stored_analysis is None:
        raise ServiceNotFoundError("Supplier evaluation analysis not found")

    evaluation = await _get_evaluation_for_analysis(db, stored_analysis.evaluation_id)
    requirement_by_id: dict[uuid.UUID, EvaluationRequirementItem] = {}
    response_by_id: dict[uuid.UUID, SupplierEvaluationResponse] = {}
    response_by_supplier_id: dict[uuid.UUID, SupplierEvaluationResponse] = {}
    structured_fit_by_key: dict[tuple[uuid.UUID, uuid.UUID], str] = {}

    if evaluation is not None:
        requirement_by_id = {
            requirement.requirement_item_id: requirement
            for requirement in evaluation.requirement_items or []
        }
        for response in evaluation.responses or []:
            response_by_id[response.response_id] = response
            response_by_supplier_id[response.supplier_id] = response
            for requirement_response in response.requirement_responses or []:
                structured_fit_by_key[
                    (response.response_id, requirement_response.requirement_item_id)
                ] = requirement_response.fit_status

    def requirement_sort_key(item: SupplierRequirementAnalysis) -> tuple[int, str, str]:
        requirement = requirement_by_id.get(item.requirement_id)
        response = response_by_id.get(item.supplier_response_id)
        order = requirement.requirement_order if requirement is not None and requirement.requirement_order is not None else 999_999
        supplier_name = (
            response.supplier.supplier_name
            if response is not None and response.supplier is not None
            else ""
        )
        return order, supplier_name or "", str(item.id)

    requirement_rows: list[SupplierRequirementAnalysisResponse] = []
    for row in sorted(stored_analysis.requirement_analyses or [], key=requirement_sort_key):
        response = response_by_id.get(row.supplier_response_id)
        requirement = requirement_by_id.get(row.requirement_id)
        supplier = response.supplier if response is not None else None
        requirement_rows.append(
            SupplierRequirementAnalysisResponse(
                id=row.id,
                analysis_id=row.analysis_id,
                supplier_response_id=row.supplier_response_id,
                supplier_id=response.supplier_id if response is not None else uuid.UUID(int=0),
                supplier_name=supplier.supplier_name if supplier is not None else None,
                requirement_id=row.requirement_id,
                requirement_key=requirement.requirement_key if requirement is not None else None,
                requirement_section=requirement.requirement_section if requirement is not None else None,
                requirement_text=requirement.requirement_text if requirement is not None else "",
                evaluated_fit=row.evaluated_fit,
                structured_fit=structured_fit_by_key.get((row.supplier_response_id, row.requirement_id)),
                confidence_score=row.confidence_score,
                reasoning_text=row.reasoning_text,
                evidence_reference=row.evidence_reference,
                created_at=row.created_at,
            )
        )

    counts_by_supplier = _calculate_counts_by_supplier(requirement_rows)
    comparison_rows: list[SupplierComparisonSummaryResponse] = []
    for summary in sorted(
        stored_analysis.comparison_summaries or [],
        key=lambda item: (item.recommendation_rank, str(item.supplier_id)),
    ):
        response = response_by_supplier_id.get(summary.supplier_id)
        supplier = response.supplier if response is not None else None
        counts = counts_by_supplier.get(summary.supplier_id, {})
        comparison_rows.append(
            SupplierComparisonSummaryResponse(
                id=summary.id,
                analysis_id=summary.analysis_id,
                supplier_id=summary.supplier_id,
                supplier_name=supplier.supplier_name if supplier is not None else None,
                supplier_type=supplier.supplier_type if supplier is not None else None,
                supplier_response_id=response.response_id if response is not None else None,
                overall_score=summary.overall_score,
                meets_count=int(counts.get("meets_count", 0)),
                partially_meets_count=int(counts.get("partially_meets_count", 0)),
                not_meets_count=int(counts.get("not_meets_count", 0)),
                total_requirements=int(counts.get("total_requirements", 0)),
                meets_percent=float(counts.get("meets_percent", 0)),
                partially_meets_percent=float(counts.get("partially_meets_percent", 0)),
                not_meets_percent=float(counts.get("not_meets_percent", 0)),
                strengths=_as_string_list(summary.strengths),
                weaknesses=_as_string_list(summary.weaknesses),
                risk_flags=_as_string_list(summary.risk_flags),
                recommendation_rank=summary.recommendation_rank,
                created_at=summary.created_at,
            )
        )

    return SupplierEvaluationAnalysisResponse(
        analysis_id=stored_analysis.analysis_id,
        evaluation_id=stored_analysis.evaluation_id,
        status=stored_analysis.status,
        started_at=stored_analysis.started_at,
        completed_at=stored_analysis.completed_at,
        triggered_by=stored_analysis.triggered_by,
        provider=stored_analysis.provider,
        model=stored_analysis.model,
        prompt_version=stored_analysis.prompt_version,
        input_snapshot_json=stored_analysis.input_snapshot_json,
        summary_json=stored_analysis.summary_json,
        error_message=stored_analysis.error_message,
        created_at=stored_analysis.created_at,
        requirement_analyses=requirement_rows,
        comparison_summaries=comparison_rows,
    )


async def run_supplier_evaluation_analysis(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
    payload: SupplierEvaluationAnalysisRunRequest,
) -> SupplierEvaluationAnalysisResponse:
    evaluation = await _get_evaluation_for_analysis(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")
    _ensure_evaluation_can_run_analysis(evaluation)

    now = datetime.now(UTC)
    initial_metadata = _initial_ai_metadata()
    snapshot = _build_input_snapshot(evaluation)
    analysis = SupplierEvaluationAnalysis(
        evaluation_id=evaluation.evaluation_id,
        status=ANALYSIS_STATUS_RUNNING,
        started_at=now,
        triggered_by=_strip_optional(payload.triggered_by),
        provider=initial_metadata.get("provider"),
        model=initial_metadata.get("model"),
        prompt_version=PROMPT_VERSION,
        input_snapshot_json=snapshot,
        created_at=now,
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)
    analysis_id = analysis.analysis_id

    try:
        deterministic_results = _build_deterministic_requirement_results(snapshot)
        deterministic_summaries = _build_supplier_summaries(deterministic_results, snapshot)
        ai_payload, ai_metadata = await _generate_ai_enhancements(
            snapshot,
            deterministic_results,
            deterministic_summaries,
        )
        final_results, ai_summary_json = _apply_ai_enhancements(deterministic_results, ai_payload)
        final_summaries = _build_supplier_summaries(final_results, snapshot)
        summary_json = _build_summary_json(snapshot, final_results, final_summaries, ai_metadata)
        if ai_summary_json is not None:
            summary_json["ai_generated_summary"] = ai_summary_json

        completed_at = datetime.now(UTC)
        analysis.status = ANALYSIS_STATUS_COMPLETED
        analysis.completed_at = completed_at
        analysis.provider = ai_metadata.get("provider")
        analysis.model = ai_metadata.get("model")
        analysis.summary_json = summary_json
        analysis.error_message = None

        for result in final_results:
            db.add(
                SupplierRequirementAnalysis(
                    analysis_id=analysis.analysis_id,
                    supplier_response_id=uuid.UUID(str(result["supplier_response_id"])),
                    requirement_id=uuid.UUID(str(result["requirement_id"])),
                    evaluated_fit=str(result["evaluated_fit"]),
                    confidence_score=float(result["confidence_score"]),
                    reasoning_text=str(result["reasoning_text"]),
                    evidence_reference=result.get("evidence_reference"),
                    created_at=completed_at,
                )
            )
        for summary in final_summaries:
            db.add(
                SupplierComparisonSummary(
                    analysis_id=analysis.analysis_id,
                    supplier_id=uuid.UUID(str(summary["supplier_id"])),
                    overall_score=float(summary["overall_score"]),
                    strengths=summary.get("strengths") or [],
                    weaknesses=summary.get("weaknesses") or [],
                    risk_flags=summary.get("risk_flags") or [],
                    recommendation_rank=int(summary["recommendation_rank"]),
                    created_at=completed_at,
                )
            )

        await db.commit()
    except Exception as exc:
        await db.rollback()
        failed_analysis = await _get_analysis_by_id(db, analysis_id)
        if failed_analysis is None:
            raise
        failed_analysis.status = ANALYSIS_STATUS_FAILED
        failed_analysis.completed_at = datetime.now(UTC)
        failed_analysis.error_message = str(exc)
        failed_analysis.summary_json = {
            "generated_at": datetime.now(UTC).isoformat(),
            "ai_generation": initial_metadata,
            "error": str(exc),
        }
        await db.commit()
        return await _build_analysis_response(db, failed_analysis)

    completed_analysis = await _get_analysis_by_id(db, analysis_id)
    if completed_analysis is None:
        raise ServiceNotFoundError("Supplier evaluation analysis not found")
    return await _build_analysis_response(db, completed_analysis)


async def get_supplier_evaluation_analysis(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
) -> SupplierEvaluationAnalysisListResponse:
    evaluation = await _get_evaluation_for_analysis(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")

    result = await db.execute(
        _analysis_query()
        .where(SupplierEvaluationAnalysis.evaluation_id == evaluation_id)
        .order_by(SupplierEvaluationAnalysis.created_at.desc(), SupplierEvaluationAnalysis.analysis_id.desc())
    )
    analyses = result.scalars().all()
    history = [await _build_analysis_response(db, analysis) for analysis in analyses]
    return SupplierEvaluationAnalysisListResponse(latest=history[0] if history else None, history=history)


async def get_supplier_evaluation_comparison(
    db: AsyncSession,
    evaluation_id: uuid.UUID,
) -> SupplierEvaluationComparisonResponse:
    evaluation = await _get_evaluation_for_analysis(db, evaluation_id)
    if evaluation is None:
        raise ServiceNotFoundError("Supplier evaluation not found")

    latest = await _get_latest_analysis(db, evaluation_id)
    if latest is None:
        return SupplierEvaluationComparisonResponse(
            analysis_id=None,
            evaluation_id=evaluation_id,
            status=ANALYSIS_STATUS_NOT_STARTED,
            summary_json=None,
            comparison_summaries=[],
            requirement_analyses=[],
        )

    response = await _build_analysis_response(db, latest)
    return SupplierEvaluationComparisonResponse(
        analysis_id=response.analysis_id,
        evaluation_id=response.evaluation_id,
        status=response.status,
        summary_json=response.summary_json,
        comparison_summaries=response.comparison_summaries,
        requirement_analyses=response.requirement_analyses,
    )
