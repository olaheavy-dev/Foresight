"""E-AUD: audit completeness (docs/09 §11).

On a disposable PostgreSQL database seeded with the P1 and P2 demos, the real recommendation
workflow (Forecaster baseline → Advisor → Verifier rules → judge → persistence) is run three ways
per persona: drafts that pass, drafts that fail once and are revised, and drafts that keep failing
and are withdrawn. The Advisor's drafts and the judge's verdicts are scripted (`evals.stubs`,
model names `stub/advisor` and `stub/judge` in the step rows), because this suite measures the
records the system keeps, not advice quality (that is E-VER/E-GRD); everything else is the
product's code, so every row walked here was written by the app itself.

For every recommendation the chain is walked:
`rec_ → ver_ (≥ 1; last APPROVE when approved) → fnd_ / fc_ / sim_ → calc_ (inputs_hash,
engine_version) → txn_ → imp_ (importer, profile, reconciliation) → raw file hash`, plus
`run_ → step_` and the `aud_` events (with the workspace's audit hash chain intact).

- Audit completeness = recommendations with an unbroken chain / all recommendations.
- Recomputability: up to 50 stored calculations (forecasts, simulations, finding statistics),
  rebuilt from stored data → identical `result_hash`.
- Rejected/withdrawn traceability: every REJECT verification stored with its critique and rule
  results; every withdrawn recommendation has its rejected rounds and an audit event.
- Provenance labels: every forecast/simulation in a chain states its starting-balance and income
  provenance, and a declared figure is labelled `declared` in the Evidence view.

The committed P1 canonical live traces (evals/results/*_p1_canonical) are not re-walked here:
their recorded model requests depend on wall-clock deadlines, so a replay takes a different path.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from backend.agents.findings import build_candidates, data_end
from backend.agents.runner import run_workflow
from backend.app.views import PROVENANCE
from backend.finance_core.calc import content_hash
from backend.pipeline import ledger, packs
from backend.pipeline.forecast import run_forecast, verify, verify_simulation
from backend.storage import models as m
from backend.storage.agent_repo import AgentStore
from backend.storage.repositories import WorkspaceContext, demo_workspace
from evals.assistant import eval_mesh, eval_mode, seeded_database
from evals.metrics import r4
from evals.stubs import StubMesh
from evals.suites import Target, target

SUITE_ID = "E-AUD"
NAME = "audit"
AS_OF = "2026-10-11"
PERSONAS = ("P1", "P2")
MODES = ("feasible", "flawed_once", "flawed_always")
CATEGORIES = ("food.delivery", "eating_out", "groceries")
SAMPLE = 50
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _build_corpus(session: Any, mesh: Any) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """Run the recommendation workflow per persona and mode. Each run's recommendations are walked
    as the run left them (before the next mode starts), so approved chains are checked as
    approved. Returns the workspace ids, the walked chains and the calculations they cite."""
    used: list[str] = []
    chains: list[dict[str, Any]] = []
    cited: list[str] = []
    for persona in PERSONAS:
        ws = demo_workspace(session, persona)
        if ws is None:
            continue
        used.append(ws.id)
        ctx = WorkspaceContext.open(session, ws.id)
        store = AgentStore(ctx)
        for mode in MODES:
            forecast = run_forecast(ctx, as_of=date.fromisoformat(AS_OF))
            session.commit()
            out = run_workflow(
                store,
                workflow="recommendation",
                trigger="user",
                mesh=StubMesh(mesh, advisor_mode=mode, judge_pass=True, categories=CATEGORIES),
                inputs={
                    "as_of": AS_OF,
                    "forecast_id": forecast.calculation.id,
                    "risk_flags": [{"kind": "advice_requested"}],
                },
            )
            for rec in (r for r in ctx.all(m.Recommendation) if r.run_id == out.run_id):
                links = _walk(ctx, store, rec)
                broken = sorted(k for k, ok in links.items() if not ok)
                chains.append({"rec": rec.id, "persona": persona, "mode": mode,
                               "status": rec.status, "broken": broken})  # fmt: skip
                for cid in _cited_calcs(ctx, rec):
                    if cid not in cited:
                        cited.append(cid)
            # The next mode starts with no active advice (a repeat would be a V-09 duplicate).
            for rec in ctx.all(m.Recommendation):
                if rec.status == "approved":
                    rec.status = "dismissed"
            session.commit()
    return used, chains, cited


def _cited_calcs(ctx: WorkspaceContext, rec: m.Recommendation) -> list[str]:
    out: list[str] = []
    for ref in [*(r.get("id") for r in rec.trigger_refs or []), *(rec.impact_calc_refs or [])]:
        cid = str(ref)
        if cid.startswith("calc_"):
            out.append(cid)
        elif cid.startswith("fnd_"):
            f = ctx.get(m.Finding, cid)
            out += list((f.calc_ids if f else []) or [])
    return out


def _txns_for_query(ctx: WorkspaceContext, query: dict[str, Any]) -> list[m.Transaction]:
    if "obligation_keys" in query:
        keys = set(query["obligation_keys"])
        ids = {i for o in ctx.all(m.RecurringObligation) if o.key in keys for i in o.member_ids}
        return [t for t in ctx.all(m.Transaction) if t.id in ids]
    if "category" in query:
        latest = ctx.latest_categorisations()
        start, end = date.fromisoformat(query["from"]), date.fromisoformat(query["to"])
        return [
            t
            for t in ctx.all(m.Transaction)
            if start <= t.posted_on <= end
            and t.id in latest
            and latest[t.id].category_key == query["category"]
        ]
    return []


def _txns_for_calc(ctx: WorkspaceContext, calc: m.Calculation) -> list[m.Transaction]:
    """The ledger a forecast or simulation was built from: active transactions up to as_of."""
    as_of = date.fromisoformat(str(calc.params.get("as_of")))
    return [t for t in ctx.all(m.Transaction) if t.status == "active" and t.posted_on <= as_of]


def _imports_ok(ctx: WorkspaceContext, txns: list[m.Transaction]) -> bool:
    """Every imported transaction leads to its import batch and the raw file's hash."""
    if not txns:
        return False
    batches = {b.id: b for b in ctx.all(m.ImportBatch)}
    for t in txns:
        if t.entry_method != "import":
            continue
        b = batches.get(t.import_batch_id or "")
        if b is None or not HEX64.match(b.file_sha256 or "") or not b.importer:
            return False
        if b.status != "committed" or b.reconciliation_status is None:
            return False
    return True


