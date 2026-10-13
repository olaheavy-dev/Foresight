"""E-ORC: orchestration (docs/09 §10) over `orchestration_cases.jsonl` (30 cases).

Every case runs the real LangGraph graph on a disposable PostgreSQL database seeded with the demo
personas, and every assertion reads the persisted `AgentRun` / `AgentStep` / `Recommendation` /
`VerificationResult` rows, never the graph's return value alone.

Model calls are answered from the committed cassettes (`FORESIGHT_EVAL_MESH=replay`, no key, no
network). A case whose requests were never recorded is reported "not recorded", never a pass.
Where a case asks for a stub (`stubs`), only that part is scripted and the step says so: the stub
Advisor's steps carry the model name `stub/advisor`, the fault-injection cases (ORC-6/7) run on a
scripted transport. Cases for features that do not exist yet (ORC-11 digest, ORC-14 PDF) are
"not measured yet" and never count as passes.
"""

from __future__ import annotations

import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from backend.agents.budget import Budget
from backend.agents.graph import default_nodes
from backend.agents.routes import SYSTEM_EVENTS, WORKFLOW_ROUTES
from backend.agents.runner import RunOutcome, ask, run_workflow
from backend.agents.runtime import NodeOutput, NodeSpec, RunContext
from backend.agents.state import ForesightState
from backend.mesh.cassettes import CassetteMiss
from backend.mesh.mesh_client import MeshClient
from backend.pipeline.forecast import run_forecast
from backend.storage import models as m
from backend.storage.agent_repo import AgentStore
from backend.storage.repositories import WorkspaceContext, create_workspace, demo_workspace
from evals.assistant import eval_mesh, eval_mode, fresh_breaker, seeded_database
from evals.authored import AUTHORED_DIR
from evals.common import read_jsonl
from evals.egress import EgressBlocked, egress_guard
from evals.metrics import r4
from evals.stubs import StubMesh
from evals.suites import Target, target

SUITE_ID = "E-ORC"
NAME = "orchestration"
CASES = AUTHORED_DIR / "orchestration_cases.jsonl"
PERSONA = {"P1-base": "P1", "P2-base": "P2"}
AGENTS = ("coordinator", "ledger", "analyst", "forecaster", "advisor", "verifier")
# docs/09 §10 ORC-2: the six node types every case set must reach.
# docs/00 §5 / docs/06 §4: each agent's deterministic tools. A step calling a tool outside its
# agent's list fails ORC-3.
TOOL_ALLOW_LIST: dict[str, frozenset[str]] = {
    "coordinator": frozenset(
        {"route_table", "budget_guard", "load_snapshot", "answer_cache", "compose_response"}
    ),
    "ledger": frozenset(
        {
            "normalise_narration",
            "merchant_memory_lookup",
            "rule_categorise",
            "detect_transfer_pairs",
            "detect_duplicates",
            "transaction_page",
            "propose_format_profile",
        }
    ),
    "analyst": frozenset(
        {
            "detect_recurring",
            "category_trend",
            "detect_new_merchant_spike",
            "detect_price_change",
            "detect_duplicate_subscriptions",
            "list_findings",
        }
    ),
    "forecaster": frozenset({"build_forecast", "simulate", "goal_projection", "backtest"}),
    "advisor": frozenset({"simulate", "list_findings", "get_goal"}),
    "verifier": frozenset(
        {"verify_evidence_refs", "recompute_impact", "check_feasibility", "check_generic_advice"}
    ),
}
EVENT_ALIASES = {"daily_0630": "daily_refresh"}  # the case names the 06:30 cron slot
UNBUILT = {
    "ORC-11": "the scheduled digest (PRO-01/PRO-03) is not built: its graph nodes are slots",
    "ORC-14": "the PDF importer (Stage 4) is not built",
}


@dataclass
class CaseResult:
    case: str
    checks: list[str]
    status: str = "fail"  # pass | fail | not_recorded | not_measured
    assertions: dict[str, bool] = field(default_factory=dict)
    agents: list[str] = field(default_factory=list)
    steps: int = 0
    llm_calls: int = 0
    note: str = ""

    def finish(self) -> CaseResult:
        if self.status not in ("not_recorded", "not_measured"):
            self.status = "pass" if self.assertions and all(self.assertions.values()) else "fail"
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "case": self.case,
            "checks": self.checks,
            "status": self.status,
            "assertions": self.assertions,
            "agents": self.agents,
            "steps": self.steps,
            "llm_calls": self.llm_calls,
            "note": self.note,
        }


