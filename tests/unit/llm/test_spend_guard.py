"""Project-wide daily spend guard (backend/llm/spend_guard.py)."""

from __future__ import annotations

from datetime import date

import pytest

from backend.llm.availability import AiAvailability
from backend.llm.client import ModelTier, ModelUnavailableError
from backend.llm.spend_guard import DailySpendGuard
from tests.unit.llm.fakes import ScriptedCompletions, client, ok

MSG = [{"role": "user", "content": "hello"}]


class Store:
    def __init__(self) -> None:
        self.by_day: dict[date, float] = {}
        self.reads = 0

    def spent_on(self, day: date) -> float:
        self.reads += 1
        return self.by_day.get(day, 0.0)


def make(store: Store, day: list[date], now: list[float], budget: float = 0.50) -> DailySpendGuard:
    return DailySpendGuard(
        store.spent_on, budget_usd=budget, today=lambda: day[0], clock=lambda: now[0]
    )


def test_pauses_at_the_budget_and_resumes_the_next_utc_day() -> None:
    store, day, now = Store(), [date(2026, 10, 14)], [0.0]
    store.by_day[day[0]] = 0.49
    guard = make(store, day, now)
    assert guard.exhausted() is False
    guard.charge(0.02)  # a live call not yet written as a step
    assert guard.exhausted() is True
    day[0] = date(2026, 10, 15)
    assert guard.exhausted() is False


def test_store_is_read_at_most_once_a_minute() -> None:
    store, day, now = Store(), [date(2026, 10, 14)], [0.0]
    guard = make(store, day, now)
    guard.exhausted()
    guard.exhausted()
    assert store.reads == 1
    store.by_day[day[0]] = 0.60
    assert guard.exhausted() is False  # cached
    now[0] = 61.0
    assert guard.exhausted() is True


def test_unreadable_store_keeps_answering_and_zero_budget_disables() -> None:
    def broken(day: date) -> float:
        raise RuntimeError("db down")

    guard = DailySpendGuard(broken, budget_usd=0.50)
    assert guard.exhausted() is False
    store = Store()
    store.by_day[date.today()] = 99.0
    assert DailySpendGuard(store.spent_on, budget_usd=0).exhausted() is False


def test_used_budget_makes_ai_unavailable_and_refuses_live_calls() -> None:
    store, day, now = Store(), [date(2026, 10, 14)], [0.0]
    store.by_day[day[0]] = 0.50
    guard = make(store, day, now)
    availability = AiAvailability(lambda: False, budget_used=guard.exhausted)
    assert availability.status() == "unavailable"

    calls = ScriptedCompletions(ok())
    model_client = client(calls, spend_guard=guard)
    with pytest.raises(ModelUnavailableError):
        model_client.complete(tier=ModelTier.FAST, messages=MSG)
    assert calls.calls == []
    assert model_client.availability.status() == "unavailable"
