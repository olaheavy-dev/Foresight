"""A model verdict must agree with the engine's verdict category (docs/08 §5.4)."""

from __future__ import annotations

import pytest

from backend.agents.compose import contradicts


@pytest.mark.parametrize(
    ("kind", "text", "contradiction"),
    [
        ("goes_negative", "This would leave you about {{R7}} overdrawn before payday.", False),
        ("goes_negative", "You can't afford it before your {{R8}} payday.", False),
        ("goes_negative", "Yes, you can comfortably afford it.", True),
        ("goes_negative", "Your balance would dip below your buffer.", True),
        ("breaches_buffer", "You'd stay positive but fall below your buffer before {{R8}}.", False),
        ("breaches_buffer", "This would leave you overdrawn.", True),
        ("breaches_buffer", "You can afford it.", True),
        ("tight", "Probably fine, though a bad month could take you under your buffer.", False),
        ("tight", "You'd be overdrawn.", True),
        ("comfortable", "Yes. You stay above your buffer in every pay cycle.", False),
        ("comfortable", "You would drop below your buffer before {{R8}}.", True),
        ("comfortable", "This would take you overdrawn.", True),
    ],
)
def test_contradictions_are_caught(kind: str, text: str, contradiction: bool) -> None:
    assert contradicts(kind, text) is contradiction