# --------------------------------------------------------------------------- run helpers


def _store(session: Any, persona: str) -> AgentStore:
    ws = demo_workspace(session, persona)
    if ws is None:
        raise LookupError(f"demo persona {persona} is not seeded")
    store = AgentStore(WorkspaceContext.open(session, ws.id))
    # Each case starts with no active advice, so an earlier case's approval is not a duplicate
    # (V-09) here; the earlier rows stay in the audit trail.
    for rec in store.ctx.all(m.Recommendation):
        if rec.status in ("approved", "accepted"):
            rec.status = "dismissed"
    session.commit()
    return store


def _invoked(steps: list[m.AgentStep]) -> list[str]:
    """Agents with at least one step that ran (a `skipped` slot is not an invocation)."""
    seen: list[str] = []
    for s in steps:
        if s.status != "skipped" and s.agent in AGENTS and s.agent not in seen:
            seen.append(s.agent)
    return seen


def _first_index(steps: list[m.AgentStep], agent: str) -> int | None:
    return next(
        (i for i, s in enumerate(steps) if s.agent == agent and s.status != "skipped"), None
    )


def _in_order(steps: list[m.AgentStep], agents: list[str]) -> bool:
    idx = [_first_index(steps, a) for a in agents]
    return all(i is not None for i in idx) and idx == sorted(idx)  # type: ignore[type-var]


def _record(result: CaseResult, store: AgentStore, run_id: str) -> list[m.AgentStep]:
    steps = store.steps(run_id)
    result.agents = _invoked(steps)
    result.steps = len(steps)
    result.llm_calls = sum(s.llm_calls for s in steps)
    return steps


def _common(
    result: CaseResult, case: dict[str, Any], store: AgentStore, out: RunOutcome
) -> list[m.AgentStep]:
    steps = _record(result, store, out.run_id)
    run = store.run(out.run_id)
    result.assertions["run_recorded"] = run is not None and run.status == "succeeded"
    result.assertions["min_steps"] = len(steps) >= int(case["min_steps"])
    result.assertions["expected_agents_invoked"] = set(case["expected_agents"]) <= set(
        result.agents
    )
    return steps


# --------------------------------------------------------------------------- case runners


def _system(case: dict[str, Any], session: Any, mesh: Any, result: CaseResult) -> None:
    store = _store(session, PERSONA[case["dataset"]])
    inputs = dict(case["input"])
    named = str(inputs.pop("event", "") or "import_committed")
    event = EVENT_ALIASES.get(named, named)
    if "buffer_minor" in inputs:  # a preference change (prefs_version_changed)
        store.ctx.workspace.buffer_minor = int(inputs.pop("buffer_minor"))
        session.commit()
    inputs.pop("import", None)  # the seeded demo already holds this export's rows
    workflow, route = SYSTEM_EVENTS[event], WORKFLOW_ROUTES[SYSTEM_EVENTS[event]]
    result.assertions["route_table_workflow"] = workflow == case["workflow"]
    out = run_workflow(
        store,
        workflow=workflow,
        trigger=case["trigger"],
        event=event,
        mesh=mesh,
        inputs={"as_of": case["as_of"]},
    )
    steps = _common(result, case, store, out)
    route_steps = [s for s in steps if s.node == "route_event"]
    result.assertions["routed_by_table_with_no_coordinator_llm_call"] = (
        len(route_steps) == 1
        and route_steps[0].llm_calls == 0
        and all(s.llm_calls == 0 for s in steps if s.agent == "coordinator")
    )
    planned = [r for r in route if r != "advice_loop"]
    ran = [s.node for s in steps]
    result.assertions["steps_follow_route_table"] = [n for n in ran if n in planned] == [
        n for n in planned if n in ran
    ]
    if "ORC-1" in case["checks"]:
        order = [a for a in AGENTS if a in case["expected_agents"]]
        result.assertions["agent_order"] = _in_order(steps, order)
    if case["terminal_state"] == "briefing_refreshed":
        # The briefing slot is reached; the briefing itself is PRO-01 (not built yet).
        result.assertions["briefing_step_reached"] = any(s.node == "briefing" for s in steps)


