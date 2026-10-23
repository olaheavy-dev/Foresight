"""MODEL_PROVIDER=openai: same gateway, OpenAI directly (docs/11). No network."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APITimeoutError, RateLimitError

from backend.mesh.mesh_client import (
    OPENAI_BASE_URL,
    MeshClient,
    MeshConfigError,
    MeshSpendLimitError,
    ModelTier,
)
from backend.settings import Settings


class StubCompletions:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            id="chatcmpl_1",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=100, total_tokens=1100),
        )


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "model_provider": "openai",
        "openai_api_key": "sk_test",
        "mesh_model_fast": "openai/gpt-6-luna",
        "mesh_model_fast_fallback": "anthropic/claude-haiku-5.5",
        "mesh_model_reasoning": "openai/gpt-6-sol",
        "mesh_model_reasoning_fallback": "google/gemini-3.1-pro",
    }
    values.update(overrides)
    return Settings(**values)


def _client(completions: StubCompletions, **overrides: Any) -> MeshClient:
    stub = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return MeshClient(settings=_settings(**overrides), client=stub, sleep=lambda _: None)  # type: ignore[arg-type]


def _ask(client: MeshClient, tier: ModelTier = ModelTier.FAST) -> Any:
    return client.complete(tier=tier, messages=[{"role": "user", "content": "hello"}])


def test_openai_provider_uses_the_fixed_openai_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    client = MeshClient(settings=_settings())
    assert client.provider == "openai"
    assert client.base_url == OPENAI_BASE_URL


def test_openai_provider_needs_its_own_key() -> None:
    with pytest.raises(MeshConfigError, match="OPENAI_API_KEY"):
        MeshClient(settings=_settings(openai_api_key="", mesh_api_key="rsk_test"))


def test_unknown_provider_is_a_config_error() -> None:
    with pytest.raises(MeshConfigError, match="MODEL_PROVIDER"):
        MeshClient(settings=_settings(model_provider="elsewhere"))


def test_model_is_sent_without_its_prefix_and_priced() -> None:
    completions = StubCompletions()
    result = _ask(_client(completions))
    assert completions.calls[0]["model"] == "gpt-6-luna"
    assert result.text == "ok"
    assert result.cost_estimate is not None
    assert result.cost_estimate > 0


def test_the_token_limit_is_sent_as_max_completion_tokens() -> None:
    """OpenAI answers 400 unsupported_parameter to `max_tokens` on the GPT-6 models."""
    completions = StubCompletions()
    _ask(_client(completions))
    assert "max_tokens" not in completions.calls[0]
    assert completions.calls[0]["max_completion_tokens"] == 1024


def test_other_providers_fallbacks_are_skipped() -> None:
    """Haiku can't be reached on OpenAI, so a failing primary isn't followed by a doomed call."""
    client = _client(StubCompletions())
    assert client.models_for(ModelTier.FAST) == ("openai/gpt-6-luna", "")


def test_a_non_openai_primary_is_refused_at_start_up() -> None:
    """Codex on #67: the service mustn't look healthy and then fail every Advisor call."""
    with pytest.raises(MeshConfigError, match="claude-sonnet"):
        _client(StubCompletions(), mesh_model_reasoning="anthropic/claude-sonnet-5.5")


def test_new_recordings_say_which_provider_served_them(tmp_path: Any) -> None:
    import json

    from backend.mesh.cassettes import CassetteStore

    store = CassetteStore(tmp_path, provider="openai")
    stub = SimpleNamespace(chat=SimpleNamespace(completions=StubCompletions()))
    client = MeshClient(
        settings=_settings(mesh_cassette_mode="record", mesh_cassette_dir=str(tmp_path)),
        client=stub,  # type: ignore[arg-type]
        cassettes=store,
        sleep=lambda _: None,
    )
    _ask(client)
    (saved,) = tmp_path.glob("*.json")
    entry = json.loads(saved.read_text())
    assert entry["provider"] == "openai"
    assert "provider" not in entry["request"]  # the key is unchanged


def test_replay_still_answers_recordings_of_other_providers() -> None:
    """Recordings made through Mesh keep their keys (prefixed model IDs), so replay is unchanged."""
    client = MeshClient(
        settings=_settings(
            mesh_cassette_mode="replay", mesh_model_reasoning="anthropic/claude-sonnet-5.5"
        )
    )
    assert client.models_for(ModelTier.REASONING) == (
        "anthropic/claude-sonnet-5.5",
        "google/gemini-3.1-pro",
    )


def test_insufficient_quota_is_a_spend_limit_not_a_retry() -> None:
    response = httpx.Response(429, request=httpx.Request("POST", OPENAI_BASE_URL))
    error = RateLimitError(
        "quota",
        response=response,
        body={"error": {"code": "insufficient_quota", "message": "quota"}},
    )
    completions = StubCompletions(error=error)
    client = _client(completions)
    with pytest.raises(MeshSpendLimitError):
        _ask(client)
    assert len(completions.calls) == 1


