"""A model client for the LLM eval suites (docs/09 §13, §16).

`EVAL_LLM_MODE` chooses the mode: `replay` (default; recorded cassettes under evals/cassettes, no
key, no network), `record` (live calls to the provider, every exchange saved) or `live`. A suite
that meets a request with no cassette reports its LLM arms as "not measured", never a guess.
"""

from __future__ import annotations

import os
from pathlib import Path

from backend.llm.cassettes import CassetteMiss
from backend.llm.client import ModelClient, ModelConfigError
from backend.settings import get_settings

CASSETTES = Path(__file__).resolve().parent / "cassettes"
MODES = ("replay", "record", "live")


def eval_mode() -> str:
    mode = os.environ.get("EVAL_LLM_MODE", "replay")
    if mode not in MODES:
        raise ValueError(f"EVAL_LLM_MODE must be one of {MODES}, not {mode!r}")
    return mode


def eval_model_client() -> ModelClient | None:
    """The suite's model client, or None when no model can be reached in this mode."""
    mode = eval_mode()
    # Prompts carry the eval canary in record/replay (backend.agents.prompting reads settings).
    os.environ["MODEL_CASSETTE_MODE"] = mode
    os.environ["MODEL_CASSETTE_DIR"] = str(CASSETTES)
    get_settings.cache_clear()
    try:
        return ModelClient(settings=get_settings())
    except ModelConfigError:
        return None


NOT_RECORDED = (CassetteMiss,)

__all__ = ["CASSETTES", "NOT_RECORDED", "eval_model_client", "eval_mode"]
