from __future__ import annotations

import asyncio
import copy
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.models.asset import Asset
from app.models.asset_release import AssetRelease
from app.models.asset_spec import AssetSpec
from app.models.document_template import DocumentTemplate

GENERATION_MODE_TEMPLATE_PREFILL = "TEMPLATE_PREFILL"
GENERATION_MODE_AI_ASSISTED = "AI_ASSISTED"
GENERATION_STATUS_COMPLETED = "COMPLETED"
GENERATION_STATUS_FALLBACK = "FALLBACK"
GENERATION_OPERATION_CREATE = "CREATE"
GENERATION_OPERATION_REGENERATE = "REGENERATE"
GENERATION_OPERATION_IMPROVE = "IMPROVE"
GENERATION_HISTORY_LIMIT = 20
URS_GENERATION_PROMPT_VERSION = "urs-ai-draft-v1"
PROMPT_TEMPLATE_CONTENT_CHARS = 2500
PROMPT_BASELINE_DRAFT_CHARS = 4500
PROMPT_EXISTING_CONTENT_CHARS = 3000
PROMPT_SOURCE_TEXT_CHARS = 1800
PROMPT_RELEASE_TEXT_CHARS = 1000
PROMPT_SPEC_TEXT_CHARS = 300
PROMPT_MAX_SPECS = 20


class UrsGenerationError(Exception):
    """Raised when AI-assisted URS generation fails."""


class UrsGenerationUnavailableError(UrsGenerationError):
    """Raised when the configured AI provider cannot be used safely."""


@dataclass(slots=True)
class AiGeneratedDraft:
    content: str
    generation_metadata: dict[str, Any]


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _truncate_for_prompt(value: Any, max_chars: int) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars].rstrip()}\n\n[Truncated for AI prompt size]"


def sanitize_urs_generation_failure_reason(reason: str | None) -> str | None:
    normalized = _strip_optional(reason)
    if normalized is None:
        return None

    lowered = normalized.lower()
    if any(marker in lowered for marker in ("request too large", "tokens per minute", "tpm", "status 413")):
        return (
            "The AI provider rejected the request because the draft context was too large for the configured model. "
            "The system used template prefill instead."
        )
    if "rate limit" in lowered or "provider rate limits" in lowered or "status 429" in lowered:
        return "The AI provider rate limit was reached. The system used template prefill instead."
    if "authentication" in lowered or "api_key" in lowered or "api key" in lowered:
        return "The AI provider is not configured correctly. The system used template prefill instead."
    if "timed out" in lowered or "timeout" in lowered:
        return "The AI provider timed out. The system used template prefill instead."
    if "communication failed" in lowered:
        return "The AI provider could not be reached. The system used template prefill instead."
    if "llm_enabled is false" in lowered:
        return "AI-assisted generation is disabled. The system used template prefill instead."
    if "llm_model is not configured" in lowered:
        return "The AI model is not configured. The system used template prefill instead."
    if "llm_api_key is not configured" in lowered:
        return "The AI API key is not configured. The system used template prefill instead."

    return "AI-assisted generation could not be completed. The system used template prefill instead."


