"""One-gateway rule (docs/05 §3.1): no AI SDK is imported anywhere except backend/llm.

Complements the import-linter contract in pyproject.toml by also scanning tools/ and evals/.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = {
    "openai",
    "langchain_openai",
    "langchain_community",
    "litellm",
    "anthropic",
    "google.genai",
    "cohere",
    "transformers",
    "sentence_transformers",
    "tiktoken",
}
ALLOWED_DIR = ROOT / "backend" / "llm"
SCANNED = ("backend", "tools", "evals")


def _imported_modules(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _is_forbidden(module: str) -> bool:
    return any(module == f or module.startswith(f + ".") for f in FORBIDDEN)


def test_no_ai_sdk_outside_model_client() -> None:
    offenders = []
    for top in SCANNED:
        for path in (ROOT / top).rglob("*.py"):
            if ALLOWED_DIR in path.parents:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            bad = sorted(m for m in _imported_modules(tree) if _is_forbidden(m))
            if bad:
                offenders.append(f"{path.relative_to(ROOT)}: {', '.join(bad)}")
    assert offenders == []


def test_the_provider_address_cannot_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding: an environment variable must not be able to route calls elsewhere."""
    from backend.llm.client import OPENAI_BASE_URL, ModelClient
    from backend.settings import Settings

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    client = ModelClient(settings=Settings(model_provider="openai", openai_api_key="sk_test"))
    assert OPENAI_BASE_URL == "https://api.openai.com/v1"
    assert client.base_url == OPENAI_BASE_URL


def test_a_stale_model_client_provider_fails_at_start_up() -> None:
    """Mesh was removed on 23 Oct 2026: an env still naming it must not start quietly."""
    from backend.llm.client import ModelClient, ModelConfigError
    from backend.settings import Settings

    with pytest.raises(ModelConfigError, match="unknown MODEL_PROVIDER 'mesh'"):
        ModelClient(settings=Settings(model_provider="mesh", openai_api_key="sk_test"))


def test_a_refused_config_is_logged_once_and_ai_shows_as_paused(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The API still starts with a stale config, so the reason must reach the server log."""
    from backend.app.routers import ask
    from backend.settings import get_settings

    monkeypatch.setenv("MODEL_PROVIDER", "mesh")
    monkeypatch.setenv("MODEL_CASSETTE_MODE", "live")
    monkeypatch.setattr(ask, "_model_client", None)
    monkeypatch.setattr(ask, "_client_refused", False)
    get_settings.cache_clear()
    try:
        with caplog.at_level("WARNING", logger=ask.__name__):
            assert ask.get_model_client() is None
            assert ask.get_model_client() is None
        warnings = [r.getMessage() for r in caplog.records if r.name == ask.__name__]
        assert warnings == ["AI answers are off: unknown MODEL_PROVIDER 'mesh'"]
        assert ask.ai_status(None) == "unavailable"
    finally:
        get_settings.cache_clear()


def test_old_mesh_setting_names_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Renamed 23 Oct 2026: a stale MESH_MODEL_* override (e.g. the old Sonnet Advisor) left in a
    server env is not read, so the OpenAI defaults apply instead of turning AI answers off."""
    from backend.settings import Settings

    monkeypatch.setenv("MESH_MODEL_REASONING", "anthropic/claude-sonnet-5.5")
    monkeypatch.setenv("MESH_DAILY_BUDGET_USD", "9")
    s = Settings()
    assert s.model_reasoning == "openai/gpt-6-sol"
    assert s.model_daily_budget_usd == 0.50
