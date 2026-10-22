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


def test_mesh_base_url_cannot_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review finding: an environment variable must not be able to route calls elsewhere."""
    from backend.mesh.mesh_client import MESH_BASE_URL, MeshClient
    from backend.settings import Settings

    monkeypatch.setenv("MESH_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    client = MeshClient(settings=Settings(model_provider="mesh", mesh_api_key="rsk_test"))
    assert MESH_BASE_URL == "https://api.meshapi.ai/v1"
    assert client.base_url == MESH_BASE_URL
