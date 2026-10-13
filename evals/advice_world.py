"""`AdviceWorld`s for the core-loop suites (E-VER, E-GRD) built from a persona's truth files.

E-VER measures the Verifier, not the categoriser: spend windows, recurring payments and findings
come from the generator's truth labels, so a Verifier mistake is never caused by an upstream
categorisation error. The forecast the Verifier simulates on is the real pipeline forecast
(`evals.suites.forecast.inputs_at`), and truth recurring keys are mapped to the keys that
forecast detected (by counterparty), so timing proposals move the payments the forecast contains.

Symbolic evidence IDs follow evals/datasets/authored/README.md: `fnd:<type>:<subject>` for every
`expected_findings` × `subject` pair in `truth_anomalies.json`, `fc:baseline`, and `goal:<key>`
for goals a case supplies.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from functools import lru_cache
from typing import Any

from backend.agents.advice.world import AdviceWorld, Finding, Goal, SpendRow
from backend.finance_core.types import (
    Cadence,
    FlowKind,
    RecurringObligation,
    ScenarioModifier,
    WorkingDayShift,
)
from evals.common import build_ledger, load_dataset, uk_categorisation_pack
from evals.suites.forecast import inputs_at

BASELINE = "fc:baseline"
SHIFTS = {"next_working_day": WorkingDayShift.NEXT, "calendar_day": WorkingDayShift.NONE}


def _flow_kind(value: str) -> FlowKind:
    try:
        return FlowKind(value)
    except ValueError:
        return FlowKind.SPENDING


def _cadence(value: str) -> Cadence:
    try:
        return Cadence(value)
    except ValueError:  # e.g. "semiannual": not projected by the engine either
        return Cadence.IRREGULAR


def _current_amount(r: dict[str, Any], as_of: date, truth: list[dict[str, Any]]) -> int:
    if r.get("amount_minor") is None:  # a variable payment (e.g. a sweep): its recent median
        seen = sorted(
            int(t["amount_minor"])
            for t in truth
            if t.get("recurring") == r["key"] and str(t["date"]) <= as_of.isoformat()
        )
        return seen[len(seen) // 2] if seen else 0
    amount = int(r["amount_minor"])
    for change in sorted(r.get("price_changes") or [], key=lambda c: str(c.get("from"))):
        if str(change.get("from", "9999")) <= as_of.isoformat() and "new_minor" in change:
            amount = int(change["new_minor"])
    return amount


def _obligations(ds_name: str, as_of: date) -> dict[str, RecurringObligation]:
    ds = load_dataset(ds_name)
    out: dict[str, RecurringObligation] = {}
    for r in ds.truth_json("truth_recurring.json")["recurring"]:
        out[r["key"]] = RecurringObligation(
            key=r["key"],
            label=str(r.get("label") or r["key"]),
            category_key=str(r["category"]),
            flow_kind=_flow_kind(str(r.get("flow", "spending"))),
            amount_minor=_current_amount(r, as_of, ds.truth),
            currency=ds.home_currency,
            cadence=_cadence(str(r.get("cadence", "monthly"))),
            anchor_day=r.get("anchor_day"),
            active_months=frozenset(r.get("active_months") or range(1, 13)),
            is_commitment=bool(r.get("is_commitment")),
            shift=SHIFTS.get(str(r.get("day_rule")), WorkingDayShift.NONE),
        )
    return out


def _findings(ds_name: str) -> dict[str, Finding]:
    ds = load_dataset(ds_name)
    out: dict[str, Finding] = {}
    for a in ds.truth_json("truth_anomalies.json")["anomalies"]:
        subject = a.get("subject")
        if subject is None:
            continue
        subj = "+".join(subject) if isinstance(subject, list) else str(subject)
        for kind in a.get("expected_findings") or ():
            fid = f"fnd:{kind}:{subj}"
            out[fid] = Finding(
                id=fid, finding_type=kind, subject=subj, summary=_finding_summary(kind, subj, a)
            )
    return out


def _finding_summary(kind: str, subject: str, a: dict[str, Any]) -> str:
    texts = {
        "category_spike": f"Spending in {subject} over the last 30 days is well above its usual "
        "level for the previous three months.",
        "subscription_overlap": f"Two streaming or TV subscriptions overlap: {subject}.",
        "price_change": f"The recurring payment {subject} rose in price.",
        "income_late": f"An income payment from {subject} arrived much later than usual.",
        "amount_jump": f"The payment {subject} was much larger than usual.",
        "new_merchant": f"A large first payment to a new merchant ({subject}).",
    }
    return texts.get(kind, f"{kind} about {subject}")


@lru_cache(maxsize=4)
def base_world(ds_name: str) -> AdviceWorld:
    """The persona's world at its as_of, without any case context."""
    ds = load_dataset(ds_name)
    as_of = ds.as_of
    rows = tuple(
        SpendRow(
            on=date.fromisoformat(str(t["date"])),
            amount_minor=int(t["amount_minor"]),
            category=str(t.get("category") or "uncategorised"),
            flow_kind=str(t.get("flow") or "spending"),
            recurring_key=t.get("recurring"),
        )
        for t in ds.truth
        if date.fromisoformat(str(t["date"])) <= as_of
    )
    ledger = build_ledger(ds)
    inputs = inputs_at(ds, ledger, str(ds.accounts[0]["id"]), as_of)
    obligations = _obligations(ds_name, as_of)
    keys = {o.label.lower(): o.key for o in inputs.obligations}
    counterparties = {
        r["key"]: str(r.get("counterparty") or r.get("label") or "").lower()
        for r in ds.truth_json("truth_recurring.json")["recurring"]
    }
    mapping = {
        k: next(
            (
                det
                for det in (k, keys.get(counterparties.get(k, "")))
                if det in {o.key for o in inputs.obligations}
            ),
            k,
        )
        for k in obligations
    }
    pack = uk_categorisation_pack()
    return AdviceWorld(
        as_of=as_of,
        currency=ds.home_currency,
        locale_pack="uk",
        rows=rows,
        obligations=obligations,
        findings=_findings(ds_name),
        forecast_ids=frozenset({BASELINE}),
        protected_categories=pack.protected_categories,
        buffer_minor=inputs.buffer_minor,
        account_currencies={
            str(a["id"]): str(a.get("currency", ds.home_currency)) for a in ds.accounts
        },
        forecast_inputs=inputs,
        forecast_obligation_keys=mapping,
    )


