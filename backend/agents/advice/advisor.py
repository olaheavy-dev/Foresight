"""The Advisor (docs/06 §4.4): typed proposals from the reasoning tier, impacts from code.

The model sees aggregates only (findings, per-cycle forecast lows, per-category totals, recurring
payment labels and amounts), never raw transactions (docs/05 §7.3). After the call, each proposal's
impact is recomputed deterministically (`recompute_impact`) and that, not the model's claim, is
what the user is shown.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.agents.advice.impact import Impact, recompute_impact
from backend.agents.advice.models import AdvisorOutput, InterventionProposal
from backend.agents.advice.world import AdviceWorld
from backend.agents.cache import prompt_version
from backend.agents.prompting import system_prompt
from backend.finance_core.simulate import ScenarioError, simulate
from backend.finance_core.types import ScenarioSpec
from backend.llm.client import ModelClient, ModelResult, ModelTier

ADVISOR_PROMPT = "advisor"
SPEND_FLOWS = frozenset({"spending", "commitment", "betting"})
MAX_CATEGORIES = 12


@dataclass
class Advice:
    proposals: list[InterventionProposal]
    impacts: dict[str, Impact]
    llm: list[ModelResult] = field(default_factory=list)
    prompt_version: str = ""


def forecast_summary(world: AdviceWorld, forecast_id: str) -> dict[str, Any]:
    inputs = world.forecast_inputs
    if inputs is None:
        return {"id": forecast_id, "cycles": []}
    try:
        result = simulate(
            inputs, ScenarioSpec("baseline", inputs.currency, tuple(world.pending_scenario))
        )
    except ScenarioError:
        return {"id": forecast_id, "cycles": []}
    return {
        "id": forecast_id,
        "buffer_minor": world.buffer_minor,
        "cycles": [
            {
                "payday": c.payday.isoformat(),
                "lowest_before_payday_minor": c.low.p50,
                "low_date": c.low_date.isoformat(),
                "chance_below_buffer": c.chance_below_buffer,
            }
            for c in result.simulated.pay_cycles
        ],
    }


def spending_table(world: AdviceWorld) -> list[dict[str, Any]]:
    by_cat: dict[str, int] = defaultdict(int)
    start, end = world.window(0)
    for r in world.rows:
        if r.flow_kind in SPEND_FLOWS and start <= r.on <= end and r.amount_minor < 0:
            by_cat[r.category] += -r.amount_minor
    top = sorted(by_cat, key=lambda c: -by_cat[c])[:MAX_CATEGORIES]
    return [
        {
            "category_key": c,
            "last_30d_minor": world.last_30d(c),
            "median_3x30_minor": world.median_3x30(c),
        }
        for c in top
    ]


def recurring_table(world: AdviceWorld) -> list[dict[str, Any]]:
    return [
        {
            "recurring_id": key,
            "label": ob.label,
            "category_key": ob.category_key,
            "monthly_minor": world.monthly_amount(key),
        }
        for key, ob in sorted(world.obligations.items())
        if world.obligation_active(key)
    ]


def advisor_messages(
    world: AdviceWorld,
    *,
    forecast_id: str,
    question: str | None,
    revision: Sequence[dict[str, Any]] = (),
) -> list[dict[str, str]]:
    data = {
        "currency": world.currency,
        "as_of": world.as_of.isoformat(),
        "findings": [
            {"id": f.id, "type": f.finding_type, "about": f.subject, "summary": f.summary}
            for f in world.findings.values()
            if not f.superseded
        ],
        "forecast": forecast_summary(world, forecast_id),
        "spending": spending_table(world),
        "recurring": recurring_table(world),
        "protected": sorted(world.protected_categories - {world.user_requested_category or ""}),
        "question": question or "",
    }
    if revision:
        data["revision"] = list(revision)
    return [
        {"role": "system", "content": system_prompt(ADVISOR_PROMPT)},
        {"role": "user", "content": json.dumps({"data": data}, ensure_ascii=False, default=str)},
    ]


def advise(
    world: AdviceWorld,
    model_client: ModelClient,
    *,
    forecast_id: str,
    question: str | None = None,
    revision: Sequence[dict[str, Any]] = (),
    before_llm: Callable[[], None] | None = None,
) -> Advice:
    if before_llm is not None:
        before_llm()
    result = model_client.structured(
        tier=ModelTier.REASONING,
        messages=advisor_messages(
            world, forecast_id=forecast_id, question=question, revision=revision
        ),
        output=AdvisorOutput,
        name="advisor",
        max_tokens=1600,
        locale_pack=world.locale_pack,
    )
    proposals: list[InterventionProposal] = []
    seen: set[str] = set()
    for i, p in enumerate(result.value.proposals):
        pid = p.proposal_id if p.proposal_id and p.proposal_id not in seen else f"prp_{i + 1}"
        seen.add(pid)
        proposals.append(p.model_copy(update={"proposal_id": pid}))
    impacts = {p.proposal_id: recompute_impact(p, world) for p in proposals}
    return Advice(proposals, impacts, list(result.calls), prompt_version(ADVISOR_PROMPT))
