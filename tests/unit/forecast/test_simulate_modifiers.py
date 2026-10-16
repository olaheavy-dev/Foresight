"""The scenario modifiers beyond v1 (docs/07 §6.5): each changes exactly what it says, on the same
draws as the baseline."""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import pytest

from backend.finance_core.simulate import ScenarioError, horizon_covering, simulate
from backend.finance_core.types import ScenarioModifier, ScenarioSpec
from evals.common import build_ledger, load_dataset
from evals.suites.forecast import inputs_at


@pytest.fixture(scope="module")
def base():  # type: ignore[no-untyped-def]
    ds = load_dataset("P1-base")
    inputs = inputs_at(ds, build_ledger(ds), str(ds.accounts[0]["id"]), ds.as_of)
    return dataclasses.replace(inputs, n_paths=100, horizon_days=120)


def _sim(base, *mods: ScenarioModifier):  # type: ignore[no-untyped-def]
    return simulate(base, ScenarioSpec("t", base.currency, tuple(mods)))


def _paydays(inputs, start: date, end: date) -> set[date]:  # type: ignore[no-untyped-def]
    from backend.finance_core.calendar import paydays_between

    return {
        d
        for st in inputs.income_streams
        if st.payday_rule is not None
        for d in paydays_between(st.payday_rule, start, end, inputs.holidays)
    }


def _end_shift(base, *mods: ScenarioModifier) -> int:  # type: ignore[no-untyped-def]
    res = _sim(base, *mods)
    return res.simulated.p50[-1] - res.baseline.p50[-1]


def test_split_outflow_takes_the_whole_amount_in_instalments(base) -> None:  # type: ignore[no-untyped-def]
    start = base.as_of + timedelta(days=5)
    mod = ScenarioModifier(
        type="split_outflow", date=start, amount_minor=30_001, instalments=3, cadence="monthly"
    )
    assert _end_shift(base, mod) == -30_001


def test_recurring_cancel_removes_every_occurrence(base) -> None:  # type: ignore[no-untyped-def]
    ob = next(o for o in base.obligations if o.key == "rob_netflix")
    mod = ScenarioModifier(
        type="recurring_cancel", recurring_id=ob.key, from_date=base.as_of + timedelta(days=1)
    )
    shift = _end_shift(base, mod)
    assert shift > 0
    assert shift % abs(ob.amount_minor) == 0


def test_recurring_change_charges_the_new_amount(base) -> None:  # type: ignore[no-untyped-def]
    ob = next(o for o in base.obligations if o.key == "rob_netflix")
    cancel = _end_shift(base, ScenarioModifier(type="recurring_cancel", recurring_id=ob.key))
    change = _end_shift(
        base,
        ScenarioModifier(
            type="recurring_change", recurring_id=ob.key, amount_minor=abs(ob.amount_minor) + 100
        ),
    )
    months = cancel // abs(ob.amount_minor)
    assert change == -100 * months


def test_income_loss_and_category_cap_and_buffer(base) -> None:  # type: ignore[no-untyped-def]
    loss = _sim(
        base, ScenarioModifier(type="income_change_pct", income_stream_key="all_income", pct=-100)
    )
    assert loss.simulated.p50[-1] < loss.baseline.p50[-1]
    cap = _end_shift(
        base,
        ScenarioModifier(type="category_cap", category_key="food.delivery", monthly_cap_minor=0),
    )
    assert cap > 0
    buffer = _sim(base, ScenarioModifier(type="buffer_override", buffer_minor=0))
    assert buffer.simulated.p50 == buffer.baseline.p50
    assert all(
        c.chance_below_buffer in (0.0, None) or c.chance_below_buffer <= 1
        for c in buffer.simulated.pay_cycles
    )


def test_unknown_targets_are_rejected_not_guessed(base) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ScenarioError):
        _sim(base, ScenarioModifier(type="recurring_cancel", recurring_id="rob_nope"))
    with pytest.raises(ScenarioError):
        _sim(base, ScenarioModifier(type="category_cut_pct", category_key="no.such", pct=10))
    with pytest.raises(ScenarioError):
        _sim(base, ScenarioModifier(type="move_to_goal", amount_minor=100, date=date(2026, 11, 1)))


def test_split_outflow_refuses_a_first_payment_on_or_before_the_forecast(base) -> None:  # type: ignore[no-untyped-def]
    mod = ScenarioModifier(
        type="split_outflow", date=base.as_of, amount_minor=30_000, instalments=3, cadence="monthly"
    )
    with pytest.raises(ScenarioError, match="not after the forecast date"):
        _end_shift(base, mod)


