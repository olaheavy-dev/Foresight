"""Graph nodes for the Forecaster, the risk check and the core loop (docs/06 W3, W4).

- `forecaster`: baseline forecast from stored data; for a what-if question, the parse
  (`backend.agents.forecaster`) and a same-seed simulation, both stored as Calculations.
- `risk_check`: deterministic; flags pay cycles likely to go below the buffer.
- `advise`: the Advisor on the reasoning tier; impacts recomputed by code.
- `verify`: deterministic rules V-01…V-20, then the judge on the verifier tier; every pass is a
  stored VerificationResult and every proposal a Recommendation, so the trail shows rejected
  drafts as well as the approved one.

Each node checks its preconditions before any model call: with no ledger or no forecast it records
an honest skipped step and changes nothing.
"""

from __future__ import annotations

import dataclasses
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from backend.agents.advice.advisor import advise as run_advisor
from backend.agents.advice.card import build_card
from backend.agents.advice.impact import Impact
from backend.agents.advice.models import InterventionProposal
from backend.agents.advice.verifier import verification_record, verify
from backend.agents.advice.world import AdviceWorld, Finding, SpendRow
from backend.agents.forecaster import drivers, parse_scenario, to_engine_spec
from backend.agents.runtime import NodeOutput, NodeSpec, RunContext
from backend.agents.state import ForesightState
from backend.finance_core.simulate import ScenarioError
from backend.finance_core.types import ForecastInputs, ScenarioModifier
from backend.pipeline import ledger, packs
from backend.pipeline.forecast import NoLedgerData, forecast_inputs, run_forecast, run_simulation
from backend.storage import models as m

MAX_REVISIONS = 2  # docs/06 W4: initial + 2 revisions (same cap as the graph)
RISK_CHANCE = 0.2  # a pay cycle with ≥ 20% chance of going below the buffer is a risk
SCENARIO_INTENTS = frozenset({"affordability", "scenario"})
LIVE_FINDING = ("candidate", "open", "ranked")


def _skip(reason: str, label: str) -> NodeOutput:
    return NodeOutput(status="skipped", output={"reason": reason}, label=label)


# --------------------------------------------------------------------------- the world

JUDGE_POOL = 3  # judge calls for one round's proposals run concurrently (docs/05 §6.4)
SUMMARIES = {
    "category_spike": "Spending in {subject} over the last 30 days is well above its usual level "
    "for the previous three months.",
    "price_change": "The recurring payment {subject} rose in price.",
    "subscription_overlap": "Two subscriptions overlap: {subject}.",
}


def _finding(row: m.Finding) -> Finding:
    """A stored finding as the Advisor and the judge see it (deterministic, number-free)."""
    subject_data = row.subject or {}
    subject = str(
        subject_data.get("category_key")
        or "+".join(subject_data.get("obligation_keys") or ())
        or subject_data.get("key")
        or row.kind
    )
    template = SUMMARIES.get(row.kind, "{kind} about {subject}.")
    return Finding(
        id=row.id,
        finding_type=row.kind,
        subject=subject,
        summary=template.format(subject=subject.replace(".", " "), kind=row.kind),
    )


def normalise_refs(raw: dict[str, Any], ctx: RunContext, world: AdviceWorld) -> dict[str, Any]:
    """Give each cited ID the kind the store says it is, before the Verifier (V-01/V-02).

    A `calc_` ID that is this run's stored forecast or simulation becomes `forecast` or
    `simulation`; a stored finding becomes `finding`. IDs the store doesn't have are left as they
    are, so V-01 still rejects evidence that doesn't exist. The lookup is by ID in the store, never
    by prefix."""
    refs = []
    with ctx.lock:
        for ref in raw.get("trigger_refs") or []:
            ref = dict(ref)
            rid = str(ref.get("id") or "")
            calc = ctx.store.ctx.calculation(rid)
            if (
                calc is not None
                and calc.kind in ("forecast", "simulation")
                and (rid in world.forecast_ids)
            ):
                ref["kind"] = calc.kind
            elif rid in world.findings:
                ref["kind"] = "finding"
            refs.append(ref)
    return {**raw, "trigger_refs": refs}


