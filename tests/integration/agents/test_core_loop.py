"""The core loop on the seeded P1 demo through the real graph (docs/06 W4; docs/09 ORC-4, ORC-5).

Real nodes: Forecaster (baseline forecast from stored data), risk check, Advisor, Verifier
(deterministic rules + judge). Only the Analyst is a no-op stand-in, and Mesh is scripted: the
scripted Advisor reads the figures it was sent, so its claims are whatever the code would accept
or reject on the real data.

- ORC-4: an injected infeasible draft (a cap far below the usual level) is rejected by V-04
  without a judge call; the revision passes the rules and the judge; the recommendation is
  approved after one revision, and both rounds are stored.
- ORC-5: an Advisor that keeps proposing the infeasible cap is stopped after two revisions and
  the recommendation is withdrawn; nothing is approved.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from backend.agents.runner import run_workflow
from backend.agents.runtime import NodeOutput, NodeSpec, RunContext
from backend.agents.state import ForesightState
from backend.pipeline.seed_demo import seed_all
from backend.storage import models as m
from backend.storage.agent_repo import AgentStore
from backend.storage.repositories import WorkspaceContext, demo_workspace
from tests.unit.mesh.fakes import ScriptedCompletions, client, json_ok

pytestmark = pytest.mark.postgres

CATEGORY = "food.delivery"


@pytest.fixture(scope="module")
def seeded(migrated_engine: Engine) -> Engine:
    with sessionmaker(bind=migrated_engine, expire_on_commit=False)() as session:
        seed_all(session)
    return migrated_engine


@pytest.fixture
def p1(seeded: Engine) -> Iterator[AgentStore]:
    with sessionmaker(bind=seeded, expire_on_commit=False)() as session:
        ws = demo_workspace(session, "P1")
        assert ws is not None
        store = AgentStore(WorkspaceContext.open(session, ws.id))
        # Each test starts with no active advice (V-09 would treat an earlier test's approval
        # as a duplicate).
        for rec in store.ctx.all(m.Recommendation):
            if rec.status in ("approved", "accepted"):
                rec.status = "dismissed"
        session.commit()
        yield store


def _no_analyst(state: ForesightState, ctx: RunContext) -> NodeOutput:
    return NodeOutput(update={"findings": []}, label="Analysing spending patterns")


STAND_INS = {"analyst": NodeSpec("analyst", "analyst", "tool", _no_analyst, "Analysing")}


def _data(kwargs: dict[str, Any]) -> dict[str, Any]:
    user = [msg for msg in kwargs["messages"] if msg["role"] == "user"][0]
    # Known issue: backend.mesh.redact masks bare 6+ digit figures in the JSON text as REF
    # (unquoted); a real model reads past it, so the scripted Advisor does too.
    text = re.sub(r"(?<=: )REF(?=[,}\]])", "null", user["content"])
    return dict(json.loads(text)["data"])


def _proposal(data: dict[str, Any], *, feasible: bool) -> dict[str, Any]:
    row = next(r for r in data["spending"] if r["category_key"] == CATEGORY)
    cap = int(row["median_3x30_minor"] * 0.8) if feasible else int(row["median_3x30_minor"] * 0.2)
    return {
        "proposal_id": "prp_delivery",
        "action": "cap_category",
        "currency": data["currency"],
        "params": {"category_key": CATEGORY, "monthly_cap_minor": cap},
        "title": "Keep food delivery under {{cap}} a month",
        "rationale": "Food delivery is above its usual level before payday; a cap of {{cap}} "
        "a month keeps the lowest balance nearer your buffer.",
        "trigger_refs": [{"kind": "forecast", "id": data["forecast"]["id"], "role": "trigger"}],
        "expected_direction": "improves_buffer",
        "claimed_monthly_impact_minor": max(0, row["last_30d_minor"] - cap),
    }


def advisor(*, feasible: bool) -> Callable[[dict[str, Any]], Any]:
    def step(kwargs: dict[str, Any]) -> Any:
        return json_ok({"proposals": [_proposal(_data(kwargs), feasible=feasible)]})

    return step


JUDGE_PASS = json_ok(
    {
        "criteria": [
            {"rule": rule, "passed": True, "reason": "fine"}
            for rule in ("V-11", "V-12", "V-13", "V-14")
        ]
    }
)


def _run(store: AgentStore, *steps: Any) -> Any:
    completions = ScriptedCompletions(*steps)
    out = run_workflow(
        store,
        workflow="risk_detection",
        trigger="event",
        event="data_version_changed",
        mesh=client(completions),
        nodes=STAND_INS,
    )
    return out, completions


def test_orc4_bad_draft_rejected_then_revised_and_approved(p1: AgentStore) -> None:
    out, completions = _run(p1, advisor(feasible=False), advisor(feasible=True), JUDGE_PASS)
    steps = p1.steps(out.run_id)
    nodes = [s.node for s in steps]
    assert nodes.count("advise") == 2
    assert nodes.count("verify") == 2
    assert nodes.count("revise") == 1
    assert "withdraw" not in nodes
    # The rejected round never reached the judge: 2 Advisor calls + 1 judge call.
    assert len(completions.calls) == 3
    verify_steps = [s for s in steps if s.node == "verify"]
    assert verify_steps[0].label.startswith("Verifier rejected")
    assert verify_steps[1].label == "Checked: recommendation approved"
    assert verify_steps[1].model
    assert verify_steps[1].tier == "verifier"

    recs = [r for r in p1.ctx.all(m.Recommendation) if r.run_id == out.run_id]
    assert len(recs) == 1
    rec = recs[0]
    assert rec.status == "approved"
    assert rec.revision_count == 1
    rounds = p1.verifications(rec.id)
    assert [v.round for v in rounds] == [1, 2]
    assert [v.verdict for v in rounds] == ["REJECT", "APPROVE"]
    failed = [r["rule"] for r in rounds[0].rule_results if not r["passed"]]
    assert any(rule.startswith("V-04") for rule in failed)
    assert out.state["approved_recs"] == [rec.id]
    # The approved recommendation carries a hydrated card for the composer: server-filled text.
    card = rec.proposal["card"]
    assert card["recommendation_id"] == rec.id
    assert "{{" not in card["title"]
    assert "£" in card["title"]
    assert card["verification"]["revisions"] == 1
    assert card["impact"]["monthly_saving"]["minor"] > 0


def test_orc5_permanently_bad_advisor_is_withdrawn_after_two_revisions(p1: AgentStore) -> None:
    bad = advisor(feasible=False)
    out, completions = _run(p1, bad, bad, bad)
    nodes = [s.node for s in p1.steps(out.run_id)]
    assert nodes.count("verify") == 3  # initial + 2 revisions
    assert nodes.count("revise") == 2
    assert nodes.count("withdraw") == 1
    assert len(completions.calls) == 3  # Advisor only: no draft reached the judge
    recs = [r for r in p1.ctx.all(m.Recommendation) if r.run_id == out.run_id]
    assert [r.status for r in recs] == ["withdrawn"]
    assert [v.verdict for v in p1.verifications(recs[0].id)] == ["REJECT"] * 3
    assert not out.state.get("approved_recs")


def test_a_rejected_draft_after_the_deadline_withdraws_instead_of_looping(p1: AgentStore) -> None:
    """Regression: once the run deadline passes every node is skipped, so a rejected draft must
    leave the loop (it used to cycle advise → verify → revise until LangGraph's recursion limit)."""
    start = datetime.now(timezone.utc)
    late = {"now": False}

    def clock() -> datetime:
        return start + (timedelta(hours=1) if late["now"] else timedelta())

    def advise(state: ForesightState, ctx: RunContext) -> NodeOutput:
        return NodeOutput(update={"proposals": [{"proposal_key": "p1"}]})

    def verify(state: ForesightState, ctx: RunContext) -> NodeOutput:
        late["now"] = True  # the deadline passes while the first draft is being checked
        return NodeOutput(update={"verdict": "reject", "proposals": [{"proposal_key": "p1"}]})

    def risk(state: ForesightState, ctx: RunContext) -> NodeOutput:
        return NodeOutput(update={"risk_flags": [{"kind": "buffer_breach"}]})

    out = run_workflow(
        p1,
        workflow="risk_detection",
        trigger="event",
        event="data_version_changed",
        nodes={
            **STAND_INS,
            "advise": NodeSpec("advise", "advisor", "llm", advise, "Drafting"),
            "verify": NodeSpec("verify", "verifier", "llm", verify, "Checking"),
            "risk_check": NodeSpec("risk_check", "forecaster", "tool", risk, "Risks"),
        },
        clock=clock,
    )
    nodes = [s.node for s in p1.steps(out.run_id)]
    # One skipped revision round (the deadline is noticed by the next node), then withdraw.
    assert nodes.count("verify") == 2
    assert nodes.count("revise") == 1
    assert nodes.count("withdraw") == 1
    assert len(nodes) < 20
    assert out.partial is True


# --------------------------------------------------------------------- 14 Oct fixes (P1 live run)


def test_seed_persists_deterministic_findings_the_question_route_can_see(p1: AgentStore) -> None:
    from backend.agents.core_loop import world_from_store

    rows = [f for f in p1.ctx.all(m.Finding) if f.status in ("candidate", "open")]
    kinds = {(f.kind, (f.subject or {}).get("category_key")) for f in rows}
    assert ("category_spike", "food.delivery") in kinds
    ctx = RunContext(store=p1, run_id="run_x", workflow="conversation",
                     deadline_at=datetime.now(timezone.utc) + timedelta(minutes=1))  # fmt: skip
    world = world_from_store(ctx, {}, None)
    spike = next(f for f in world.findings.values() if f.subject == "food.delivery")
    assert spike.finding_type == "category_spike"
    assert "{{" not in spike.summary


def _calc_ref_advisor(*, real: bool) -> Callable[[dict[str, Any]], Any]:
    def step(kwargs: dict[str, Any]) -> Any:
        data = _data(kwargs)
        p = _proposal(data, feasible=True)
        rid = data["forecast"]["id"] if real else "calc_000000000000000000000000"
        p["trigger_refs"] = [{"kind": "calculation", "id": rid, "role": "trigger"}]
        return json_ok({"proposals": [p]})

    return step


def test_a_forecast_cited_as_calculation_is_normalised_from_the_store(p1: AgentStore) -> None:
    out, completions = _run(p1, _calc_ref_advisor(real=True), JUDGE_PASS)
    recs = [r for r in p1.ctx.all(m.Recommendation) if r.run_id == out.run_id]
    assert [r.status for r in recs] == ["approved"]
    assert len(completions.calls) == 2  # Advisor + judge: V-02 passed after normalisation


def test_a_calc_ref_the_store_does_not_have_is_still_rejected(p1: AgentStore) -> None:
    bad = _calc_ref_advisor(real=False)
    out, _ = _run(p1, bad, bad, bad)
    recs = [r for r in p1.ctx.all(m.Recommendation) if r.run_id == out.run_id]
    rounds = p1.verifications(recs[0].id)
    failed = {r["rule"].split("@")[0] for r in rounds[0].rule_results if not r["passed"]}
    assert {"V-01", "V-02"} <= failed
    assert recs[0].status == "withdrawn"


UNDERSTAND = json_ok(
    {
        "standalone_question": "My car needs a £650 repair on 14 October. Will I be OK?",
        "intent": "affordability",
        "slots": {"amount_minor": 65000, "date": "2026-10-14", "case": "deadline"},
        "needs_forecast": True,
        "needs_advice": True,
        "confidence": 0.95,
        "out_of_scope": False,
        "injection_suspected": False,
    }
)
PARSE = json_ok(
    {
        "status": "parsed",
        "spec": {
            "schema": "scenario_spec/1",
            "name": "Car repair",
            "currency": "GBP",
            "scope": "mine",
            "modifiers": [
                {"type": "one_off_outflow", "date": "2026-10-14", "amount_minor": 65000,
                 "label": "Car repair"}
            ],
        },
    }
)  # fmt: skip


def test_deadline_still_ends_with_a_deterministic_answer(p1: AgentStore) -> None:
    from backend.agents import core_loop
    from backend.agents.compose import NOT_CHECKED_IN_TIME
    from backend.agents.runner import ask

    start = datetime.now(timezone.utc)
    late = {"now": False}

    def clock() -> datetime:
        return start + (timedelta(hours=1) if late["now"] else timedelta())

    def verify_then_late(state: ForesightState, ctx: RunContext) -> NodeOutput:
        out = core_loop.verify_node(state, ctx)
        late["now"] = True  # the deadline passes during the first Verifier round
        return out

    completions = ScriptedCompletions(UNDERSTAND, PARSE, advisor(feasible=False))
    thread = p1.create_thread()
    p1.session.commit()
    out = ask(
        p1,
        thread_id=thread.id,
        text="My car needs a £650 repair on 14 October. Will I be OK before payday?",
        client_msg_id="deadline-1",
        mesh=client(completions),
        nodes={"verify": NodeSpec("verify", "verifier", "llm", verify_then_late, "Checking")},
        clock=clock,
    )
    assert out.response_id is not None
    assert out.partial is True
    assert len(completions.calls) == 3  # no compose call after the deadline
    body = p1.response(out.response_id).body  # type: ignore[union-attr]
    assert NOT_CHECKED_IN_TIME in json.dumps(body)
    steps = {s.node: s for s in p1.steps(out.run_id)}
    assert steps["compose"].status == "ok"
    assert steps["compose"].llm_calls == 0
    assert steps["withdraw"].output["reason"] == "deadline"
    recs = [r for r in p1.ctx.all(m.Recommendation) if r.run_id == out.run_id]
    assert [r.status for r in recs] == ["withdrawn"]
    audit = [
        e for e in p1.ctx.all(m.AuditEvent)
        if e.action == "recommendation_withdrawn" and e.subject_id == recs[0].id
    ]  # fmt: skip
    assert audit
    assert audit[0].after["reason"] == "deadline"


def _two(data: dict[str, Any], first: dict[str, Any], second: dict[str, Any]) -> Any:
    return json_ok({"proposals": [first, second]})


def _cap(data: dict[str, Any], category: str, share: float, pid: str) -> dict[str, Any]:
    row = next(r for r in data["spending"] if r["category_key"] == category)
    cap = int(row["median_3x30_minor"] * share)
    p = _proposal(data, feasible=True)
    p.update(
        proposal_id=pid,
        params={"category_key": category, "monthly_cap_minor": cap},
        title=f"Keep {category.split('.')[-1].replace('_', ' ')} under {{{{cap}}}} a month",
        claimed_monthly_impact_minor=max(0, row["last_30d_minor"] - cap),
    )
    return p


def test_a_revision_that_repeats_approved_advice_is_withdrawn_as_a_duplicate(
    p1: AgentStore,
) -> None:
    def round1(kwargs: dict[str, Any]) -> Any:
        d = _data(kwargs)
        return _two(d, _cap(d, CATEGORY, 0.8, "delivery"), _cap(d, "food.eating_out", 0.2, "out"))

    def round2(kwargs: dict[str, Any]) -> Any:
        d = _data(kwargs)
        return _two(d, _cap(d, CATEGORY, 0.8, "delivery"), _cap(d, "food.eating_out", 0.8, "out"))

    out, completions = _run(p1, round1, JUDGE_PASS, round2, JUDGE_PASS)
    recs = sorted(
        (r for r in p1.ctx.all(m.Recommendation) if r.run_id == out.run_id),
        key=lambda r: r.created_at,
    )
    statuses = [(r.proposal["params"]["category_key"], r.status) for r in recs]
    assert statuses.count((CATEGORY, "approved")) == 1
    assert (CATEGORY, "withdrawn") in statuses
    assert ("food.eating_out", "approved") in statuses
    assert len(completions.calls) == 4  # the duplicate never reached the judge


def test_drafts_unchecked_at_the_deadline_are_withdrawn(p1: AgentStore) -> None:
    from backend.agents import core_loop

    start = datetime.now(timezone.utc)
    late = {"now": False}
    calls = {"advise": 0}

    def clock() -> datetime:
        return start + (timedelta(hours=1) if late["now"] else timedelta())

    def advise_then_late(state: ForesightState, ctx: RunContext) -> NodeOutput:
        out = core_loop.advise_node(state, ctx)
        calls["advise"] += 1
        late["now"] = calls["advise"] == 2  # time runs out while round 2 is drafted
        return out

    bad = advisor(feasible=False)
    out = run_workflow(
        p1,
        workflow="risk_detection",
        trigger="event",
        event="data_version_changed",
        mesh=client(ScriptedCompletions(bad, bad)),
        nodes={**STAND_INS,
               "advise": NodeSpec("advise", "advisor", "llm", advise_then_late, "Drafting")},
        clock=clock,
    )  # fmt: skip
    steps = p1.steps(out.run_id)
    assert [s.node for s in steps].count("withdraw") == 1
    recs = [r for r in p1.ctx.all(m.Recommendation) if r.run_id == out.run_id]
    assert recs
    assert {r.status for r in recs} == {"withdrawn"}
