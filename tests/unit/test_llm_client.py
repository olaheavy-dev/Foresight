"""ModelClient behaviour with a stubbed transport; no network, no real OpenAI client."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIConnectionError

from backend.llm.client import (
    ModelCallError,
    ModelClient,
    ModelConfigError,
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
            raise APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1"))
        return SimpleNamespace(
            id="resp_1",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, total_tokens=12),
        )


def _client(completions: StubCompletions, **overrides: str) -> ModelClient:
    settings = Settings(
        model_provider="openai",
        openai_api_key="sk_test",
        # The wire name drops the prefix: the stub sees "fast-primary".
        model_fast=overrides.get("fast", "openai/fast-primary"),
        model_fast_fallback=overrides.get("fast_fallback", "openai/fast-backup"),
        model_reasoning=overrides.get("reasoning", "openai/reason-primary"),
    )
    stub = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return ModelClient(settings=settings, client=stub, sleep=lambda _: None)  # type: ignore[arg-type]


def _ask(client: ModelClient, content: str = "hello") -> Any:
    return client.complete(tier=ModelTier.FAST, messages=[{"role": "user", "content": content}])


def test_missing_key_is_a_config_error() -> None:
    with pytest.raises(ModelConfigError):
        ModelClient(settings=Settings(model_provider="openai", openai_api_key=""))


def test_missing_model_is_a_config_error() -> None:
    client = _client(StubCompletions(), fast="")
    with pytest.raises(ModelConfigError):
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
    with pytest.raises(ModelCallError):
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


def test_transport_layer_never_turns_json_numbers_into_words() -> None:
    """Regression: layer 2 ran over raw JSON and produced `{"a": ACCOUNT}` (flaky analyst test)."""
    import json

    from backend.llm.client import redact_messages

    payload = {
        "ts": 1760000000000,
        "count": 12345678,
        "ratio": 0.012345678,
        "note": "card 4000 1234 5678 9011 and account 12345678",
    }
    out = redact_messages([{"role": "user", "content": json.dumps(payload)}])
    data = json.loads(out[0]["content"])
    assert data["ts"] == 1760000000000
    assert data["count"] == 12345678
    assert data["ratio"] == 0.012345678
    assert "4111" not in data["note"]
    assert "12345678" not in data["note"]


def test_transport_layer_keeps_clean_json_byte_for_byte() -> None:
    import json

    from backend.llm.client import redact_messages

    text = json.dumps({"findings": [{"id": "fnd_x", "recent_minor": 12977, "z": 2.5}]})
    assert redact_messages([{"role": "user", "content": text}])[0]["content"] == text


def test_masking_never_alters_foresight_reference_ids() -> None:
    """Regression: a calc id ending in eight digits was masked as ACCOUNT (flaky analyst test)."""
    import json

    from backend.llm.client import redact_messages

    calc = "calc_0a1b2c3d4e5f612345678"
    placeholder = "{{" + calc + "#recent_minor|money}}"
    payload = {"placeholders": {"a": placeholder}, "id": "fnd_01M4V6CCBJKVBGKE0TF75YXX68"}
    payload["note"] = "paid from account 12345678, card 4000 1234 5678 9011"
    data = json.loads(
        redact_messages([{"role": "user", "content": json.dumps(payload)}])[0]["content"]
    )
    assert data["placeholders"]["a"] == placeholder
    assert data["id"] == "fnd_01M4V6CCBJKVBGKE0TF75YXX68"
    assert "12345678" not in data["note"]
    assert "4111" not in data["note"]
