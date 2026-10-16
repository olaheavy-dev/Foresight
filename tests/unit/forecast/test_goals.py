"""Goal projection (docs/07 §6.7, `residual` funding) on P1's forecast paths."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest

from backend.finance_core.goals import (
    GoalError,
    GoalSpec,
    change_increment,
    horizon_for,
    project_goal,
)
from evals.common import build_ledger, load_dataset
from evals.suites.forecast import inputs_at


@pytest.fixture(scope="module")
def base():  # type: ignore[no-untyped-def]
    ds = load_dataset("P1-base")
    inputs = inputs_at(ds, build_ledger(ds), str(ds.accounts[0]["id"]), ds.as_of)
    return dataclasses.replace(inputs, n_paths=200, horizon_days=180)


def _goal(base, target: int, days: int = 150) -> GoalSpec:  # type: ignore[no-untyped-def]
    return GoalSpec("goal_x", "Trip", base.currency, target, base.as_of + timedelta(days=days))


def test_the_shortfall_is_the_target_less_p50_progress_to_the_penny(base) -> None:  # type: ignore[no-untyped-def]
    """SIM-11 (docs/09 §8): goal consistency."""
    for target in (10_000, 150_000, 900_000):
        r = project_goal(base, _goal(base, target))
        assert r.shortfall_minor == target - r.progress.p50
        assert r.progress.p10 <= r.progress.p50 <= r.progress.p90
        assert r.progress.p10 >= 0  # progress is floored at zero


def test_a_projection_is_deterministic_and_a_lower_target_is_never_less_likely(base) -> None:  # type: ignore[no-untyped-def]
    a = project_goal(base, _goal(base, 150_000))
    assert a == project_goal(base, _goal(base, 150_000))
    chances = [project_goal(base, _goal(base, t)).p_achieve for t in (900_000, 150_000, 1_000)]
    assert chances == sorted(chances)


def test_bands_and_the_required_monthly_change(base) -> None:  # type: ignore[no-untyped-def]
    rich = dataclasses.replace(base, starting_balance_minor=base.starting_balance_minor + 2_000_000)
    easy = project_goal(rich, _goal(base, 100))
    assert (easy.status_band, easy.required_monthly_minor) == ("on_track", 0)
    # P1's lows dip below its £500 buffer, so even a small target needs a monthly change.
    tight = project_goal(base, _goal(base, 100))
    assert tight.required_monthly_minor is not None
    hard = project_goal(base, _goal(base, 5_000_000))
    assert hard.status_band == "off_track"
    assert hard.required_monthly_minor is not None
    assert hard.required_monthly_minor > 0
    assert hard.required_monthly_minor % change_increment(base.currency) == 0  # £10 steps
    assert hard.lower_confidence  # 150 days out: beyond the 90-day band


def test_goals_the_engine_cannot_project_are_refused(base) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(GoalError, match="known balance"):
        project_goal(
            dataclasses.replace(base, starting_balance_provenance="relative"), _goal(base, 1_000)
        )
    with pytest.raises(GoalError, match="cross-currency"):
        project_goal(base, dataclasses.replace(_goal(base, 1_000), currency="EUR"))
    with pytest.raises(GoalError, match="outside the forecast"):
        project_goal(base, _goal(base, 1_000, days=400))
    with pytest.raises(GoalError):
        horizon_for(base.as_of, base.as_of + timedelta(days=366))
    assert horizon_for(base.as_of, base.as_of + timedelta(days=30)) == 90
    assert horizon_for(base.as_of, base.as_of + timedelta(days=200)) == 200


def test_the_trajectory_ends_at_the_progress_it_reports(base) -> None:  # type: ignore[no-untyped-def]
    """The chart plots progress itself: each pay cycle's low above the buffer, ending at the
    target cycle, so its last point is the projection the figures show."""
    r = project_goal(base, _goal(base, 150_000))
    assert r.trajectory_dates[-1] == r.measured_on
    last = (r.trajectory_p10[-1], r.trajectory_p50[-1], r.trajectory_p90[-1])
    assert last == (r.progress.p10, r.progress.p50, r.progress.p90)
    assert list(r.trajectory_dates) == sorted(r.trajectory_dates)


def test_on_track_needs_the_median_to_meet_the_target_as_well() -> None:
    """#54 (Codex): with an even split, p can be exactly 0.5 while the interpolated P50 misses."""
    from backend.finance_core.goals import _band

    assert _band(0.5, 149_999, 150_000) == "at_risk"
    assert _band(0.5, 150_000, 150_000) == "on_track"
    assert _band(0.2, 0, 150_000) == "off_track"


def test_spending_between_the_last_payday_and_the_target_lowers_progress(base) -> None:  # type: ignore[no-untyped-def]
    """#54 (Codex): the target cycle runs from its payday up to the goal's date, so a purchase in
    between counts (it used to be measured over the cycle before, and was left out)."""
    from backend.finance_core.forecast.engine import build_forecast
    from backend.finance_core.types import KnownFlow

    rich = dataclasses.replace(base, starting_balance_minor=base.starting_balance_minor + 900_000)
    paydays = [c.payday for c in build_forecast(rich).pay_cycles]
    payday = paydays[2]
    target = payday + timedelta(days=12)
    goal = GoalSpec("goal_x", "Trip", base.currency, 150_000, target)
    before = project_goal(rich, goal)
    spend = KnownFlow(payday + timedelta(days=5), -60_000, "Laptop")
    after = project_goal(dataclasses.replace(rich, known_flows=(spend,)), goal)
    assert after.progress.p50 == before.progress.p50 - 60_000
    assert after.measured_on == target
