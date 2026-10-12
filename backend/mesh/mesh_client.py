"""The only gateway to language models.

Every model call in Foresight goes through this module to Mesh API
(https://api.meshapi.ai/v1). No other module may import an AI SDK; an import-linter
contract and tests/test_mesh_only.py enforce that (docs/05 §3.1).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from backend.settings import Settings, get_settings

# Fixed, not configurable: the hackathon requires every model call to go through Mesh, so no
# environment variable or setting can point the client anywhere else.
MESH_BASE_URL = "https://api.meshapi.ai/v1"


class ModelTier(str, Enum):
    FAST = "fast"  # Coordinator, Ledger Agent
    REASONING = "reasoning"  # Advisor, Verifier


class MeshConfigError(RuntimeError):
    """Raised when Mesh is not configured (missing key or model ID)."""


class MeshCallError(RuntimeError):
    """Raised when both the primary and fallback models fail."""


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class MeshResult:
    text: str
    model: str
    response_id: str
    usage: Usage
    latency_ms: int
    used_fallback: bool


# Patterns removed before any text leaves the app (docs/07 §8). Order matters: longer
# numbers first so a card number is not partly matched as an account number.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD]"),
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "[IBAN]"),
    (re.compile(r"(?<![\d-])\d{2}-\d{2}-\d{2}(?![\d-])"), "[SORT_CODE]"),
    (re.compile(r"\b\d{8}\b"), "[ACCOUNT]"),
    (re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b"), "[NI_NUMBER]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), "[EMAIL]"),
    (re.compile(r"\b[\w.-]{2,}@[a-z]{2,}\b", re.IGNORECASE), "[UPI_ID]"),
)


def redact(text: str) -> str:
    """Mask account identifiers, card numbers and contact details before a model sees text."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class MeshClient:
    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None) -> None:
        self._settings = settings or get_settings()
        if client is None:
            if not self._settings.mesh_api_key:
                raise MeshConfigError("MESH_API_KEY is not set")
            client = OpenAI(
                api_key=self._settings.mesh_api_key,
                base_url=MESH_BASE_URL,
                timeout=self._settings.mesh_timeout_seconds,
                max_retries=self._settings.mesh_max_retries,
            )
        self._client = client

    @property
    def base_url(self) -> str:
        return str(self._client.base_url).rstrip("/")

    def _models_for(self, tier: ModelTier) -> tuple[str, str]:
        if tier is ModelTier.FAST:
            primary, fallback = (
                self._settings.mesh_model_fast,
                self._settings.mesh_model_fast_fallback,
            )
        else:
            primary, fallback = (
                self._settings.mesh_model_reasoning,
                self._settings.mesh_model_reasoning_fallback,
            )
        if not primary:
            raise MeshConfigError(f"No Mesh model configured for tier '{tier.value}'")
        return primary, fallback

    def complete(
        self,
        *,
        tier: ModelTier,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
    ) -> MeshResult:
        """Run one chat completion, falling back to the tier's fallback model on failure."""
        primary, fallback = self._models_for(tier)
        safe_messages = [{**m, "content": redact(m["content"])} for m in messages]
        attempts = [(primary, False)] + ([(fallback, True)] if fallback else [])
        last_error: Exception | None = None
        for model, is_fallback in attempts:
            started = time.monotonic()
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": safe_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
                if response_format is not None:
                    kwargs["response_format"] = response_format
                response = self._client.chat.completions.create(**kwargs)
            except (APIConnectionError, APITimeoutError, RateLimitError, APIStatusError) as exc:
                last_error = exc
                continue
            usage = response.usage
            return MeshResult(
                text=response.choices[0].message.content or "",
                model=response.model,
                response_id=response.id,
                usage=Usage(
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
                ),
                latency_ms=int((time.monotonic() - started) * 1000),
                used_fallback=is_fallback,
            )
        raise MeshCallError(f"Mesh call failed for tier '{tier.value}'") from last_error

    def check(self) -> bool:
        """Metadata call that spends no credits: confirms the key and base URL work."""
        self._client.models.list()
        return True
