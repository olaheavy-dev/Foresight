"""The only gateway to language models.

Every model call in Foresight goes through this module to OpenAI (https://api.openai.com/v1;
owner decision 20 Oct 2026, docs/00 §12 item 14). No other module may import an AI SDK; an
import-linter contract and tests/unit/test_mesh_only.py enforce that (docs/05 §3.1). The module
keeps its old name, `mesh`, from the gateway it first called.

What a call goes through (docs/05 §6.4, docs/06 §10.1):

1. Redaction of every message by `backend.mesh.redact` (locale-aware, deterministic).
2. Replay mode answers from a recorded cassette and never touches the network.
3. Otherwise the circuit breaker may refuse at once (`MeshUnavailableError`).
4. The tier's primary model: up to `mesh_max_retries` retries on transport errors, timeouts and 5xx
   (backoff 1 s, 4 s), honouring a 429 `Retry-After` up to 10 s; then one attempt on the tier's
   fallback model. A 429 `insufficient_quota` (no credit) stops at once with
   `MeshSpendLimitError`.
5. Each request is shaped by the model's capabilities (`capabilities.py`): temperature is never
   sent to a model that rejects it, and a forced tool choice only where it is accepted.
6. Structured output: the model's preferred mode (`json_schema` or forced tool-call arguments),
   then the other, then JSON mode, moving on only when the provider rejects the request shape
   (400); output validated with Pydantic, with one repair retry carrying the validation errors.
"""

from __future__ import annotations

import dataclasses
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
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
from backend.mesh.availability import AiAvailability
from backend.mesh.breaker import BreakerState, CircuitBreaker
from backend.mesh.capabilities import capabilities_for
from backend.mesh.cassettes import CassetteMiss, CassetteStore, RecordedResponse, request_hash
from backend.mesh.prices import cost_estimate
from backend.mesh.spend_guard import DailySpendGuard
from backend.settings import Settings, get_settings

# Fixed, not configurable: no environment variable or setting can point the client at any other
# address. `model_provider` must name one of these (only OpenAI since Mesh was removed).
OPENAI_BASE_URL = "https://api.openai.com/v1"
PROVIDER_BASE_URLS = {"openai": OPENAI_BASE_URL}