def _calc_ok(calc: m.Calculation | None) -> bool:
    return (
        calc is not None
        and bool(HEX64.match(calc.inputs_hash or ""))
        and bool(calc.engine_version)
        and calc.result is not None
    )


def _walk(ctx: WorkspaceContext, store: AgentStore, rec: m.Recommendation) -> dict[str, bool]:
    links: dict[str, bool] = {}
    vers = sorted(
        (v for v in ctx.all(m.VerificationResult) if v.recommendation_id == rec.id),
        key=lambda v: v.round,
    )
    links["ver_present"] = bool(vers)
    if rec.status == "approved":
        links["last_ver_approves"] = bool(vers) and vers[-1].verdict == "APPROVE"
    if rec.status == "withdrawn":
        links["withdrawn_has_rejections"] = any(v.verdict == "REJECT" for v in vers)
    calcs_seen: list[m.Calculation] = []
    for ref in rec.trigger_refs or []:
        rid = str(ref.get("id"))
        if rid.startswith("fnd_"):
            f = ctx.get(m.Finding, rid)
            links[f"finding:{rid}"] = f is not None
            if f is None:
                continue
            fcalcs = [ctx.calculation(c) for c in f.calc_ids or []]
            links[f"finding_calc:{rid}"] = bool(fcalcs) and all(_calc_ok(c) for c in fcalcs)
            txns = _txns_for_query(ctx, f.txn_query or {})
            links[f"finding_txns:{rid}"] = bool(txns) and _imports_ok(ctx, txns)
        else:
            calc = ctx.calculation(rid.replace("fc_", "calc_").replace("sim_", "calc_"))
            links[f"trigger_calc:{rid}"] = _calc_ok(calc)
            if calc is not None:
                calcs_seen.append(calc)
    impact = [ctx.calculation(c) for c in rec.impact_calc_refs or []]
    links["impact_calcs"] = bool(impact) and all(_calc_ok(c) for c in impact)
    sims = [c for c in impact if c is not None and c.kind == "simulation"]
    links["impact_simulation"] = bool(sims) and all(
        "spec" in c.params and "seed" in (c.result.get("simulated") or {}) for c in sims
    )
    calcs_seen += [c for c in impact if c is not None]
    for calc in calcs_seen:
        if calc.kind in ("forecast", "simulation"):
            links[f"calc_txns:{calc.id}"] = _imports_ok(ctx, _txns_for_calc(ctx, calc))
    run = store.run(rec.run_id)
    steps = store.steps(rec.run_id) if run is not None else []
    nodes = {s.node for s in steps}
    links["run_and_steps"] = run is not None and {"advise", "verify"} <= nodes
    actions = {e.action for e in ctx.all(m.AuditEvent) if e.subject_id == rec.id}
    wanted = {"approved": "recommendation_approved", "withdrawn": "recommendation_withdrawn"}
    if rec.status in wanted:
        links["audit_event"] = wanted[rec.status] in actions
    return links


