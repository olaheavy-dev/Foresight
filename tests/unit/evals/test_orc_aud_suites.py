"""E-ORC and E-AUD are registered and, without a database, say "not measured" (never a pass)."""

from __future__ import annotations

import pytest

from evals.gates import gate
from evals.run import SUITES
from evals.suites import audit, orchestration


def test_both_suites_are_registered() -> None:
    ids = {s.SUITE_ID for s in SUITES}
    assert {"E-ORC", "E-AUD"} <= ids


@pytest.mark.parametrize("suite", [orchestration, audit])
def test_without_a_database_nothing_is_measured(
    suite: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = suite.run(fast=True)  # type: ignore[attr-defined]
    assert out["targets"]
    assert all(t["met"] is None for t in out["targets"])
    # Unmeasured targets never pass a gate on their own merit: the suite only "ran".
    assert gate({**out, "error": None})["failed"] == []
