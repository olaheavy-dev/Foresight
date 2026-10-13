"""ENG-07 persistence: forecasts and simulations from stored data, reproducible by hash."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.finance_core.calc import content_hash
from backend.finance_core.types import ScenarioModifier, ScenarioSpec
from backend.pipeline.forecast import forecast_inputs, run_forecast, run_simulation, verify
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