def _deepcopy_dict(value: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(value) if value is not None else {}


def build_generation_metadata(
    *,
    requested_mode: str,
    actual_mode: str,
    status: str,
    operation: str,
    purpose_notes: str | None,
    special_instructions: str | None,
    additional_notes: str | None,
    provider: str | None = None,
    model: str | None = None,
    fallback_reason: str | None = None,
    used_existing_content: bool = False,
    generated_at: datetime | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    resolved_generated_at = generated_at or datetime.now(UTC)
    return {
        "requested_mode": requested_mode,
        "mode": actual_mode,
        "status": status,
        "operation": operation,
        "generated_at": resolved_generated_at.isoformat(),
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "fallback_reason": _strip_optional(fallback_reason),
        "used_existing_content": used_existing_content,
        "inputs": {
            "purpose_notes": _strip_optional(purpose_notes),
            "special_instructions": _strip_optional(special_instructions),
        },
    }


def carry_forward_generation_history(
    source_context: dict[str, Any],
    previous_source_context: dict[str, Any] | None,
) -> dict[str, Any]:
    next_context = _deepcopy_dict(source_context)
    previous = _deepcopy_dict(previous_source_context)

    previous_history = previous.get("generation_history")
    if isinstance(previous_history, list):
        next_context["generation_history"] = previous_history[:GENERATION_HISTORY_LIMIT]
    else:
        previous_generation = previous.get("generation")
        if isinstance(previous_generation, dict):
            next_context["generation_history"] = [previous_generation]

    return next_context


def append_generation_metadata(
    source_context: dict[str, Any],
    generation_metadata: dict[str, Any],
) -> dict[str, Any]:
    next_context = _deepcopy_dict(source_context)
    history = next_context.get("generation_history")
    if not isinstance(history, list):
        history = []

    history.insert(0, copy.deepcopy(generation_metadata))
    next_context["generation_history"] = history[:GENERATION_HISTORY_LIMIT]
    next_context["generation"] = copy.deepcopy(generation_metadata)

    merge_inputs = next_context.get("merge_inputs")
    if isinstance(merge_inputs, dict):
        inputs = generation_metadata.get("inputs")
        if isinstance(inputs, dict):
            merge_inputs["purpose_notes"] = inputs.get("purpose_notes")
            merge_inputs["special_instructions"] = inputs.get("special_instructions")
        merge_inputs["generated_on"] = generation_metadata.get("generated_at")

    return next_context


def extract_generation_metadata(source_context: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(source_context, dict):
        generation = source_context.get("generation")
        if isinstance(generation, dict):
            return {
                "generation_mode": generation.get("mode") or GENERATION_MODE_TEMPLATE_PREFILL,
                "generation_requested_mode": generation.get("requested_mode") or GENERATION_MODE_TEMPLATE_PREFILL,
                "generation_status": generation.get("status") or GENERATION_STATUS_COMPLETED,
                "generation_operation": generation.get("operation") or GENERATION_OPERATION_CREATE,
                "generation_provider": generation.get("provider"),
                "generation_model": generation.get("model"),
                "generation_fallback_reason": generation.get("fallback_reason"),
                "last_generated_at": generation.get("generated_at"),
            }

        merge_inputs = source_context.get("merge_inputs")
        generated_on = merge_inputs.get("generated_on") if isinstance(merge_inputs, dict) else None
        return {
            "generation_mode": GENERATION_MODE_TEMPLATE_PREFILL,
            "generation_requested_mode": GENERATION_MODE_TEMPLATE_PREFILL,
            "generation_status": GENERATION_STATUS_COMPLETED,
            "generation_operation": GENERATION_OPERATION_CREATE,
            "generation_provider": None,
            "generation_model": None,
            "generation_fallback_reason": None,
            "last_generated_at": generated_on,
        }

    return {
        "generation_mode": GENERATION_MODE_TEMPLATE_PREFILL,
        "generation_requested_mode": GENERATION_MODE_TEMPLATE_PREFILL,
        "generation_status": GENERATION_STATUS_COMPLETED,
        "generation_operation": GENERATION_OPERATION_CREATE,
        "generation_provider": None,
        "generation_model": None,
        "generation_fallback_reason": None,
        "last_generated_at": None,
    }


def get_generation_inputs(source_context: dict[str, Any] | None) -> dict[str, str | None]:
    if isinstance(source_context, dict):
        generation = source_context.get("generation")
        if isinstance(generation, dict):
            inputs = generation.get("inputs")
            if isinstance(inputs, dict):
                return {
                    "purpose_notes": _strip_optional(inputs.get("purpose_notes")),
                    "special_instructions": _strip_optional(inputs.get("special_instructions")),
                }

        merge_inputs = source_context.get("merge_inputs")
        if isinstance(merge_inputs, dict):
            return {
                "purpose_notes": _strip_optional(merge_inputs.get("purpose_notes")),
                "special_instructions": _strip_optional(merge_inputs.get("special_instructions")),
            }

    return {
        "purpose_notes": None,
        "special_instructions": None,
    }


def _summarize_specs(specs: list[AssetSpec]) -> list[dict[str, Any]]:
    return [
        {
            "group": spec.parameter_grouping,
            "name": spec.parameter_name,
            "value": spec.parameter_value,
            "guidance": spec.guidelines,
        }
        for spec in specs
    ]


def _summarize_specs_for_prompt(specs: list[AssetSpec]) -> list[dict[str, Any]]:
    return [
        {
            "group": _truncate_for_prompt(spec.parameter_grouping, PROMPT_SPEC_TEXT_CHARS),
            "name": _truncate_for_prompt(spec.parameter_name, PROMPT_SPEC_TEXT_CHARS),
            "value": _truncate_for_prompt(spec.parameter_value, PROMPT_SPEC_TEXT_CHARS),
            "guidance": _truncate_for_prompt(spec.guidelines, PROMPT_SPEC_TEXT_CHARS),
        }
        for spec in specs[:PROMPT_MAX_SPECS]
    ]


def _compact_prompt_source_context(source_context: dict[str, Any]) -> dict[str, Any]:
    compact = copy.deepcopy(source_context)
    compact.pop("generation_history", None)
    compact.pop("generation", None)

    source_urs = compact.get("source_urs")
    if isinstance(source_urs, dict):
        source_urs["text"] = _truncate_for_prompt(source_urs.get("text"), PROMPT_SOURCE_TEXT_CHARS)

    release = compact.get("release")
    if isinstance(release, dict):
        for field in ("system_config_report", "documentation_text"):
            if field in release:
                release[field] = _truncate_for_prompt(release.get(field), PROMPT_RELEASE_TEXT_CHARS)

    specs = compact.get("asset_specs")
    if isinstance(specs, list):
        compact["asset_specs"] = [
            {
                key: _truncate_for_prompt(value, PROMPT_SPEC_TEXT_CHARS)
                for key, value in spec.items()
                if key in {"parameter_grouping", "parameter_name", "parameter_value", "guidelines"}
            }
            for spec in specs[:PROMPT_MAX_SPECS]
            if isinstance(spec, dict)
        ]

    return compact


def _build_prompt_instructions(operation: str) -> str:
    operation_text = (
        "Improve the existing draft while preserving supported facts and the overall URS intent."
        if operation == GENERATION_OPERATION_IMPROVE
        else "Generate a fresh first-draft URS grounded in the provided context."
    )
    return (
        "You are drafting an enterprise User Requirements Specification (URS) for a compliance-managed system.\n"
        f"{operation_text}\n"
        "Return plain Markdown only.\n"
        "Use only the supplied business context. Do not invent external facts, regulations, integrations, or system capabilities.\n"
        "If context is missing, use neutral wording such as 'To be confirmed during detailed design' or 'Not yet specified'.\n"
        "Keep the content professional, reviewable, and editable by humans.\n"
        "Structure the draft with clear URS-style sections covering: document title, purpose, scope, system or asset overview, "
        "business context, user requirements, technical or functional expectations written in user-readable language, "
        "compliance or traceability considerations, and assumptions or constraints.\n"
        "If an attached or pasted source URS is supplied, treat it as primary requirement evidence and transform it into a clean reviewable baseline without losing traceable requirements.\n"
        "When listing requirements, keep them specific to the provided context and avoid unsupported precision.\n"
        "Preserve the supplied title and keep the draft grounded in the deterministic baseline and template."
    )


def _build_prompt_input(
    *,
    title: str,
    template: DocumentTemplate,
    asset: Asset,
    release: AssetRelease | None,
    specs: list[AssetSpec],
    deterministic_content: str,
    source_context: dict[str, Any],
    purpose_notes: str | None,
    special_instructions: str | None,
    additional_notes: str | None,
    existing_content: str | None,
    operation: str,
) -> str:
    release_context = {
        "release_id": str(release.release_id) if release is not None else None,
        "version": release.version if release is not None else None,
        "documentation_mode": release.documentation_mode if release is not None else None,
        "system_config_report": _truncate_for_prompt(
            release.system_config_report if release is not None else None,
            PROMPT_RELEASE_TEXT_CHARS,
        ),
        "documentation_text": _truncate_for_prompt(
            release.documentation_text if release is not None else None,
            PROMPT_RELEASE_TEXT_CHARS,
        ),
    }

    prompt_payload = {
        "document_title": title,
        "document_type": template.document_type,
        "operation": operation,
        "template": {
            "template_code": template.template_code,
            "template_name": template.template_name,
            "template_content": _truncate_for_prompt(template.template_content, PROMPT_TEMPLATE_CONTENT_CHARS),
        },
        "asset": {
            "asset_uuid": str(asset.asset_uuid),
            "asset_code": asset.asset_id,
            "asset_name": asset.asset_name,
            "asset_description": asset.asset_description,
            "short_description": asset.short_description,
            "asset_owner": asset.asset_owner,
            "manufacturer": asset.manufacturer,
            "model": asset.model,
            "asset_version": asset.asset_version,
            "asset_tags": asset.tags,
        },
        "release": release_context,
        "asset_specs": _summarize_specs_for_prompt(specs),
        "user_notes": {
            "purpose_notes": _truncate_for_prompt(_strip_optional(purpose_notes), 1200),
            "special_instructions": _truncate_for_prompt(_strip_optional(special_instructions), 1200),
        },
        "structured_source_context": _compact_prompt_source_context(source_context),
        "deterministic_baseline_draft": _truncate_for_prompt(deterministic_content, PROMPT_BASELINE_DRAFT_CHARS),
        "existing_draft_content": _truncate_for_prompt(_strip_optional(existing_content), PROMPT_EXISTING_CONTENT_CHARS),
    }

    serialized = json.dumps(prompt_payload, ensure_ascii=True, indent=2)
    max_prompt_chars = max(4000, get_settings().URS_GENERATION_MAX_PROMPT_CHARS)
    if len(serialized) <= max_prompt_chars:
        return serialized

    prompt_payload["structured_source_context"] = {
        "target": prompt_payload["structured_source_context"].get("target"),
        "asset": prompt_payload["structured_source_context"].get("asset"),
        "release": prompt_payload["structured_source_context"].get("release"),
        "source_urs_present": bool(
            isinstance(prompt_payload["structured_source_context"].get("source_urs"), dict)
            and prompt_payload["structured_source_context"]["source_urs"].get("text_present")
        ),
    }
    prompt_payload["template"]["template_content"] = _truncate_for_prompt(
        prompt_payload["template"]["template_content"],
        1200,
    )
    prompt_payload["deterministic_baseline_draft"] = _truncate_for_prompt(
        prompt_payload["deterministic_baseline_draft"],
        2500,
    )
    prompt_payload["existing_draft_content"] = _truncate_for_prompt(
        prompt_payload["existing_draft_content"],
        1800,
    )
    prompt_payload["asset_specs"] = prompt_payload["asset_specs"][:10]
    serialized = json.dumps(prompt_payload, ensure_ascii=True, indent=2)
    if len(serialized) <= max_prompt_chars:
        return serialized

    minimal_payload = {
        "document_title": title,
        "document_type": template.document_type,
        "operation": operation,
        "template": {
            "template_code": template.template_code,
            "template_name": template.template_name,
        },
        "asset": prompt_payload["asset"],
        "release": release_context,
        "asset_specs": prompt_payload["asset_specs"][:5],
        "user_notes": prompt_payload["user_notes"],
        "deterministic_baseline_draft": _truncate_for_prompt(deterministic_content, 1800),
        "existing_draft_content": _truncate_for_prompt(_strip_optional(existing_content), 1200),
        "prompt_note": "Some context was omitted to stay within the configured AI prompt size.",
    }
    return json.dumps(minimal_payload, ensure_ascii=True, indent=2)


def _extract_chat_completion_output_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    chunks: list[str] = []
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                chunks.append(content.strip())
                continue
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text_value = part.get("text")
                    if isinstance(text_value, str) and text_value.strip():
                        chunks.append(text_value.strip())

    if chunks:
        return "\n\n".join(chunks).strip()

    output = payload.get("output")
    if not isinstance(output, list):
        return ""

    for item in output:
        if not isinstance(item, dict):
            continue
        contents = item.get("content")
        if not isinstance(contents, list):
            continue
        for content in contents:
            if not isinstance(content, dict):
                continue
            text_value = content.get("text")
            if isinstance(text_value, str) and text_value.strip():
                chunks.append(text_value.strip())
                continue
            if isinstance(text_value, dict):
                nested_value = text_value.get("value")
                if isinstance(nested_value, str) and nested_value.strip():
                    chunks.append(nested_value.strip())

    return "\n\n".join(chunks).strip()


def _build_llm_headers(api_key: str, request_id: str) -> dict[str, str]:
    settings = get_settings()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Client-Request-Id": request_id,
    }
    if settings.LLM_ORGANIZATION_ID:
        headers["OpenAI-Organization"] = settings.LLM_ORGANIZATION_ID
    if settings.LLM_PROJECT_ID:
        headers["OpenAI-Project"] = settings.LLM_PROJECT_ID
    return headers


def _build_ai_unavailable_message(reason: str) -> str:
    return f"AI-assisted URS generation is currently unavailable: {reason}"


def _infer_provider_name() -> str:
    settings = get_settings()
    configured_provider = _strip_optional(settings.LLM_PROVIDER)
    if configured_provider and configured_provider.lower() not in {"openai-compatible", "default"}:
        return configured_provider.lower()

    hostname = urlparse(settings.LLM_BASE_URL).netloc.lower()
    if "groq" in hostname:
        return "groq"
    if "openai" in hostname:
        return "openai"
    return "openai-compatible"


async def _generate_with_openai_compatible(
    *,
    instructions: str,
    prompt_input: str,
) -> tuple[str, str, str]:
    settings = get_settings()
    api_key = _strip_optional(settings.LLM_API_KEY)
    model = _strip_optional(settings.LLM_MODEL)
    if api_key is None:
        raise UrsGenerationUnavailableError(_build_ai_unavailable_message("LLM_API_KEY is not configured"))
    if model is None:
        raise UrsGenerationUnavailableError(_build_ai_unavailable_message("LLM_MODEL is not configured"))

    request_id = str(uuid.uuid4())
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": prompt_input},
        ],
        "max_tokens": max(256, settings.LLM_MAX_OUTPUT_TOKENS),
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
                raise UrsGenerationError("AI provider returned an unexpected response payload")

            content = _extract_chat_completion_output_text(response_payload)
            if not content:
                raise UrsGenerationError("AI provider returned empty content")

            return content, model, request_id
        except httpx.TimeoutException as exc:
            if attempt >= max_attempts:
                raise UrsGenerationUnavailableError(_build_ai_unavailable_message("the AI provider timed out")) from exc
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                error_payload = exc.response.json()
                if isinstance(error_payload, dict):
                    error = error_payload.get("error")
                    if isinstance(error, dict):
                        detail = str(error.get("message") or "").strip()
            except ValueError:
                detail = ""

            if exc.response.status_code in {401, 403}:
                message = "provider authentication failed"
                if detail:
                    message = f"{message}: {detail}"
                raise UrsGenerationUnavailableError(_build_ai_unavailable_message(message)) from exc

            if exc.response.status_code == 429:
                message = "provider rate limits were reached"
                retryable = True
            else:
                message = f"provider request failed with status {exc.response.status_code}"
                retryable = exc.response.status_code >= 500

            if detail:
                message = f"{message}: {detail}"
            if not retryable or attempt >= max_attempts:
                raise UrsGenerationUnavailableError(_build_ai_unavailable_message(message)) from exc
        except httpx.HTTPError as exc:
            if attempt >= max_attempts:
                raise UrsGenerationUnavailableError(_build_ai_unavailable_message("provider communication failed")) from exc

        await asyncio.sleep(min(1.5 * attempt, 3.0))

    raise UrsGenerationUnavailableError(_build_ai_unavailable_message("provider communication failed"))


async def generate_ai_urs_draft(
    *,
    title: str,
    template: DocumentTemplate,
    asset: Asset,
    release: AssetRelease | None,
    specs: list[AssetSpec],
    deterministic_content: str,
    source_context: dict[str, Any],
    purpose_notes: str | None,
    special_instructions: str | None,
    additional_notes: str | None,
    operation: str,
    existing_content: str | None = None,
) -> AiGeneratedDraft:
    settings = get_settings()
    if not settings.LLM_ENABLED:
        raise UrsGenerationUnavailableError(_build_ai_unavailable_message("LLM_ENABLED is false"))

    provider_name = _infer_provider_name()
    instructions = _build_prompt_instructions(operation)
    prompt_input = _build_prompt_input(
        title=title,
        template=template,
        asset=asset,
        release=release,
        specs=specs,
        deterministic_content=deterministic_content,
        source_context=source_context,
        purpose_notes=purpose_notes,
        special_instructions=special_instructions,
        additional_notes=additional_notes,
        existing_content=existing_content,
        operation=operation,
    )

    content, model, _request_id = await _generate_with_openai_compatible(
        instructions=instructions,
        prompt_input=prompt_input,
    )
    generation_metadata = build_generation_metadata(
        requested_mode=GENERATION_MODE_AI_ASSISTED,
        actual_mode=GENERATION_MODE_AI_ASSISTED,
        status=GENERATION_STATUS_COMPLETED,
        operation=operation,
        purpose_notes=purpose_notes,
        special_instructions=special_instructions,
        additional_notes=additional_notes,
        provider=provider_name,
        model=model,
        used_existing_content=bool(_strip_optional(existing_content)),
        prompt_version=URS_GENERATION_PROMPT_VERSION,
    )
    return AiGeneratedDraft(
        content=content,
        generation_metadata=generation_metadata,
    )
