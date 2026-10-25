"""The Verifier's deterministic rules on P1's world (docs/06 §5), and the Forecaster helpers."""

from __future__ import annotations

from typing import Any

import pytest

from backend.agents.advice.models import InterventionProposal
from backend.agents.advice.rules import critique_for
from backend.agents.advice.verifier import verify
from backend.agents.forecaster import SpecModel, tier_for, to_engine_spec
from backend.llm.client import ModelTier
from evals.advice_world import BASELINE, case_world
from evals.suites.scenarios import score_case

CASE = {"dataset": "P1-base", "context": {}}


def _proposal(**over: Any) -> InterventionProposal:
    base: dict[str, Any] = {
        "proposal_id": "prp_1",
        "action": "cap_category",
        "currency": "GBP",
        "params": {"category_key": "food.delivery", "monthly_cap_minor": 16000},
        "title": "Keep food delivery under {{cap}} a month",
        "rationale": "Food delivery is above its usual level; a cap of {{cap}} brings it back.",
        "trigger_refs": [
            {"kind": "finding", "id": "fnd:category_spike:food.delivery", "role": "trigger"}
        ],
        "expected_direction": "improves_buffer",
        "claimed_monthly_impact_minor": 28640 - 16000,
    }
    base.update(over)
    return InterventionProposal.model_validate(base)


def _failed(p: InterventionProposal, **ctx: Any) -> list[str]:
    world = case_world({**CASE, "context": ctx})
    return verify(p, world, round=1, use_judge=False).verification.failed_rules


def test_a_grounded_feasible_cap_passes_every_rule() -> None:
    assert _failed(_proposal()) == []


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"trigger_refs": [{"kind": "finding", "id": "fnd:nope:x", "role": "trigger"}]}, "V-01"),
        (
            {
                "params": {"category_key": "food.delivery", "monthly_cap_minor": 4000},
                "claimed_monthly_impact_minor": 24640,
            },
            "V-04",
        ),
        ({"claimed_monthly_impact_minor": 20000}, "V-06"),
        ({"rationale": "You spend £286 on delivery."}, "V-07"),
        ({"title": "Spend less", "rationale": "Try to spend less and save more."}, "V-10"),
        (
            {
                "params": {"category_key": "family_support_abroad", "monthly_cap_minor": 20000},
                "claimed_monthly_impact_minor": 6500,
                "trigger_refs": [{"kind": "forecast", "id": BASELINE, "role": "trigger"}],
            },
            "V-17",
        ),
        ({"claimed_impact_text": "you have £20 + €30"}, "V-20"),
    ],
)
def test_each_defect_trips_its_rule(change: dict[str, Any], rule: str) -> None:
    assert rule in _failed(_proposal(**change))


def test_protected_category_is_allowed_when_the_user_asked() -> None:
    p = _proposal(
        params={"category_key": "family_support_abroad", "monthly_cap_minor": 20000},
        claimed_monthly_impact_minor=6500,
        trigger_refs=[{"kind": "forecast", "id": BASELINE, "role": "trigger"}],
    )
    assert "V-17" not in _failed(p, user_asked_about="family_support_abroad")


def test_critiques_are_templates_with_the_rule_evidence() -> None:
    world = case_world(CASE)
    v = verify(_proposal(claimed_monthly_impact_minor=1), world, round=1, use_judge=False)
    v06 = next(r for r in v.verification.deterministic if r.rule == "V-06")
    assert critique_for(v06) == "Set claimed_monthly_impact_minor to the recomputed 12640."


def test_parse_helpers() -> None:
    assert tier_for("£1,200 holiday on 6 Nov") is ModelTier.FAST
    assert tier_for("£1,200 holiday and my pay is a week late") is ModelTier.REASONING
    spec = SpecModel.model_validate(
        {
            "schema": "scenario_spec/1",
            "name": "x",
            "currency": "GBP",
            "modifiers": [
                {
                    "type": "split_outflow",
                    "start_date": "2026-11-01",
                    "amount_minor": 900,
                    "instalments": 3,
                    "cadence": "monthly",
                },
                {"type": "income_delay", "income_stream_id": "inc_salary", "days": 7},
            ],
        }
    )
    engine = to_engine_spec(spec)
    assert engine.modifiers[0].date is not None
    assert engine.modifiers[0].instalments == 3
    assert engine.modifiers[1].income_stream_key == "inc_salary"


def test_scn_scoring_ignores_labels_and_unscored_one_off_categories() -> None:
    case = {
        "id": "X",
        "needs_clarification": False,
        "gold": {
            "modifiers": [
                {
                    "type": "one_off_outflow",
                    "date": "2026-10-14",
                    "amount_minor": 65000,
                    "label": "Car repair",
                }
            ]
        },
    }

    class Parsed:
        status = "parsed"
        spec = SpecModel.model_validate(
            {
                "schema": "scenario_spec/1",
                "name": "Repair",
                "currency": "GBP",
                "modifiers": [
                    {
                        "type": "one_off_outflow",
                        "date": "2026-10-14",
                        "amount_minor": 65000,
                        "label": "Repair",
                        "category_key": "transport.car",
                    }
                ],
            }
        )

    assert score_case(case, Parsed())["exact"] is True


@pytest.mark.parametrize("horizon", [90, 140])  # the usual forecast, and one a what-if extended
def test_a_purchase_moved_onto_or_past_the_last_payday_is_paid_in_a_reported_low(
    horizon: int,
) -> None:
    """#57 (and #55 review): a payment moved to the forecast's last payday, or past its horizon,
    used to sit in no reported low, so its impact showed the payment vanishing and the
    improvement could be approved. The impact now runs through the next payday, so the payment
    is in a reported low; a move whose cycle can't close within 180 days is refused."""
    import dataclasses
    from datetime import timedelta

    from backend.agents.advice.impact import recompute_impact
    from backend.finance_core.simulate import MAX_HORIZON_DAYS, simulate
    from backend.finance_core.types import ScenarioModifier, ScenarioSpec

    base = case_world(CASE)
    assert base.forecast_inputs is not None
    inputs = dataclasses.replace(base.forecast_inputs, horizon_days=horizon)
    world = dataclasses.replace(base, forecast_inputs=inputs)
    last = simulate(inputs, ScenarioSpec("b", inputs.currency, ())).baseline.pay_cycles[-1].payday
    start = inputs.as_of + timedelta(3)

    def move(to: Any) -> Any:
        return recompute_impact(
            _proposal(
                action="move_purchase_date",
                params={"amount_minor": 50_000, "from_date": str(start), "to_date": str(to),
                        "label": "Laptop"},
            ),
            world,
        )  # fmt: skip

    for to in (last, inputs.as_of + timedelta(days=horizon + 10)):
        impact = move(to)
        assert impact.error is None, impact.error
        assert impact.after[-1].payday > to  # the cycle it's paid in closes
        # Had the payment vanished, some reported low would be higher than it is.
        refund = ScenarioModifier(
            type="one_off_inflow", date=start, amount_minor=50_000, label="Laptop"
        )
        horizon_used = (impact.after[-1].payday - inputs.as_of).days
        vanished = simulate(
            dataclasses.replace(inputs, horizon_days=max(horizon_used, horizon)),
            ScenarioSpec("v", inputs.currency, (refund,)),
        ).simulated.pay_cycles
        assert any(a.low_p50 < v.low.p50 for a, v in zip(impact.after, vanished, strict=False))
    refused = move(inputs.as_of + timedelta(days=MAX_HORIZON_DAYS)).error
    assert refused is not None
    assert move(last - timedelta(days=3)).error is None
