"""AI availability (owner decision, 13 Oct 2026): status words from the Mesh balance, the breaker
and spend refusals; cached; never a figure, never billing words for users."""

from __future__ import annotations

import pytest

from backend.mesh.availability import PAUSED_TEXT, AiAvailability, user_status
from backend.mesh.mesh_client import MeshSpendLimitError, ModelTier
from tests.unit.mesh.fakes import ScriptedCompletions, client, spend_limit


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _availability(balances: list[float | None | Exception], *, breaker_open: bool = False,
                  clock: Clock | None = None) -> tuple[AiAvailability, list[int]]:  # fmt: skip
    calls = [0]

    def fetch() -> float | None:
        calls[0] += 1
        value = balances[min(calls[0] - 1, len(balances) - 1)]
        if isinstance(value, Exception):
            raise value
        return value

    return (
        AiAvailability(fetch, lambda: breaker_open, low_usd=2.0, worst_case_usd=0.30,
                       clock=clock or Clock()),
        calls,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("available", "expected"),
    [(19.5, "ok"), (2.0, "ok"), (1.99, "low"), (0.31, "low"), (0.30, "unavailable"),
     (0.0, "unavailable"), (None, "ok")],
)  # fmt: skip
def test_status_follows_the_thresholds(available: float | None, expected: str) -> None:
    availability, _ = _availability([available])
    assert availability.status() == expected


def test_the_balance_is_cached_for_five_minutes() -> None:
    clock = Clock()
    availability, calls = _availability([10.0, 0.1], clock=clock)
    assert availability.status() == "ok"
    clock.now = 299
    assert availability.status() == "ok"
    assert calls[0] == 1
    clock.now = 300
    assert availability.status() == "unavailable"
    assert calls[0] == 2


def test_an_unreadable_balance_never_stops_answers() -> None:
    availability, _ = _availability([RuntimeError("network")])
    assert availability.status() == "ok"


def test_an_open_breaker_pauses_answers() -> None:
    availability, calls = _availability([50.0], breaker_open=True)
    assert availability.status() == "unavailable"
    assert calls[0] == 0  # no balance call needed


def test_a_spend_refusal_pauses_at_once_until_the_next_check() -> None:
    clock = Clock()
    availability, _ = _availability([10.0, 10.0], clock=clock)
    assert availability.status() == "ok"
    availability.note_spend_limit()
    assert availability.status() == "unavailable"
    clock.now = 301
    assert availability.status() == "ok"


def test_users_never_see_low_or_billing_words() -> None:
    assert user_status("low") == ("ok", "AI answers are available.")
    status, message = user_status("unavailable")
    assert status == "unavailable"
    assert message == PAUSED_TEXT
    for word in ("credit", "balance", "billing", "top up", "$"):
        assert word not in PAUSED_TEXT.lower()


def test_a_402_from_mesh_flips_the_client_to_unavailable() -> None:
    mesh = client(ScriptedCompletions(spend_limit()))
    with pytest.raises(MeshSpendLimitError):
        mesh.complete(tier=ModelTier.FAST, messages=[{"role": "user", "content": "hi"}])
    assert mesh.availability.status() == "unavailable"
