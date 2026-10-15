"""The /api/simulate adapter accepts every field the engine's ScenarioModifier has (review R6)."""

from __future__ import annotations

import dataclasses

from backend.app.routers.engine import _MODIFIER_FIELDS, ALIASES, _modifier
from backend.finance_core.types import ScenarioModifier


def test_the_api_accepts_exactly_the_engines_modifier_fields() -> None:
    engine = {f.name for f in dataclasses.fields(ScenarioModifier)}
    assert _MODIFIER_FIELDS == engine, "the API adapter and the engine's modifier have drifted"


def test_ids_from_the_api_become_engine_keys() -> None:
    ids = {"inc_X": "income:acme", "rob_Y": "rent:monthly"}
    raised = _modifier({"type": "income_change_pct", "income_stream_key": "inc_X", "pct": 10}, ids)
    assert raised.income_stream_key == "income:acme"
    assert raised.pct == 10
    cut = _modifier(
        {"type": "recurring_cancel", "recurring_id": "rob_Y", "from_date": "2026-11-01"}, ids
    )
    assert cut.recurring_id == "rent:monthly"
    assert str(cut.from_date) == "2026-11-01"
    split = _modifier(
        {"type": "split_outflow", "date": "2026-11-02", "amount_minor": 90000, "instalments": 3,
         "cadence": "monthly"}
    )  # fmt: skip
    assert (split.instalments, split.cadence) == (3, "monthly")


def test_the_documented_field_names_are_accepted() -> None:
    """#45 (Codex): docs/07's names map to the engine's; "all" occurrences is the default."""
    assert set(ALIASES.values()) <= _MODIFIER_FIELDS
    delay = _modifier(
        {"type": "income_delay", "income_stream_id": "inc_X", "days": 3, "occurrences": "all"},
        {"inc_X": "income:acme"},
    )
    assert (delay.income_stream_key, delay.occurrences) == ("income:acme", None)
    spread = _modifier({"type": "split_outflow", "start_date": "2026-11-02", "amount_minor": 1,
                        "instalments": 2, "cadence": "monthly"})  # fmt: skip
    assert str(spread.date) == "2026-11-02"
