"""The exact answer cache key (docs/05 §4.2 stage 3). No embeddings: the Understand step has already
reduced paraphrases to the same intent and canonical slots, and every version that could change the
answer is part of the key, so a stale hit is impossible by construction."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache
def prompt_version(name: str) -> str:
    """Short hash of one prompt file, stored on every step that used it (docs/06 §11)."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


@lru_cache
def prompt_bundle_version() -> str:
    digest = hashlib.sha256()
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


# Slots that only label a question and never enter a calculation ("a £1,200 holiday" and
# "a £1,200 trip" run the same simulation). They stay out of the cache key so paraphrases meet;
# every slot that changes a number (amount, date, period, category, merchant, …) stays in it.
DESCRIPTIVE_SLOTS = frozenset({"purpose"})


def _canonical_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = " ".join(value.lower().split())
        return int(text) if text.lstrip("-").isdigit() else text
    if isinstance(value, list):
        return sorted((_canonical_value(v) for v in value), key=str)
    return value


def canonical_slots(slots: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in sorted(slots):
        if key.lower() in DESCRIPTIVE_SLOTS:
            continue
        out[key.lower()] = _canonical_value(slots[key])
    return out


def answer_cache_key(
    *,
    workspace_id: str,
    intent: str,
    slots: dict[str, Any],
    data_version: int,
    prefs_version: int,
    advice_state_version: str,
    engine_version: str,
    as_of: str,
    locale_pack: str,
    prompt_bundle: str,
) -> str:
    body = {
        "workspace_id": workspace_id,
        "intent": intent,
        "slots": canonical_slots(slots),
        "data_version": data_version,
        "prefs_version": prefs_version,
        "advice_state_version": advice_state_version,
        "engine_version": engine_version,
        "as_of": as_of,
        "locale_pack": locale_pack,
        "prompt_bundle_version": prompt_bundle,
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
