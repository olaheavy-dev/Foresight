"""E-UI: generated UI quality (docs/09 §10a) over `ui_questions.jsonl` (40 questions + 20
paraphrases).

- UI-8 (intent accuracy, clarification on low confidence) runs the real Understand step, replayed
  from cassettes; no database needed.
- UI-1, UI-2, UI-7, UI-9, UI-10 need whole answers: with `DATABASE_URL` set, every question is
  asked on a disposable database seeded with the demo personas, through the real graph (whatever
  specialist nodes exist), and the stored `agent_response/1` snapshots are scored. Without a
  database those checks are "not measured".
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.agents.runner import ask
from backend.app.ui_contracts.response import AgentResponse
from backend.app.ui_contracts.validation import check_skeleton, visible_tabs
from backend.mesh.cassettes import CassetteMiss
from backend.storage.agent_repo import AgentStore
from backend.storage.repositories import WorkspaceContext, demo_workspace
from evals.assistant import NotRecorded, eval_mesh, eval_mode, seeded_database, understand
from evals.authored import AUTHORED_DIR
from evals.common import read_jsonl
from evals.metrics import r4
from evals.suites import Target, target

SUITE_ID = "E-UI"
NAME = "ui"
CASES = AUTHORED_DIR / "ui_questions.jsonl"
DEV_CASES = AUTHORED_DIR / "ui_questions_dev.jsonl"  # the only set tuning may look at
PERSONA = {"P1-base": "P1", "P2-base": "P2"}


def _rate(n: int, d: int) -> float | None:
    return r4(n / d) if d else None


def _intent_scores(rows: list[dict[str, Any]], mesh: Any) -> dict[str, Any]:
    scored = correct = clarify_n = clarified = missing = 0
    per_class: dict[str, dict[str, int]] = {}
    for row in rows:
        try:
            got = understand(mesh, row["question"], [], row["as_of"])
        except NotRecorded:
            missing += 1
            continue
        scored += 1
        if row["low_confidence"]:
            clarify_n += 1
            clarified += got.confidence < 0.6
            continue
        ok = got.intent == row["intent"]
        correct += ok
        c = per_class.setdefault(row["intent"], {"tp": 0, "fp": 0, "fn": 0})
        if ok:
            c["tp"] += 1
        else:
            c["fn"] += 1
            per_class.setdefault(got.intent, {"tp": 0, "fp": 0, "fn": 0})["fp"] += 1
    f1s = []
    for c in per_class.values():
        p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
        r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
        f1s.append(2 * p * r / (p + r) if p + r else 0.0)
    labelled = scored - clarify_n
    return {
        "scored": scored,
        "not_recorded": missing,
        "accuracy": _rate(correct, labelled),
        "macro_f1": r4(sum(f1s) / len(f1s)) if f1s else None,
        "low_confidence_clarified": _rate(clarified, clarify_n),
    }


def _expected_types(row: dict[str, Any]) -> set[str]:
    exp = row["expected"]
    types = {t for t in (exp.get("overview") or {}).values() if t}
    return types | set(exp.get("details") or [])


def _composition(rows: list[dict[str, Any]], mesh: Any) -> dict[str, Any] | None:
    with seeded_database() as factory:
        if factory is None:
            return None
        valid = budget_ok = skeleton_ok = placement_ok = answered = failed = 0
        tp = fp = fn = 0
        detail: list[dict[str, Any]] = []
        with factory() as session:
            for row in rows:
                ws = demo_workspace(session, PERSONA.get(row["dataset"], "P1"))
                if ws is None:
                    failed += 1
                    continue
                store = AgentStore(WorkspaceContext.open(session, ws.id))
                thread = store.create_thread()
                session.commit()
                try:
                    out = ask(store, thread_id=thread.id, text=row["question"],
                              client_msg_id=uuid.uuid4().hex, mesh=mesh,
                              as_of=row["as_of"])  # fmt: skip
                except (CassetteMiss, LookupError):
                    session.rollback()
                    failed += 1
                    detail.append({"case": row["id"], "error": "not recorded"})
                    continue
                snapshot = store.response(out.response_id) if out.response_id else None
                if snapshot is None:
                    failed += 1
                    continue
                answered += 1
                try:
                    body = AgentResponse.model_validate(snapshot.body)
                    valid += 1
                except ValueError:
                    detail.append({"case": row["id"], "error": "invalid response"})
                    continue
                blocks = body.blocks
                skeleton = check_skeleton(blocks)
                skeleton_ok += not skeleton
                budget_ok += not any(i.code == "skeleton_budget" for i in skeleton)
                order = visible_tabs(blocks)
                placement_ok += order == sorted(
                    order, key=["details", "recommendation", "transactions", "checked"].index
                )
                got: set[str] = {b.type for b in blocks if b.placement.area == "overview"} | {
                    b.type for b in blocks
                    if b.placement.area == "tab" and b.placement.tab == "details"
                }  # fmt: skip
                want = _expected_types(row)
                tp += len(got & want)
                fp += len(got - want)
                fn += len(want - got)
                detail.append({"case": row["id"], "got": sorted(got), "want": sorted(want),
                               "skeleton_issues": [i.code for i in skeleton]})  # fmt: skip
        return {
            "answered": answered,
            "not_answered": failed,
            "ui1_schema_valid": _rate(valid, answered),
            "ui2_block_precision": _rate(tp, tp + fp),
            "ui2_block_recall": _rate(tp, tp + fn),
            "ui7_overview_budget": _rate(budget_ok, valid),
            "ui9_tab_placement": _rate(placement_ok, valid),
            "ui10_skeleton": _rate(skeleton_ok, valid),
            "detail": detail,
        }


def run(fast: bool = False, cases: Any = None) -> dict[str, Any]:
    rows = read_jsonl(cases or CASES)
    if fast:
        rows = rows[:8]
    mesh = eval_mesh()
    intents = _intent_scores(rows, mesh)
    composed = _composition(rows, mesh)
    metrics: dict[str, Any] = {
        "mode": eval_mode(),
        "ui8_intent": intents,
        "composition": composed or "not measured: needs DATABASE_URL (PostgreSQL)",
    }
    c = composed or {}
    targets: list[Target] = [
        target("UI-8", "Intent accuracy (Understand)", intents["accuracy"], ">=", 0.90,
               f"{intents['scored']} questions", stage1=False),
        target("UI-8b", "Low-confidence questions clarified", intents["low_confidence_clarified"],
               ">=", 1.0, "clarify rows", stage1=False),
        target("UI-1", "Schema validity", c.get("ui1_schema_valid"), ">=", 0.98, "60 answers",
               stage1=False),
        target("UI-2", "Block-selection precision", c.get("ui2_block_precision"), ">=", 0.85,
               "60 answers", stage1=False),
        target("UI-2b", "Block-selection recall", c.get("ui2_block_recall"), ">=", 0.80,
               "60 answers", stage1=False),
        target("UI-7", "Overview budget respected", c.get("ui7_overview_budget"), ">=", 1.0,
               "60 answers", stage1=False),
        target("UI-9", "Tab placement", c.get("ui9_tab_placement"), ">=", 1.0, "60 answers",
               stage1=False),
        target("UI-10", "Answer skeleton followed", c.get("ui10_skeleton"), ">=", 1.0,
               "60 answers", stage1=False),
    ]  # fmt: skip
    notes = [
        f"{eval_mode()} mode; {intents['not_recorded']} Understand requests not recorded.",
        "Composition scores depend on the specialist nodes present when they were recorded "
        "(compose's value catalogue follows their outputs); re-record after specialist changes.",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
