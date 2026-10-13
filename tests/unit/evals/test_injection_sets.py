"""The E-SEC sets are hand-authored and frozen with the other authored sets (docs/09 §3.9)."""

from __future__ import annotations

from evals.authored import AUTHORED_DIR, verify
from evals.common import read_jsonl


def test_authored_sets_are_frozen() -> None:
    assert verify() == []


def test_injection_sets_have_the_documented_shape() -> None:
    rows = read_jsonl(AUTHORED_DIR / "injection_cases.jsonl")
    assert sum(r["channel"] == "chat" for r in rows) == 40
    assert sum(r["channel"] == "data" for r in rows) == 40
    assert len({r["id"] for r in rows}) == 80
    for r in rows:
        assert r["text"]
        assert r["attacker_goal"]
        assert r["expected"]
    assert len(read_jsonl(AUTHORED_DIR / "injection_cases_dev.jsonl")) >= 20
    assert len(read_jsonl(AUTHORED_DIR / "injection_benign_questions.jsonl")) == 60