def test_split_outflow_refuses_instalments_past_the_horizon(base) -> None:  # type: ignore[no-untyped-def]
    start = base.as_of + timedelta(days=5)
    mod = ScenarioModifier(
        type="split_outflow", date=start, amount_minor=60_000, instalments=12, cadence="monthly"
    )
    with pytest.raises(ScenarioError, match="after the forecast horizon"):
        _end_shift(base, mod)


def test_a_what_if_dated_past_the_horizon_extends_it_to_show_the_change(base) -> None:  # type: ignore[no-untyped-def]
    """E-EFF UIQ-007: "rent goes up to £1,300 from February" on a 90-day forecast ending in
    January was refused; the horizon now runs through the payday closing the cycle the change
    lands in, at most 180 days (docs/00 §6: 365 is for goals)."""
    short = dataclasses.replace(base, horizon_days=90)
    ob = next(o for o in base.obligations if o.key == "rob_northside_lettings")
    feb = short.as_of + timedelta(days=113)
    rent = ScenarioModifier(
        type="recurring_change", recurring_id=ob.key, amount_minor=130_000, from_date=feb
    )
    spec = ScenarioSpec("t", base.currency, (rent,))
    with pytest.raises(ScenarioError, match="outside the forecast horizon"):
        simulate(short, spec)
    horizon = horizon_covering(short, spec)
    end = short.as_of + timedelta(days=horizon)
    assert end > feb  # through the payday that closes the cycle the new rent lands in
    assert end in _paydays(short, feb, end)
    res = simulate(short, dataclasses.replace(spec, horizon_days=horizon))
    assert res.simulated.p50[-1] < res.baseline.p50[-1]  # the higher rent shows
    soon = ScenarioModifier(type="one_off_outflow", amount_minor=1, date=short.as_of + timedelta(5))
    assert horizon_covering(short, dataclasses.replace(spec, modifiers=(soon,))) == 90
    split = ScenarioModifier(
        type="split_outflow", date=feb, amount_minor=900, instalments=2, cadence="monthly"
    )
    covered = short.as_of + timedelta(
        days=horizon_covering(short, dataclasses.replace(spec, modifiers=(split,)))
    )
    last_instalment = date(feb.year, 3, 1)
    assert covered > last_instalment  # the payday closing the last instalment's cycle
    assert covered in _paydays(short, last_instalment, covered)
    late = dataclasses.replace(rent, from_date=short.as_of + timedelta(days=500))
    with pytest.raises(ScenarioError, match="more than 180 days"):
        horizon_covering(short, dataclasses.replace(spec, modifiers=(late,)))


def test_a_cancellation_reaches_the_bills_next_payment_or_is_refused(base) -> None:  # type: ignore[no-untyped-def]
    """#55 review: council tax is paid on the 15th, April to January. Cancelling it from 10 Jan
    (past the 90-day forecast) runs until the 15 Jan payment; from 1 Feb its next payment is
    15 Apr, past the 180-day cap, so the what-if is refused, never answered as no change."""
    short = dataclasses.replace(base, horizon_days=90)
    year = short.as_of.year + 1

    def spec(on: date) -> ScenarioSpec:
        mod = ScenarioModifier(
            type="recurring_cancel", recurring_id="rob_leeds_city_council", from_date=on
        )
        return ScenarioSpec("t", base.currency, (mod,))

    jan = spec(date(year, 1, 10))
    horizon = horizon_covering(short, jan)
    assert short.as_of + timedelta(days=horizon) >= date(year, 1, 15)
    res = simulate(short, dataclasses.replace(jan, horizon_days=horizon))
    assert res.simulated.p50[-1] > res.baseline.p50[-1]  # January's bill is gone
    feb = spec(date(year, 2, 1))
    with pytest.raises(ScenarioError, match="no .* payment falls in the forecast"):
        simulate(short, dataclasses.replace(feb, horizon_days=horizon_covering(short, feb)))


