"""Coordinator routing tables (docs/06 §6). Data, not prompts: system events never call a model."""

from __future__ import annotations

from backend.agents.contracts import Intent
from backend.agents.state import Workflow

# docs/06 §6.1: system-triggered workflows follow a fixed route (no LLM routing).
SYSTEM_EVENTS: dict[str, Workflow] = {
    "import_committed": "ingestion",
    "transaction_added": "ingestion",
    "data_version_changed": "risk_detection",
    "prefs_version_changed": "risk_detection",
    "daily_refresh": "risk_detection",
    "scenario_submitted": "scenario",
    "advice_needed": "recommendation",
    "digest_due": "digest",
}

# The specialists each workflow runs, in order. The advise ⇄ verify loop (W4) is a sub-graph that
# only runs when a risk or material finding asks for advice.
WORKFLOW_ROUTES: dict[Workflow, tuple[str, ...]] = {
    "ingestion": ("ledger", "analyst", "forecaster", "risk_check", "advice_loop", "briefing"),
    "risk_detection": ("analyst", "forecaster", "risk_check", "advice_loop", "briefing"),
    "scenario": ("forecaster", "advice_loop", "compose"),
    "recommendation": ("advice_loop",),
    "digest": ("freshness_check", "select_content", "compose_digest", "deliver"),
}

# docs/06 §6.2: user question intent → specialists in order. "advice_loop" runs only when the
# Understand step says the question needs advice (or the intent always needs it).
INTENT_ROUTES: dict[Intent, tuple[str, ...]] = {
    "spending_breakdown": ("analyst",),
    "trend_or_change": ("analyst",),
    "transaction_lookup": ("ledger_query",),
    "subscription_review": ("analyst", "advice_loop?"),
    "affordability": ("forecaster", "advice_loop"),
    "scenario": ("forecaster",),
    "goal_status": ("forecaster", "advice_loop?"),
    "risk_check": ("forecaster", "risk_check"),
    "advice_request": ("analyst", "forecaster", "advice_loop"),
    "explain_recommendation": (),
    "smalltalk_or_out_of_scope": (),
}


def route_for_event(event: str) -> tuple[Workflow, tuple[str, ...]]:
    workflow = SYSTEM_EVENTS[event]
    return workflow, WORKFLOW_ROUTES[workflow]


def route_for_intent(intent: Intent, *, needs_advice: bool) -> tuple[str, ...]:
    """Expand optional steps (`name?`) according to the Understand step's `needs_advice`."""
    route: list[str] = []
    for step in INTENT_ROUTES[intent]:
        if step.endswith("?"):
            if needs_advice:
                route.append(step[:-1])
        else:
            route.append(step)
    return tuple(route)