def _scenario(case: dict[str, Any], session: Any, mesh: Any, result: CaseResult) -> None:
    store = _store(session, PERSONA[case["dataset"]])
    text = case["input"]["scenario_text"]
    out = run_workflow(
        store,
        workflow="scenario",
        trigger="user",
        mesh=mesh,
        inputs={
            "as_of": case["as_of"],
            "user_message": text,
            # Lab free text goes straight to the Forecaster's parser (docs/05 §4.4).
            "intent": {"intent": "scenario", "standalone_question": text, "slots": {}},
        },
    )
    steps = _common(result, case, store, out)
    sim = [s for s in steps if s.node == "forecaster" and s.output.get("simulation_id")]
    result.assertions["forecaster_parsed_and_simulated"] = bool(sim)
    result.assertions["response_composed"] = any(s.node == "compose" for s in steps)


def _recommendation(case: dict[str, Any], session: Any, mesh: Any, result: CaseResult) -> None:
    store = _store(session, PERSONA[case["dataset"]])
    stub = (case.get("stubs") or {}).get("advisor")
    client: Any = StubMesh(mesh, advisor_mode=stub) if stub else mesh
    with session.begin_nested():
        forecast = run_forecast(store.ctx, as_of=date.fromisoformat(case["as_of"]))
    session.commit()
    out = run_workflow(
        store,
        workflow="recommendation",
        trigger="user",
        mesh=client,
        inputs={
            "as_of": case["as_of"],
            "forecast_id": forecast.calculation.id,
            # The `advice_needed` event: advice was asked for on the baseline forecast.
            "risk_flags": [{"kind": "advice_requested", "forecast_id": forecast.calculation.id}],
        },
    )
    steps = _common(result, case, store, out)
    recs = [r for r in store.ctx.all(m.Recommendation) if r.run_id == out.run_id]
    vers = [v for v in store.ctx.all(m.VerificationResult) if v.run_id == out.run_id]
    verdicts = [v.verdict for v in sorted(vers, key=lambda v: v.round)]
    if case["terminal_state"] == "approved":
        result.assertions["approved"] = any(r.status == "approved" for r in recs)
        if stub == "flawed_once":
            result.assertions["loop_looped_reject_then_approve"] = (
                "REJECT" in verdicts
                and verdicts[-1] == "APPROVE"
                and any(s.node == "revise" for s in steps)
            )
    if case["terminal_state"] == "withdrawn":
        result.assertions["withdrawn_after_two_revisions"] = (
            any(s.node == "withdraw" for s in steps)
            and sum(1 for s in steps if s.node == "revise") == 2
            and not any(r.status == "approved" for r in recs)
            and any(r.status == "withdrawn" for r in recs)
        )
    if stub:
        stubbed = [s for s in steps if s.node == "advise"]
        result.assertions["stub_labelled"] = all(s.model == "stub/advisor" for s in stubbed)


def _ask(
    case: dict[str, Any],
    session: Any,
    mesh: Any,
    result: CaseResult,
    *,
    budget: Budget | None = None,
) -> tuple[AgentStore, RunOutcome]:
    store = _store(session, PERSONA[case["dataset"]])
    thread = store.create_thread()
    session.commit()
    out = ask(
        store,
        thread_id=thread.id,
        text=case["input"]["question"],
        client_msg_id=uuid.uuid4().hex,
        mesh=mesh,
        budget=budget,
        as_of=case["as_of"],
    )
    return store, out


def _conversation(case: dict[str, Any], session: Any, mesh: Any, result: CaseResult) -> None:
    budget = None
    limits = (case.get("stubs") or {}).get("budget")
    if limits:
        budget = Budget(max_calls=int(limits["llm_calls"]))
    store, out = _ask(case, session, mesh, result, budget=budget)
    steps = _common(result, case, store, out)
    intent = (out.state.get("intent") or {}).get("intent")
    terminal = case["terminal_state"]
    if terminal == "clarify":
        result.assertions["clarifying_question"] = any(s.node == "clarify" for s in steps)
    elif terminal == "refused":
        result.assertions["refused"] = any(s.node == "refuse" for s in steps)
    elif terminal == "partial":
        audits = [e.action for e in store.ctx.all(m.AuditEvent) if e.run_id == out.run_id]
        result.assertions["partial_with_audit"] = (
            out.partial is True and "run_budget_exceeded" in audits
        )
        result.assertions["within_budget"] = result.llm_calls <= int(limits["llm_calls"])
        result.assertions["deterministic_answer_returned"] = out.response_id is not None
    else:
        result.assertions["answer_stored"] = out.response_id is not None
    if "ORC-9" in case["checks"] and terminal == "response":
        result.assertions["intent_affordability"] = intent == "affordability"
        sim = [s for s in steps if s.node == "forecaster" and s.output.get("simulation_id")]
        result.assertions["forecaster_parsed_and_simulated"] = bool(sim)
        body = store.response(out.response_id).body if out.response_id else {}  # type: ignore[union-attr]
        result.assertions["scenario_comparison_in_answer"] = any(
            b.get("type") == "ScenarioComparison" for b in (body or {}).get("blocks", [])
        )


