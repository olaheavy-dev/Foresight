"""ENG-07 persistence: forecasts and simulations from stored data, reproducible by hash."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.finance_core.calc import content_hash
from backend.finance_core.types import ScenarioModifier, ScenarioSpec
from backend.pipeline.forecast import (
    HISTORY_DAYS,
    forecast_inputs,
    run_forecast,
    run_simulation,
    store_impact_simulation,
    verify,
    verify_simulation,
)
from backend.pipeline.ingest import declare_balance, ingest_file
from backend.storage import models as m
from backend.storage.repositories import WorkspaceContext
from tests.integration.pipeline.helpers import dataset, export, workspace_with_account

pytestmark = pytest.mark.postgres


def _p1(session: Session) -> tuple[WorkspaceContext, str, date, int]:
    spec = dataset("P1-base")["workspace"]
    ctx, acct = workspace_with_account(session, buffer_minor=spec["buffer_minor"])
    name, data = export("P1-base")
    ingest_file(ctx, name, data, account_id=acct)
    declared = spec["declared_balance"]
    on, amount = date.fromisoformat(declared["as_of"]), declared["amount_minor"]
    declare_balance(ctx, acct, on, amount)
    return ctx, acct, on, amount


def test_forecast_is_persisted_and_recomputes_identically(session: Session) -> None:
    ctx, acct, on, amount = _p1(session)

    stored = run_forecast(ctx, as_of=on, n_paths=200)
    row = stored.calculation
    assert stored.created
    assert row.kind == "forecast"
    assert row.id.startswith("calc_")
    assert ctx.calculation(row.id) is row
    assert stored.inputs.starting_balance_minor == amount
    assert stored.inputs.starting_balance_provenance == "declared"
    assert stored.inputs.income_streams
    assert stored.inputs.obligations
    assert row.result["horizon_days"] == 90
    assert len(row.result["p50"]) == len(row.result["dates"])

    rebuilt = forecast_inputs(ctx, as_of=on, n_paths=200)
    assert content_hash(rebuilt) == row.inputs_hash
    assert verify(ctx, row.id)

    again = run_forecast(ctx, as_of=on, n_paths=200)
    assert not again.created
    assert again.calculation.id == row.id
    assert [e.action for e in ctx.all(m.AuditEvent)].count("forecast.rebuilt") == 1

    # New data makes the stored forecast stale rather than silently different.
    declare_balance(ctx, acct, on, amount + 100)
    with pytest.raises(ValueError, match="do not match"):
        verify(ctx, row.id)
    session.rollback()


def test_an_unchanged_question_reads_the_stored_forecast_without_recomputing(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/05 A5: read paths are cheap. Once a forecast is stored, the same question on the
    same data returns it as stored; new data computes a new one."""
    from backend.pipeline import forecast as fc

    ctx, acct, on, amount = _p1(session)
    first = run_forecast(ctx, as_of=on, n_paths=200)

    def engine_called(*_a: object, **_k: object) -> None:
        raise AssertionError("the engine ran for a forecast that was already stored")

    with monkeypatch.context() as patch:
        patch.setattr(fc, "calibration_for", engine_called)
        patch.setattr(fc, "build_forecast", engine_called)
        again = run_forecast(ctx, as_of=on, n_paths=200)
    assert not again.created
    assert again.calculation.id == first.calculation.id
    assert again.result == first.result

    declare_balance(ctx, acct, on, amount + 100)
    fresh = run_forecast(ctx, as_of=on, n_paths=200)
    assert fresh.created
    assert fresh.calculation.id != first.calculation.id
    session.rollback()


def test_product_forecast_carries_the_prior_and_a_calibration_it_can_rebuild(
    session: Session,
) -> None:
    """Engine v1.3 (docs/07 §6.2b, §6.8a): the stored forecast records the irregular-expense
    prior and the calibration fitted from the user's own past forecasts, and `verify` rebuilds
    the identical result from them."""
    ctx, _acct, on, _amount = _p1(session)
    stored = run_forecast(ctx, as_of=on, n_paths=200)
    params = stored.calculation.params
    assert params["prior"]["currency"] == "GBP"
    assert "ONS" in params["prior"]["source"]
    cal = params["calibration"]
    assert cal is not None
    assert cal["as_of"] == on.isoformat()
    assert any(b["windows"] >= 4 for b in cal["buckets"])  # a year of P1 history: calibrated
    assert stored.result.engine_version == "fc-1.3.0"
    assert verify(ctx, stored.calculation.id)
    session.rollback()


