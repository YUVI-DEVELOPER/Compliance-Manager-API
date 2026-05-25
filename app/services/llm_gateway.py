from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.urs_generation_service import _build_llm_headers, _extract_chat_completion_output_text


class LLMGatewayUnavailableError(Exception):
    pass


class LLMGatewayError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Step2LLMResult:
    payload: dict[str, Any]
    raw_response: dict[str, Any]
    model_name: str
    provider: str


def _strip_optional(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _safe_error(value: Any) -> str:
    settings = get_settings()
    message = str(value or "LLM request failed.")
    api_key = _strip_optional(settings.STEP2_AI_API_KEY)
    if api_key:
        message = message.replace(api_key, "[redacted]")
    message = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", message, flags=re.IGNORECASE)
    return message[:1000]


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


class Step2LLMGateway:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def provider(self) -> str:
        return _strip_optional(self.settings.STEP2_AI_PROVIDER) or "openai_compatible"

    @property
    def model_name(self) -> str | None:
        return _strip_optional(self.settings.STEP2_AI_MODEL)

    def is_enabled(self) -> bool:
        return bool(self.settings.STEP2_AI_ASSISTANT_ENABLED)

    def is_configured(self) -> bool:
        return bool(
            self.is_enabled()
            and _strip_optional(self.settings.STEP2_AI_API_KEY)
            and self.model_name
            and _strip_optional(self.settings.STEP2_AI_BASE_URL)
        )

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> Step2LLMResult:
        if not self.is_enabled():
            raise LLMGatewayUnavailableError("Step 2 AI assistant is disabled by configuration.")
        if not self.is_configured():
            raise LLMGatewayUnavailableError("Step 2 AI assistant is not configured.")

        api_key = _strip_optional(self.settings.STEP2_AI_API_KEY)
        model = self.model_name
        base_url = _strip_optional(self.settings.STEP2_AI_BASE_URL)
        if api_key is None or model is None or base_url is None:
            raise LLMGatewayUnavailableError("Step 2 AI assistant is not configured.")

        request_id = str(uuid.uuid4())
        request_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=True, indent=2, default=str)},
            ],
            "temperature": self.settings.STEP2_AI_TEMPERATURE,
            "max_tokens": max(256, self.settings.STEP2_AI_MAX_TOKENS),
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.STEP2_AI_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers=_build_llm_headers(api_key, request_id),
                    json=request_payload,
                )
                response.raise_for_status()
            raw_response = response.json()
        except httpx.HTTPError as exc:
            raise LLMGatewayError(_safe_error(exc)) from exc

        if not isinstance(raw_response, dict):
            raise LLMGatewayError("AI provider returned an unexpected response payload.")

        content = _extract_chat_completion_output_text(raw_response)
        payload = _extract_json_payload(content)
        if payload is None:
            raise LLMGatewayError("AI provider did not return valid JSON.")

        return Step2LLMResult(
            payload=payload,
            raw_response=raw_response,
            model_name=model,
            provider=self.provider,
        )


def get_step2_llm_gateway() -> Step2LLMGateway:
    return Step2LLMGateway()
