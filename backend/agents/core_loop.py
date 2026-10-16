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
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any

from backend.agents.advice.advisor import advise as run_advisor
from backend.agents.advice.card import build_card
from backend.agents.advice.impact import Impact
from backend.agents.advice.models import InterventionProposal
from backend.agents.advice.verifier import verification_record, verify
from backend.agents.advice.world import AdviceWorld, Finding, SpendRow
from backend.agents.budget import BudgetExceeded
from backend.agents.contracts import PAY_TODAY
from backend.agents.forecaster import drivers, parse_scenario, to_engine_spec
from backend.agents.runtime import NodeOutput, NodeSpec, RunContext, concurrent_ms
from backend.agents.state import ForesightState
from backend.finance_core.simulate import ScenarioError, horizon_covering
from backend.finance_core.types import ForecastInputs, ScenarioModifier, ScenarioSpec
from backend.pipeline import ledger, packs
from backend.pipeline.forecast import (
    HISTORY_DAYS,
    NoLedgerData,
    forecast_inputs,
    run_forecast,
    run_simulation,
    store_impact_simulation,
)
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
    horizon = (state.get("scenario_spec") or {}).get("horizon_days")
    if inputs is not None and horizon and horizon != inputs.horizon_days:
        # The what-if ran on a longer horizon to reach its dates; advice on it uses the same one.
        inputs = dataclasses.replace(inputs, horizon_days=int(horizon))
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
    inputs = stored.inputs
    default = _pay_today_spec(intent, inputs)
    if default is not None:
        # Owner decision (13 Oct 2026): an affordability question with an amount but no date
        # assumes the payment is made today (the as_of financial date), the most cautious
        # choice, and answers straight away; the answer says so and offers "Change date".
        spec, assumptions = default, [PAY_TODAY]
        try:
            with ctx.lock:
                spec, sim = _simulate(ctx, spec, inputs, assumptions)
        except ScenarioError as exc:
            return NodeOutput(
                update=update, output={"forecast_id": forecast_id, "scenario_error": str(exc)},
                status="failed", error=str(exc), label="The what-if couldn't be simulated",
            )  # fmt: skip
        return _simulated(state, update, forecast_id, spec, sim, assumptions, [], None)
    dated = _dated_purchase_spec(intent, inputs)
    if dated is not None and _plain_purchase(intent):
        # Understand already gave the one purchase's amount and date and nothing else: the
        # model parse would only restate them, so simulate that payment straight away (saves a
        # fast-tier call on the advice path; docs/05 §6.4 latency).
        try:
            with ctx.lock:
                dated, sim = _simulate(ctx, dated, inputs)
        except ScenarioError:
            pass
        else:
            return _simulated(state, update, forecast_id, dated, sim, [], [], None)
    mesh = ctx.require_mesh()
    with ctx.lock:
        recurring = [
            {"recurring_id": o.key, "label": o.label}
            for o in ctx.store.ctx.all(m.RecurringObligation)
        ]
        income = [
            {"income_stream_id": s.key, "label": s.source_label}
            for s in ctx.store.ctx.all(m.IncomeStream)
            if s.provenance != "rejected"  # the user said it isn't income (R4)
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
    if (parsed.parse.status == "needs_clarification" or parsed.parse.spec is None) and dated:
        # The parse asked for something Understand already has (one purchase, its amount and
        # date): never ask again what the question answered; simulate that one payment.
        try:
            with ctx.lock:
                dated, sim = _simulate(ctx, dated, inputs)
        except ScenarioError:
            pass
        else:
            return _simulated(
                state, update, forecast_id, dated, sim, [], parsed.llm, parsed.prompt_version
            )
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
            spec, sim = _simulate(ctx, spec, inputs)
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
    return _simulated(state, update, forecast_id, spec, sim, [], parsed.llm, parsed.prompt_version)


def _simulate(
    ctx: RunContext, spec: ScenarioSpec, inputs: ForecastInputs, assumptions: Sequence[str] = ()
) -> tuple[ScenarioSpec, Any]:
    """Simulate on a horizon that reaches the what-if: "rent goes up from February" on a 90-day
    forecast ending in January is run long enough to show it, instead of being refused."""
    horizon = horizon_covering(inputs.as_of, spec, inputs.horizon_days)
    if horizon != inputs.horizon_days:
        spec = dataclasses.replace(spec, horizon_days=horizon)
    sim = run_simulation(ctx.store.ctx, spec, horizon_days=horizon, assumptions=assumptions)
    return spec, sim


def _simulated(
    state: ForesightState,
    update: dict[str, Any],
    forecast_id: str,
    spec: ScenarioSpec,
    sim: Any,
    assumptions: list[str],
    llm: Any,
    prompt: str | None,
) -> NodeOutput:
    modifiers = [modifier_json(mod) for mod in spec.modifiers]
    spec_dict: dict[str, Any] = {"name": spec.name, "modifiers": modifiers}
    if assumptions:
        spec_dict["assumptions"] = list(assumptions)
    if spec.horizon_days is not None:
        spec_dict["horizon_days"] = spec.horizon_days
    # docs/06 W3: a what-if that takes a pay cycle below the buffer asks the Advisor ⇄ Verifier
    # loop for advice (the scenario workflow has no separate risk check).
    breach = [
        {
            "kind": "scenario_buffer_breach",
            "payday": c.payday.isoformat(),
            "chance": c.chance_below_buffer,
            "simulation_id": sim.calculation.id,
        }
        for c in sim.result.simulated.pay_cycles
        if c.chance_below_buffer is not None and c.chance_below_buffer >= RISK_CHANCE
    ]
    if breach and state.get("workflow") == "scenario":
        update["risk_flags"] = breach
    return NodeOutput(
        update={**update, "simulation_ids": [sim.calculation.id], "scenario_spec": spec_dict},
        output={
            "forecast_id": forecast_id,
            "simulation_id": sim.calculation.id,
            "modifiers": [mod["type"] for mod in modifiers],
            "drivers": drivers(sim.result.delta_lows),
            "assumptions": list(assumptions),
        },
        tool_calls=[{"name": "simulate", "result_refs": [sim.calculation.id]}],
        label="Simulating your what-if on the same forecast",
        llm=llm or [],
        prompt_version=prompt,
    )


def _pay_today_spec(intent: dict[str, Any], inputs: ForecastInputs) -> ScenarioSpec | None:
    """An affordability question with an amount and no date: one payment today."""
    slots = intent.get("slots") or {}
    if intent.get("intent") != "affordability" or slots.get("date"):
        return None
    try:
        amount = int(slots.get("amount_minor") or 0)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None  # a missing amount still gets the clarifying question
    label = str(slots.get("purpose") or "Payment").replace("_", " ").capitalize()
    # The forecast's `as_of` is the day of the latest known balance; a payment made "today" has
    # not left it yet, so it lands on the forecast's first day, the earliest it can fall.
    first_day = inputs.as_of + timedelta(days=1)
    payment = ScenarioModifier(
        type="one_off_outflow", date=first_day, amount_minor=amount, label=label
    )
    return ScenarioSpec(f"{label} today", inputs.currency, (payment,))


# Understand slots that a plain one-purchase question can carry; any other slot (instalments,
# months, a percentage, …) means the what-if is richer than one payment, so the parse decides.
PLAIN_PURCHASE_SLOTS = frozenset({"amount_minor", "date", "purpose", "merchant", "modifier"})


def _plain_purchase(intent: dict[str, Any]) -> bool:
    slots = intent.get("slots") or {}
    return set(slots) <= PLAIN_PURCHASE_SLOTS and slots.get("modifier") in (None, "one_off_outflow")


def _dated_purchase_spec(intent: dict[str, Any], inputs: ForecastInputs) -> ScenarioSpec | None:
    """An affordability question whose Understand slots give an amount and a date: one payment
    on that date (never before the forecast's first day)."""
    slots = intent.get("slots") or {}
    if intent.get("intent") != "affordability" or not slots.get("date"):
        return None
    try:
        amount = int(slots.get("amount_minor") or 0)
        on = date.fromisoformat(str(slots["date"]))
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    label = str(slots.get("purpose") or "Payment").replace("_", " ").capitalize()
    on = max(on, inputs.as_of + timedelta(days=1))
    payment = ScenarioModifier(type="one_off_outflow", date=on, amount_minor=amount, label=label)
    return ScenarioSpec(label, inputs.currency, (payment,))


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


def _store_impact(
    ctx: RunContext, world: AdviceWorld, inputs: ForecastInputs | None, impact: Impact
) -> list[str]:
    """Persist the simulation the Verifier recomputed this proposal's impact with, so the audit
    chain runs `rec_ → impact calc_ → sim_ (seed, spec, engine version)` (docs/06 §10.2).
    Caller holds `ctx.lock`."""
    if inputs is None or not impact.scenario:
        return []
    spec = ScenarioSpec(
        "recommendation_impact", inputs.currency, (*world.pending_scenario, *impact.scenario)
    )
    try:
        stored = store_impact_simulation(ctx.store.ctx, inputs, spec, window_days=HISTORY_DAYS)
    except ScenarioError:
        return []
    return [stored.calculation.id]


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

    # The round's judge calls run concurrently, so the budget is shared out before they start, in
    # proposal order: the i-th proposal may call the judge only if i calls are still allowed. A
    # check made inside each thread would let every concurrent call through (docs/09 ORC-10).
    with ctx.lock:
        free = ctx.budget.calls_left()

    def check(item: tuple[int, dict[str, Any]]) -> tuple[dict[str, Any], InterventionProposal, Any]:
        index, raw = item

        def guarded() -> None:
            with ctx.lock:
                if index >= free:
                    raise BudgetExceeded("run budget used: no call left for this judge")
                ctx.before_llm()

        p = InterventionProposal.model_validate(
            {k: v for k, v in raw.items() if k in InterventionProposal.model_fields}
        )
        try:
            return raw, p, verify(p, world, round=round_, mesh=mesh, before_llm=guarded)
        except BudgetExceeded as exc:
            return raw, p, exc

    with ThreadPoolExecutor(max_workers=JUDGE_POOL) as pool:
        checked = list(pool.map(check, enumerate(normalised)))
    refused = [o for _, _, o in checked if isinstance(o, BudgetExceeded)]
    if refused:
        # The judge calls that did run were paid for: charge them, then stop like any node
        # whose budget ran out (the instrument records a skipped step with these calls).
        with ctx.lock:
            for _, _, o in checked:
                if not isinstance(o, BudgetExceeded):
                    ctx.charge(o.llm)
            ctx.budget.exceeded = True
        raise refused[0]
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
            impact_refs = [*world.forecast_ids, *_store_impact(ctx, world, inputs, outcome.impact)]
            rec_id = raw.get("rec_id")
            if rec_id is None:
                rec = ctx.store.add_recommendation(
                    run_id=ctx.run_id,
                    proposal_key=str(raw.get("proposal_key") or p.proposal_id),
                    status=status,
                    proposal=p.model_dump(),
                    trigger_refs=[r.model_dump() for r in p.trigger_refs],
                    impact_calc_refs=impact_refs,
                    revision_count=round_ - 1,
                )
                rec_id = rec.id
            else:
                rec = ctx.store.set_recommendation_status(rec_id, status)
                rec.proposal = p.model_dump()
                rec.revision_count = round_ - 1
                rec.impact_calc_refs = impact_refs
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
            with ctx.lock:
                ctx.store.ctx.append_audit(
                    "recommendation_approved",
                    "recommendation",
                    rec_id,
                    actor="agent:verifier",
                    after={"round": round_, "verification_id": ver.id},
                    run_id=ctx.run_id,
                )
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
        model_ms=concurrent_ms([outcome.llm for _, _, outcome in checked], JUDGE_POOL),
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
