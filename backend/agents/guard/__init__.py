"""Prompt-injection defence and scope screening (docs/05 §4.2, §7.4a; docs/06 rule 6).

Deterministic and model-free. The rule pack (`rules.yaml`) is data; its sha256 is its version.
"""

from backend.agents.guard.canary import (
    canary_instruction,
    contains_canary,
    make_canary,
    prompt_canary,
)
from backend.agents.guard.output import Violation, numerals_outside_placeholders, output_screen
from backend.agents.guard.rules import RulePack, load_rule_pack, parse_rule_pack
from backend.agents.guard.screen import (
    WITHHELD,
    NormalisedInput,
    ScreenResult,
    detect_suspicious_text,
    normalise_input,
    prepare_for_model,
    quarantine,
    screen_input,
)

__all__ = [
    "WITHHELD",
    "NormalisedInput",
    "RulePack",
    "ScreenResult",
    "Violation",
    "canary_instruction",
    "contains_canary",
    "detect_suspicious_text",
    "load_rule_pack",
    "make_canary",
    "normalise_input",
    "numerals_outside_placeholders",
    "output_screen",
    "parse_rule_pack",
    "prepare_for_model",
    "prompt_canary",
    "quarantine",
    "screen_input",
]
