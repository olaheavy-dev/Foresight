"""Loads `models.yaml` (or the file named by MODELS_FILE): per-model capabilities and prices
are configuration, so trying another model needs no code change (docs/06 §13)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_FILE = Path(__file__).with_name("models.yaml")


@lru_cache
def load(path: str | None = None) -> dict[str, Any]:
    source = Path(path or os.environ.get("MODELS_FILE") or DEFAULT_FILE)
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    data.setdefault("defaults", {})
    data.setdefault("provider_defaults", {})
    data.setdefault("models", {})
    return data
