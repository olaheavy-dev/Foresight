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
from backend.mesh.mesh_client import MeshClient
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
        "prefs_version": 0,
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
    mesh: MeshClient | None = None,
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
        prefs_version=0,
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
        mesh=mesh,
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
    turns = [m for m in store.messages(thread_id) if m.role == "user"][-3:]
    return [{"question": m.standalone_question or m.text} for m in turns]


def ask(
    store: AgentStore,
    *,
    thread_id: str,
    text: str,
    client_msg_id: str,
    mesh: MeshClient | None,
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
        mesh=mesh,
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