def _scripted_mesh(mode: str) -> tuple[MeshClient, Any]:
    """A Mesh client on a scripted transport (no network) for the fault-injection cases."""
    from tests.unit.mesh.fakes import (
        ScriptedCompletions,
        client,
        json_ok,
        service_unavailable,
        settings,
    )

    understand = {
        "standalone_question": "Where does my money go?",
        "intent": "spending_breakdown",
        "slots": {},
        "needs_forecast": False,
        "needs_advice": False,
        "confidence": 0.93,
        "out_of_scope": False,
        "injection_suspected": False,
    }
    if mode == "503_once":
        fake = ScriptedCompletions(service_unavailable(), json_ok(understand), default=json_ok({}))
    else:  # malformed_json_twice: the Understand output stays invalid after the one repair
        fake = ScriptedCompletions(
            json_ok({"not": "an intent"}), json_ok({"still": "wrong"}), default=json_ok({})
        )
    # The scripted transport answers every call: never the cassette store, whatever the
    # environment's MESH_CASSETTE_MODE (the full eval run sets replay).
    return client(fake, settings=settings(mesh_cassette_mode="live")), fake


def _fault(case: dict[str, Any], session: Any, result: CaseResult) -> None:
    mode = case["stubs"]["mesh"]
    mesh, _ = _scripted_mesh(mode)
    store, out = _ask(case, session, mesh, result)
    steps = _common(result, case, store, out)
    understand = next((s for s in steps if s.node == "understand"), None)
    result.note = "scripted transport (fault injection)"
    if mode == "503_once":
        result.assertions["retried_then_succeeded"] = (
            understand is not None and understand.status in ("ok", "retried")
            and understand.attempt == 2
        )  # fmt: skip
    else:
        result.assertions["one_repair_then_degraded"] = (
            understand is not None and understand.llm_calls == 2 and understand.status == "failed"
        )
    body = store.response(out.response_id).body if out.response_id else {}  # type: ignore[union-attr]
    blocks = (body or {}).get("blocks", [])
    result.assertions["run_completed_with_an_answer"] = bool(blocks)
    if mode != "503_once":
        result.assertions["narrative_fallback"] = bool(blocks) and blocks[0].get("type") == (
            "Narrative"
        )
    # The case's expected agents assume the specialist ran; with a degraded Understand the
    # route is the fallback one, so this case asserts the fault handling, not the agent set.
    result.assertions.pop("expected_agents_invoked", None)


def _snapshot(case: dict[str, Any], session: Any, result: CaseResult) -> None:
    store = _store(session, PERSONA[case["dataset"]])
    latest = next(
        iter(sorted(store.ctx.all(m.AgentResponse), key=lambda r: r.created_at, reverse=True)),
        None,
    )
    if latest is None:
        result.status = "not_measured"
        result.note = "no stored answer to reopen (earlier cases were not recorded)"
        return
    before = store.step_count()
    reopened = store.response(latest.id)
    result.assertions["snapshot_reloaded"] = reopened is not None and reopened.body == latest.body
    result.assertions["zero_agent_steps"] = store.step_count() == before


def _egress(case: dict[str, Any], session: Any, mesh: Any, result: CaseResult) -> None:
    result.assertions["tracing_off"] = all(
        os.environ.get(v, "false").lower() == "false"
        for v in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")
    )
    with egress_guard() as blocked:
        _system(case, session, mesh, result)
        result.assertions["full_run_inside_guard"] = result.assertions.get("run_recorded", False)
        result.assertions["no_blocked_attempts_in_normal_run"] = blocked == []

        def leak(state: ForesightState, ctx: RunContext) -> NodeOutput:
            socket.create_connection(("example.org", 443), timeout=2)
            return NodeOutput()

        store = _store(session, PERSONA[case["dataset"]])
        injected = {"briefing": NodeSpec("briefing", "coordinator", "tool", leak, "Leak")}
        try:
            run_workflow(
                store,
                workflow="ingestion",
                trigger="event",
                event="import_committed",
                mesh=mesh,
                nodes=injected,
                inputs={"as_of": case["as_of"]},
            )
            failed = False
        except EgressBlocked:
            failed = True
        result.assertions["other_host_fails_the_run"] = failed and any(
            b.startswith("example.org") for b in blocked
        )


