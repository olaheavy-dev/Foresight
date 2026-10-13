"""Advisor model trial: the P1 canonical case through the real graph with one arm's models.

Usage: python -m evals.advisor_trial_p1 <unused> <arm>. Adapted from the P1 canonical script.

Writes evals/results/<UTC>_p1_canonical/live_traces/p1_car_repair.{json,md}: steps, the
recommendation's Verifier rounds and the cost, from the stored AgentRun/AgentStep rows. P1 is a
synthetic persona; workspace and run IDs are replaced by stable labels.
"""

import json
import os
import sys
from datetime import datetime, timezone

from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.agents.runner import ask
from backend.pipeline.seed_demo import seed_all
from backend.storage import models as m
from backend.storage.agent_repo import AgentStore
from backend.storage.repositories import WorkspaceContext, demo_workspace
from evals.advisor_trial import RUN_DIR, _mesh_for
from tests.integration.storage.disposable import alembic_config

QUESTION = (
    "My car needs a £650 repair on 14 October. Will I be OK before payday, and what should I do?"
)
url = os.environ["DATABASE_URL"]
command.upgrade(alembic_config(url), "head")
engine = create_engine(url)
with sessionmaker(bind=engine, expire_on_commit=False)() as session:
    seed_all(session)
    ws = demo_workspace(session, "P1")
    assert ws is not None
    store = AgentStore(WorkspaceContext.open(session, ws.id))
    thread = store.create_thread()
    session.commit()
    arm = sys.argv[2]
    mesh = _mesh_for(arm, "record")
    assert mesh is not None
    out = ask(store, thread_id=thread.id, text=QUESTION, client_msg_id="p1-canonical", mesh=mesh)
    steps = [
        {
            "seq": s.seq,
            "node": s.node,
            "agent": s.agent,
            "status": s.status,
            "label": s.label,
            "model": s.model,
            "llm_calls": s.llm_calls,
            "tokens_in": s.tokens_in,
            "tokens_out": s.tokens_out,
            "cost_estimate_usd": s.cost_estimate_usd,
            "latency_ms": s.latency_ms,
        }
        for s in store.steps(out.run_id)
    ]
    recs = []
    for rec in store.ctx.all(m.Recommendation):
        if rec.run_id != out.run_id:
            continue
        recs.append(
            {
                "status": rec.status,
                "revisions": rec.revision_count,
                "final": {k: rec.proposal.get(k) for k in ("action", "params", "title")},
                "rounds": [
                    {
                        "round": v.round,
                        "verdict": v.verdict,
                        "failed": [r["rule"] for r in v.rule_results if not r["passed"]],
                        "critique": v.critique,
                    }
                    for v in store.verifications(rec.id)
                ],
            }
        )
    answer_blocks = []
    if out.response_id:
        body = store.response(out.response_id).body
        for blk in body.get("blocks", []):
            item = {
                "type": blk["type"],
                "where": blk.get("placement", {}).get("slot")
                or blk.get("placement", {}).get("tab"),
            }
            if blk["type"] == "InterventionCard":
                item.update(
                    title=blk["title"],
                    status=blk["status"],
                    verification=blk["verification"],
                    monthly_saving=(blk["impact"].get("monthly_saving") or {}).get("display"),
                    p_breach=[
                        blk["impact"]["p_breach_before"]["display"],
                        blk["impact"]["p_breach_after"]["display"],
                    ],
                    low_deltas=[
                        (d["cycle_label"], d["before"]["display"], d["after"]["display"])
                        for d in blk["impact"].get("low_deltas", [])
                    ],
                )
            elif blk["type"] == "Narrative":
                item["text"] = " ".join(
                    x.get("text", "") for x in blk.get("segments", []) if x.get("kind") == "text"
                )
            answer_blocks.append(item)
        evidence = body.get("evidence_line") or body.get("evidence")
        answer_blocks.append({"evidence_line": evidence})
    cost = store.run_cost(out.run_id)
    run = store.run(out.run_id)
    assert run is not None
    trace = {
        "persona": "P1-base (synthetic)",
        "question": QUESTION,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run": {"status": run.status, "partial": run.partial, "answered": bool(out.response_id)},
        "steps": steps,
        "recommendations": recs,
        "answer": answer_blocks,
        "cost": {
            "model_calls": cost.model_calls,
            "tokens": cost.tokens,
            "usd_estimate": cost.usd_estimate,
        },
    }
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
folder = RUN_DIR / f"p1_arm_{sys.argv[2]}"
folder.mkdir(parents=True, exist_ok=True)
(folder / "p1_car_repair.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False) + "\n")
lines = [
    f"# P1 canonical live run ({trace['recorded_at']})",
    "",
    f"Question: {QUESTION}",
    "",
    f"Run: {trace['run']}",
    "",
    "| # | Node | Status | Label | Model | Calls |",
    "|---|---|---|---|---|---|",
]
lines += [
    f"| {s['seq']} | {s['node']} | {s['status']} | {s['label']} | {s['model'] or ''} | "
    f"{s['llm_calls']} |"
    for s in steps
]
for r in recs:
    lines += [
        "",
        f"Recommendation: {r['status']} after {r['revisions']} revision(s): "
        f"{r['final']['title']}",
    ]
    lines += [f"- round {x['round']}: {x['verdict']} {x['failed']}" for x in r["rounds"]]
lines += ["", "Answer blocks:"] + [
    f"- {json.dumps(b, ensure_ascii=False)}" for b in trace["answer"]
]
lines += ["", f"Cost: {trace['cost']}"]
(folder / "p1_car_repair.md").write_text("\n".join(lines) + "\n")
print(folder)
print("\n".join(lines))