def _recompute(ctx: WorkspaceContext, calc: m.Calculation) -> bool | None:
    """True/False when the calculation's kind can be rebuilt; None when it cannot (counted as
    not recomputable)."""
    try:
        if calc.kind == "forecast":
            return verify(ctx, calc.id)
        if calc.kind == "simulation":
            return verify_simulation(ctx, calc.id)
        if calc.kind == "finding_stats":
            ws = ctx.workspace
            rows = ctx.transactions(currency=ws.home_currency)
            latest = ctx.latest_categorisations()
            txns = [ledger.transaction(r) for r in rows]
            cats = [ledger.categorisation(latest[r.id]) for r in rows if r.id in latest]
            as_of = data_end(txns, date.today())
            specs = build_candidates(
                txns, cats, packs.categorisation_pack(ws.country), as_of=as_of,
                workspace_id=ctx.workspace_id, currency=ws.home_currency,
                holidays=packs.holidays(ws.country, (t.posted_on for t in txns)),
            )  # fmt: skip
            spec = next((s for s in specs if s.calc_id == calc.id), None)
            return spec is not None and content_hash(spec.stats) == content_hash(calc.result)
    except (LookupError, ValueError, KeyError):
        return False
    return None


def run(fast: bool = False) -> dict[str, Any]:
    mesh = eval_mesh()
    with seeded_database() as factory:
        if factory is None:
            return {
                "metrics": {"mode": eval_mode(), "chains": "not measured: needs DATABASE_URL"},
                "targets": [
                    target("AUD-complete", "Audit completeness", None, ">=", 1.0, "all recs"),
                    target("AUD-recompute", "Recomputability", None, ">=", 1.0, "50 calcs"),
                    target(
                        "AUD-rejected",
                        "Rejected/withdrawn traceability",
                        None,
                        ">=",
                        1.0,
                        "all rejections",
                    ),
                    target("AUD-provenance", "Provenance labels", None, ">=", 1.0, "chains"),
                ],  # fmt: skip
                "notes": ["E-AUD needs DATABASE_URL (PostgreSQL); not measured."],
            }
        with factory() as session:
            workspaces, chains, calc_ids = _build_corpus(session, mesh)
            rejected_ok = rejected_n = 0
            provenance_ok = provenance_n = 0
            chain_valid = True
            stored: list[str] = []
            for ws_id in workspaces:
                ctx = WorkspaceContext.open(session, ws_id)
                chain_valid = chain_valid and ctx.audit_chain_valid()
                stored += [
                    c.id
                    for c in ctx.all(m.Calculation)
                    if c.kind in ("forecast", "simulation", "finding_stats")
                ]
                for v in ctx.all(m.VerificationResult):
                    if v.verdict == "REJECT":
                        rejected_n += 1
                        rejected_ok += bool((v.critique or "").strip()) and bool(v.rule_results)
                for calc in (ctx.calculation(c) for c in calc_ids):
                    if calc is None or calc.kind not in ("forecast", "simulation"):
                        continue
                    provenance_n += 1
                    p = calc.params
                    balance = p.get("starting_balance_provenance")
                    income = p.get("income_provenance")
                    label_ok = balance in PROVENANCE and (
                        balance != "declared" or PROVENANCE[balance] == "declared"
                    )
                    provenance_ok += label_ok and isinstance(income, dict)
            # The calculations the chains cite first, then every other stored one, up to 50.
            sample = [*calc_ids, *sorted(c for c in stored if c not in calc_ids)][:SAMPLE]
            recomputed: dict[str, bool | None] = {}
            for cid in sample:
                for ws_id in workspaces:
                    ctx = WorkspaceContext.open(session, ws_id)
                    calc = ctx.calculation(cid)
                    if calc is not None:
                        recomputed[cid] = _recompute(ctx, calc)
                        break
    complete = sum(1 for c in chains if not c["broken"])
    recompute_ok = sum(1 for v in recomputed.values() if v is True)
    kinds: dict[str, int] = {}
    for c in chains:
        for link in c["broken"]:
            kinds[link.split(":")[0]] = kinds.get(link.split(":")[0], 0) + 1
    metrics = {
        "mode": eval_mode(),
        "recommendations": len(chains),
        "by_status": {
            s: sum(1 for c in chains if c["status"] == s)
            for s in sorted({c["status"] for c in chains})
        },  # fmt: skip
        "complete_chains": complete,
        "broken_link_kinds": kinds,
        "audit_hash_chain_valid": chain_valid,
        "recomputed": {
            "sampled": len(recomputed),
            "identical": recompute_ok,
            "not_rebuildable": sum(1 for v in recomputed.values() if v is None),
        },  # fmt: skip
        "rejections": {"total": rejected_n, "with_critique": rejected_ok},
        "provenance": {"chains_calcs": provenance_n, "labelled": provenance_ok},
        "detail": chains,
    }
    targets: list[Target] = [
        target("AUD-complete", "Audit completeness (unbroken chains)",
               r4(complete / len(chains)) if chains else None, ">=", 1.0,
               f"{len(chains)} recommendations"),
        target("AUD-hashchain", "Audit event hash chain intact", 1.0 if chain_valid else 0.0,
               ">=", 1.0, "P1, P2 audit log"),
        target("AUD-recompute", "Recomputability (identical result hash)",
               r4(recompute_ok / len(recomputed)) if recomputed else None, ">=", 1.0,
               f"{len(recomputed)} calculations"),
        target("AUD-rejected", "Rejected/withdrawn traceability",
               r4(rejected_ok / rejected_n) if rejected_n else None, ">=", 1.0,
               f"{rejected_n} rejections"),
        target("AUD-provenance", "Provenance labels on chain calculations",
               r4(provenance_ok / provenance_n) if provenance_n else None, ">=", 1.0,
               f"{provenance_n} calculations"),
    ]  # fmt: skip
    notes = [
        f"{eval_mode()} mode. Advisor drafts and judge verdicts are scripted (stub/advisor, "
        "stub/judge in the step rows); the chain under test is written by the product's code.",
        "The P1 canonical live traces are not re-walked: their recorded model requests depend "
        "on wall-clock deadlines, so a replay would take a different path.",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}


__all__ = ["NAME", "SUITE_ID", "run"]