def _format_profile(case: dict[str, Any], session: Any, mesh: Any, result: CaseResult) -> None:
    from backend.agents import ledger_nodes as ln
    from backend.pipeline.ingest import ingest_file
    from backend.storage.ids import new_id
    from evals.common import load_dataset

    ctx = create_workspace(
        session, name="ORC-15", country="GB", home_currency="GBP", locale="en-GB",
        timezone_name="Europe/London",
    )  # fmt: skip
    acct = m.Account(id=new_id("acct"), name="Current account", currency="GBP")
    ctx.add(acct)
    session.commit()
    store = AgentStore(ctx)
    ds = load_dataset(case["dataset"])
    file = next(iter(ds.layout))
    data = ds.file_bytes(file)
    first = ingest_file(ctx, "statement.csv", data, account_id=acct.id)
    result.assertions["needs_user_input"] = first.status == "needs_review"
    run = ln.propose_format_profiles(store, mesh, "statement.csv", data)
    steps = store.steps(run.run_id or "") if run.run_id else []
    result.agents = _invoked(steps)
    result.steps = len(steps)
    result.llm_calls = sum(s.llm_calls for s in steps)
    proposal = run.proposals[0] if run.proposals else None
    result.assertions["ledger_proposed_profile"] = (
        proposal is not None and proposal.profile is not None and not proposal.problems
        and [s.agent for s in steps] == ["ledger"]
    )  # fmt: skip
    if proposal is None or proposal.profile is None:
        return
    ln.confirm_format_profile(ctx, proposal.profile)
    second = ingest_file(ctx, "statement.csv", data, account_id=acct.id,
                         answers={"date_order": "DMY"})  # fmt: skip
    result.assertions["committed_after_confirmation"] = second.status == "committed"
    again = ln.propose_format_profiles(store, mesh, "again.csv", data)
    result.assertions["reused_with_no_model_call"] = not again.needed and again.proposals == []


# --------------------------------------------------------------------------- the suite


def _run_case(case: dict[str, Any], factory: Any, mesh: Any) -> CaseResult:
    result = CaseResult(case=case["id"], checks=list(case["checks"]))
    unbuilt = [UNBUILT[c] for c in case["checks"] if c in UNBUILT]
    if unbuilt or case.get("stage", 2) > 2:
        result.status = "not_measured"
        result.note = "; ".join(unbuilt) or f"stage {case['stage']} case"
        return result
    fresh_breaker(mesh)
    with factory() as session:
        try:
            if "ORC-13" in case["checks"]:
                _egress(case, session, mesh, result)
            elif "ORC-15" in case["checks"]:
                _format_profile(case, session, mesh, result)
            elif "ORC-12" in case["checks"]:
                _snapshot(case, session, result)
            elif (case.get("stubs") or {}).get("mesh"):
                _fault(case, session, result)
            elif case["workflow"] in ("ingestion", "risk_detection"):
                _system(case, session, mesh, result)
            elif case["workflow"] == "scenario":
                _scenario(case, session, mesh, result)
            elif case["workflow"] == "recommendation":
                _recommendation(case, session, mesh, result)
            else:
                _conversation(case, session, mesh, result)
        except CassetteMiss as miss:
            session.rollback()
            result.status = "not_recorded"
            result.note = f"no cassette: {str(miss)[:120]}"
        except Exception as exc:  # noqa: BLE001 - one broken case must not hide the others
            session.rollback()
            result.status = "fail"
            result.assertions["ran_without_error"] = False
            result.note = f"{type(exc).__name__}: {str(exc)[:200]}"
            return result
    return result.finish()


