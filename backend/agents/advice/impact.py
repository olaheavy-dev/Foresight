"""Recompute a proposal's impact deterministically (docs/06 §4.4 `quantify_proposals`, V-05/V-06).

Two parts, both from code, never from the model:

- **Monthly impact** (minor units), the figure V-06 compares with the Advisor's claim (±1%). The
  basis per action follows evals/datasets/authored/README.md: a cap saves the last 30 days' spend
  above it; cancelling a bill saves its monthly amount; a downgrade saves old − new; moving a date
  changes risk, not the monthly total (0). Mixing currencies has no basis (None, V-20).
- **Risk**: the proposal is translated into ScenarioModifiers and simulated on the baseline
  forecast with the same seed (common random numbers), giving every pay cycle's lowest balance
  and chance of going below the buffer before and after.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from backend.agents.advice.models import InterventionProposal
from backend.agents.advice.world import AdviceWorld
from backend.finance_core.simulate import (
    ScenarioError,
    check_cycle_closes,
    horizon_covering,
    simulate,
)
from backend.finance_core.types import ScenarioModifier, ScenarioSpec

TIMING_ACTIONS = frozenset({"move_purchase_date", "defer_purchase", "reschedule_transfer"})


@dataclass(frozen=True)
class CycleRisk:
    payday: date
    low_p50: int
    chance_below_buffer: float | None


@dataclass(frozen=True)
class Impact:
    monthly_minor: int | None  # None: no single-currency basis (V-20)
    basis: str
    before: tuple[CycleRisk, ...] = ()
    after: tuple[CycleRisk, ...] = ()
    scenario: tuple[ScenarioModifier, ...] = ()
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def simulated(self) -> bool:
        return bool(self.before) and bool(self.after)

    def risk(self, cycles: tuple[CycleRisk, ...]) -> float | None:
        chances = [c.chance_below_buffer for c in cycles if c.chance_below_buffer is not None]
        return max(chances) if chances else None

    @property
    def risk_before(self) -> float | None:
        return self.risk(self.before)

    @property
    def risk_after(self) -> float | None:
        return self.risk(self.after)

    def cycles_made_worse(self, tolerance: float = 0.005) -> list[date]:
        """Pay cycles whose breach chance rises (V-08)."""
        out = []
        for b, a in zip(self.before, self.after, strict=False):
            if (
                b.chance_below_buffer is not None
                and a.chance_below_buffer is not None
                and a.chance_below_buffer > b.chance_below_buffer + tolerance
            ):
                out.append(b.payday)
        return out


def _int(params: dict[str, Any], key: str) -> int | None:
    value = params.get(key)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date(params: dict[str, Any], key: str) -> date | None:
    value = params.get(key)
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def monthly_impact(p: InterventionProposal, world: AdviceWorld) -> tuple[int | None, str]:
    params = p.params
    if p.currency != world.currency:
        return None, "cross_currency"
    if p.action == "cap_category":
        cap = _int(params, "monthly_cap_minor")
        cat = str(params.get("category_key") or "")
        if cap is None or not cat:
            return None, "cap_vs_last_30d"
        return max(0, world.last_30d(cat) - cap), "cap_vs_last_30d"
    if p.action == "cancel_recurring":
        key = str(params.get("recurring_id") or "")
        if world.obligation(key) is None:
            return None, "monthly_recurring_amount"
        return world.monthly_amount(key), "monthly_recurring_amount"
    if p.action == "downgrade_recurring":
        key = str(params.get("recurring_id") or "")
        new = _int(params, "new_amount_minor")
        if world.obligation(key) is None or new is None:
            return None, "old_minus_new_amount"
        return world.monthly_amount(key) - new, "old_minus_new_amount"
    return 0, "timing_only"


def _transfer_mods(p: InterventionProposal, world: AdviceWorld) -> tuple[ScenarioModifier, ...]:
    key = str(p.params.get("recurring_id") or "")
    ob = world.obligation(key)
    start, end = _date(p.params, "from_date"), _date(p.params, "to_date")
    if ob is None or start is None or end is None:
        raise ScenarioError("reschedule_transfer needs a known transfer and both dates")
    amount = abs(ob.amount_minor)
    # The occurrence nearest the stated date (a shifted direct debit can move by a few days).
    found = world.occurrences(key, start - timedelta(days=4), start + timedelta(days=4))
    if not found:
        raise ScenarioError(f"no {ob.label} payment around {start.isoformat()}")
    # Paid on its new date, however late: the impact's horizon reaches it (#57).
    return (
        ScenarioModifier(
            type="one_off_inflow", date=found[0], amount_minor=amount, label=f"{ob.label} moved"
        ),
        ScenarioModifier(
            type="one_off_outflow", date=end, amount_minor=amount, label=f"{ob.label} moved"
        ),
    )


def proposal_modifiers(p: InterventionProposal, world: AdviceWorld) -> tuple[ScenarioModifier, ...]:
    """The proposal as ScenarioModifiers on top of the world's pending scenario."""
    params = p.params
    first_day = world.as_of + timedelta(days=1)
    if p.action == "cap_category":
        return (
            ScenarioModifier(
                type="category_cap",
                category_key=str(params.get("category_key")),
                monthly_cap_minor=_int(params, "monthly_cap_minor"),
                from_date=first_day,
            ),
        )
    if p.action in ("cancel_recurring", "downgrade_recurring"):
        key = str(params.get("recurring_id") or "")
        forecast_key = world.forecast_obligation_keys.get(key, key)
        if p.action == "cancel_recurring":
            return (
                ScenarioModifier(
                    type="recurring_cancel", recurring_id=forecast_key, from_date=first_day
                ),
            )
        return (
            ScenarioModifier(
                type="recurring_change",
                recurring_id=forecast_key,
                amount_minor=_int(params, "new_amount_minor"),
                from_date=first_day,
            ),
        )
    if p.action == "reschedule_transfer":
        return _transfer_mods(p, world)
    if p.action in ("move_purchase_date", "defer_purchase"):
        amount = _int(params, "amount_minor")
        start, end = _date(params, "from_date"), _date(params, "to_date")
        if amount is None or start is None or end is None:
            raise ScenarioError(f"{p.action} needs an amount and both dates")
        if start == end:
            return ()
        label = str(params.get("label") or "purchase")
        # Paid on its new date, however late: the impact's horizon reaches it (#57).
        return (
            ScenarioModifier(type="one_off_inflow", date=start, amount_minor=amount, label=label),
            ScenarioModifier(type="one_off_outflow", date=end, amount_minor=amount, label=label),
        )
    if p.action in ("set_aside_amount", "build_buffer"):
        amount = _int(params, "amount_minor")
        if amount is None:
            raise ScenarioError(f"{p.action} needs an amount")
        return (
            ScenarioModifier(
                type="recurring_add",
                amount_minor=amount,
                cadence=str(params.get("cadence") or "monthly"),
                from_date=first_day,
                label="Set aside",
            ),
        )
    raise ScenarioError(f"no scenario for action {p.action}")


