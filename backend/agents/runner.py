"""Running a workflow: create the AgentRun, run the graph, close the run (docs/06 §8, §10).

`run_workflow` serves system events and evals; `ask` serves a question in a thread, including the
idempotent `client_msg_id` (docs/05 §6.4) and the stored standalone question (docs/01 FR-88).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from backend.agents.budget import Budget
from backend.agents.runtime import NodeSpec, RunContext, deadline_for, utcnow
from backend.agents.state import ForesightState
from backend.llm.client import ModelClient
from backend.storage.agent_repo import AgentStore

LOCALE_PACKS = {"GB": "uk", "IN": "in"}


@dataclass(frozen=True)
class RunOutcome:
    run_id: str
    status: str  # succeeded | failed
    partial: bool
    response_id: str | None
    state: dict[str, Any]
    reused: bool = False  # True when an idempotent retry returned an existing run


def _initial_state(store: AgentStore, run_id: str, workflow: str, trigger: str) -> ForesightState:
    ws = store.ctx.workspace
    return {
        "run_id": run_id,
        "workspace_id": ws.id,
        "workflow": workflow,  # type: ignore[typeddict-item]
        "trigger": trigger,  # type: ignore[typeddict-item]
        "data_version": int(ws.data_version or 0),
        "prefs_version": store.ctx.prefs_version(),
        "currency": ws.home_currency,
        "home_currency": ws.home_currency,
        "locale_pack": LOCALE_PACKS.get(ws.country.upper(), "uk"),
        "scope": "mine",
        "as_of": date.today().isoformat(),
        "errors": [],
        "partial": False,
        "revision_round": 0,
        "cache_hit": False,
    }


def run_workflow(
    store: AgentStore,
    *,
    workflow: str,
    trigger: str,
    model_client: ModelClient | None = None,
    event: str | None = None,
    inputs: Mapping[str, Any] | None = None,
    nodes: Mapping[str, NodeSpec] | None = None,
    checkpointer: Any = None,
    budget: Budget | None = None,
    clock: Callable[[], datetime] = utcnow,
    thread_id: str | None = None,
    on_run_created: Callable[[str], None] | None = None,
) -> RunOutcome:
    from backend.agents.graph import build_graph

    ws = store.ctx.workspace
    run = store.create_run(
        workflow=workflow,
        trigger=trigger,
        data_version=int(ws.data_version or 0),
        prefs_version=store.ctx.prefs_version(),
        deadline_at=deadline_for(workflow, clock()),
        thread_id=thread_id,
    )
    store.session.commit()
    if on_run_created is not None:
        on_run_created(run.id)
    ctx = RunContext(
        store=store,
        run_id=run.id,
        workflow=workflow,
        deadline_at=run.deadline_at,
        model_client=model_client,
        budget=budget or Budget(),
        clock=clock,
    )
    state = _initial_state(store, run.id, workflow, trigger)
    state["event"] = event
    state["thread_id"] = thread_id
    state.update(dict(inputs or {}))  # type: ignore[typeddict-item]
    graph = build_graph(workflow, ctx, nodes=nodes, checkpointer=checkpointer)
    try:
        final = graph.invoke(state, config={"configurable": {"thread_id": run.id}})
    except Exception as exc:
        store.session.rollback()
        store.finish_run(run.id, status="failed", error=f"{type(exc).__name__}: {exc}")
        store.session.commit()
        raise
    partial = bool(final.get("partial"))
    store.finish_run(
        run.id,
        status="succeeded",
        partial=partial,
        revision_count=int(final.get("revision_round") or 0),
    )
    store.session.commit()
    return RunOutcome(
        run_id=run.id,
        status="succeeded",
        partial=partial,
        response_id=final.get("response_id"),
        state=dict(final),
    )


def _history(store: AgentStore, thread_id: str) -> list[dict[str, Any]]:
    """The last three turns as the Understand step left them: the standalone question plus its
    intent and slots (the previous answer's structured refs, docs/05 §4.2 stage 2), so a
    follow-up can carry over what it does not change. Never figures from an answer."""
    turns = [m for m in store.messages(thread_id) if m.role == "user"][-3:]
    out: list[dict[str, Any]] = []
    for msg in turns:
        entry: dict[str, Any] = {"question": msg.standalone_question or msg.text}
        understood = next(
            (s.output for s in store.steps(msg.run_id) if s.node == "understand" and s.output),
            None,
        ) if msg.run_id else None  # fmt: skip
        if understood and understood.get("intent"):
            entry["intent"] = understood["intent"]
            entry["slots"] = understood.get("slots") or {}
        out.append(entry)
    return out


def ask(
    store: AgentStore,
    *,
    thread_id: str,
    text: str,
    client_msg_id: str,
    model_client: ModelClient | None,
    action: Mapping[str, Any] | None = None,
    nodes: Mapping[str, NodeSpec] | None = None,
    checkpointer: Any = None,
    budget: Budget | None = None,
    clock: Callable[[], datetime] = utcnow,
    on_run_created: Callable[[str], None] | None = None,
    as_of: str | None = None,
) -> RunOutcome:
    existing = store.message_by_client_id(thread_id, client_msg_id)
    if existing is not None and existing.run_id:
        run = store.run(existing.run_id)
        assert run is not None
        assistant = next(
            (m for m in store.messages(thread_id) if m.run_id == run.id and m.role == "assistant"),
            None,
        )
        return RunOutcome(
            run_id=run.id,
            status=run.status,
            partial=run.partial,
            response_id=assistant.response_id if assistant else None,
            state={},
            reused=True,
        )
    history = _history(store, thread_id)
    message = store.add_message(
        thread_id,
        role="user",
        text=text,
        client_msg_id=client_msg_id,
        action=dict(action) if action else None,
    )
    store.session.commit()

    def created(run_id: str) -> None:
        # Link the question to its run at once, so a retry during the run finds it (05 §6.4).
        message.run_id = run_id
        store.session.commit()
        if on_run_created is not None:
            on_run_created(run_id)

    outcome = run_workflow(
        store,
        workflow="conversation",
        trigger="user",
        model_client=model_client,
        inputs={
            "user_message": text,
            "history": history,
            "scenario_input": dict(action) if action else None,
        }
        | ({"as_of": as_of} if as_of else {}),
        nodes=nodes,
        checkpointer=checkpointer,
        budget=budget,
        clock=clock,
        thread_id=thread_id,
        on_run_created=created,
    )
    intent = outcome.state.get("intent") or {}
    message.run_id = outcome.run_id
    message.standalone_question = intent.get("standalone_question")
    store.session.commit()
    return outcome


# What a question's advice follow-up needs from the question's final state (docs/06 §13): the
# question, the forecast and what-if it asked about, and the rejected round's drafts with their
# critiques, so the loop carries on from where the question stopped.
FOLLOWUP_KEYS = (
    "intent",
    "user_message",
    "forecast_id",
    "snapshot_id",
    "simulation_ids",
    "scenario_spec",
    "risk_flags",
    "locale_pack",
    "as_of",
    "proposals",
    "revision_round",
    "verifications",
    "data_version",
    "prefs_version",
)


def followup_inputs(outcome: RunOutcome) -> dict[str, Any] | None:
    """The seed for an `advice_followup` run, or None when the question needs no follow-up."""
    final = outcome.state
    if not final.get("followup_pending") or not outcome.response_id or outcome.partial:
        return None
    seed = {k: final[k] for k in FOLLOWUP_KEYS if k in final}
    # The follow-up answers with the advice itself: the recommendation leads (the question's own
    # answer is already in the thread). The Advisor reads only the question text, not the intent.
    intent = dict(final.get("intent") or {})
    seed["intent"] = {**intent, "intent": "advice_request", "needs_advice": True}
    seed["follow_up_of"] = outcome.response_id
    seed["verdict"] = None
    return seed


def run_followup(
    store: AgentStore,
    outcome: RunOutcome,
    *,
    model_client: ModelClient | None,
    nodes: Mapping[str, NodeSpec] | None = None,
    clock: Callable[[], datetime] = utcnow,
) -> RunOutcome | None:
    """Carry a question's advice loop on after its answer: revise from the stored critiques,
    verify, and answer again in the same thread. Runs in the background in the API; evals and
    tests call it straight after `ask`, so recording and replay take one path."""
    seed = followup_inputs(outcome)
    if seed is None:
        return None
    return run_workflow(
        store,
        workflow="advice_followup",
        trigger="event",
        event="advice_deferred",
        model_client=model_client,
        nodes=nodes,
        inputs=seed,
        thread_id=outcome.state.get("thread_id"),
        clock=clock,
    )