def test_no_balance_lookup_on_openai() -> None:
    client = _client(StubCompletions())
    assert client._available_usd() is None


def test_results_carry_the_provider_for_agent_steps() -> None:
    """Codex on #67: activity and audit rows must not label OpenAI calls as Mesh."""
    assert _ask(_client(StubCompletions())).provider == "openai"


def test_the_advisor_can_never_fall_back_to_its_judge() -> None:
    """Codex on #67: in a degraded run the same model must not write and check advice."""
    s = Settings()
    advisor_models = {s.mesh_model_reasoning, s.mesh_model_reasoning_fallback} - {""}
    judge_models = {s.mesh_model_verifier, s.mesh_model_verifier_fallback} - {""}
    assert not advisor_models & judge_models


@pytest.mark.parametrize(
    "overrides",
    [
        {"mesh_model_reasoning": "openai/gpt-6.1-sol"},
        {"mesh_model_reasoning_fallback": "openai/gpt-6.1-sol"},
        {"mesh_model_verifier_fallback": "openai/gpt-6-sol"},
    ],
)
def test_a_configuration_where_the_advisor_judges_itself_is_refused(
    overrides: dict[str, str],
) -> None:
    """Codex on #67: an override must not make one model write and check advice."""
    with pytest.raises(MeshConfigError, match="judge"):
        _client(StubCompletions(), **overrides)


def test_a_replay_keeps_the_provider_that_recorded_it(tmp_path: Any) -> None:
    """Codex on #67: a recording replayed under another MODEL_PROVIDER keeps its own route."""
    from backend.mesh.cassettes import CassetteStore

    stub = SimpleNamespace(chat=SimpleNamespace(completions=StubCompletions()))
    recorder = MeshClient(
        settings=_settings(mesh_cassette_mode="record", mesh_cassette_dir=str(tmp_path)),
        client=stub,  # type: ignore[arg-type]
        cassettes=CassetteStore(tmp_path, provider="openai"),
        sleep=lambda _: None,
    )
    _ask(recorder)
    replayer = MeshClient(
        settings=_settings(
            model_provider="mesh", mesh_cassette_mode="replay", mesh_cassette_dir=str(tmp_path)
        )
    )
    replayed = _ask(replayer)
    assert replayed.replayed
    assert replayed.provider == "openai"


def test_recordings_from_before_the_field_replay_as_mesh(tmp_path: Any) -> None:
    import json

    from backend.mesh.cassettes import CassetteStore

    stub = SimpleNamespace(chat=SimpleNamespace(completions=StubCompletions()))
    recorder = MeshClient(
        settings=_settings(mesh_cassette_mode="record", mesh_cassette_dir=str(tmp_path)),
        client=stub,  # type: ignore[arg-type]
        cassettes=CassetteStore(tmp_path),
        sleep=lambda _: None,
    )
    _ask(recorder)
    (saved,) = tmp_path.glob("*.json")
    assert "provider" not in json.loads(saved.read_text())
    replayer = MeshClient(
        settings=_settings(mesh_cassette_mode="replay", mesh_cassette_dir=str(tmp_path))
    )
    assert _ask(replayer).provider == "mesh"


def test_a_migrated_mesh_config_with_skipped_shared_fallbacks_starts() -> None:
    """Codex on #67: Gemini fallbacks left on both tiers are skipped under openai, never called,
    so they don't make the Advisor its own judge."""
    client = _client(
        StubCompletions(),
        mesh_model_reasoning_fallback="google/gemini-3.1-pro",
        mesh_model_verifier_fallback="google/gemini-3.1-pro",
    )
    assert client.models_for(ModelTier.REASONING)[1] == ""
    assert client.models_for(ModelTier.VERIFIER)[1] == ""


def test_the_fast_fallback_gets_the_long_timeout() -> None:
    """GPT-6 Sol behind Luna often takes over 8 s; the fast timeout would doom the fallback."""

    class LunaTimesOut(StubCompletions):
        def create(self, **kwargs: Any) -> SimpleNamespace:
            if kwargs["model"] == "gpt-6-luna":
                self.calls.append(kwargs)
                raise APITimeoutError(request=httpx.Request("POST", OPENAI_BASE_URL))
            return super().create(**kwargs)

    completions = LunaTimesOut()
    client = _client(completions, mesh_model_fast_fallback="openai/gpt-6-sol", mesh_max_retries=0)
    assert _ask(client).text == "ok"
    s = client._settings
    assert [(c["model"], c["timeout"]) for c in completions.calls] == [
        ("gpt-6-luna", s.mesh_timeout_fast_seconds),
        ("gpt-6-sol", s.mesh_timeout_reasoning_seconds),
    ]
