"""What each configured model accepts, read from `models.yaml` (configuration).

The observations behind the file's values are noted in it: the OpenAI models accept json_schema
(strict) and a forced tool choice, and the GPT-6 models only their default temperature (probed
21 Oct 2026). Anthropic and Google models, used through Mesh until 23 Oct 2026, are not listed.

An unlisted model gets the conservative default: no temperature, no forced tool choice,
json_schema first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.llm import model_config

StructuredMode = Literal["json_schema", "tools"]


@dataclass(frozen=True)
class ModelCapabilities:
    supports_temperature: bool
    supports_forced_tool_choice: bool
    structured_mode: StructuredMode


def _caps(entry: dict[str, object]) -> ModelCapabilities:
    mode = str(entry.get("structured_mode", "json_schema"))
    return ModelCapabilities(
        supports_temperature=bool(entry.get("supports_temperature", False)),
        supports_forced_tool_choice=bool(entry.get("supports_forced_tool_choice", False)),
        structured_mode="tools" if mode == "tools" else "json_schema",
    )


def capabilities_for(model: str) -> ModelCapabilities:
    """From `models.yaml`: the model's own entry, else its provider's default, else the
    conservative default (no temperature, no forced tool choice, json_schema first)."""
    config = model_config.load()
    if model in config["models"]:
        return _caps(config["models"][model])
    provider = model.split("/", 1)[0] if "/" in model else ""
    if provider in config["provider_defaults"]:
        return _caps(config["provider_defaults"][provider])
    return _caps(config["defaults"])