def _cycles(result: Any) -> tuple[CycleRisk, ...]:
    return tuple(
        CycleRisk(c.payday, c.low.p50, c.chance_below_buffer) for c in result.simulated.pay_cycles
    )


def recompute_impact(p: InterventionProposal, world: AdviceWorld) -> Impact:
    monthly, basis = monthly_impact(p, world)
    inputs = world.forecast_inputs
    if inputs is None or monthly is None and basis == "cross_currency":
        return Impact(monthly, basis, error="no forecast to simulate" if inputs is None else None)
    pending = tuple(world.pending_scenario)
    try:
        mods = proposal_modifiers(p, world)
        after_spec = ScenarioSpec("after", inputs.currency, (*pending, *mods))
        # Before and after run through the first payday after the latest change, so a payment
        # moved to or past the forecast's last payday is paid in a reported low instead of
        # vanishing from it; one whose cycle can't close within 180 days is refused (#57).
        horizon = horizon_covering(inputs, after_spec)
        if horizon != inputs.horizon_days:
            inputs = dataclasses.replace(inputs, horizon_days=horizon)
        before = simulate(inputs, ScenarioSpec("before", inputs.currency, pending))
        after = simulate(inputs, after_spec)
        check_cycle_closes(inputs, after_spec, after)
    except ScenarioError as exc:
        return Impact(monthly, basis, error=str(exc))
    return Impact(
        monthly,
        basis,
        before=_cycles(before),
        after=_cycles(after),
        scenario=mods,
        detail={"pending": len(pending), "modifiers": [m.type for m in mods]},
    )
