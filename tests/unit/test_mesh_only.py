"""Mesh-only rule (docs/05 §3.1): no AI SDK is imported anywhere except backend/mesh.

Complements the import-linter contract in pyproject.toml by also scanning tools/ and evals/.
"""

from __future__ import annotations

import ast
from pathlib import Path

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


def test_mesh_client_targets_mesh_base_url() -> None:
    from backend.mesh.mesh_client import MESH_BASE_URL
    from backend.settings import Settings

    assert MESH_BASE_URL == "https://api.meshapi.ai/v1"
    assert Settings().mesh_base_url == MESH_BASE_URL
