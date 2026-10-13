"""MeshClient behaviour with a stubbed transport; no network, no real OpenAI client."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIConnectionError

from backend.mesh.mesh_client import (
    MeshCallError,
    MeshClient,
    MeshConfigError,
    ModelTier,
)
from backend.settings import Settings


class StubCompletions:
    def __init__(self, fail_models: set[str] | None = None) -> None:
        self.fail_models = fail_models or set()
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if kwargs["model"] in self.fail_models:
            raise APIConnectionError(request=httpx.Request("POST", "https://api.meshapi.ai/v1"))
        return SimpleNamespace(
            id="resp_1",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        )


def _client(completions: StubCompletions, **overrides: str) -> MeshClient:
    settings = Settings(
        mesh_api_key="rsk_test",
        mesh_model_fast=overrides.get("fast", "fast-primary"),
        mesh_model_fast_fallback=overrides.get("fast_fallback", "fast-backup"),
        mesh_model_reasoning=overrides.get("reasoning", "reason-primary"),
    )
    stub = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return MeshClient(settings=settings, client=stub, sleep=lambda _: None)  # type: ignore[arg-type]


def _ask(client: MeshClient, content: str = "hello") -> Any:
    return client.complete(tier=ModelTier.FAST, messages=[{"role": "user", "content": content}])


def test_missing_key_is_a_config_error() -> None:
    with pytest.raises(MeshConfigError):
        MeshClient(settings=Settings(mesh_api_key=""))


def test_missing_model_is_a_config_error() -> None:
    client = _client(StubCompletions(), fast="")
    with pytest.raises(MeshConfigError):
        _ask(client)


def test_returns_text_model_and_usage() -> None:
    result = _ask(_client(StubCompletions()))
    assert result.text == "ok"
    assert result.model == "fast-primary"
    assert result.usage.total_tokens == 12
    assert result.used_fallback is False


def test_falls_back_when_primary_fails() -> None:
    completions = StubCompletions(fail_models={"fast-primary"})
    result = _ask(_client(completions))
    assert result.model == "fast-backup"
    assert result.used_fallback is True
    # The primary is retried twice (docs/06 §10.1) before one attempt on the fallback.
    assert [c["model"] for c in completions.calls] == ["fast-primary"] * 3 + ["fast-backup"]


def test_raises_when_all_models_fail() -> None:
    completions = StubCompletions(fail_models={"fast-primary", "fast-backup"})
    with pytest.raises(MeshCallError):
        _ask(_client(completions))


def test_outgoing_messages_are_redacted() -> None:
    completions = StubCompletions()
    sort_code = "-".join(["40", "11", "62"])
    _ask(_client(completions), content=f"paid from {sort_code} account 41234567")
    sent = completions.calls[0]["messages"][0]["content"]
    assert sort_code not in sent
    assert "41234567" not in sent


def test_phone_and_grouped_account_never_reach_the_transport() -> None:
    """Review finding, checked at the transport boundary rather than in redact() alone."""
    completions = StubCompletions()
    _ask(_client(completions), content="ring 07700 900123, account 4123 4567, thanks")
    sent = completions.calls[0]["messages"][0]["content"]
    assert "07700 900123" not in sent
    assert "4123 4567" not in sent
    assert "thanks" in sent
