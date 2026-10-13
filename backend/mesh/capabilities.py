"""What each configured model accepts through Mesh (observed in live probes, 13 Oct 2026).

- Anthropic models (Bedrock upstream) reject `temperature` ("temperature is deprecated for this
  model") and a forced `tool_choice`; they accept `response_format` json_schema with temperature
  omitted, and tool_choice "auto". Their steps record the temperature as "model default".
- google/gemini-3.1-pro returned unparseable content for json_schema; its tool calls work, so it
  uses the tool-call path.
- openai/gpt-6-luna, openai/gpt-6.1-sol and google/gemini-3.8-flash accept both json_schema
  (strict) and a forced tool choice.

An unlisted model gets the conservative default: no temperature, no forced tool choice,
json_schema first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

StructuredMode = Literal["json_schema", "tools"]


@dataclass(frozen=True)
class ModelCapabilities:
    supports_temperature: bool
    supports_forced_tool_choice: bool
    structured_mode: StructuredMode


_OPENAI = ModelCapabilities(
    supports_temperature=True, supports_forced_tool_choice=True, structured_mode="json_schema"
)
_ANTHROPIC = ModelCapabilities(
    supports_temperature=False, supports_forced_tool_choice=False, structured_mode="json_schema"
)

MODEL_CAPABILITIES: dict[str, ModelCapabilities] = {
    "openai/gpt-6-luna": _OPENAI,
    "openai/gpt-6.1-sol": _OPENAI,
    "anthropic/claude-sonnet-5.5": _ANTHROPIC,
    "anthropic/claude-haiku-5.5": _ANTHROPIC,
    "google/gemini-3.1-pro": ModelCapabilities(
        supports_temperature=True, supports_forced_tool_choice=True, structured_mode="tools"
    ),
    "google/gemini-3.8-flash": _OPENAI,
    # Probed 13 Oct 2026 (advisor model trial): json_schema, forced tools and temperature work.
    "openai/gpt-5.6-luna-pro": _OPENAI,
}

DEFAULT_CAPABILITIES = ModelCapabilities(
    supports_temperature=False, supports_forced_tool_choice=False, structured_mode="json_schema"
)


def capabilities_for(model: str) -> ModelCapabilities:
    if model in MODEL_CAPABILITIES:
        return MODEL_CAPABILITIES[model]
    if model.startswith("anthropic/"):
        return _ANTHROPIC
    return DEFAULT_CAPABILITIES
