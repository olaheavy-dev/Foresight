"""The only gateway to language models.

Every model call in Foresight goes through this module to Mesh API
(https://api.meshapi.ai/v1). No other module may import an AI SDK; an import-linter
contract and tests/test_mesh_only.py enforce that (docs/05 §3.1).

What a call goes through (docs/05 §6.4, docs/06 §10.1):

1. Redaction of every message by `backend.mesh.redact` (locale-aware, deterministic).
2. Replay mode answers from a recorded cassette and never touches the network.
3. Otherwise the circuit breaker may refuse at once (`MeshUnavailableError`).
4. The tier's primary model: up to `mesh_max_retries` retries on transport errors, timeouts and 5xx
   (backoff 1 s, 4 s), honouring a 429 `Retry-After` up to 10 s; then one attempt on the tier's
   fallback model. A 402 (no Mesh balance) stops at once with `MeshSpendLimitError`.
5. Each request is shaped by the model's capabilities (`capabilities.py`): temperature is never
   sent to a model that rejects it, and a forced tool choice only where it is accepted.
6. Structured output: the model's preferred mode (`json_schema` or forced tool-call arguments),
   then the other, then JSON mode, moving on only when the provider rejects the request shape
   (400); output validated with Pydantic, with one repair retry carrying the validation errors.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

import backend.mesh.redact as redaction
from backend.mesh.breaker import CircuitBreaker
from backend.mesh.capabilities import capabilities_for
from backend.mesh.cassettes import CassetteMiss, CassetteStore, RecordedResponse, request_hash
from backend.mesh.prices import cost_estimate
from backend.settings import Settings, get_settings

# Fixed, not configurable: the hackathon requires every model call to go through Mesh, so no
# environment variable or setting can point the client anywhere else.
MESH_BASE_URL = "https://api.meshapi.ai/v1"

__all__ = [
    "MESH_BASE_URL",
    "CassetteMiss",
    "MeshCallError",
    "MeshClient",
    "MeshConfigError",
    "MeshResult",
    "MeshSchemaError",
    "MeshSpendLimitError",
    "MeshUnavailableError",
    "ModelTier",
    "StructuredResult",
    "Usage",
    "redact_messages",
]


class ModelTier(str, Enum):
    FAST = "fast"  # Coordinator Understand and block plan, Ledger Agent, digest headline
    REASONING = "reasoning"  # Behaviour Analyst, Advisor
    VERIFIER = "verifier"  # Verifier judge: a different provider from the Advisor (docs/06 §13)


class MeshConfigError(RuntimeError):
    """Raised when Mesh is not configured (missing key or model ID)."""


class MeshCallError(RuntimeError):
    """Raised when both the primary and fallback models fail."""


class MeshSpendLimitError(MeshCallError):
    """Mesh refused for lack of balance (402 / spend_limit_exceeded). Callers degrade."""


class MeshUnavailableError(MeshCallError):
    """The circuit breaker is open: Mesh is failing, so no call was attempted."""


class MeshSchemaError(MeshCallError):
    """The model's output failed validation twice (initial attempt + one repair).

    `calls` holds every Mesh call made before giving up, so budgets and cost still count them.
    """

    def __init__(self, message: str, calls: tuple[MeshResult, ...] = ()) -> None:
        super().__init__(message)
        self.calls = calls


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
    attempts: int = 1
    replayed: bool = False
    request_hash: str = ""
    cost_estimate: float | None = None
    tier: str = ""
    # The temperature actually sent, or None when the model rejects it ("model default").
    temperature: float | None = None
    strategy: str | None = None  # json_schema | tools | json_object for structured calls


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    value: T
    result: MeshResult  # the call that produced `value` (after any repair)
    strategy: str  # json_schema | tools | json_object
    repaired: bool
    calls: tuple[MeshResult, ...]  # every Mesh call made, for budgets and AgentStep accounting


# Second, transport-level layer (docs/05 §7.3: "a missed field at one layer is caught by the
# other"). Plain identifier shapes only; it runs after `backend.mesh.redact` on the final text.
_TRANSPORT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "CARD"),
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "IBAN"),
    (
        re.compile(r"(?<![\w+])(?:\+44\s?(?:\(0\)\s?)?|0)\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}(?!\d)"),
        "PHONE",
    ),
    (re.compile(r"(?<![\w+])(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"), "PHONE"),
    (re.compile(r"(?<![\d-])\d{2}-\d{2}-\d{2}(?![\d-])"), "SORT_CODE"),
    (re.compile(r"\b\d{4} ?\d{4}\b"), "ACCOUNT"),
    (re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b"), "ID"),
    (re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), "EMAIL"),
)


def _transport_redact(text: str) -> str:
    for pattern, replacement in _TRANSPORT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_messages(
    messages: list[dict[str, str]], *, locale_pack: str = "uk"
) -> list[dict[str, str]]:
    """Mask identifiers in every message before it can leave the app (docs/05 §7.3, §7.4a L2).

    Layer 1 is `backend.mesh.redact`: locale-aware (uk, in), deterministic; it masks cards, IBANs,
    sort codes, account numbers, references, phones, e-mail, UPI IDs, Indian identifiers and person
    names in transfer narrations. Layer 2 re-checks the final text for plain identifier shapes.
    """
    payload = redaction.redact({"messages": messages}, locale_pack=locale_pack)
    return [{**m, "content": _transport_redact(str(m["content"]))} for m in payload["messages"]]


_RETRY_BACKOFF_SECONDS = (1.0, 4.0)
_MAX_RETRY_AFTER_SECONDS = 10.0


class _UnsupportedRequest(Exception):
    """A 400 from the provider: this request shape (usually the output strategy) isn't accepted."""


