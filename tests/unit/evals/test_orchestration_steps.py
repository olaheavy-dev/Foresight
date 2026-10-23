"""E-ORC counts an agent as having done a case's work only if one of its steps succeeded."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from evals.suites.orchestration import CaseResult, _common

CASE = {"min_steps": 2, "expected_agents": ["coordinator", "advisor"]}


def _check(*steps: tuple[str, str]) -> CaseResult:
    rows = [SimpleNamespace(agent=a, status=s, llm_calls=1) for a, s in steps]
    store: Any = SimpleNamespace(
        steps=lambda _run: rows, run=lambda _run: SimpleNamespace(status="succeeded")
    )
    result = CaseResult(case="ORC-T", checks=[])
    _common(result, CASE, store, SimpleNamespace(run_id="run_1"))  # type: ignore[arg-type]
    return result.finish()


def test_an_advisor_that_only_failed_does_not_pass_the_case() -> None:
    """A failed Advisor step whose answer came from the deterministic fallback (Codex on #67)."""
    result = _check(("coordinator", "ok"), ("advisor", "failed"))
    assert result.agents == ["coordinator", "advisor"]
    assert result.assertions["expected_agents_succeeded"] is False
    assert result.status == "fail"


def test_a_retried_advisor_step_counts() -> None:
    result = _check(("coordinator", "ok"), ("advisor", "failed"), ("advisor", "retried"))
    assert result.status == "pass"
