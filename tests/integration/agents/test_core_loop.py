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
        yield AgentStore(WorkspaceContext.open(session, ws.id))


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
