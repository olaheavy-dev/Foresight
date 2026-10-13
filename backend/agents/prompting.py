"""System prompts with the prompt canary (docs/05 §7.4a L4).

Every system prompt ends with the canary line, so an output that repeats it is a proven leak and is
dropped. Live runs use the deployment's own canary (from `SESSION_SECRET`). Recorded and replayed
runs use a fixed one, so cassettes match across processes; it is not secret there, and the real
canary never reaches a cassette because live mode records nothing.
"""

from __future__ import annotations

from backend.agents.cache import PROMPTS_DIR
from backend.agents.guard import canary_instruction, make_canary, prompt_canary
from backend.settings import get_settings

EVAL_CANARY_SECRET = "foresight-cassettes"  # noqa: S105 - not a secret: see the module docstring


# Set by the eval harness, whose Mesh client records or replays even when the process settings
# say live: its prompts must carry the fixed canary too.
force_eval_canary = False


def active_canary() -> str:
    if force_eval_canary or get_settings().mesh_cassette_mode in {"record", "replay"}:
        return make_canary(EVAL_CANARY_SECRET)
    return prompt_canary()


def system_prompt(name: str) -> str:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").rstrip()
    return f"{text}\n\n{canary_instruction(active_canary())}\n"