@dataclass(frozen=True)
class _Structured:
    name: str
    schema: dict[str, Any]
    strategy: str  # json_schema | tools | json_object


def _error_code(exc: APIStatusError) -> str:
    """Mesh errors look like {"error": {"code": "invalid_request" | "spend_limit_exceeded"}}."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        inner = body.get("error", body)
        if isinstance(inner, dict):
            return str(inner.get("code") or "")
    return ""


def _status(exc: APIStatusError) -> int:
    return int(getattr(exc, "status_code", 0) or 0)


def _retry_after(exc: RateLimitError) -> float:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    try:
        return min(float(headers.get("retry-after", 1.0)), _MAX_RETRY_AFTER_SECONDS)
    except (TypeError, ValueError):
        return 1.0


def _normalise(response: Any) -> RecordedResponse:
    message = response.choices[0].message
    tool_calls = getattr(message, "tool_calls", None) or []
    tool_arguments = tool_calls[0].function.arguments if tool_calls else None
    usage = getattr(response, "usage", None)
    return RecordedResponse(
        mesh_response_id=str(response.id),
        model=str(response.model),
        content=message.content,
        tool_arguments=tool_arguments,
        prompt_tokens=int(usage.prompt_tokens) if usage else 0,
        completion_tokens=int(usage.completion_tokens) if usage else 0,
    )


def _request_kwargs(
    model: str,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    structured: _Structured | None,
    response_format: dict[str, Any] | None,
) -> tuple[dict[str, Any], float | None, str | None]:
    """Shape one request for `model`: (kwargs, temperature sent or None, strategy used)."""
    caps = capabilities_for(model)
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    sent_temperature: float | None = None
    if caps.supports_temperature:
        kwargs["temperature"] = temperature
        sent_temperature = temperature
    strategy: str | None = None
    if structured is not None:
        strategy = structured.strategy
        # A model whose json_schema output can't be parsed uses tool calls instead.
        if strategy == "json_schema" and caps.structured_mode == "tools":
            strategy = "tools"
        if strategy == "json_schema":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": structured.name,
                    "schema": structured.schema,
                    "strict": False,
                },
            }
        elif strategy == "tools":
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {"name": structured.name, "parameters": structured.schema},
                }
            ]
            if caps.supports_forced_tool_choice:
                kwargs["tool_choice"] = {"type": "function", "function": {"name": structured.name}}
            else:
                kwargs["tool_choice"] = "auto"
                kwargs["messages"] = [
                    *messages,
                    {
                        "role": "system",
                        "content": f"Answer only by calling the `{structured.name}` tool.",
                    },
                ]
        else:
            kwargs["response_format"] = {"type": "json_object"}
            kwargs["messages"] = [
                *messages,
                {
                    "role": "system",
                    "content": "Reply with one JSON object matching this JSON Schema: "
                    + json.dumps(structured.schema, sort_keys=True),
                },
            ]
    elif response_format is not None:
        kwargs["response_format"] = response_format
    return kwargs, sent_temperature, strategy


class MeshClient:
    def __init__(
        self,
        settings: Settings | None = None,
        client: OpenAI | None = None,
        *,
        cassettes: CassetteStore | None = None,
        breaker: CircuitBreaker | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings or get_settings()
        self._mode = self._settings.mesh_cassette_mode
        if self._mode not in {"live", "record", "replay"}:
            raise MeshConfigError(f"unknown MESH_CASSETTE_MODE '{self._mode}'")
        if client is None and self._mode != "replay":
            if not self._settings.mesh_api_key:
                raise MeshConfigError("MESH_API_KEY is not set")
            client = OpenAI(
                api_key=self._settings.mesh_api_key,
                base_url=MESH_BASE_URL,
                timeout=self._settings.mesh_timeout_reasoning_seconds,
                max_retries=0,  # retries are ours: counted, logged and visible to the breaker
            )
        self._client = client
        self._cassettes = cassettes or (
            CassetteStore(self._settings.mesh_cassette_dir, live_run_sha=self._settings.build_sha)
            if self._mode != "live"
            else None
        )
        self.breaker = breaker or CircuitBreaker()
        self._sleep = sleep

    # ------------------------------------------------------------------ configuration

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def base_url(self) -> str:
        if self._client is None:
            return MESH_BASE_URL
        return str(self._client.base_url).rstrip("/")

    def models_for(self, tier: ModelTier) -> tuple[str, str]:
        s = self._settings
        primary, fallback = {
            ModelTier.FAST: (s.mesh_model_fast, s.mesh_model_fast_fallback),
            ModelTier.REASONING: (s.mesh_model_reasoning, s.mesh_model_reasoning_fallback),
            ModelTier.VERIFIER: (s.mesh_model_verifier, s.mesh_model_verifier_fallback),
        }[tier]
        if not primary:
            raise MeshConfigError(f"No Mesh model configured for tier '{tier.value}'")
        return primary, fallback

    def _timeout(self, tier: ModelTier) -> float:
        if tier is ModelTier.FAST:
            return self._settings.mesh_timeout_fast_seconds
        return self._settings.mesh_timeout_reasoning_seconds

    # ------------------------------------------------------------------ public API

    def complete(
        self,
        *,
        tier: ModelTier,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
        locale_pack: str = "uk",
    ) -> MeshResult:
        """Run one chat completion, falling back to the tier's fallback model on failure."""
        _, result = self._call(
            tier=tier,
            messages=redact_messages(messages, locale_pack=locale_pack),
            structured=None,
            response_format=response_format,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return result

    def structured(
        self,
        *,
        tier: ModelTier,
        messages: list[dict[str, str]],
        output: type[T],
        name: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        locale_pack: str = "uk",
    ) -> StructuredResult[T]:
        """A typed answer: `output` validated by Pydantic, with one repair retry (docs/06 §10.1).

        Raises `MeshSchemaError` if the output is still invalid after the repair, so the caller
        can degrade (docs/06 §10.1).
        """
        schema = output.model_json_schema()
        safe = redact_messages(messages, locale_pack=locale_pack)
        primary, _ = self.models_for(tier)
        preferred = capabilities_for(primary).structured_mode
        order = [preferred, *(s for s in ("json_schema", "tools") if s != preferred), "json_object"]
        last_unsupported: Exception | None = None
        for strategy in order:
            try:
                return self._structured_with(
                    _Structured(name=name, schema=schema, strategy=strategy),
                    tier,
                    safe,
                    output,
                    max_tokens,
                    temperature,
                )
            except _UnsupportedRequest as exc:
                last_unsupported = exc
                continue
        raise MeshCallError(
            f"no structured-output strategy was accepted for tier '{tier.value}'"
        ) from last_unsupported

    def check(self) -> bool:
        """Metadata call that spends no credits: confirms the key and base URL work."""
        if self._client is None:
            raise MeshConfigError("replay mode has no live client")
        self._client.models.list()
        return True

    # ------------------------------------------------------------------ internals

    def _structured_with(
        self,
        structured: _Structured,
        tier: ModelTier,
        messages: list[dict[str, str]],
        output: type[T],
        max_tokens: int,
        temperature: float,
    ) -> StructuredResult[T]:
        calls: list[MeshResult] = []
        convo = list(messages)
        for repair in (False, True):
            recorded, result = self._call(
                tier=tier,
                messages=convo,
                structured=structured,
                response_format=None,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            calls.append(result)
            raw = recorded.tool_arguments or recorded.content or ""
            try:
                value = output.model_validate_json(raw)
            except ValidationError as exc:
                if repair:
                    raise MeshSchemaError(
                        f"{structured.name}: output invalid after one repair "
                        f"({exc.error_count()} error(s))",
                        calls=tuple(calls),
                    ) from exc
                errors = json.dumps(exc.errors(include_url=False, include_input=False))[:2000]
                convo = [
                    *convo,
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": f"That output failed validation: {errors} "
                        "Return only the corrected JSON.",
                    },
                ]
                continue
            return StructuredResult(
                value=value,
                result=result,
                strategy=result.strategy or structured.strategy,
                repaired=repair,
                calls=tuple(calls),
            )
        raise AssertionError("unreachable")  # pragma: no cover

    def _call(
        self,
        *,
        tier: ModelTier,
        messages: list[dict[str, str]],
        structured: _Structured | None,
        response_format: dict[str, Any] | None,
        max_tokens: int,
        temperature: float,
    ) -> tuple[RecordedResponse, MeshResult]:
        primary, fallback = self.models_for(tier)
        # The cassette key is the request as asked for (primary model, requested shape), so a
        # replay answers exactly what the live run answered, whichever model served it.
        request: dict[str, Any] = {
            "tier": tier.value,
            "model": primary,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if structured is not None:
            request.update(
                schema_name=structured.name, schema=structured.schema, strategy=structured.strategy
            )
        if response_format is not None:
            request["response_format"] = response_format
        key = request_hash(request)
        started = time.monotonic()

        if self._mode == "replay":
            assert self._cassettes is not None
            recorded = self._cassettes.load(request)
            _, sent_temperature, strategy = _request_kwargs(
                primary,
                messages,
                temperature=temperature,
                structured=structured,
                response_format=response_format,
            )
            return recorded, self._result(
                recorded, tier, started, False, 1, True, key, sent_temperature, strategy
            )

        if not self.breaker.allow():
            raise MeshUnavailableError("Mesh circuit breaker is open")

        assert self._client is not None
        attempts = 0
        last_error: Exception | None = None
        plan = [(primary, False, 1 + self._settings.mesh_max_retries)]
        if fallback:
            plan.append((fallback, True, 1))
        for model, is_fallback, tries in plan:
            kwargs, sent_temperature, strategy = _request_kwargs(
                model,
                messages,
                temperature=temperature,
                structured=structured,
                response_format=response_format,
            )
            for attempt in range(tries):
                attempts += 1
                try:
                    response = self._client.chat.completions.create(
                        **kwargs, max_tokens=max_tokens, timeout=self._timeout(tier)
                    )
                except BadRequestError as exc:
                    if _error_code(exc) == "spend_limit_exceeded":
                        raise MeshSpendLimitError("Mesh balance exhausted") from exc
                    # The request shape was rejected; not an outage, so the breaker isn't told.
                    raise _UnsupportedRequest(str(exc)) from exc
                except RateLimitError as exc:
                    last_error = exc
                    self.breaker.record(False)
                    if attempt + 1 < tries:
                        self._sleep(_retry_after(exc))
                    continue
                except APIStatusError as exc:
                    status = _status(exc)
                    if status == 402 or _error_code(exc) == "spend_limit_exceeded":
                        raise MeshSpendLimitError(
                            "Mesh balance exhausted (402 spend_limit_exceeded)"
                        ) from exc
                    if status in (401, 403):
                        raise MeshCallError(f"Mesh rejected the key ({status})") from exc
                    last_error = exc
                    self.breaker.record(False)
                    if attempt + 1 < tries:
                        self._sleep(_RETRY_BACKOFF_SECONDS[min(attempt, 1)])
                    continue
                except (APIConnectionError, APITimeoutError) as exc:
                    last_error = exc
                    self.breaker.record(False)
                    if attempt + 1 < tries:
                        self._sleep(_RETRY_BACKOFF_SECONDS[min(attempt, 1)])
                    continue
                self.breaker.record(True)
                recorded = _normalise(response)
                if self._mode == "record":
                    assert self._cassettes is not None
                    self._cassettes.save(request, recorded)
                return recorded, self._result(
                    recorded,
                    tier,
                    started,
                    is_fallback,
                    attempts,
                    False,
                    key,
                    sent_temperature,
                    strategy,
                )
            if not self.breaker.allow():
                break
        raise MeshCallError(f"Mesh call failed for tier '{tier.value}'") from last_error

    @staticmethod
    def _result(
        recorded: RecordedResponse,
        tier: ModelTier,
        started: float,
        used_fallback: bool,
        attempts: int,
        replayed: bool,
        key: str,
        sent_temperature: float | None,
        strategy: str | None,
    ) -> MeshResult:
        text = recorded.content if recorded.content is not None else recorded.tool_arguments
        return MeshResult(
            text=text or "",
            model=recorded.model,
            response_id=recorded.mesh_response_id,
            usage=Usage(
                prompt_tokens=recorded.prompt_tokens,
                completion_tokens=recorded.completion_tokens,
                total_tokens=recorded.prompt_tokens + recorded.completion_tokens,
            ),
            latency_ms=int((time.monotonic() - started) * 1000),
            used_fallback=used_fallback,
            attempts=attempts,
            replayed=replayed,
            request_hash=key,
            cost_estimate=cost_estimate(
                recorded.model, recorded.prompt_tokens, recorded.completion_tokens
            ),
            tier=tier.value,
            temperature=sent_temperature,
            strategy=strategy,
        )
