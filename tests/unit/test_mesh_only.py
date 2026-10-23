"""Mesh-only rule (docs/05 §3.1): no AI SDK is imported anywhere except backend/mesh.

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
ALLOWED_DIR = ROOT / "backend" / "mesh"
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


def test_no_ai_sdk_outside_mesh() -> None:
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
    from backend.mesh.mesh_client import OPENAI_BASE_URL, MeshClient
    from backend.settings import Settings

    monkeypatch.setenv("MESH_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    client = MeshClient(settings=Settings(model_provider="openai", openai_api_key="sk_test"))
    assert OPENAI_BASE_URL == "https://api.openai.com/v1"
    assert client.base_url == OPENAI_BASE_URL


def test_a_stale_mesh_provider_fails_at_start_up() -> None:
    """Mesh was removed on 23 Oct 2026: an env still naming it must not start quietly."""
    from backend.mesh.mesh_client import MeshClient, MeshConfigError
    from backend.settings import Settings

    with pytest.raises(MeshConfigError, match="unknown MODEL_PROVIDER 'mesh'"):
        MeshClient(settings=Settings(model_provider="mesh", openai_api_key="sk_test"))


def test_a_refused_config_is_logged_once_and_ai_shows_as_paused(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The API still starts with a stale config, so the reason must reach the server log."""
    from backend.app.routers import ask
    from backend.settings import get_settings

    monkeypatch.setenv("MODEL_PROVIDER", "mesh")
    monkeypatch.setenv("MESH_CASSETTE_MODE", "live")
    monkeypatch.setattr(ask, "_mesh", None)
    monkeypatch.setattr(ask, "_mesh_refused", False)
    get_settings.cache_clear()
    try:
        with caplog.at_level("WARNING", logger=ask.__name__):
            assert ask.get_mesh() is None
            assert ask.get_mesh() is None
        warnings = [r.getMessage() for r in caplog.records if r.name == ask.__name__]
        assert warnings == ["AI answers are off: unknown MODEL_PROVIDER 'mesh'"]
        assert ask.ai_status(None) == "unavailable"
    finally:
        get_settings.cache_clear()
