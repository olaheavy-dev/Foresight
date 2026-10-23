"""A scripted stand-in for the OpenAI client's chat completions: no network, ever."""

from __future__ import annotations

import json
from collections.abc import Callable
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, BadRequestError, RateLimitError

from backend.mesh.mesh_client import MeshClient
from backend.settings import Settings

URL = "https://api.meshapi.ai/v1/chat/completions"

Step = Any  # a response namespace, an exception, or a callable(kwargs) -> either


def ok(
    content: str | None = "ok",
    *,
    model: str = "served-model",
    tool_arguments: str | None = None,
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
) -> SimpleNamespace:
    tool_calls = (
        [SimpleNamespace(function=SimpleNamespace(name="t", arguments=tool_arguments))]
        if tool_arguments is not None
        else None
    )
    return SimpleNamespace(
        id="resp_test",
        model=model,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def json_ok(value: dict[str, Any], **kw: Any) -> SimpleNamespace:
    return ok(json.dumps(value), **kw)


def connection_error() -> APIConnectionError:
    return APIConnectionError(request=httpx.Request("POST", URL))


def status_error(
    cls: type[APIStatusError],
    status: int,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> APIStatusError:
    response = httpx.Response(
        status, request=httpx.Request("POST", URL), headers=headers or {}, json=body or {}
    )
    return cls("mesh error", response=response, body=body)


def service_unavailable() -> APIStatusError:
    """A transient Mesh 503 (retried with backoff, docs/06 §10.1)."""
    return status_error(APIStatusError, 503)


def spend_limit() -> APIStatusError:
    body = {"error": {"code": "spend_limit_exceeded", "message": "Insufficient balance."}}
    return status_error(APIStatusError, 402, body)


def rate_limited(retry_after: str) -> APIStatusError:
    return status_error(RateLimitError, 429, {}, {"retry-after": retry_after})


def bad_request(code: str = "invalid_request") -> APIStatusError:
    return status_error(BadRequestError, 400, {"error": {"code": code, "message": "nope"}})


class ScriptedCompletions:
    def __init__(self, *steps: Step, default: Step | None = None) -> None:
        self.steps = list(steps)
        self.default = default
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        step = self.steps.pop(0) if self.steps else self.default
        if step is None:
            raise AssertionError("unexpected extra Mesh call")
        if callable(step) and not isinstance(step, SimpleNamespace):
            step = step(kwargs)
        if isinstance(step, BaseException):
            raise step
        return step


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "model_provider": "mesh",  # not the developer's .env: these fixtures name Mesh models
        "mesh_api_key": "rsk_test",
        "mesh_model_fast": "openai/gpt-6-luna",
        "mesh_model_fast_fallback": "anthropic/claude-haiku-5.5",
        "mesh_model_reasoning": "anthropic/claude-sonnet-5.5",
        "mesh_model_reasoning_fallback": "google/gemini-3.1-pro",
        "mesh_model_verifier": "openai/gpt-6.1-sol",
        "mesh_model_verifier_fallback": "",  # never the Advisor's model (docs/06 §13)
        "mesh_daily_budget_usd": 0.0,  # the daily guard has its own tests (test_spend_guard.py)
    }
    base.update(overrides)
    return Settings(**base)


def client(
    completions: ScriptedCompletions | None,
    *,
    sleeps: list[float] | None = None,
    **kwargs: Any,
) -> MeshClient:
    record: Callable[[float], None] = sleeps.append if sleeps is not None else lambda _: None
    stub = (
        SimpleNamespace(chat=SimpleNamespace(completions=completions), base_url=URL)
        if completions is not None
        else None
    )
    return MeshClient(
        settings=kwargs.pop("settings", None) or settings(),
        client=stub,  # type: ignore[arg-type]
        sleep=record,
        **kwargs,
    )


def fake_redact_module(transform: Callable[[str], str]) -> ModuleType:
    module = ModuleType("backend.mesh.redact")

    def redact(payload: dict[str, Any], *, locale_pack: str) -> dict[str, Any]:
        return {
            "messages": [
                {**m, "content": transform(m["content"]) + f"|{locale_pack}"}
                for m in payload["messages"]
            ]
        }

    module.redact = redact  # type: ignore[attr-defined]
    return module
