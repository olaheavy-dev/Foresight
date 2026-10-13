"""Coordinator route tables, budget guard, answer-cache key and graph topology (docs/06 §6,
docs/01 FR-60, docs/05 §4.2). No database, no model."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, get_args

import pytest

from backend.agents.budget import Budget, BudgetExceeded
from backend.agents.cache import answer_cache_key, canonical_slots
from backend.agents.contracts import Intent
from backend.agents.graph import _next_after, build_graph, default_nodes
from backend.agents.routes import (
    INTENT_ROUTES,
    SYSTEM_EVENTS,
    WORKFLOW_ROUTES,
    route_for_event,
    route_for_intent,
)
from backend.agents.runtime import RunContext


def test_every_intent_has_a_route() -> None:
    assert set(INTENT_ROUTES) == set(get_args(Intent))


def test_every_system_event_routes_to_a_workflow_without_a_model() -> None:
    nodes = default_nodes()
    for event in SYSTEM_EVENTS:
        workflow, route = route_for_event(event)
        assert route == WORKFLOW_ROUTES[workflow]
        for step in route:
            assert step == "advice_loop" or step in nodes


def test_optional_advice_follows_needs_advice() -> None:
    assert route_for_intent("subscription_review", needs_advice=False) == ("analyst",)
    assert route_for_intent("subscription_review", needs_advice=True) == ("analyst", "advice_loop")
    assert route_for_intent("affordability", needs_advice=False) == ("forecaster", "advice_loop")
    assert route_for_intent("explain_recommendation", needs_advice=True) == ()


def test_budget_refuses_the_thirteenth_call() -> None:
    budget = Budget()
    for _ in range(12):
        budget.check()
        budget.charge(1, 100)
    with pytest.raises(BudgetExceeded):
        budget.check()
    assert budget.exceeded


def test_budget_refuses_after_sixty_thousand_tokens() -> None:
    budget = Budget()
    budget.check()
    budget.charge(1, 60_000)
    with pytest.raises(BudgetExceeded):
        budget.check()


def _key(**overrides: Any) -> str:
    base: dict[str, Any] = {
        "workspace_id": "wsp_1",
        "intent": "affordability",
        "slots": {"amount": "£1,200", "category": "Holiday"},
        "data_version": 3,
        "prefs_version": 0,
        "advice_state_version": "0:-",
        "engine_version": "fc-1",
        "as_of": "2026-10-13",
        "locale_pack": "uk",
        "prompt_bundle": "p1",
    }
    base.update(overrides)
    return answer_cache_key(**base)


def test_cache_key_ignores_slot_case_and_spacing() -> None:
    assert _key() == _key(slots={"Category": " holiday ", "amount": "£1,200"})
    assert canonical_slots({"B": ["y", "X"]}) == {"b": ["x", "y"]}


@pytest.mark.parametrize(
    "change",
    [
        {"slots": {"amount": "£800", "category": "holiday"}},
        {"intent": "scenario"},
        {"data_version": 4},
        {"prefs_version": 1},
        {"advice_state_version": "1:2026-10-13T10:00:00"},
        {"engine_version": "fc-2"},
        {"as_of": "2026-10-14"},
        {"prompt_bundle": "p2"},
        {"workspace_id": "wsp_2"},
    ],
)
def test_anything_that_could_change_the_answer_changes_the_key(change: dict[str, Any]) -> None:
    assert _key(**change) != _key()


def _ctx() -> RunContext:
    return RunContext(
        store=None,  # type: ignore[arg-type]  # compiling a graph never touches storage
        run_id="run_x",
        workflow="x",
        deadline_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )


@pytest.mark.parametrize("workflow", sorted(set(WORKFLOW_ROUTES) | {"conversation"}))
def test_every_workflow_graph_compiles(workflow: str) -> None:
    graph = build_graph(workflow, _ctx())
    names = set(graph.get_graph().nodes)
    assert {"advise", "verify", "revise", "withdraw"} <= names


def test_dispatch_walks_the_route_and_skips_unrequested_advice() -> None:
    state: Any = {"workflow": "risk_detection", "route": list(WORKFLOW_ROUTES["risk_detection"])}
    assert _next_after(None, state) == "analyst"
    assert _next_after("risk_check", state) == "briefing"  # no risk flags → no advice loop
    state["risk_flags"] = [{"kind": "buffer_breach"}]
    assert _next_after("risk_check", state) == "advise"
    assert _next_after("briefing", state) == "__end__"


def test_conversation_always_ends_in_compose_then_persist() -> None:
    state: Any = {"workflow": "conversation", "route": ["forecaster", "advice_loop"]}
    assert _next_after("forecaster", state) == "advise"
    assert _next_after("advice_loop", state) == "compose"
    assert _next_after("compose", state) == "persist_response"