DATE_FIELDS = ("date", "from_date", "to_date")


def modifier_json(mod: ScenarioModifier) -> dict[str, Any]:
    """A modifier as JSON-safe state (the checkpointer stores the state)."""
    out: dict[str, Any] = {}
    for k, v in dataclasses.asdict(mod).items():
        if v in (None, ""):
            continue
        out[k] = v.isoformat() if k in DATE_FIELDS else v
    return out


def modifier_from_json(data: dict[str, Any]) -> ScenarioModifier:
    fields: dict[str, Any] = {
        k: date.fromisoformat(v) if k in DATE_FIELDS and isinstance(v, str) else v
        for k, v in data.items()
    }
    return ScenarioModifier(**fields)


def _inputs(ctx: RunContext) -> ForecastInputs | None:
    with ctx.lock:
        try:
            return forecast_inputs(ctx.store.ctx)
        except NoLedgerData:
            return None


def world_from_store(
    ctx: RunContext, state: ForesightState, inputs: ForecastInputs | None
) -> AdviceWorld:
    w = ctx.store.ctx
    with ctx.lock:
        ws = w.workspace
        latest = w.latest_categorisations()
        obligations = {o.key: ledger.obligation(o) for o in w.all(m.RecurringObligation)}
        member = {t: o.key for o in obligations.values() for t in o.member_ids}
        rows = tuple(
            SpendRow(
                on=t.posted_on,
                amount_minor=t.amount_minor,
                category=latest[t.id].category_key if t.id in latest else "uncategorised",
                flow_kind=latest[t.id].flow_kind if t.id in latest else "spending",
                recurring_key=member.get(t.id),
            )
            for t in w.transactions(currency=ws.home_currency)
        )
        findings = {f.id: _finding(f) for f in w.all(m.Finding) if f.status in LIVE_FINDING}
        active = tuple(
            (
                str((r.proposal or {}).get("action")),
                str(
                    ((r.proposal or {}).get("params") or {}).get("category_key")
                    or ((r.proposal or {}).get("params") or {}).get("recurring_id")
                    or ""
                ),
            )
            for r in w.all(m.Recommendation)
            if r.status in ("approved", "accepted")
        )
        pack = packs.categorisation_pack(ws.country)
    slots = (state.get("intent") or {}).get("slots") or {}
    asked = slots.get("category") if isinstance(slots.get("category"), str) else None
    forecast_ids = {i for i in (state.get("forecast_id"), state.get("snapshot_id")) if i}
    forecast_ids |= set(state.get("simulation_ids") or ())
    pending = tuple(
        modifier_from_json(mod) for mod in (state.get("scenario_spec") or {}).get("modifiers", ())
    )
    return AdviceWorld(
        as_of=inputs.as_of if inputs else ws.created_at.date(),
        currency=ws.home_currency,
        locale_pack=str(state.get("locale_pack") or "uk"),
        rows=rows,
        obligations=obligations,
        findings=findings,
        forecast_ids=frozenset(forecast_ids),
        protected_categories=pack.protected_categories,
        buffer_minor=inputs.buffer_minor if inputs else None,
        user_requested_category=asked,
        forecast_inputs=inputs,
        pending_scenario=pending,
        active_recommendations=active,
    )


# --------------------------------------------------------------------------- Forecaster


