"""Step model wait (`AgentStep.model_ms`) and the E-EFF percentile (docs/09 E-EFF)."""

from __future__ import annotations

from typing import Any

from backend.agents.runtime import concurrent_ms, model_ms
from backend.llm.client import ModelResult, Usage
from evals.suites.efficiency import percentile


def call(ms: int, measured: bool = True) -> ModelResult:
    return ModelResult(
        text="", model="m", response_id="r", usage=Usage(1, 1, 2), latency_ms=ms,
        used_fallback=False, latency_measured=measured,
    )  # fmt: skip


def test_sequential_calls_add_up_and_an_unmeasured_call_voids_the_sum() -> None:
    assert model_ms([call(100), call(250)]) == 350
    assert model_ms([call(100), call(250, measured=False)]) is None
    assert model_ms([]) is None


def test_concurrent_groups_overlap_on_the_pool() -> None:
    # Three judge calls on three workers: the slowest one is the wait.
    assert concurrent_ms([[call(5000)], [call(9000)], [call(7000)]], 3) == 9000
    # A repair retry runs after its group's first call, on the same worker.
    assert concurrent_ms([[call(5000), call(4000)], [call(6000)]], 3) == 9000
    # Four groups on two workers: the third and fourth wait for a free worker.
    assert concurrent_ms([[call(3)], [call(5)], [call(4)], [call(1)]], 2) == 7
    assert concurrent_ms([[call(3)], [call(5, measured=False)]], 3) is None
    assert concurrent_ms([[], []], 3) is None


def test_percentile_interpolates() -> None:
    assert percentile([], 50) is None
    assert percentile([10.0], 95) == 10.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert percentile(list(map(float, range(1, 101))), 95) == 95.05


def test_a_dated_purchase_question_never_asks_again_for_what_it_gave() -> None:
    """Understand's amount and date for one purchase make a one-off payment (owner rule: don't
    re-ask what the question answered); before the forecast starts it moves to its first day."""
    from datetime import date
    from types import SimpleNamespace

    from backend.agents.core_loop import _dated_purchase_spec

    inputs: Any = SimpleNamespace(as_of=date(2026, 10, 11), currency="GBP")
    intent = {
        "intent": "affordability",
        "slots": {"amount_minor": 120000, "date": "2026-11-01", "purpose": "holiday"},
    }
    spec = _dated_purchase_spec(intent, inputs)
    assert spec is not None
    (payment,) = spec.modifiers
    assert (payment.type, payment.amount_minor, payment.date, payment.label) == (
        "one_off_outflow", 120000, date(2026, 11, 1), "Holiday",
    )  # fmt: skip
    early = {**intent, "slots": {**intent["slots"], "date": "2026-10-01"}}
    assert _dated_purchase_spec(early, inputs).modifiers[0].date == date(2026, 10, 12)  # type: ignore[union-attr]
    assert _dated_purchase_spec({**intent, "intent": "scenario"}, inputs) is None
    assert _dated_purchase_spec({**intent, "slots": {"amount_minor": 120000}}, inputs) is None
