"""Coordinator nodes (docs/06 §4.0, §6; docs/05 §4.2).

System events route through a fixed table with no model call. A user question goes:
intake → (prefetch ‖ understand) → triage → clarify | refuse | answer-cache lookup → specialists.
"""

from __future__ import annotations

import json
from typing import Any

from backend.agents.cache import (
    PROMPTS_DIR,
    answer_cache_key,
    prompt_bundle_version,
    prompt_version,
)
from backend.agents.contracts import CLARIFY_BELOW, IntentClassification
from backend.agents.routes import WORKFLOW_ROUTES, route_for_intent
from backend.agents.runtime import NodeOutput, RunContext
from backend.agents.state import ForesightState
from backend.finance_core.forecast.engine import ENGINE_VERSION
from backend.mesh.mesh_client import ModelTier

UNDERSTAND_PROMPT = "understand"

# Templated user-facing text (never model text). The refusal follows docs/01 FR-63.
REFUSAL_TEXT = (
    "I can only help with questions about the money in this profile: spending, bills, what's "
    "coming up, what you can afford and what to do about it. I can't recommend financial "
    "products, investments or tax steps."
)
CLARIFY_TEXT = "Could you say a bit more, for example the amount or the date you have in mind?"


def route_event(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """System-triggered workflows: the fixed route table, no model call (docs/06 §6.1, ORC-8)."""
    route = list(WORKFLOW_ROUTES[state["workflow"]])
    return NodeOutput(
        update={"route": route},
        output={"event": state.get("event"), "route": route},
        label="Planning the work",
    )


def intake(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """Stage 0 bookkeeping (docs/05 §4.2). Idempotency and limits are applied by the runner;
    the input screen is TODO(AGT-13) and runs here once the guard is wired in."""
    action = state.get("scenario_input") if isinstance(state.get("scenario_input"), dict) else None
    return NodeOutput(
        output={
            "structured_action": action is not None,
            "chars": len(state.get("user_message") or ""),
        },
        label="Reading your question",
    )


def prefetch(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """Load the stored snapshot refs for the current versions while Understand runs."""
    with ctx.lock:
        forecast = ctx.store.ctx.latest_calculation("forecast")
    forecast_id = forecast.id if forecast is not None else None
    stale = forecast is not None and forecast.data_version != state.get("data_version")
    return NodeOutput(
        update={"snapshot_id": forecast_id, "forecast_id": None if stale else forecast_id},
        output={"forecast_id": forecast_id, "stale": stale},
        tool_calls=[{"name": "load_snapshot", "result_refs": [forecast_id] if forecast_id else []}],
        label="Loading your latest forecast",
    )


def prompt_text(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _understand_messages(state: ForesightState) -> list[dict[str, str]]:
    # The user's words travel only inside a JSON data field, never as instructions (docs/06 rule 6).
    payload = {"history": state.get("history") or [], "message": state.get("user_message") or ""}
    return [
        {"role": "system", "content": prompt_text(UNDERSTAND_PROMPT)},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def understand(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """One fast-tier call: standalone rewrite + intent + slots + flags (docs/05 §4.2 stage 2)."""
    action = state.get("scenario_input")
    if isinstance(action, dict) and action.get("intent"):
        # Structured follow-up (a block action): no classification needed (docs/06 W5).
        intent = IntentClassification(
            standalone_question=str(action.get("question") or state.get("user_message") or ""),
            intent=action["intent"],
            slots=action.get("slots") or {},
            needs_forecast=bool(action.get("needs_forecast")),
            needs_advice=bool(action.get("needs_advice")),
            confidence=1.0,
        )
        return NodeOutput(
            update={"intent": intent.model_dump()},
            output=intent.model_dump(),
            label="Following up on the previous answer",
        )
    mesh = ctx.require_mesh()
    ctx.before_llm()
    result = mesh.structured(
        tier=ModelTier.FAST,
        messages=_understand_messages(state),
        output=IntentClassification,
        name="understand",
        max_tokens=400,
        locale_pack=state.get("locale_pack") or "uk",
    )
    ctx.charge(result.calls)
    value = result.value
    return NodeOutput(
        update={"intent": value.model_dump()},
        output=value.model_dump(),
        llm=result.calls,
        prompt_version=prompt_version(UNDERSTAND_PROMPT),
        status="retried" if result.repaired else "ok",
        label="Understanding your question",
    )


def triage(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """Join point after prefetch ‖ understand: decide refuse, clarify or answer."""
    decision = triage_decision(state)
    return NodeOutput(output={"decision": decision}, label="Deciding how to answer")


def triage_decision(state: ForesightState) -> str:
    intent = state.get("intent")
    if intent is None:
        return "persist_response"
    if (
        intent["injection_suspected"]
        or intent["out_of_scope"]
        or intent["intent"] == "smalltalk_or_out_of_scope"
    ):
        return "refuse"
    if intent["confidence"] < CLARIFY_BELOW:
        return "clarify"
    return "cache_lookup"


def refuse(state: ForesightState, ctx: RunContext) -> NodeOutput:
    intent = state.get("intent") or {}
    reason = "injection" if intent.get("injection_suspected") else "out_of_scope"
    if reason == "injection":
        with ctx.lock:
            ctx.store.ctx.append_audit(
                "input_refused",
                "agent_run",
                ctx.run_id,
                actor="agent:coordinator",
                after={"reason": reason},
                run_id=ctx.run_id,
            )
    body = {"kind": "refusal", "reason": reason, "text": REFUSAL_TEXT}
    return NodeOutput(
        update={"response_body": body},
        output={"reason": reason},
        label="Outside what Foresight can help with",
    )


def clarify(state: ForesightState, ctx: RunContext) -> NodeOutput:
    # TODO(AGT-10): 2–4 option chips from the intent's slot schema (docs/08 clarifying block).
    body = {"kind": "clarify", "text": CLARIFY_TEXT}
    return NodeOutput(
        update={"response_body": body, "needs_user_input": body},
        output={"reason": "low_confidence"},
        label="Asking a clarifying question",
    )


def cache_key_for(state: ForesightState, ctx: RunContext) -> str:
    intent = state["intent"] or {}
    with ctx.lock:
        advice_version = ctx.store.advice_state_version()
    return answer_cache_key(
        workspace_id=ctx.store.ctx.workspace_id,
        intent=str(intent.get("intent")),
        slots=dict(intent.get("slots") or {}),
        data_version=int(state.get("data_version") or 0),
        prefs_version=int(state.get("prefs_version") or 0),
        advice_state_version=advice_version,
        engine_version=ENGINE_VERSION,
        as_of=str(state.get("as_of") or ""),
        locale_pack=str(state.get("locale_pack") or "uk"),
        prompt_bundle=prompt_bundle_version(),
    )


def cache_lookup(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """Exact answer cache (docs/05 §4.2 stage 3). A hit costs no model calls."""
    key = cache_key_for(state, ctx)
    with ctx.lock:
        hit = ctx.store.cache_get(key)
    if hit is not None:
        return NodeOutput(
            update={"cache_key": key, "cache_hit": True, "response_id": hit.id},
            output={"hit": True, "response_id": hit.id},
            cached=True,
            label="Same data as an earlier answer",
        )
    intent = state["intent"] or {}
    route = list(route_for_intent(intent["intent"], needs_advice=bool(intent.get("needs_advice"))))
    return NodeOutput(
        update={"cache_key": key, "cache_hit": False, "route": route},
        output={"hit": False, "route": route},
        label="Planning the work",
    )


def cache_decision(state: ForesightState) -> str:
    return "persist_response" if state.get("cache_hit") else "route"


def persist_response(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """Store the answer snapshot and the assistant turn; cache it when it is cacheable."""
    if state.get("cache_hit"):
        response_id = state.get("response_id")
        _assistant_message(state, ctx, response_id)
        return NodeOutput(output={"response_id": response_id, "cached": True}, label="Answer ready")
    body = state.get("response_body")
    if body is None:
        _assistant_message(state, ctx, None)
        return NodeOutput(
            status="skipped",
            output={"reason": "no answer was composed"},
            update={"partial": True},
            label="No answer could be composed",
        )
    intent = state.get("intent") or {}
    with ctx.lock:
        snapshot = ctx.store.save_response(
            run_id=ctx.run_id,
            surface="workspace",
            intent=intent.get("intent"),
            body=body,
            data_version=int(state.get("data_version") or 0),
            prefs_version=int(state.get("prefs_version") or 0),
            engine_version=ENGINE_VERSION,
            partial=bool(state.get("partial")),
        )
        cacheable = (
            body.get("kind") not in {"refusal", "clarify"}
            and state.get("cache_key")
            and not state.get("partial")
        )
        if cacheable:
            ctx.store.cache_put(
                str(state["cache_key"]), response_id=snapshot.id, intent=str(intent.get("intent"))
            )
    _assistant_message(state, ctx, snapshot.id)
    return NodeOutput(
        update={"response_id": snapshot.id},
        output={"response_id": snapshot.id, "cached": bool(cacheable)},
        label="Answer ready",
    )


def _assistant_message(state: ForesightState, ctx: RunContext, response_id: Any) -> None:
    thread_id = state.get("thread_id")
    if not thread_id:
        return
    with ctx.lock:
        ctx.store.add_message(
            thread_id, role="assistant", run_id=ctx.run_id, response_id=response_id
        )