def test_simulation_is_persisted_against_the_same_baseline(session: Session) -> None:
    ctx, _, on, _ = _p1(session)
    spec = ScenarioSpec(
        name="repair",
        currency="GBP",
        modifiers=(
            ScenarioModifier(
                type="one_off_outflow", date=on + timedelta(days=5), amount_minor=50000
            ),
        ),
    )
    sim = run_simulation(ctx, spec, as_of=on, n_paths=200)
    assert sim.created
    assert sim.calculation.kind == "simulation"
    assert sim.result.simulated.min_balance_p50_minor < sim.result.baseline.min_balance_p50_minor
    assert sim.calculation.params["spec"]["name"] == "repair"
    session.rollback()


def test_without_any_balance_the_forecast_is_relative(session: Session) -> None:
    ctx, acct = workspace_with_account(session, buffer_minor=10000)
    name, data = export("P1-base")
    ingest_file(ctx, name, data, account_id=acct)
    inputs = forecast_inputs(ctx, n_paths=50)
    assert inputs.starting_balance_provenance == "relative"
    assert inputs.starting_balance_minor == 0
    assert inputs.buffer_minor is None
    session.rollback()


def test_forecast_params_state_balance_and_income_provenance(session: Session) -> None:
    """The Evidence drawer shows a calculation's params: a declared balance must say so there
    (docs/09 §11 provenance labels), and storing it must not stop the forecast recomputing."""
    ctx, _, on, _ = _p1(session)
    fc = run_forecast(ctx, as_of=on, n_paths=200)
    params = fc.calculation.params
    assert params["starting_balance_provenance"] == "declared"
    assert isinstance(params["income_provenance"], dict)
    assert params["income_provenance"]  # P1's salary is detected
    assert verify(ctx, fc.calculation.id) is True
    session.rollback()


def test_any_stored_simulation_rebuilds_identically(session: Session) -> None:
    ctx, _, on, _ = _p1(session)
    spec = ScenarioSpec(
        name="repair",
        currency="GBP",
        modifiers=(
            ScenarioModifier(type="category_cap", category_key="food.delivery",
                             monthly_cap_minor=8000, from_date=on + timedelta(days=1)),
            ScenarioModifier(type="one_off_outflow", date=on + timedelta(days=5),
                             amount_minor=50000),
        ),
    )  # fmt: skip
    sim = run_simulation(ctx, spec, as_of=on, n_paths=200)
    assert verify_simulation(ctx, sim.calculation.id) is True
    inputs = forecast_inputs(ctx, as_of=on, n_paths=200)
    impact = store_impact_simulation(ctx, inputs, spec, window_days=HISTORY_DAYS)
    assert impact.calculation.params["purpose"] == "recommendation_impact"
    assert verify_simulation(ctx, impact.calculation.id) is True
    session.rollback()


def test_the_calibration_is_fitted_once_per_data_version_across_requests(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """23 Oct 2026: every goal and Lab simulation refitted the band calibration (about 13 past
    forecasts), most of their time (about 5 s of a goal on the 2-vCPU server). The fit is reused
    from the stored forecast or the process cache until the ledger changes, and is identical to a
    fresh fit."""
    from backend.pipeline import forecast as fc

    ctx, acct, on, _amount = _p1(session)
    run_forecast(ctx, as_of=on, n_paths=200)  # seeding stores a forecast with its fit
    fits: list[int] = []
    real = fc._fit_calibration
    monkeypatch.setattr(fc, "_fit_calibration", lambda *a, **k: fits.append(1) or real(*a, **k))

    def fit_in_a_new_request() -> object:
        request = WorkspaceContext.open(session, ctx.workspace_id)  # a fresh per-request memo
        inputs = forecast_inputs(request, as_of=on, horizon_days=200)
        return fc.calibration_for(request, inputs, fc.irregular_prior(inputs.currency))

    # A cold API process: the demo pool's worker fitted it elsewhere.
    getattr(fc, "_calibrations", {}).clear()
    from_store = fit_in_a_new_request()
    assert fits == []  # read from the stored forecast
    assert fit_in_a_new_request() is from_store  # then from the process cache
    assert fits == []
    inputs = forecast_inputs(ctx, as_of=on)
    assert from_store == real(ctx, inputs, fc.irregular_prior(inputs.currency), HISTORY_DAYS)

    declare_balance(ctx, acct, on, 123_45)  # a ledger change bumps data_version
    session.commit()
    fit_in_a_new_request()
    assert fits == [1]  # refitted for the new data