def test_an_income_change_reaches_its_first_payday_or_is_refused(base) -> None:  # type: ignore[no-untyped-def]
    """#55 review: a pay cut from a date past the forecast runs until the stream's first payday on
    or after it (shifted paydays can be over a month apart); one that scales no payday is
    refused, never "no change"."""
    from backend.finance_core.calendar import paydays_between

    short = dataclasses.replace(base, horizon_days=90)
    stream = next(s for s in short.income_streams if s.payday_rule is not None)
    start = short.as_of + timedelta(days=100)
    cut = ScenarioModifier(
        type="income_change_pct", income_stream_key=stream.key, pct=-50, from_date=start
    )
    spec = ScenarioSpec("t", base.currency, (cut,))
    window = (start, start + timedelta(days=62), short.holidays)
    first = paydays_between(stream.payday_rule, *window)[0]
    horizon = horizon_covering(short, spec)
    assert short.as_of + timedelta(days=horizon) >= first
    res = simulate(short, dataclasses.replace(spec, horizon_days=horizon))
    assert res.simulated.p50[-1] < res.baseline.p50[-1]  # the cut payday is in the forecast
    narrow = dataclasses.replace(cut, from_date=first + timedelta(1), to_date=first + timedelta(2))
    with pytest.raises(ScenarioError, match="no .* payday falls in the period"):
        simulate(short, ScenarioSpec("t", base.currency, (narrow,), horizon_days=horizon))


def test_an_all_income_change_reaches_every_streams_first_payday(base) -> None:  # type: ignore[no-untyped-def]
    """#55 review: with two streams, the horizon runs past the later of their first changed
    paydays, so the change is applied to both, not just the earlier one."""
    from backend.finance_core.types import PaydayRule

    short = dataclasses.replace(base, horizon_days=90)
    (salary,) = short.income_streams
    side = dataclasses.replace(
        salary, key="inc_side", payday_rule=PaydayRule(kind="fixed_day", day_of_month=15)
    )
    two = dataclasses.replace(short, income_streams=(salary, side))
    start = date(short.as_of.year + 1, 1, 29)  # after the 28 Jan salary: next is 15 Feb, 26 Feb
    cut = ScenarioModifier(type="income_change_pct", pct=-50, from_date=start)
    horizon = horizon_covering(two, ScenarioSpec("t", base.currency, (cut,)))
    end = two.as_of + timedelta(days=horizon)
    assert end > date(start.year, 2, 26)  # past the salary's first cut payday (26 Feb)...
    assert end in _paydays(two, start, end)  # ...to the payday closing that cycle


def test_an_all_income_change_one_stream_cant_reach_is_refused(base) -> None:  # type: ignore[no-untyped-def]
    """#55 review: when one stream's first changed payday is past the forecast's end, the change
    would apply to the other stream only; it is refused instead of shown as partial."""
    from backend.finance_core.types import PaydayRule

    short = dataclasses.replace(base, horizon_days=90)
    (salary,) = short.income_streams
    side = dataclasses.replace(
        salary, key="inc_side", payday_rule=PaydayRule(kind="fixed_day", day_of_month=15)
    )
    two = dataclasses.replace(short, income_streams=(salary, side))
    # From 16 Dec: the salary (paid early, 18 Dec) is cut; the side income's next payday, 15 Jan,
    # is after the forecast ends on 9 Jan.
    start = date(two.as_of.year, 12, 16)
    cut = ScenarioModifier(type="income_change_pct", pct=-50, from_date=start)
    with pytest.raises(ScenarioError, match="forecast ends before the first changed payday"):
        simulate(two, ScenarioSpec("t", base.currency, (cut,)))


def test_a_date_far_past_the_cap_is_refused_not_crashed(base) -> None:  # type: ignore[no-untyped-def]
    """#55 review: 9999-12-31 overflowed `date + timedelta` before the cap applied; it now caps
    the horizon and the engine refuses the what-if with a ScenarioError."""
    short = dataclasses.replace(base, horizon_days=90)
    far = date(9999, 12, 31)
    for mod in (
        ScenarioModifier(type="one_off_outflow", date=far, amount_minor=100),
        ScenarioModifier(type="split_outflow", date=far, amount_minor=900, instalments=3),
    ):
        with pytest.raises(ScenarioError, match="more than 180 days"):
            horizon_covering(short, ScenarioSpec("t", base.currency, (mod,)))