def forecaster_node(state: ForesightState, ctx: RunContext) -> NodeOutput:
    with ctx.lock:
        try:
            stored = run_forecast(ctx.store.ctx, actor="agent:forecaster")
        except NoLedgerData:
            return _skip("no ledger data", "No transactions to forecast yet")
    forecast_id = stored.calculation.id
    update: dict[str, Any] = {"forecast_id": forecast_id}
    intent = state.get("intent") or {}
    question = state.get("user_message")
    if intent.get("intent") not in SCENARIO_INTENTS or not question:
        return NodeOutput(
            update=update,
            output={"forecast_id": forecast_id, "created": stored.created},
            tool_calls=[{"name": "build_forecast", "result_refs": [forecast_id]}],
            label="Building your forecast",
        )
    mesh = ctx.require_mesh()
    inputs = stored.inputs
    with ctx.lock:
        recurring = [
            {"recurring_id": o.key, "label": o.label}
            for o in ctx.store.ctx.all(m.RecurringObligation)
        ]
        income = [
            {"income_stream_id": s.key, "label": s.source_label}
            for s in ctx.store.ctx.all(m.IncomeStream)
        ]
        categories = sorted(packs.categorisation_pack(ctx.store.ctx.workspace.country).categories)
    parsed = parse_scenario(
        str(intent.get("standalone_question") or question),
        mesh,
        today=inputs.as_of,
        currency=inputs.currency,
        categories=categories,
        recurring=recurring,
        income=income,
        locale_pack=str(state.get("locale_pack") or "uk"),
        before_llm=ctx.before_llm,
    )
    ctx.charge(parsed.llm)
    if parsed.parse.status == "needs_clarification" or parsed.parse.spec is None:
        clar = parsed.parse.clarification
        return NodeOutput(
            update={**update, "needs_user_input": clar.model_dump() if clar else {"slot": "other"}},
            output={"forecast_id": forecast_id, "needs_clarification": True},
            label="Asking what's missing from the what-if",
            llm=parsed.llm,
            prompt_version=parsed.prompt_version,
        )
    spec = to_engine_spec(parsed.parse.spec)
    try:
        with ctx.lock:
            sim = run_simulation(ctx.store.ctx, spec)
    except ScenarioError as exc:
        return NodeOutput(
            update=update,
            output={"forecast_id": forecast_id, "scenario_error": str(exc)},
            status="failed",
            error=str(exc),
            label="The what-if couldn't be simulated",
            llm=parsed.llm,
            prompt_version=parsed.prompt_version,
        )
    modifiers = [modifier_json(mod) for mod in spec.modifiers]
    spec_dict: dict[str, Any] = {"name": spec.name, "modifiers": modifiers}
    return NodeOutput(
        update={**update, "simulation_ids": [sim.calculation.id], "scenario_spec": spec_dict},
        output={
            "forecast_id": forecast_id,
            "simulation_id": sim.calculation.id,
            "modifiers": [mod["type"] for mod in modifiers],
            "drivers": drivers(sim.result.delta_lows),
        },
        tool_calls=[{"name": "simulate", "result_refs": [sim.calculation.id]}],
        label="Simulating your what-if on the same forecast",
        llm=parsed.llm,
        prompt_version=parsed.prompt_version,
    )


def risk_check_node(state: ForesightState, ctx: RunContext) -> NodeOutput:
    inputs = _inputs(ctx)
    if inputs is None or inputs.buffer_minor is None:
        return _skip("no forecast or no buffer", "No buffer to check against")
    with ctx.lock:
        stored = run_forecast(ctx.store.ctx, actor="agent:forecaster")
    flags = [
        {
            "kind": "buffer_breach",
            "payday": c.payday.isoformat(),
            "chance": c.chance_below_buffer,
            "forecast_id": stored.calculation.id,
        }
        for c in stored.result.pay_cycles
        if c.chance_below_buffer is not None and c.chance_below_buffer >= RISK_CHANCE
    ]
    return NodeOutput(
        update={"risk_flags": flags, "forecast_id": stored.calculation.id},
        output={"flags": len(flags), "cycles": [f["payday"] for f in flags]},
        label="Checking the pay cycles against your buffer",
    )


# --------------------------------------------------------------------------- the core loop