__all__ = [
    "OPENAI_BASE_URL",
    "PROVIDER_BASE_URLS",
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
    VERIFIER = "verifier"  # Verifier judge: a different model from the Advisor (docs/06 §13)


class MeshConfigError(RuntimeError):
    """Raised when the model client is not configured (provider, key or model ID)."""


class MeshCallError(RuntimeError):
    """Raised when both the primary and fallback models fail."""


class MeshSpendLimitError(MeshCallError):
    """The provider refused for lack of credit (429 insufficient_quota). Callers degrade."""


class MeshUnavailableError(MeshCallError):
    """The circuit breaker is open (the provider is failing) or today's budget is used, so no
    call was attempted."""


class MeshSchemaError(MeshCallError):
    """The model's output failed validation twice (initial attempt + one repair).

    `calls` holds every model call made before giving up, so budgets and cost still count them.
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
    # False when a replayed call has no recorded live latency (latency_ms is then local time).
    latency_measured: bool = True
    # The route the call took, stored on each AgentStep: "openai", or "mesh" for a replayed
    # recording made through the old gateway.
    provider: str = "openai"


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


def _transport_redact_json(value: Any) -> Any:
    if isinstance(value, str):
        return _transport_redact(value)
    if isinstance(value, list):
        return [_transport_redact_json(v) for v in value]
    if isinstance(value, dict):
        return {k: _transport_redact_json(v) for k, v in value.items()}
    return value  # numbers, booleans, null: amounts and counts, never identifiers


def _transport_redact_content(text: str) -> str:
    """Layer 2 on one message. A JSON message is walked so only its string values are masked:
    running the patterns over raw JSON turned numbers into bare words (`{"a": 12345678}` →
    `{"a": ACCOUNT}`), which broke the JSON. Unchanged text is returned byte for byte."""
    if text.lstrip()[:1] in ("{", "["):
        try:
            data = json.loads(text)
        except ValueError:
            return _transport_redact(text)
        masked = _transport_redact_json(data)
        return text if masked == data else json.dumps(masked, ensure_ascii=False)
    return _transport_redact(text)


def redact_messages(
    messages: list[dict[str, str]], *, locale_pack: str = "uk"
) -> list[dict[str, str]]:
    """Mask identifiers in every message before it can leave the app (docs/05 §7.3, §7.4a L2).

    Layer 1 is `backend.mesh.redact`: locale-aware (uk, in), deterministic; it masks cards, IBANs,
    sort codes, account numbers, references, phones, e-mail, UPI IDs, Indian identifiers and person
    names in transfer narrations. Layer 2 re-checks the final text for plain identifier shapes.
    """
    protected: list[dict[str, str]] = []
    stash: dict[str, str] = {}
    for m in messages:
        protected.append({**m, "content": _protect_refs(str(m["content"]), stash)})
    payload = redaction.redact({"messages": protected}, locale_pack=locale_pack)
    return [
        {**m, "content": _restore_refs(_transport_redact_content(str(m["content"])), stash)}
        for m in payload["messages"]
    ]


# Foresight's own reference ids (`calc_<hex>#path|fmt`, `fnd_<ulid>`, …) are not personal data, but
# their random hex/ULID tails can look like account or card numbers to the masking patterns. They
# are swapped for letter-only tokens before masking and restored after (flaky-test investigation,
# 13 Oct 2026: a calc id ending in eight digits was masked as ACCOUNT, breaking the placeholder).
_REF_PATTERN = re.compile(
    r"\b(?:calc|fnd|fc|sim|scn|rec|ver|rsp|txn|run|step|wsp|imp|acct|acc|goal|aud|thr|msg|fmt|lay)"
    r"_[0-9A-Za-z]{6,}(?:#[\w.\[\]-]+)?(?:\|[\w%.-]+)?"
)


def _token(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return f"QQREF{letters}QQ"


def _protect_refs(text: str, stash: dict[str, str]) -> str:
    def swap(match: re.Match[str]) -> str:
        token = _token(len(stash))
        stash[token] = match.group(0)
        return token

    return _REF_PATTERN.sub(swap, text)


def _restore_refs(text: str, stash: dict[str, str]) -> str:
    for token, original in stash.items():
        text = text.replace(token, original)
    return text


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
    """Provider errors look like {"error": {"code": "insufficient_quota" | ...}}."""
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
        spend_guard: DailySpendGuard | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._mode = self._settings.mesh_cassette_mode
        self._local = threading.local()  # per-thread replay pass in record mode
        if self._mode not in {"live", "record", "replay"}:
            raise MeshConfigError(f"unknown MESH_CASSETTE_MODE '{self._mode}'")
        self._provider = self._settings.model_provider
        if self._provider not in PROVIDER_BASE_URLS:
            raise MeshConfigError(f"unknown MODEL_PROVIDER '{self._provider}'")
        if client is None and self._mode != "replay":
            if not self._settings.openai_api_key:
                raise MeshConfigError("OPENAI_API_KEY is not set")
            client = OpenAI(
                api_key=self._settings.openai_api_key,
                base_url=PROVIDER_BASE_URLS[self._provider],
                timeout=self._settings.mesh_timeout_reasoning_seconds,
                max_retries=0,  # retries are ours: counted, logged and visible to the breaker
            )
        self._client = client
        if self._mode != "replay":
            # Fail at start-up, not on the first Advisor call, when a tier can't be served.
            s = self._settings
            for primary in (s.mesh_model_fast, s.mesh_model_reasoning, s.mesh_model_verifier):
                if primary and not self._serves(primary):
                    raise MeshConfigError(
                        f"MODEL_PROVIDER '{self._provider}' can't serve '{primary}'"
                    )

            # The judge is a different model from the Advisor (docs/06 §13), fallbacks included;
            # a fallback the provider skips (models_for) is never called, so it doesn't count.
            def served(*models: str) -> set[str]:
                return {m for m in models if m and self._serves(m)}

            advisor = served(s.mesh_model_reasoning, s.mesh_model_reasoning_fallback)
            judge = served(s.mesh_model_verifier, s.mesh_model_verifier_fallback)
            if advisor & judge:
                raise MeshConfigError(
                    f"the Verifier judge can't use the Advisor's model: {sorted(advisor & judge)}"
                )
        self._cassettes = cassettes or (
            CassetteStore(
                self._settings.mesh_cassette_dir,
                live_run_sha=self._settings.build_sha,
                provider=self._provider,
            )
            if self._mode != "live"
            else None
        )
        self.breaker = breaker or CircuitBreaker()
        self._sleep = sleep
        # Live calls only: recordings for evals are capped by their own spend checks.
        self.spend_guard = spend_guard or (
            DailySpendGuard(self._spent_on, budget_usd=self._settings.mesh_daily_budget_usd)
            if self._mode == "live"
            else None
        )
        self.availability = AiAvailability(
            lambda: self.breaker.state is BreakerState.OPEN,
            budget_used=lambda: self.spend_guard is not None and self.spend_guard.exhausted(),
        )

    def _spent_on(self, day: date) -> float | None:
        """Model spend recorded for `day` (UTC) across every workspace; None without a database."""
        if not self._settings.database_url:
            return None
        from backend.storage.spend import spent_on

        return spent_on(self._settings.database_url, day)

    # ------------------------------------------------------------------ configuration

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def base_url(self) -> str:
        if self._client is None:
            return PROVIDER_BASE_URLS[self._provider]
        return str(self._client.base_url).rstrip("/")

    @staticmethod
    def _wire_model(model: str) -> str:
        """The model ID as OpenAI expects it: "gpt-6-luna", not "openai/gpt-6-luna". Settings,
        prices and cassette keys keep the prefixed ID."""
        return model.removeprefix("openai/")

    @staticmethod
    def _token_limit(max_tokens: int) -> dict[str, Any]:
        """OpenAI rejects `max_tokens` for the GPT-6 models (400 unsupported_parameter, probed
        21 Oct 2026) and takes `max_completion_tokens`."""
        return {"max_completion_tokens": max_tokens}

    @staticmethod
    def _serves(model: str) -> bool:
        return model.startswith("openai/")

    def models_for(self, tier: ModelTier) -> tuple[str, str]:
        s = self._settings
        primary, fallback = {
            ModelTier.FAST: (s.mesh_model_fast, s.mesh_model_fast_fallback),
            ModelTier.REASONING: (s.mesh_model_reasoning, s.mesh_model_reasoning_fallback),
            ModelTier.VERIFIER: (s.mesh_model_verifier, s.mesh_model_verifier_fallback),
        }[tier]
        if not primary:
            raise MeshConfigError(f"No model configured for tier '{tier.value}'")
        # Replay never reaches a provider, so recordings of other models still answer.
        if self._mode != "replay":
            if not self._serves(primary):
                raise MeshConfigError(
                    f"MODEL_PROVIDER '{self._provider}' can't serve '{primary}' "
                    f"(tier '{tier.value}')"
                )
            if fallback and not self._serves(fallback):
                fallback = ""
        return primary, fallback

    def _timeout(self, tier: ModelTier, *, fallback: bool = False) -> float:
        # The fast tier's fallback runs only after the primary failed, and may be a slower model
        # (GPT-6 Sol behind Luna): an answer matters more than speed, so it gets the long timeout.
        if tier is ModelTier.FAST and not fallback:
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
        if self._mode == "record":
            # Record mode takes the path replay will take: if this request is already recorded
            # under any strategy, use that answer (replay falls through to it); only a request
            # recorded under none goes live. Otherwise record and replay diverge.
            recorded = self._replay_pass(order, name, schema, tier, safe, output, max_tokens,
                                         temperature)  # fmt: skip
            if recorded is not None:
                return recorded
        last_unsupported: Exception | None = None
        first_miss: CassetteMiss | None = None
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
            except CassetteMiss as miss:
                # The live run fell back past this strategy (the model rejected it), so its
                # answer is recorded under a later one: replay follows the same order.
                if self._mode != "replay":
                    raise
                first_miss = first_miss or miss
                continue
        if first_miss is not None:
            raise first_miss
        raise MeshCallError(
            f"no structured-output strategy was accepted for tier '{tier.value}'"
        ) from last_unsupported

    def _replay_pass(
        self,
        order: list[str],
        name: str,
        schema: dict[str, Any],
        tier: ModelTier,
        safe: list[dict[str, str]],
        output: type[T],
        max_tokens: int,
        temperature: float,
    ) -> StructuredResult[T] | None:
        """The answer replay would give (first recorded strategy in order), or None."""
        self._local.replay_only = True
        try:
            for strategy in order:
                try:
                    return self._structured_with(
                        _Structured(name=name, schema=schema, strategy=strategy),
                        tier, safe, output, max_tokens, temperature,
                    )  # fmt: skip
                except (CassetteMiss, _UnsupportedRequest):
                    continue
            return None
        finally:
            self._local.replay_only = False

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

        if getattr(self._local, "replay_only", False):
            replayable = True  # record mode's replay pass (per thread): never call live here
        else:
            replayable = self._mode == "replay" or (
                self._mode == "record"
                and self._cassettes is not None
                and self._cassettes.has(request)
            )
        if replayable:
            # Record mode re-uses what is already recorded, so re-running a recording session
            # only pays for requests that are new or changed.
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
            raise MeshUnavailableError("the model circuit breaker is open")
        if self.spend_guard is not None and self.spend_guard.exhausted():
            raise MeshUnavailableError("today's model budget is used")

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
                        **{
                            **kwargs,
                            "model": self._wire_model(model),
                            **self._token_limit(max_tokens),
                        },
                        timeout=self._timeout(tier, fallback=is_fallback),
                    )
                except BadRequestError as exc:
                    # The request shape was rejected; not an outage, so the breaker isn't told.
                    raise _UnsupportedRequest(str(exc)) from exc
                except RateLimitError as exc:
                    if _error_code(exc) == "insufficient_quota":  # OpenAI's "no credit" is a 429
                        self.availability.note_spend_limit()
                        raise MeshSpendLimitError("provider balance exhausted") from exc
                    last_error = exc
                    self.breaker.record(False)
                    if attempt + 1 < tries:
                        self._sleep(_retry_after(exc))
                    continue
                except APIStatusError as exc:
                    status = _status(exc)
                    if status in (401, 403):
                        raise MeshCallError(f"the provider rejected the key ({status})") from exc
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
                answer = _normalise(response)
                recorded = dataclasses.replace(
                    answer,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    cost_estimate_usd=cost_estimate(
                        answer.model, answer.prompt_tokens, answer.completion_tokens
                    ),
                )
                if self.spend_guard is not None:
                    self.spend_guard.charge(recorded.cost_estimate_usd)
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

    def _result(
        self,
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
        # A replay reports the live call's recorded latency, never the time to read a file.
        latency_ms = int((time.monotonic() - started) * 1000)
        measured = not replayed or recorded.latency_ms is not None
        if replayed and recorded.latency_ms is not None:
            latency_ms = recorded.latency_ms
        return MeshResult(
            text=text or "",
            model=recorded.model,
            response_id=recorded.mesh_response_id,
            usage=Usage(
                prompt_tokens=recorded.prompt_tokens,
                completion_tokens=recorded.completion_tokens,
                total_tokens=recorded.prompt_tokens + recorded.completion_tokens,
            ),
            latency_ms=latency_ms,
            latency_measured=measured,
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
            # A replay keeps the route its latency and cost came from (Codex on #67).
            provider=(recorded.provider or self._provider) if replayed else self._provider,
        )