def _distinctness(factory: Any, run_ids: list[str]) -> tuple[dict[str, Any], bool | None]:
    """ORC-3: each LLM agent uses its own prompts, and every tool call is on its agent's list."""
    prompts: dict[str, set[str]] = {}
    outside: list[str] = []
    with factory() as session:
        steps = [s for s in session.query(m.AgentStep).all() if s.run_id in set(run_ids)]
    for s in steps:
        if s.kind == "llm" and s.prompt_version and s.llm_calls:
            prompts.setdefault(s.agent, set()).add(s.prompt_version)
        for call in s.tool_calls or []:
            name = str(call.get("name"))
            if name not in TOOL_ALLOW_LIST.get(s.agent, frozenset()):
                outside.append(f"{s.agent}:{name}")
    agents = sorted(prompts)
    shared = [
        f"{a}/{b}" for i, a in enumerate(agents) for b in agents[i + 1 :] if prompts[a] & prompts[b]
    ]
    nodes = default_nodes()
    registry_ok = all(
        s.agent == nodes[s.node].agent for s in steps if s.node in nodes and s.node != "briefing"
    )
    detail = {
        "prompt_versions_per_agent": {a: sorted(v) for a, v in prompts.items()},
        "prompts_shared_between_agents": shared,
        "tool_calls_outside_allow_list": sorted(set(outside)),
        "steps_attributed_to_their_registered_agent": registry_ok,
    }
    if not steps:
        return detail, None
    return detail, not shared and not outside and registry_ok


def run(fast: bool = False) -> dict[str, Any]:
    cases = read_jsonl(CASES)
    if fast:
        cases = cases[:6]
    started = time.monotonic()
    mesh = eval_mesh()
    results: list[CaseResult] = []
    with seeded_database() as factory:
        if factory is None:
            return {
                "metrics": {"mode": eval_mode(), "cases": "not measured: needs DATABASE_URL"},
                "targets": [
                    target("ORC-pass", "Case pass rate", None, ">=", 1.0, "30 cases"),
                    target("ORC-2", "All six node types reached", None, "==", 1, "30 cases"),
                    target(
                        "ORC-3",
                        "Agents distinct (prompts, tool allow-lists)",
                        None,
                        "==",
                        1,
                        "30 cases",
                    ),
                ],  # fmt: skip
                "notes": ["E-ORC needs DATABASE_URL (PostgreSQL); not measured."],
            }
        # ORC-12 reopens an answer stored by an earlier case: run it last.
        ordered = sorted(cases, key=lambda c: "ORC-12" in c["checks"])
        results = [_run_case(c, factory, mesh) for c in ordered]
        with factory() as session:
            run_ids = [r.id for r in session.query(m.AgentRun).all()]
        distinct_detail, distinct_ok = _distinctness(factory, run_ids)
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    measured = [r for r in results if r.status in ("pass", "fail")]
    coverage = {a: sum(1 for r in results if a in r.agents) for a in AGENTS}
    reached = all(coverage[a] >= 1 for a in AGENTS) if measured else None
    pass_rate = r4(sum(r.status == "pass" for r in measured) / len(measured)) if measured else None
    metrics = {
        "mode": eval_mode(),
        "case_count": len(results),
        "by_status": by_status,
        "case_pass_rate_measured": pass_rate,
        "agent_coverage": coverage,
        "distinctness": distinct_detail,
        "detail": [r.as_dict() for r in results],
        "seconds": round(time.monotonic() - started, 1),
    }
    not_recorded = by_status.get("not_recorded", 0)
    # A case not recorded or not built is not a pass: the rate over all cases counts them as
    # unmet, so the gate cannot pass while any applicable case is missing.
    all_rate = r4(sum(r.status == "pass" for r in results) / len(results)) if results else None
    targets: list[Target] = [
        target("ORC-pass", "Case pass rate (all 30; not recorded or not built count as unmet)",
               all_rate, ">=", 1.0, f"{len(results)} cases"),
        target("ORC-pass-measured", "Case pass rate (cases that ran)", pass_rate, ">=", 1.0,
               f"{len(measured)} cases"),
        target("ORC-2", "All six node types reached", None if reached is None else int(reached),
               "==", 1, "coverage table"),
        target("ORC-3", "Agents distinct (prompts, tool allow-lists)",
               None if distinct_ok is None else int(distinct_ok), "==", 1, "all runs"),
    ]  # fmt: skip
    notes = [
        f"{eval_mode()} mode; {not_recorded} case(s) not recorded, "
        f"{by_status.get('not_measured', 0)} not measured (feature not built).",
        "ORC-4/5 stub only the Advisor (steps carry the model `stub/advisor`); the Verifier, its "
        "judge and everything else are real. ORC-6/7 run on a scripted transport.",
        "Ingestion cases run on the seeded demo (the export named in the case is already "
        "imported); the Home briefing slot is reached but the briefing is PRO-01 (not built).",
        "`daily_0630` is the 06:30 cron slot, routed as the `daily_refresh` system event.",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}


__all__: list[str] = ["NAME", "SUITE_ID", "run"]
