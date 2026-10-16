"""Forecast, what-if simulation and stored calculations: engine output only, no agents."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any, TypeVar

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from backend.app import views
from backend.app.session import Db, Profile
from backend.app.ui_contracts.primitives import ScenarioSpecPayload
from backend.app.ui_contracts.response import CalculationView, ForecastView, SimulationView
from backend.finance_core.calc import content_hash
from backend.finance_core.simulate import ScenarioError, horizon_covering
from backend.finance_core.types import ScenarioModifier, ScenarioSpec
from backend.pipeline.forecast import (
    NoLedgerData,
    StoredForecast,
    StoredSimulation,
    forecast_inputs,
    run_forecast,
    run_simulation,
)
from backend.storage import models as m
from backend.storage.repositories import WorkspaceContext, demo_workspace

router = APIRouter(prefix="/api", tags=["engine"])

T = TypeVar("T")
DEFAULT_HORIZON = 90
SCOPE_HELP = "mine | household | account:<acct_id> (docs/00 §13)"


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


def _persisting(ctx: WorkspaceContext, work: Callable[[], T]) -> T:
    """Run an engine call that may store a calculation. Two identical requests at once race to
    insert the same calculation id; the loser retries and reads the winner's row."""
    for attempt in (1, 2):
        try:
            value = work()
            ctx.session.commit()
            return value
        except NoLedgerData:
            ctx.session.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "There are no transactions in this profile yet. Import a statement first.",
            ) from None
        except ScenarioError as exc:
            ctx.session.rollback()
            raise _unprocessable(str(exc)) from None
        except IntegrityError:
            ctx.session.rollback()
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def resolve_scope(
    ctx: WorkspaceContext, scope: str, scope_account_id: str | None = None
) -> list[str]:
    """The forecast accounts for a scope. Stage 1 forecasts every tracked home-currency account
    together; that is "mine" (there is no joint data before Stage 4), and "account:<id>" is
    accepted when that account is the only one, because the numbers are then identical."""
    accounts = views.forecast_accounts(ctx)
    kind, _, account = scope.partition(":")
    account = account or scope_account_id or ""
    if kind == "mine" and not account:
        return accounts
    if kind == "household":
        raise _unprocessable("This profile has no joint account, so there is no household view.")
    if kind == "account" and account:
        if account not in accounts:
            raise _unprocessable(f"No forecast account {account} in this profile.")
        if accounts != [account]:
            raise _unprocessable("Per-account forecasts arrive with the multi-account layer.")
        return accounts
    raise _unprocessable(f"Unknown scope {scope!r}; use {SCOPE_HELP}.")


@router.get("/forecast", response_model=ForecastView)
def forecast(
    ctx: Profile,
    scope: str = Query(default="mine", max_length=60, description=SCOPE_HELP),
    as_of: date | None = None,
    horizon: int = Query(default=DEFAULT_HORIZON, ge=30, le=365),
) -> ForecastView:
    """The baseline forecast. Identical questions on unchanged data return the stored
    calculation; any data change gives a new one."""
    accounts = resolve_scope(ctx, scope)
    stored: StoredForecast = _persisting(
        ctx, lambda: run_forecast(ctx, as_of=as_of, horizon_days=horizon)
    )
    ws = ctx.workspace
    return ForecastView(
        forecast_id=views.content_id("fc", stored.calculation.id),
        workspace_id=ws.id,
        currency=stored.result.currency,
        locale=ws.locale,
        engine_version=stored.result.engine_version,
        data_version=stored.calculation.data_version,
        chart=views.chart_data(ctx, accounts, stored.result, stored.inputs, stored.calculation.id),
    )


# Every field the engine's ScenarioModifier has, by kind (docs/07 §6.5). Derived from the
# dataclass and checked by a unit test, so the API can never again lag behind the engine (R6).
DATE_FIELDS = frozenset({"date", "from_date", "to_date"})
INT_FIELDS = frozenset(
    {
        "amount_minor",
        "days",
        "occurrences",
        "pct",
        "instalments",
        "monthly_cap_minor",
        "buffer_minor",
    }
)
TEXT_FIELDS = frozenset(
    {"type", "label", "category_key", "income_stream_key", "recurring_id", "cadence"}
)
# The documented contract's names (docs/07 §6.5) for fields the engine names differently.
ALIASES = {"income_stream_id": "income_stream_key", "start_date": "date"}
_MODIFIER_FIELDS = DATE_FIELDS | INT_FIELDS | TEXT_FIELDS
_ACCEPTED_FIELDS = _MODIFIER_FIELDS | set(ALIASES)