def test_a_payment_just_before_a_shifted_payday_is_in_a_reported_low(base) -> None:  # type: ignore[no-untyped-def]
    """#55 review: a fixed 31 days could end before the next payday, leaving the payment out of
    every pay-cycle low (so the verdict could say comfortable). The horizon now ends on the
    payday closing the payment's cycle, and that cycle's low includes it."""
    short = dataclasses.replace(base, horizon_days=90)
    on = date(short.as_of.year + 1, 1, 29)  # after the 28 Jan payday: its cycle closes 26 Feb
    big = ScenarioModifier(type="one_off_outflow", date=on, amount_minor=500_000)
    spec = ScenarioSpec("t", base.currency, (big,))
    horizon = horizon_covering(short, spec)
    res = simulate(short, dataclasses.replace(spec, horizon_days=horizon))
    closing = short.as_of + timedelta(days=horizon)
    cycle = next(c for c in res.simulated.pay_cycles if c.payday == closing)
    base_cycle = next(c for c in res.baseline.pay_cycles if c.payday == closing)
    assert cycle.low.p50 <= base_cycle.low.p50 - 500_000 + 1  # the payment is in that low


def test_a_change_inside_the_forecast_after_its_last_payday_still_closes_its_cycle(base) -> None:  # type: ignore[no-untyped-def]
    """The 90-day forecast ends 9 Jan, after December's early pay (18 Dec): a payment on 20 Dec
    would sit in no reported low, so the horizon runs to the 28 Jan payday. A change whose cycle
    already closes inside the forecast keeps the usual 90 days."""
    short = dataclasses.replace(base, horizon_days=90)
    late = ScenarioModifier(
        type="one_off_outflow", date=date(short.as_of.year, 12, 20), amount_minor=100
    )
    horizon = horizon_covering(short, ScenarioSpec("t", base.currency, (late,)))
    assert short.as_of + timedelta(days=horizon) == date(short.as_of.year + 1, 1, 28)
    early = dataclasses.replace(late, date=short.as_of + timedelta(days=5))
    assert horizon_covering(short, ScenarioSpec("t", base.currency, (early,))) == 90


def test_a_bounded_change_closes_the_cycle_after_it_ends(base) -> None:  # type: ignore[no-untyped-def]
    """#55 review: a pay cut from day 100 to day 150 runs through the payday after day 150, not
    just after the first cut payday, so its last changed cycle is in a reported low."""
    short = dataclasses.replace(base, horizon_days=90)
    stream = next(s for s in short.income_streams if s.payday_rule is not None)
    first, last = short.as_of + timedelta(days=100), short.as_of + timedelta(days=150)
    cut = ScenarioModifier(
        type="income_change_pct",
        income_stream_key=stream.key,
        pct=-50,
        from_date=first,
        to_date=last,
    )
    end = short.as_of + timedelta(
        days=horizon_covering(short, ScenarioSpec("t", base.currency, (cut,)))
    )
    assert end > last
    assert end in _paydays(short, last, end)


def test_without_paydays_a_month_of_the_change_is_shown_or_it_is_refused(base) -> None:  # type: ignore[no-untyped-def]
    """#55 review: with no projected payday the horizon shows 31 days of the change; when the
    180-day cap would cut that short, the what-if is refused rather than understated."""
    bare = dataclasses.replace(base, horizon_days=90, income_streams=())

    def cap_from(days: int) -> ScenarioSpec:
        mod = ScenarioModifier(
            type="category_cap",
            category_key="groceries",
            monthly_cap_minor=10_000,
            from_date=bare.as_of + timedelta(days=days),
        )
        return ScenarioSpec("t", base.currency, (mod,))

    assert horizon_covering(bare, cap_from(100)) == 131
    with pytest.raises(ScenarioError, match="a month after"):
        horizon_covering(bare, cap_from(170))


def test_a_bounded_bill_change_closes_its_last_changed_payment_not_its_end_date(base) -> None:  # type: ignore[no-untyped-def]
    """#55 review: a rent change ending 30 Mar (day 170) last changed the 1 Mar rent; the cycle to
    close is that payment's (payday 25 Mar), which fits in 180 days, not 30 Mar's (28 Apr),
    which wouldn't."""
    short = dataclasses.replace(base, horizon_days=90)
    rent = ScenarioModifier(
        type="recurring_change",
        recurring_id="rob_northside_lettings",
        amount_minor=130_000,
        from_date=short.as_of + timedelta(days=100),
        to_date=short.as_of + timedelta(days=170),
    )
    spec = ScenarioSpec("t", base.currency, (rent,))
    horizon = horizon_covering(short, spec)  # refused before: 30 Mar's cycle closes after 180
    assert horizon <= 180
    res = simulate(short, dataclasses.replace(spec, horizon_days=horizon))
    assert res.simulated.p50[-1] < res.baseline.p50[-1]