def advise_node(state: ForesightState, ctx: RunContext) -> NodeOutput:
    forecast_id = state.get("forecast_id")
    if state.get("needs_user_input"):
        return _skip("waiting for the user", "Waiting for your answer before advising")
    inputs = _inputs(ctx)
    if inputs is None or not forecast_id:
        return _skip("no forecast", "No forecast to base advice on")
    world = world_from_store(ctx, state, inputs)
    previous = [p for p in state.get("proposals") or [] if p.get("critique")]
    revision = [
        {
            "proposal": {k: v for k, v in p.items() if k in InterventionProposal.model_fields},
            "critique": p["critique"],
        }
        for p in previous
    ]
    advice = run_advisor(
        world,
        ctx.require_mesh(),
        forecast_id=str(forecast_id),
        question=(state.get("intent") or {}).get("standalone_question")
        or state.get("user_message"),
        revision=revision,
        before_llm=ctx.before_llm,
    )
    ctx.charge(advice.llm)
    keys = {p.get("proposal_id"): p.get("proposal_key") for p in previous}
    returned = {p.proposal_id for p in advice.proposals}
    with ctx.lock:
        for dropped in previous:
            rec_id = dropped.get("rec_id")
            if dropped.get("proposal_id") in returned or not rec_id:
                continue
            # A rejected draft the Advisor didn't revise is over: withdraw it, never leave it
            # in review.
            ctx.store.set_recommendation_status(rec_id, "withdrawn")
            ctx.store.ctx.append_audit(
                "recommendation_withdrawn",
                "recommendation",
                rec_id,
                actor="agent:advisor",
                after={"reason": "dropped_in_revision"},
                run_id=ctx.run_id,
            )
    proposals = []
    for p in advice.proposals:
        impact = advice.impacts[p.proposal_id]
        proposals.append(
            {
                **p.model_dump(),
                "proposal_key": keys.get(p.proposal_id) or p.proposal_id,
                "rec_id": next(
                    (q.get("rec_id") for q in previous if q.get("proposal_id") == p.proposal_id),
                    None,
                ),
                "impact": _impact_json(impact),
            }
        )
    return NodeOutput(
        update={"proposals": proposals},
        output={
            "proposals": [p["proposal_id"] for p in proposals],
            "revision_round": int(state.get("revision_round") or 0),
        },
        llm=advice.llm,
        prompt_version=advice.prompt_version,
        label="Revising the recommendation" if previous else "Drafting a recommendation",
    )


def _impact_json(impact: Impact) -> dict[str, Any]:
    return {
        "monthly_minor": impact.monthly_minor,
        "basis": impact.basis,
        "risk_before": impact.risk_before,
        "risk_after": impact.risk_after,
        "cycles": [
            {
                "payday": b.payday.isoformat(),
                "low_before": b.low_p50,
                "low_after": a.low_p50,
                "chance_before": b.chance_below_buffer,
                "chance_after": a.chance_below_buffer,
            }
            for b, a in zip(impact.before, impact.after, strict=False)
        ],
        "error": impact.error,
    }