def _modifier(raw: dict[str, Any], ids: Mapping[str, str] | None = None) -> ScenarioModifier:
    """An API modifier as the engine's. `ids` maps this profile's `inc_`/`rob_` ids (what
    /api/detected returns) to the engine's stream and obligation keys; keys pass through."""
    unknown = set(raw) - _ACCEPTED_FIELDS
    if unknown:
        raise _unprocessable(f"Unsupported modifier fields: {', '.join(sorted(unknown))}.")
    ids = ids or {}
    try:
        values: dict[str, Any] = {}
        for given, value in raw.items():
            name = ALIASES.get(given, given)
            if name in values and given != name:
                raise ValueError(f"{given} and {name} name the same thing; send one")
            if value is None or (name == "occurrences" and value == "all"):
                continue  # occurrences "all" (docs/07) is the engine's default: every payday
            if name in DATE_FIELDS:
                if not isinstance(value, str):
                    raise ValueError(f"{name} must be an ISO date")
                values[name] = date.fromisoformat(value)
            elif name in INT_FIELDS:
                values[name] = _int(value)
            else:
                if not isinstance(value, str):
                    raise ValueError(f"{name} must be text")
                text = value[:120]
                values[name] = (
                    ids.get(text, text) if name in ("income_stream_key", "recurring_id") else text
                )
        return ScenarioModifier(**values)
    except (ValueError, TypeError) as exc:
        raise _unprocessable(f"Invalid modifier: {exc}") from None


def _int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{value!r} is not a whole number")
    return value


def _engine_keys(ctx: WorkspaceContext) -> dict[str, str]:
    """This profile's income and recurring ids → the keys the engine knows them by."""
    rows: list[m.IncomeStream | m.RecurringObligation] = [
        *ctx.all(m.IncomeStream),
        *ctx.all(m.RecurringObligation),
    ]
    return {r.id: r.key for r in rows}


@router.post("/simulate", response_model=SimulationView)
def simulate(ctx: Profile, body: ScenarioSpecPayload) -> SimulationView:
    """A what-if against the baseline, using the same seed so the difference is the scenario's."""
    ws = ctx.workspace
    if body.currency != ws.home_currency:
        raise _unprocessable(
            f"Scenarios run in the profile's currency ({ws.home_currency}); "
            "there is no currency conversion."
        )
    if not body.modifiers:
        raise _unprocessable("A scenario needs at least one change.")
    accounts = resolve_scope(ctx, body.scope, body.scope_account_id)
    keys = _engine_keys(ctx)
    modifiers = tuple(_modifier(mod.model_dump(), keys) for mod in body.modifiers)

    def run() -> tuple[StoredForecast, StoredSimulation, ScenarioSpec]:
        # No horizon asked for: the one the Workspace uses, through the payday closing the
        # cycle the latest change lands in, at most 180 days (#55 review), so a what-if the
        # Workspace answers is answered here too.
        horizon = body.horizon_days or horizon_covering(
            forecast_inputs(ctx), ScenarioSpec(body.name, body.currency, modifiers)
        )
        spec = ScenarioSpec(body.name, body.currency, modifiers, horizon_days=horizon)
        baseline = run_forecast(ctx, horizon_days=horizon)
        return baseline, run_simulation(ctx, spec, horizon_days=horizon), spec

    baseline, sim, spec = _persisting(ctx, run)
    return SimulationView(
        simulation_id=views.content_id("sim", sim.calculation.id),
        scenario_id=views.scenario_id(spec),
        workspace_id=ws.id,
        currency=spec.currency,
        locale=ws.locale,
        engine_version=sim.result.simulated.engine_version,
        comparison=views.comparison_data(
            ctx, accounts, spec, sim.result.baseline, sim.result.simulated, baseline.inputs,
            baseline.calculation.id, sim.calculation.id,
        ),
    )  # fmt: skip


@router.get("/calculations/{calc_id}", response_model=CalculationView)
def calculation(ctx: Profile, calc_id: str) -> CalculationView:
    """A stored calculation with its inputs hash and engine version. Another profile's
    calculation is reported as not found, never as forbidden (docs/05 §7.2)."""
    calc = ctx.calculation(calc_id)
    if calc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such calculation.")
    return CalculationView(
        calc_id=calc.id,
        kind=calc.kind,
        workspace_id=ctx.workspace_id,
        currency=views.calc_currency(calc),
        inputs_hash=calc.inputs_hash,
        result_hash=content_hash(calc.result),
        engine_version=calc.engine_version,
        data_version=calc.data_version,
        duration_ms=calc.duration_ms,
        created_at=calc.created_at,
        params=calc.params,
        result=calc.result,
    )


public_router = APIRouter(prefix="/api/public", tags=["engine"])


@public_router.get("/demo-forecast", response_model=ForecastView)
def demo_forecast(db: Db) -> ForecastView:
    """The fictional P1 demo's baseline forecast for the public Landing preview. Read-only, no
    session and no cookie: visitors only get a private copy when they choose the demo."""
    template = demo_workspace(db, "P1")
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The demo profile hasn't been set up yet.")
    ctx = WorkspaceContext.open(db, template.id)
    return forecast(ctx, scope="mine", as_of=None, horizon=DEFAULT_HORIZON)
