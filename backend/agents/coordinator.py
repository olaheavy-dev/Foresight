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
from backend.agents.compose import ai_paused, clarify_response, paused_response, text_response
from backend.agents.contracts import CLARIFY_BELOW, IntentClassification
from backend.agents.guard import output_screen, screen_input
from backend.agents.prompting import active_canary, system_prompt
from backend.agents.routes import WORKFLOW_ROUTES, route_for_intent
from backend.agents.runtime import NodeOutput, RunContext
from backend.agents.state import ForesightState
from backend.finance_core.forecast.engine import ENGINE_VERSION
from backend.mesh.mesh_client import ModelTier

UNDERSTAND_PROMPT = "understand"
# The fast model spends hidden reasoning tokens out of max_tokens; below ~800 it can return nothing.
UNDERSTAND_MAX_TOKENS = 1000

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
    """Stages 0–1 (docs/05 §4.2): clean the text and screen it with the rule pack.

    Idempotency and rate limits are applied before the run starts. A structured follow-up (a
    block action) skips the screen. `block` refuses without a model call; `suspicious` goes on,
    and the Understand step has to confirm it is a real finance question.
    """
    action = state.get("scenario_input") if isinstance(state.get("scenario_input"), dict) else None
    if action is not None:
        return NodeOutput(
            update={"screen_verdict": "allow", "screen_rules": []},
            output={"structured_action": True},
            label="Reading your follow-up",
        )
    screen = screen_input(state.get("user_message") or "")
    normalised = screen.normalised.text if screen.normalised else (state.get("user_message") or "")
    if screen.verdict == "block":
        with ctx.lock:
            ctx.store.ctx.append_audit(
                "input_refused",
                "agent_run",
                ctx.run_id,
                actor="agent:coordinator",
                after={"reason": "screen", "rules": list(screen.rule_ids),
                       "rule_pack": screen.rule_pack},
                run_id=ctx.run_id,
            )  # fmt: skip
    return NodeOutput(
        update={
            "user_message": normalised,
            "screen_verdict": screen.verdict,
            "screen_rules": list(screen.rule_ids),
        },
        output={
            "structured_action": False,
            "chars": len(normalised),
            "screen": screen.verdict,
            "rules": list(screen.rule_ids),
            "rule_pack": screen.rule_pack,
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


_PACK_COUNTRY = {"uk": "GB", "in": "IN"}


def _category_keys(locale_pack: str) -> list[str]:
    from backend.pipeline import packs

    try:
        return sorted(packs.categorisation_pack(_PACK_COUNTRY.get(locale_pack, "GB")).categories)
    except packs.UnsupportedCountry:
        return []


def _understand_messages(state: ForesightState) -> list[dict[str, str]]:
    # The user's words travel only inside a JSON data field, never as instructions (docs/06 rule 6).
    payload = {
        "today": str(state.get("as_of") or ""),
        # The profile's own category keys (the Forecaster gets the same list), so a category slot
        # is always a key the engine knows, and paraphrases meet on one key.
        "categories": _category_keys(str(state.get("locale_pack") or "uk")),
        "history": state.get("history") or [],
        "message": state.get("user_message") or "",
    }
    return [
        {"role": "system", "content": system_prompt(UNDERSTAND_PROMPT)},
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
    if state.get("screen_verdict") == "block":
        return NodeOutput(
            status="skipped",
            output={"reason": "blocked by the input screen"},
            label="Not sent to a model",
        )
    if ai_paused(ctx):
        # No model call while AI answers are paused. A question asked before can still be
        # recognised from its stored understanding, so the answer cache can serve it.
        remembered = remembered_intent(ctx, state.get("user_message") or "")
        if remembered is not None:
            return NodeOutput(
                update={"intent": remembered, "ai_paused": True},
                output={**remembered, "remembered": True},
                label="Recognised an earlier question",
            )
        return NodeOutput(
            status="skipped",
            update={"ai_paused": True},
            output={"reason": "AI answers are paused"},
            label="AI answers are paused",
        )
    mesh = ctx.require_mesh()
    ctx.before_llm()
    result = mesh.structured(
        tier=ModelTier.FAST,
        messages=_understand_messages(state),
        output=IntentClassification,
        name="understand",
        max_tokens=UNDERSTAND_MAX_TOKENS,
        locale_pack=state.get("locale_pack") or "uk",
    )
    ctx.charge(result.calls)
    value = result.value
    leaks = [
        v for v in output_screen(value.standalone_question, canary=active_canary(),
                                 check_numerals=False)
        if v.kind in {"canary", "url"}
    ]  # fmt: skip
    if leaks:
        # A leaked canary or an injected link: refuse, never show the text (docs/05 §7.4a L4).
        value = value.model_copy(
            update={"injection_suspected": True, "standalone_question": "(withheld)"}
        )
        with ctx.lock:
            ctx.store.ctx.append_audit(
                "prompt_leak_blocked" if any(v.kind == "canary" for v in leaks)
                else "output_screen_blocked",
                "agent_run", ctx.run_id, actor="agent:coordinator",
                after={"node": "understand", "kinds": sorted({v.kind for v in leaks})},
                run_id=ctx.run_id,
            )  # fmt: skip
    return NodeOutput(
        update={"intent": value.model_dump()},
        output=value.model_dump(),
        llm=result.calls,
        prompt_version=prompt_version(UNDERSTAND_PROMPT),
        status="retried" if result.repaired else "ok",
        label="Understanding your question",
    )


def remembered_intent(ctx: RunContext, text: str) -> dict[str, Any] | None:
    """The stored understanding of the same question asked before in this profile."""
    from backend.storage import models as m

    wanted = " ".join(text.split()).lower()
    if not wanted:
        return None
    with ctx.lock:
        store = ctx.store
        messages = store.session.scalars(
            store.ctx.select(m.Message)
            .where(m.Message.role == "user", m.Message.run_id.is_not(None))
            .order_by(m.Message.created_at.desc())
            .limit(200)
        )
        for message in messages:
            if " ".join(message.text.split()).lower() != wanted or message.run_id == ctx.run_id:
                continue
            for step in store.steps(str(message.run_id)):
                if step.node == "understand" and step.status in {"ok", "retried"}:
                    output = dict(step.output or {})
                    output.pop("remembered", None)
                    try:
                        return IntentClassification.model_validate(output).model_dump()
                    except ValueError:
                        return None
    return None


def triage(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """Join point after prefetch ‖ understand: decide refuse, clarify or answer."""
    decision = triage_decision(state)
    return NodeOutput(output={"decision": decision}, label="Deciding how to answer")


def triage_decision(state: ForesightState) -> str:
    if state.get("screen_verdict") == "block":
        return "refuse"
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
    if state.get("screen_verdict") == "block":
        reason = "screen"  # audited at intake
    elif intent.get("injection_suspected"):
        reason = "injection"
    else:
        reason = "out_of_scope"
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
    with ctx.lock:
        body = text_response(
            ctx=ctx.store.ctx, state=state, run_id=ctx.run_id, text=REFUSAL_TEXT,
            status="complete",
        )  # fmt: skip
    return NodeOutput(
        update={"response_body": body, "answer_kind": "refusal"},
        output={"reason": reason},
        label="Outside what Foresight can help with",
    )


def clarify(state: ForesightState, ctx: RunContext) -> NodeOutput:
    with ctx.lock:
        body = clarify_response(
            ctx=ctx.store.ctx, state=state, run_id=ctx.run_id, question=CLARIFY_TEXT
        )
    return NodeOutput(
        update={
            "response_body": body,
            "needs_user_input": {"kind": "clarify"},
            "answer_kind": "clarify",
        },  # fmt: skip
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
    if state.get("ai_paused"):
        route = []  # no model work while paused: compose shows the deterministic numbers only
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
    kind = state.get("answer_kind")
    if body is None:
        # Understanding failed or AI answers are paused: say so plainly and still show the
        # deterministic forecast, never model text (docs/06 §10.1 degradation principle).
        with ctx.lock:
            body = paused_response(ctx=ctx.store.ctx, state=state, run_id=ctx.run_id)
        kind = "unavailable"
    intent = state.get("intent") or {}
    with ctx.lock:
        snapshot = ctx.store.save_response(
            response_id=str(body.get("response_id") or "") or None,
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
            kind == "answer"
            and state.get("cache_key")
            and not state.get("partial")
            and not state.get("followup_pending")  # its follow-up is not part of the snapshot
            and body.get("status") == "complete"
        )
        if cacheable:
            ctx.store.cache_put(
                str(state["cache_key"]), response_id=snapshot.id, intent=str(intent.get("intent"))
            )
    _assistant_message(state, ctx, snapshot.id)
    return NodeOutput(
        update={"response_id": snapshot.id, "answer_kind": kind}
        | ({"partial": True} if kind == "unavailable" else {}),
        output={"response_id": snapshot.id, "cached": bool(cacheable), "kind": kind},
        label="Answer ready" if kind != "unavailable" else "AI explanations unavailable",
        status="ok" if kind != "unavailable" else "failed",
    )


def _assistant_message(state: ForesightState, ctx: RunContext, response_id: Any) -> None:
    thread_id = state.get("thread_id")
    if not thread_id:
        return
    with ctx.lock:
        ctx.store.add_message(
            thread_id, role="assistant", run_id=ctx.run_id, response_id=response_id
        )