def verify_node(state: ForesightState, ctx: RunContext) -> NodeOutput:
    proposals = list(state.get("proposals") or [])
    if not proposals:
        return NodeOutput(
            update={"verdict": "none"}, output={"proposals": 0}, label="No recommendation to check"
        )
    inputs = _inputs(ctx)
    world = world_from_store(ctx, state, inputs)
    round_ = int(state.get("revision_round") or 0) + 1
    last_round = round_ > MAX_REVISIONS
    mesh = ctx.require_mesh()
    llm = []
    verifications = list(state.get("verifications") or [])
    approved = list(state.get("approved_recs") or [])
    remaining = []
    prompt = None
    normalised = [normalise_refs(raw, ctx, world) for raw in proposals]
    with ctx.lock:
        locale = ctx.store.ctx.workspace.locale

    def guarded() -> None:
        with ctx.lock:
            ctx.before_llm()

    def check(raw: dict[str, Any]) -> tuple[dict[str, Any], InterventionProposal, Any]:
        p = InterventionProposal.model_validate(
            {k: v for k, v in raw.items() if k in InterventionProposal.model_fields}
        )
        return raw, p, verify(p, world, round=round_, mesh=mesh, before_llm=guarded)

    with ThreadPoolExecutor(max_workers=JUDGE_POOL) as pool:
        checked = list(pool.map(check, normalised))
    not_approved = 0
    for raw, p, outcome in checked:
        with ctx.lock:
            ctx.charge(outcome.llm)
        llm += outcome.llm
        prompt = outcome.prompt_version or prompt
        v = outcome.verification
        status = {"APPROVE": "approved", "WITHDRAW": "withdrawn"}.get(
            v.verdict, "withdrawn" if last_round else "in_review"
        )
        with ctx.lock:
            rec_id = raw.get("rec_id")
            if rec_id is None:
                rec = ctx.store.add_recommendation(
                    run_id=ctx.run_id,
                    proposal_key=str(raw.get("proposal_key") or p.proposal_id),
                    status=status,
                    proposal=p.model_dump(),
                    trigger_refs=[r.model_dump() for r in p.trigger_refs],
                    impact_calc_refs=[i for i in world.forecast_ids],
                    revision_count=round_ - 1,
                )
                rec_id = rec.id
            else:
                rec = ctx.store.set_recommendation_status(rec_id, status)
                rec.proposal = p.model_dump()
                rec.revision_count = round_ - 1
            ver = ctx.store.add_verification(
                run_id=ctx.run_id,
                recommendation_id=rec_id,
                round=round_,
                verdict=v.verdict if v.verdict != "WITHDRAW" else "REJECT",
                rule_results=verification_record(v),
                critique="\n".join(v.critique) or None,
            )
        verifications.append(ver.id)
        not_approved += v.verdict != "APPROVE"
        if v.verdict == "APPROVE":
            card = build_card(
                p,
                outcome.impact,
                v,
                recommendation_id=rec_id,
                verification_id=ver.id,
                revisions=round_ - 1,
                locale=locale,
                forecast_calc_id=state.get("forecast_id"),
            )
            if card is not None:
                with ctx.lock:
                    stored = ctx.store.recommendation(rec_id)
                    if stored is not None:
                        stored.proposal = {**p.model_dump(), "card": card}
            approved.append(rec_id)
        elif v.verdict == "REJECT":
            remaining.append({**raw, "rec_id": rec_id, "critique": v.critique})
    verdict = "reject" if remaining else ("approve" if approved else "none")
    rejected = sum(1 for _ in remaining)
    label = (
        "Checked: recommendation approved"
        if verdict == "approve"
        else f"Verifier rejected {rejected} draft(s)"
        if verdict == "reject"
        else "No recommendation passed the checks"
    )
    return NodeOutput(
        update={
            "proposals": remaining,
            "verdict": verdict,
            "verifications": verifications,
            "approved_recs": approved,
        },
        output={
            "verdict": verdict,
            "round": round_,
            "approved": len(approved),
            "rejected": rejected,
            "rejected_drafts": not_approved,  # rejected or withdrawn this round (evidence line)
            "failed_rules": [r.get("critique") for r in remaining],
        },
        llm=llm,
        prompt_version=prompt,
        label=label,
    )


def nodes() -> dict[str, NodeSpec]:
    return {
        "forecaster": NodeSpec(
            "forecaster", "forecaster", "llm", forecaster_node, "Building the forecast"
        ),
        "risk_check": NodeSpec(
            "risk_check", "forecaster", "tool", risk_check_node, "Checking for risks"
        ),
        "advise": NodeSpec("advise", "advisor", "llm", advise_node, "Drafting a recommendation"),
        "verify": NodeSpec("verify", "verifier", "llm", verify_node, "Checking the recommendation"),
    }
