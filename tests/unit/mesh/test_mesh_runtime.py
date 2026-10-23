"""MeshClient runtime: retries, 429, 402, breaker, model capabilities, structured output, repair,
cassettes, cost and redaction hook (docs/05 §6.4, docs/06 §10.1, docs/10 AGT-08/09).
No test touches the network."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from backend.mesh.breaker import BreakerState, CircuitBreaker
from backend.mesh.cassettes import CassetteStore
from backend.mesh.mesh_client import (
    CassetteMiss,
    MeshCallError,
    MeshClient,
    MeshSchemaError,
    MeshSpendLimitError,
    MeshUnavailableError,
    ModelTier,
)
from tests.unit.mesh.fakes import (
    ScriptedCompletions,
    bad_request,
    client,
    connection_error,
    fake_redact_module,
    json_ok,
    ok,
    rate_limited,
    settings,
    spend_limit,
)

MSG = [{"role": "user", "content": "categorise DEB TESCO STORES"}]


class Category(BaseModel):
    category: str
    confidence: float


def ask(c: MeshClient, tier: ModelTier = ModelTier.FAST) -> object:
    return c.complete(tier=tier, messages=MSG)


# ------------------------------------------------------------------------------ transport


def test_transport_errors_are_retried_twice_with_backoff() -> None:
    sleeps: list[float] = []
    calls = ScriptedCompletions(connection_error(), connection_error(), ok())
    result = client(calls, sleeps=sleeps).complete(tier=ModelTier.FAST, messages=MSG)
    assert result.attempts == 3
    assert result.used_fallback is False
    assert sleeps == [1.0, 4.0]


def test_fallback_model_after_primary_retries() -> None:
    calls = ScriptedCompletions(connection_error(), connection_error(), connection_error(), ok())
    result = client(calls).complete(tier=ModelTier.FAST, messages=MSG)
    assert [c["model"] for c in calls.calls] == ["gpt-6-luna"] * 3 + ["gpt-6-sol"]
    assert result.used_fallback is True
    assert result.attempts == 4


def test_retry_after_is_honoured_up_to_ten_seconds() -> None:
    sleeps: list[float] = []
    calls = ScriptedCompletions(rate_limited("30"), rate_limited("2"), ok())
    client(calls, sleeps=sleeps).complete(tier=ModelTier.FAST, messages=MSG)
    assert sleeps == [10.0, 2.0]


def test_no_balance_stops_at_once_without_fallback() -> None:
    calls = ScriptedCompletions(spend_limit())
    with pytest.raises(MeshSpendLimitError):
        client(calls).complete(tier=ModelTier.FAST, messages=MSG)
    assert len(calls.calls) == 1


def test_per_tier_timeouts_are_sent() -> None:
    calls = ScriptedCompletions(ok(), ok())
    c = client(calls)
    c.complete(tier=ModelTier.FAST, messages=MSG)
    c.complete(tier=ModelTier.REASONING, messages=MSG)
    assert [k["timeout"] for k in calls.calls] == [8.0, 25.0]


def test_cost_and_usage_are_accounted() -> None:
    calls = ScriptedCompletions(
        ok(model="openai/gpt-6-luna", prompt_tokens=1000, completion_tokens=200)
    )
    result = client(calls).complete(tier=ModelTier.FAST, messages=MSG)
    assert result.usage.total_tokens == 1200
    assert result.cost_estimate == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1_000_000)


# ------------------------------------------------------------------------------ circuit breaker


def test_breaker_opens_after_five_consecutive_failures_and_skips_calls() -> None:
    calls = ScriptedCompletions(default=connection_error())
    c = client(calls)
    with pytest.raises(MeshCallError):
        c.complete(tier=ModelTier.FAST, messages=MSG)  # 4 failures (3 primary + 1 fallback)
    with pytest.raises(MeshCallError):
        c.complete(tier=ModelTier.FAST, messages=MSG)  # 5th failure opens the breaker
    assert c.breaker.state is BreakerState.OPEN
    made = len(calls.calls)
    with pytest.raises(MeshUnavailableError):
        c.complete(tier=ModelTier.FAST, messages=MSG)
    assert len(calls.calls) == made  # no call attempted while open


def test_breaker_half_open_probe_closes_on_success() -> None:
    now = [0.0]
    breaker = CircuitBreaker(clock=lambda: now[0])
    for _ in range(5):
        breaker.record(False)
    assert breaker.state is BreakerState.OPEN
    assert not breaker.allow()
    now[0] = 61.0
    assert breaker.state is BreakerState.HALF_OPEN
    assert breaker.allow() is True
    assert breaker.allow() is False  # only one probe
    breaker.record(True)
    assert breaker.state is BreakerState.CLOSED
    assert breaker.openings == 1


def test_breaker_opens_on_failure_ratio_in_window() -> None:
    breaker = CircuitBreaker(clock=lambda: 0.0)
    for ok_ in (True, False, True, False, False):
        breaker.record(ok_)
    assert breaker.state is BreakerState.OPEN


# ------------------------------------------------------------------------------ capabilities


def test_gpt6_model_gets_json_schema_and_no_temperature() -> None:
    """OpenAI answers 400 to temperature 0.0 on the GPT-6 models (probed 21 Oct 2026)."""
    calls = ScriptedCompletions(json_ok({"category": "groceries", "confidence": 0.9}))
    out = client(calls).structured(
        tier=ModelTier.FAST, messages=MSG, output=Category, name="categorise"
    )
    sent = calls.calls[0]
    assert "temperature" not in sent
    assert sent["response_format"]["type"] == "json_schema"
    assert out.value.category == "groceries"
    assert out.strategy == "json_schema"
    assert out.result.temperature is None


def test_a_model_without_temperature_support_never_gets_it() -> None:
    calls = ScriptedCompletions(json_ok({"category": "groceries", "confidence": 0.9}))
    out = client(calls).structured(
        tier=ModelTier.REASONING, messages=MSG, output=Category, name="categorise"
    )
    assert "temperature" not in calls.calls[0]
    assert out.result.temperature is None  # recorded as "model default"


def test_a_rejected_json_schema_moves_on_to_forced_tool_calls() -> None:
    calls = ScriptedCompletions(
        bad_request(),  # json_schema rejected
        ok(None, tool_arguments='{"category": "groceries", "confidence": 0.8}'),
    )
    out = client(calls).structured(
        tier=ModelTier.REASONING, messages=MSG, output=Category, name="categorise"
    )
    tool_call = calls.calls[1]
    assert "response_format" not in tool_call
    assert tool_call["tool_choice"] == {"type": "function", "function": {"name": "categorise"}}
    assert "temperature" not in tool_call
    assert out.strategy == "tools"


# ------------------------------------------------------------------------------ repair


def test_one_repair_retry_with_validation_errors() -> None:
    calls = ScriptedCompletions(
        json_ok({"category": "groceries"}),  # missing confidence
        json_ok({"category": "groceries", "confidence": 0.9}),
    )
    out = client(calls).structured(
        tier=ModelTier.FAST, messages=MSG, output=Category, name="categorise"
    )
    assert out.repaired is True
    assert len(out.calls) == 2
    assert "failed validation" in calls.calls[1]["messages"][-1]["content"]


def test_invalid_twice_raises_schema_error() -> None:
    calls = ScriptedCompletions(ok("not json"), ok("still not json"))
    with pytest.raises(MeshSchemaError):
        client(calls).structured(
            tier=ModelTier.FAST, messages=MSG, output=Category, name="categorise"
        )


# ------------------------------------------------------------------------------ cassettes


def test_record_then_replay_without_key_or_network(tmp_path: Path) -> None:
    calls = ScriptedCompletions(json_ok({"category": "groceries", "confidence": 0.9}))
    recorder = client(
        calls,
        settings=settings(mesh_cassette_mode="record"),
        cassettes=CassetteStore(tmp_path, live_run_sha="abc1234"),
    )
    live = recorder.structured(tier=ModelTier.FAST, messages=MSG, output=Category, name="cat")
    assert len(list(tmp_path.glob("*.json"))) == 1

    player = MeshClient(
        settings=settings(mesh_cassette_mode="replay", mesh_api_key=""),
        cassettes=CassetteStore(tmp_path),
    )
    replayed = player.structured(tier=ModelTier.FAST, messages=MSG, output=Category, name="cat")
    assert replayed.value == live.value
    assert replayed.result.replayed is True
    assert replayed.result.response_id == live.result.response_id


def test_record_mode_takes_the_path_replay_takes(tmp_path: Path) -> None:
    """A request recorded under a later strategy (the first was rejected live) is answered from
    that recording in record mode too, exactly as replay answers it; nothing goes live."""
    import json as _json

    first = ScriptedCompletions(
        bad_request(),  # json_schema rejected live
        ok(None, tool_arguments=_json.dumps({"category": "groceries", "confidence": 0.9})),
    )
    rec1 = client(first, settings=settings(mesh_cassette_mode="record"),
                  cassettes=CassetteStore(tmp_path, live_run_sha="abc1234"))  # fmt: skip
    one = rec1.structured(tier=ModelTier.FAST, messages=MSG, output=Category, name="cat")
    assert one.strategy == "tools"

    # A later recording session where json_schema would now answer differently.
    second = ScriptedCompletions(json_ok({"category": "other", "confidence": 0.5}))
    rec2 = client(second, settings=settings(mesh_cassette_mode="record"),
                  cassettes=CassetteStore(tmp_path, live_run_sha="abc1234"))  # fmt: skip
    two = rec2.structured(tier=ModelTier.FAST, messages=MSG, output=Category, name="cat")
    assert two.value == one.value
    assert second.calls == []  # no live call

    player = MeshClient(settings=settings(mesh_cassette_mode="replay", mesh_api_key=""),
                        cassettes=CassetteStore(tmp_path))  # fmt: skip
    three = player.structured(tier=ModelTier.FAST, messages=MSG, output=Category, name="cat")
    assert three.value == one.value


def test_cassette_keeps_live_latency_and_replay_reports_it(tmp_path: Path) -> None:
    import json as _json

    recorder = client(
        ScriptedCompletions(ok()),
        settings=settings(mesh_cassette_mode="record"),
        cassettes=CassetteStore(tmp_path, live_run_sha="abc1234"),
    )
    live = recorder.complete(tier=ModelTier.FAST, messages=MSG)
    path = next(tmp_path.glob("*.json"))
    entry = _json.loads(path.read_text())
    assert entry["response"]["latency_ms"] == live.latency_ms
    assert entry["response"]["cost_estimate_usd"] == live.cost_estimate

    entry["response"]["latency_ms"] = 4321  # as if the live call had taken 4.3 s
    path.write_text(_json.dumps(entry))
    player = MeshClient(settings=settings(mesh_cassette_mode="replay", mesh_api_key=""),
                        cassettes=CassetteStore(tmp_path))  # fmt: skip
    replayed = ask(player)
    assert replayed.latency_ms == 4321  # type: ignore[attr-defined]
    assert replayed.latency_measured is True  # type: ignore[attr-defined]

    del entry["response"]["latency_ms"]  # recorded before latency was kept
    path.write_text(_json.dumps(entry))
    assert ask(player).latency_measured is False  # type: ignore[attr-defined]


def test_replay_of_changed_request_is_a_cassette_miss(tmp_path: Path) -> None:
    player = MeshClient(
        settings=settings(mesh_cassette_mode="replay", mesh_api_key=""),
        cassettes=CassetteStore(tmp_path),
    )
    with pytest.raises(CassetteMiss):
        player.complete(tier=ModelTier.FAST, messages=MSG)


# ------------------------------------------------------------------------------ redaction hook


def test_payload_redaction_runs_before_the_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = fake_redact_module(str.upper)
    monkeypatch.setattr("backend.mesh.redact.redact", fake.redact)
    calls = ScriptedCompletions(ok())
    client(calls).complete(tier=ModelTier.FAST, messages=MSG, locale_pack="in")
    assert calls.calls[0]["messages"][0]["content"] == "CATEGORISE DEB TESCO STORES|in"


def test_real_redaction_masks_identifiers_at_the_transport() -> None:
    calls = ScriptedCompletions(ok())
    sort_code = "-".join(["40", "11", "62"])
    msg = [{"role": "user", "content": f"FPO from {sort_code} acct 41234567 to a@b.com"}]
    client(calls).complete(tier=ModelTier.FAST, messages=msg)
    sent = calls.calls[0]["messages"][0]["content"]
    assert sort_code not in sent
    assert "41234567" not in sent
    assert "a@b.com" not in sent
