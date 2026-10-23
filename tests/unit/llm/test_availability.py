"""AI availability (owner decision, 13 Oct 2026): status words from the breaker, credit refusals
and the daily budget; never billing words for users."""

from __future__ import annotations

import pytest

from backend.llm.availability import PAUSED_TEXT, AiAvailability, user_status
from backend.llm.client import ModelSpendLimitError, ModelTier
from tests.unit.llm.fakes import ScriptedCompletions, client, spend_limit


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_answers_are_available_by_default() -> None:
    assert AiAvailability(lambda: False).status() == "ok"


def test_an_open_breaker_pauses_answers() -> None:
    assert AiAvailability(lambda: True).status() == "unavailable"


def test_a_used_budget_pauses_answers() -> None:
    assert AiAvailability(lambda: False, budget_used=lambda: True).status() == "unavailable"


def test_a_credit_refusal_pauses_for_five_minutes_then_calls_are_tried_again() -> None:
    clock = Clock()
    availability = AiAvailability(lambda: False, clock=clock)
    availability.note_spend_limit()
    assert availability.status() == "unavailable"
    clock.now = 299
    assert availability.status() == "unavailable"
    clock.now = 300
    assert availability.status() == "ok"


def test_users_never_see_billing_words() -> None:
    assert user_status("ok") == ("ok", "AI answers are available.")
    status, message = user_status("unavailable")
    assert status == "unavailable"
    assert message == PAUSED_TEXT
    for word in ("credit", "balance", "billing", "quota", "top up", "$"):
        assert word not in PAUSED_TEXT.lower()


def test_no_credit_flips_the_client_to_unavailable() -> None:
    model_client = client(ScriptedCompletions(spend_limit()))
    with pytest.raises(ModelSpendLimitError):
        model_client.complete(tier=ModelTier.FAST, messages=[{"role": "user", "content": "hi"}])
    assert model_client.availability.status() == "unavailable"
