"""Model choice and capability flags are configuration (docs/06 §13): another models file changes
what a model accepts and costs with no code change."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.llm import model_config
from backend.llm.capabilities import capabilities_for
from backend.llm.prices import cost_estimate


def test_the_shipped_file_covers_every_configured_tier_model() -> None:
    from backend.settings import Settings

    s = Settings()
    configured = {
        s.model_fast, s.model_fast_fallback, s.model_reasoning,
        s.model_reasoning_fallback, s.model_verifier, s.model_verifier_fallback,
    }  # fmt: skip
    configured.discard("")  # an empty fallback means none (the judge has none since 20 Oct 2026)
    models = model_config.load()["models"]
    assert configured <= set(models)
    assert all("price_in" in models[m] and "price_out" in models[m] for m in configured)


def test_another_file_switches_a_model_with_no_code_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "models.yaml"
    file.write_text(
        "defaults: {supports_temperature: false, supports_forced_tool_choice: false,"
        " structured_mode: json_schema}\n"
        "models:\n"
        "  acme/cheap-1: {supports_temperature: true, supports_forced_tool_choice: false,"
        " structured_mode: tools, price_in: 0.05, price_out: 0.25}\n"
    )
    monkeypatch.setenv("MODELS_FILE", str(file))
    model_config.load.cache_clear()
    try:
        caps = capabilities_for("acme/cheap-1")
        assert (caps.supports_temperature, caps.structured_mode) == (True, "tools")
        assert cost_estimate("acme/cheap-1", 1_000_000, 0) == pytest.approx(0.05)
        assert cost_estimate("openai/gpt-6-luna", 1000, 0) is None  # not in this file: no guess
    finally:
        monkeypatch.delenv("MODELS_FILE")
        model_config.load.cache_clear()
