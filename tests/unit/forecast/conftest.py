from __future__ import annotations

from datetime import date, timedelta

import holidays
import pytest

from backend.finance_core.types import (
    Cadence,
    FlowKind,
    ForecastInputs,
    IncomeStream,
    KnownFlow,
    PaydayRule,
    Provenance,
    RecurringObligation,
)

AS_OF = date(2026, 10, 12)
EW_HOLIDAYS = frozenset(
    d
    for d in holidays.UK(subdiv="ENG", years=range(2026, 2028)).keys()  # noqa: SIM118
)


def history(as_of: date = AS_OF, days: int = 90) -> tuple[tuple[date, str, int], ...]:
    """Deterministic discretionary history: groceries twice a week, delivery most evenings."""
    rows: list[tuple[date, str, int]] = []
    for i in range(days):
        d = as_of - timedelta(days=i)
        if d.weekday() in (1, 5):
            rows.append((d, "groceries", -(4200 + (i % 5) * 310)))
        if i % 4 != 0:
            rows.append((d, "food.delivery", -(900 + (i % 7) * 120)))
        if d.weekday() == 4:
            rows.append((d, "food.eating_out", -2600))
    return tuple(rows)


def make_inputs(**overrides: object) -> ForecastInputs:
    salary = IncomeStream(
        key="inc_salary",
        source="Acme Analytics Ltd",
        amount_minor=405000,
        currency="GBP",
        cadence=Cadence.MONTHLY,
        payday_rule=PaydayRule(kind="fixed_day", day_of_month=28, december_day=18),
        provenance=Provenance.DETECTED,
    )
    obligations = (
        RecurringObligation(
            key="rob_rent",
            label="Rent",
            category_key="housing.rent",
            flow_kind=FlowKind.SPENDING,
            amount_minor=-125000,
            currency="GBP",
            cadence=Cadence.MONTHLY,
            anchor_day=1,
        ),
        RecurringObligation(
            key="rob_ctax",
            label="Council tax",
            category_key="housing.council_tax",
            flow_kind=FlowKind.SPENDING,
            amount_minor=-16200,
            currency="GBP",
            cadence=Cadence.MONTHLY,
            anchor_day=15,
            active_months=frozenset({4, 5, 6, 7, 8, 9, 10, 11, 12, 1}),
        ),
        RecurringObligation(
            key="rob_savings",
            label="Savings pot",
            category_key="savings_investment",
            flow_kind=FlowKind.SAVINGS_INVESTMENT,
            amount_minor=-40000,
            currency="GBP",
            cadence=Cadence.MONTHLY,
            anchor_day=15,
        ),
    )
    base: dict[str, object] = {
        "as_of": AS_OF,
        "currency": "GBP",
        "starting_balance_minor": 218450,
        "starting_balance_provenance": "declared",
        "income_streams": (salary,),
        "obligations": obligations,
        "known_flows": (KnownFlow(date(2026, 10, 14), -65000, "Car repair", "transport.car"),),
        "discretionary_history": history(),
        "holidays": EW_HOLIDAYS,
        "buffer_minor": 50000,
        "horizon_days": 90,
        "n_paths": 200,
        "seed": 1729,
    }
    base.update(overrides)
    return ForecastInputs(**base)  # type: ignore[arg-type]


@pytest.fixture
def inputs() -> ForecastInputs:
    return make_inputs()