def _modifier(d: dict[str, Any]) -> ScenarioModifier:
    fields = {f.name for f in dataclasses.fields(ScenarioModifier)}
    kw: dict[str, Any] = {}
    for k, v in d.items():
        name = "income_stream_key" if k == "income_stream_id" else k
        if name not in fields:
            continue
        if name in ("date", "from_date", "to_date") and isinstance(v, str):
            v = date.fromisoformat(v)
        kw[name] = v
    return ScenarioModifier(**kw)


def case_world(case: dict[str, Any]) -> AdviceWorld:
    """`base_world` plus the case's context: goals, opt-ins, the user's question, extra accounts
    and any scenario the question already assumes."""
    world = base_world(str(case["dataset"]))
    ctx = case.get("context") or {}
    goals = {
        str(g["id"]): Goal(
            id=str(g["id"]),
            label=str(g.get("label") or g["id"]),
            target_minor=int(g.get("target_minor") or 0),
            target_date=date.fromisoformat(g["target_date"]) if g.get("target_date") else None,
            funded_by=g.get("funded_by"),
        )
        for g in ctx.get("goals") or ()
    }
    accounts = dict(world.account_currencies)
    for a in ctx.get("extra_accounts") or ():
        accounts[str(a["id"])] = str(a["currency"])
    scenario = ctx.get("scenario")
    pending = (_modifier(scenario),) if isinstance(scenario, dict) else ()
    return dataclasses.replace(
        world,
        goals=goals,
        account_currencies=accounts,
        betting_opt_in=bool(ctx.get("betting_opt_in")),
        user_requested_category=ctx.get("user_asked_about"),
        pending_scenario=pending,
    )
