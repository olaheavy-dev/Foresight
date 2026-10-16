"""The response composer (docs/08 §4, §6–§9, §7a; docs/10 AGT-10).

The model chooses *what to show*; the server decides *what it says*:

1. Build a catalogue of what this run can show: the visuals the stored records support and the
   values in them, each with a short label and a key (`R1`, `R2`, …). Labels carry no figures:
   the Coordinator never sends financial data to a model (docs/05 §7.3).
2. One fast-tier call picks a verdict sentence (values only as `{{R1}}` placeholders), up to three
   key numbers and the main visual. If the call is unavailable or its output fails a check, a
   deterministic template for the intent is used instead (docs/08 §9).
3. Hydrate every block from stored calculations and the ledger (docs/08 §8), cite each value
   inline as `[n]` (docs/05 §4.2 stage 5), place blocks by the per-intent slot table and enforce
   the answer skeleton (docs/08 §7a), screen the model's text (docs/05 §7.4a L4) and validate the
   whole envelope against `agent_response/1`.

The model never supplies a number, a tone or a placement.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select

from backend.agents.cache import prompt_version
from backend.agents.contracts import PAY_TODAY
from backend.agents.guard import output_screen
from backend.agents.prompting import active_canary, system_prompt
from backend.agents.runtime import NodeOutput, RunContext
from backend.agents.state import ForesightState
from backend.app import views
from backend.app.ui_contracts.blocks import (
    AgentExecutionTimeline,
    AgentStepView,
    CashFlowForecastChart,
    CategoryLabel,
    CategorySeries,
    ClarifyingQuestion,
    EntitySegment,
    EvidenceItem,
    EvidencePanel,
    FinancialMetricGroup,
    InterventionCard,
    Metric,
    Narrative,
    Reproducible,
    Risk,
    RiskAssessment,
    RunCost,
    ScenarioComparison,
    Segment,
    SpendingByCategory,
    TextSegment,
    TransactionRow,
    TransactionTable,
    ValueSegment,
)
from backend.app.ui_contracts.money import money_value
from backend.app.ui_contracts.primitives import (
    ULID,
    AskAction,
    AskPayload,
    DateRange,
    DateValue,
    MoneyAmount,
    MoneyValue,
    OverviewPlacement,
    PercentValue,
    TabPlacement,
    TxnQuery,
)
from backend.app.ui_contracts.response import (
    AgentResponse,
    EvidenceLine,
    ResponseProvenance,
)
from backend.app.ui_contracts.validation import (
    Issue,
    check_currency,
    enforce_skeleton,
    strip_numeral_sentences,
)
from backend.finance_core.calc import record
from backend.finance_core.forecast.engine import ENGINE_VERSION
from backend.finance_core.types import ScenarioSpec
from backend.mesh.mesh_client import ModelTier
from backend.pipeline.forecast import (
    NoLedgerData,
    StoredForecast,
    run_forecast,
    run_simulation,
    spec_from_json,
)
from backend.pipeline.packs import UnsupportedCountry, categorisation_pack
from backend.storage import models as m
from backend.storage.ids import new_id
from backend.storage.repositories import WorkspaceContext

log = logging.getLogger("foresight.compose")

COMPOSE_PROMPT = "compose"
AGGREGATE_VERSION = "agg-1.0.0"

# Routing intent (docs/06 §4.0) → ResponsePlan intent (docs/08 §4.1).
PLAN_INTENT: dict[str, str] = {
    "affordability": "affordability",
    "scenario": "scenario",
    "spending_breakdown": "spending_question",
    "trend_or_change": "spending_question",
    "subscription_review": "spending_question",
    "transaction_lookup": "transaction_lookup",
    "goal_status": "goal_check",
    "risk_check": "risk_review",
    "advice_request": "risk_review",
    "explain_recommendation": "recommendation_review",
    "smalltalk_or_out_of_scope": "smalltalk_or_unsupported",
}

# docs/08 §7a: the main visual for each intent, in order of preference. The first one this run's
# records can support is the main visual: the table decides, never the model.
MAIN_VISUALS: dict[str, tuple[str, ...]] = {
    "affordability": ("ScenarioComparison", "CashFlowForecastChart"),
    "scenario": ("ScenarioComparison", "CashFlowForecastChart"),
    "spending_breakdown": ("SpendingBreakdownChart", "TransactionTable"),
    "trend_or_change": ("SpendingBreakdownChart", "TransactionTable"),
    "subscription_review": ("TransactionTable", "SpendingBreakdownChart"),
    "transaction_lookup": ("TransactionTable",),
    "goal_status": ("FinancialMetricGroup", "CashFlowForecastChart"),
    "risk_check": ("RiskAssessment", "CashFlowForecastChart"),
    "advice_request": ("InterventionCard", "CashFlowForecastChart"),
    "explain_recommendation": ("EvidencePanel",),
}
# The Details tab: the deeper view for the question (docs/08 §7a).
DETAILS: dict[str, tuple[str, ...]] = {
    "affordability": ("CashFlowForecastChart",),
    "scenario": ("CashFlowForecastChart",),
    "risk_check": ("CashFlowForecastChart",),
    "advice_request": ("ScenarioComparison",),  # the effect of the checked option
    "goal_status": ("CashFlowForecastChart",),
    "spending_breakdown": ("SpendingBreakdownChart",),
    "trend_or_change": ("SpendingBreakdownChart",),
    "subscription_review": ("SpendingBreakdownChart",),  # price changes over time
    "transaction_lookup": ("TransactionTable",),  # the full filtered list
    "explain_recommendation": ("EvidencePanel",),  # the calculation inputs
}
# Kinds the Details tab repeats in full even when the Overview already shows them (docs/08 §7a:
# "full filtered list", "calculation inputs"); every other kind appears once per answer.
DETAIL_REPEATS = frozenset({"TransactionTable", "EvidencePanel"})
SPENDING_FLOWS = frozenset(
    {None, "spending", "commitment", "loan_repayment", "fee", "tax", "betting"}
)
TRANSACTION_INTENTS = frozenset(
    {"spending_breakdown", "trend_or_change", "subscription_review", "transaction_lookup"}
)
ADVICE_INTENTS = frozenset(
    {"affordability", "advice_request", "risk_check", "subscription_review", "goal_status"}
)

# Templated text (never model text).
FALLBACK_VERDICT: dict[str, str] = {
    "affordability": "Here is how that would change your balance before each payday.",
    "scenario": "Here is how that change plays out against your current path.",
    "spending_breakdown": "Here is where your money went.",
    "trend_or_change": "Here is how your spending compares with your usual pattern.",
    "subscription_review": "Here are your regular payments.",
    "transaction_lookup": "Here are the matching transactions.",
    "goal_status": "Here is how your balance is set to develop.",
    "risk_check": "Here is how your balance looks before each payday.",
    "advice_request": "Here is what the forecast shows and what was checked.",
    "explain_recommendation": "Here is the evidence behind the recommendation.",
}
# docs/05 §7.5: free help signposts (on the output screen's link allow-list).
WHAT_ELSE = {
    "uk": "None of the checked changes fully closes the gap. Free, impartial help with money "
    "worries is available from MoneyHelper: moneyhelper.org.uk.",
    "in": "None of the checked changes fully closes the gap. A free debt-advice service can "
    "help you plan what to do next.",
}
STARTER_QUESTIONS = (
    ("Lowest balance before payday", "How low will my balance get before payday?"),
    ("Where my money went", "Where did my money go in the last 30 days?"),
    ("Salary a week late", "What if my salary is a week late?"),
)


# --------------------------------------------------------------------------- model output


class ComposerOutput(BaseModel):
    """What the composer model may say: choices and placeholders, never values."""

    verdict: str = Field(max_length=300)
    key_numbers: list[str] = Field(default_factory=list, max_length=3)
    main_visual: str = Field(max_length=40)


# --------------------------------------------------------------------------- catalogue


@dataclass
class CatalogueValue:
    key: str  # R1, R2, …
    label: str  # no figures
    value: Any  # a hydrated Value (MoneyValue, PercentValue, DateValue …) with a ref
    cite: str | None = None  # the engine value it derives from, when shown as a magnitude


VerdictKind = Literal["goes_negative", "breaches_buffer", "tight", "comfortable"]
VERDICT_INTENTS = frozenset({"affordability", "scenario", "risk_check"})


@dataclass
class VerdictCase:
    """The deterministic answer (docs/08 §5.4 rule, over every pay cycle, naming the worst)."""

    kind: VerdictKind
    template: str  # with {{Rn}} placeholders filled from engine values
    payday: date | None
    shortfall_below: int | None  # the threshold the worst cycle falls under (0 or the buffer)


@dataclass
class Sources:
    """The stored records this run can show."""

    forecast: StoredForecast | None = None
    simulations: list[tuple[m.Calculation, ScenarioComparison]] = field(default_factory=list)
    spending: SpendingByCategory | None = None
    recommendations: list[InterventionCard] = field(default_factory=list)
    calcs: dict[str, m.Calculation] = field(default_factory=dict)
    values: list[CatalogueValue] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def add_value(self, label: str, value: Any, cite: str | None = None) -> str | None:
        if value is None:
            return None
        key = f"R{len(self.values) + 1}"
        self.values.append(CatalogueValue(key, label, value, cite))
        return key

    def value(self, key: str) -> CatalogueValue | None:
        return next((v for v in self.values if v.key == key), None)


def _place_overview(slot: str) -> OverviewPlacement:
    return OverviewPlacement(area="overview", slot=slot)  # type: ignore[arg-type]


def _place_tab(tab: str) -> TabPlacement:
    return TabPlacement(area="tab", tab=tab)  # type: ignore[arg-type]


PLACEHOLDER_TAB = _place_tab("details")  # temporary placement; the slot table assigns real ones


def _resolve(data: Any, path: str) -> Any:
    node = data
    for part in path.split("."):
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict):
            node = node[part]
        else:
            raise KeyError(path)
    return node


def _scenario_spec(params: dict[str, Any]) -> ScenarioSpec:
    # Every modifier field (caps, start dates, recurring ids), not a subset: a simulation is
    # rebuilt from exactly the spec it was stored with.
    return spec_from_json(params["spec"])


class Composer:
    """Builds one answer. Every value comes from a stored record; nothing is invented."""

    def __init__(self, ctx: WorkspaceContext, state: ForesightState, run_id: str) -> None:
        self.ctx = ctx
        self.state = state
        self.run_id = run_id
        ws = ctx.workspace
        self.locale = ws.locale
        self.currency = ws.home_currency
        self.intent: dict[str, Any] = dict(state.get("intent") or {})
        self.name = str(self.intent.get("intent") or "")
        self.slots: dict[str, Any] = dict(self.intent.get("slots") or {})
        self.sources = Sources()
        self.issues: list[Issue] = []
        self.citations: dict[str, int] = {}
        self.screen_kinds: list[str] = []
        self.case: VerdictCase | None = None
        self._block_seq = 0

    # ------------------------------------------------------------------ helpers

    def block_id(self, kind: str) -> str:
        self._block_seq += 1
        return f"b{self._block_seq}-{kind.lower()}"

    def money(self, minor: int, precision: str, ref: str | None) -> MoneyValue:
        return money_value(
            MoneyAmount(amount_minor=minor, currency=self.currency),
            self.locale,
            precision,  # type: ignore[arg-type]
            ref,
        )

    # ------------------------------------------------------------------ sources

    def gather(self) -> Sources:
        """Load what the specialists produced (refs in the state) plus the baseline forecast."""
        src = self.sources
        if self.name in MAIN_VISUALS or self.name in DETAILS:
            src.forecast = self._forecast()
        for ref in self._simulation_refs():
            self._simulation(ref)
        if self.name in {"spending_breakdown", "trend_or_change", "subscription_review"}:
            src.spending = self._spending()
        for rec_id in self.state.get("approved_recs") or []:
            card = self._intervention(str(rec_id))
            if card is not None:
                src.recommendations.append(card)
        if self.name == "advice_request" and not src.simulations:
            # "Effect of each option" (docs/08 §7a): the checked option's stored impact.
            for ref in self._impact_refs()[:1]:
                self._simulation(ref)
        self._catalogue_values()
        self.case = self._verdict_case() if self.name in VERDICT_INTENTS else None
        return src

    def _impact_refs(self) -> list[str]:
        out: list[str] = []
        for rec_id in self.state.get("approved_recs") or []:
            rec = self.ctx.get(m.Recommendation, str(rec_id))
            for cid in (rec.impact_calc_refs if rec else []) or []:
                calc = self.ctx.calculation(str(cid))
                if calc is not None and calc.kind == "simulation":
                    out.append(calc.id)
        return out

    def _verdict_case(self) -> VerdictCase | None:
        """docs/08 §5.4: goes_negative if any cycle's likely low is below £0; breaches_buffer if
        any is below the buffer; tight if any unlucky (P10) low is; else comfortable. Uses the
        scenario when there is one, else the baseline. None without a buffer (relative mode)."""
        if self.sources.simulations:
            calc = self.sources.simulations[0][0]
            result, prefix = (calc.result or {}).get("simulated") or {}, "simulated."
        elif self.sources.forecast is not None:
            calc = self.sources.forecast.calculation
            result, prefix = calc.result or {}, ""
            if self.chart().buffer_minor is None:
                return None
        else:
            return None
        buffer = result.get("buffer_minor")
        cycles = list(result.get("pay_cycles") or [])
        if buffer is None or not cycles:
            return None

        def low(c: dict[str, Any], q: str) -> int:
            return int((c.get("low") or {}).get(q, 0))

        def pick(test: Callable[[dict[str, Any]], bool], q: str) -> tuple[int, dict[str, Any]]:
            hits = [(i, c) for i, c in enumerate(cycles) if test(c)]
            return min(hits, key=lambda ic: low(ic[1], q)) if hits else (-1, {})

        base = f"{calc.id}#{prefix}pay_cycles"
        now = "This would take you" if self.sources.simulations else "On your current path you'd be"

        def payday_key(i: int, c: dict[str, Any]) -> str | None:
            on = date.fromisoformat(str(c["payday"]))
            return self.sources.add_value(
                "Payday that ends the worst pay cycle",
                DateValue(kind="date", value=on, display=views.short_date(on),
                          ref=f"{base}.{i}.payday"),
            )  # fmt: skip

        i, c = pick(lambda c: low(c, "p50") < 0, "p50")
        if c:
            p50 = low(c, "p50")
            short = self.sources.add_value(
                "How far below zero the balance goes in the worst pay cycle (likely)",
                self.money(-p50, "rounded", None),
                cite=f"{base}.{i}.low.p50",
            )
            day = payday_key(i, c)
            return VerdictCase(
                "goes_negative",
                f"{now} about {{{{{short}}}}} overdrawn before your {{{{{day}}}}} payday.",
                date.fromisoformat(str(c["payday"])),
                0,
            )
        i, c = pick(lambda c: low(c, "p50") < buffer, "p50")
        if c:
            buf = self.sources.add_value(
                "Your buffer", self.money(buffer, "rounded", f"{calc.id}#{prefix}buffer_minor")
            )
            day = payday_key(i, c)
            return VerdictCase(
                "breaches_buffer",
                f"You'd stay above {self.money(0, 'rounded', None).display} but drop below your "
                f"{{{{{buf}}}}} buffer before "
                f"{{{{{day}}}}}.",
                date.fromisoformat(str(c["payday"])),
                buffer,
            )
        i, c = pick(lambda c: low(c, "p10") < buffer, "p10")
        if c:
            day = payday_key(i, c)
            return VerdictCase(
                "tight",
                f"Likely fine, but in some outcomes you dip below your buffer before "
                f"{{{{{day}}}}}.",
                date.fromisoformat(str(c["payday"])),
                None,
            )
        lead = "Yes. " if self.sources.simulations else ""
        return VerdictCase(
            "comfortable", f"{lead}You stay above your buffer in every pay cycle.", None, None
        )

    def _forecast(self) -> StoredForecast | None:
        try:
            stored = run_forecast(self.ctx)
        except NoLedgerData:
            self.sources.issues.append("no ledger data: no forecast to show")
            return None
        self.sources.calcs[stored.calculation.id] = stored.calculation
        return stored

    def _simulation_refs(self) -> list[str]:
        refs: list[str] = []
        for raw in self.state.get("simulation_ids") or []:
            text = str(raw)
            refs.append("calc_" + text.removeprefix("sim_") if text.startswith("sim_") else text)
        return refs

    def _simulation(self, calc_id: str) -> None:
        calc = self.ctx.calculation(calc_id)
        if calc is None or calc.kind != "simulation":
            self.sources.issues.append(f"simulation {calc_id} not found")
            return
        try:
            spec = _scenario_spec(calc.params)
            horizon = spec.horizon_days or int(calc.params.get("horizon_days") or 90)
            baseline = run_forecast(self.ctx, horizon_days=horizon)
            sim = run_simulation(self.ctx, spec, horizon_days=horizon)
            accounts = views.forecast_accounts(self.ctx)
            data = views.comparison_data(
                self.ctx, accounts, spec, sim.result.baseline, sim.result.simulated,
                baseline.inputs, baseline.calculation.id, sim.calculation.id,
            )  # fmt: skip
        except (KeyError, TypeError, ValueError) as exc:
            self.sources.issues.append(f"simulation {calc_id} could not be hydrated: {exc}")
            return
        block = ScenarioComparison(
            type="ScenarioComparison",
            block_id=self.block_id("scenario"),
            title="With and without the change",
            currency=sim.result.simulated.currency,
            placement=PLACEHOLDER_TAB,
            evidence=[sim.calculation.id + "#simulated.min_balance_p50_minor"],
            **data.model_dump(by_alias=True),
        )
        # The baseline the comparison cites: the usual forecast, or a longer one when the what-if
        # was extended past 90 days, so its figures are in the answer's evidence too (#55 review).
        self.sources.calcs.setdefault(baseline.calculation.id, baseline.calculation)
        self.sources.calcs[sim.calculation.id] = sim.calculation
        self.sources.simulations.append((sim.calculation, block))

    def _period(self) -> tuple[date, date]:
        """The question's period from its slots; otherwise the last 30 days of data."""
        latest = self.ctx.session.scalar(
            select(func.max(m.Transaction.posted_on)).where(
                m.Transaction.workspace_id == self.ctx.workspace_id,
                m.Transaction.status == "active",
            )
        )
        end = latest or date.today()
        start = end - timedelta(days=29)
        for key in ("date_from", "from", "start"):
            if isinstance(self.slots.get(key), str):
                try:
                    start = date.fromisoformat(self.slots[key])
                except ValueError:
                    pass
        for key in ("date_to", "to", "end"):
            if isinstance(self.slots.get(key), str):
                try:
                    end = date.fromisoformat(self.slots[key])
                except ValueError:
                    pass
        return (start, end) if start <= end else (end, start)

    def _category_filter(self) -> list[str] | None:
        raw = self.slots.get("category_key") or self.slots.get("category")
        if isinstance(raw, list):
            return [str(x) for x in raw if x]
        return [str(raw)] if isinstance(raw, str) and raw else None

    def _spending_rows(
        self, start: date, end: date
    ) -> list[tuple[m.Transaction, m.Categorisation | None]]:
        total, rows = self.ctx.transaction_page(date_from=start, date_to=end, limit=5000)
        return rows

    def _spending(self) -> SpendingByCategory | None:
        """A by-category spending aggregate, executed during hydration and persisted as an
        `aggregate` Calculation so the answer stays reproducible (docs/08 §8)."""
        start, end = self._period()
        rows = self._spending_rows(start, end)
        try:
            pack_categories = categorisation_pack(self.ctx.workspace.country).categories
        except UnsupportedCountry:
            pack_categories = {}
        totals: dict[str, int] = {}
        for txn, cat in rows:
            if txn.currency != self.currency or txn.amount_minor >= 0:
                continue
            key = cat.category_key if cat is not None and cat.category_key else "uncategorised"
            flow = cat.flow_kind if cat is not None else None
            if flow not in SPENDING_FLOWS:
                continue
            totals[key] = totals.get(key, 0) + (-txn.amount_minor)
        if not totals:
            self.sources.issues.append("no spending in the period")
            return None
        ordered = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
        top, rest = ordered[:7], ordered[7:]
        if rest:
            top.append(("other", sum(v for _, v in rest)))
        grand = sum(totals.values())
        result = {
            "currency": self.currency,
            "period": {"from": start.isoformat(), "to": end.isoformat()},
            "total_minor": grand,
            "series": [{"key": k, "minor": v} for k, v in top],
        }
        calc = self._store_aggregate(
            {"kind": "spending_by_category", "from": start.isoformat(), "to": end.isoformat()},
            result,
        )
        nature_map = {
            "essential": "essential", "commitment": "commitment", "discretionary":
            "discretionary", "debt": "debt", "savings": "savings", "tax": "tax",
        }  # fmt: skip
        series: list[CategorySeries] = []
        for i, (key, minor) in enumerate(top):
            info = pack_categories.get(key)
            nature = nature_map.get(info.nature if info is not None else "", "discretionary")
            share = minor / grand if grand else 0.0
            series.append(
                CategorySeries(
                    key=key,
                    label=key.replace(".", " · ").replace("_", " ").capitalize(),
                    nature=nature,  # type: ignore[arg-type]
                    value=self.money(minor, "exact", f"{calc.id}#series.{i}.minor"),
                    share=PercentValue(
                        kind="percent", value=round(share, 4), display=f"{round(share * 100)}%"
                    ),
                    tone="neutral",
                )  # fmt: skip
            )
        highlight = [k for k in (self._category_filter() or []) if k in totals]
        return SpendingByCategory(
            type="SpendingBreakdownChart",
            block_id=self.block_id("spending"),
            title="Spending by category",
            currency=self.currency,
            placement=PLACEHOLDER_TAB,
            evidence=[f"{calc.id}#total_minor"],
            mode="by_category",
            period=DateRange(**{"from": start, "to": end}),
            total=self.money(grand, "exact", f"{calc.id}#total_minor"),
            highlight_keys=highlight,
            series=series,
        )

    def _store_aggregate(self, params: dict[str, Any], result: dict[str, Any]) -> m.Calculation:
        params = {**params, "workspace_id": self.ctx.workspace_id,
                  "data_version": self.ctx.workspace.data_version}  # fmt: skip
        rec = record("aggregate", params, params, result, AGGREGATE_VERSION)
        existing = self.ctx.calculation(rec.id)
        if existing is not None:
            self.sources.calcs[existing.id] = existing
            return existing
        row = m.Calculation(
            id=rec.id,
            kind=rec.kind,
            inputs_hash=rec.inputs_hash,
            params=rec.params,
            result=rec.result,
            engine_version=rec.engine_version,
            data_version=self.ctx.workspace.data_version,
            duration_ms=0,
        )
        self.ctx.add(row)
        self.ctx.session.flush()
        self.sources.calcs[row.id] = row
        return row

    def _intervention(self, rec_id: str) -> InterventionCard | None:
        """A checked recommendation as stored by the Advisor ⇄ Verifier loop. The stored proposal
        must already carry hydrated fields (`card`); anything missing drops the card, never
        invents it."""
        rec = self.ctx.get(m.Recommendation, rec_id)
        if rec is None or rec.status not in {"approved", "accepted"}:
            self.sources.issues.append(f"recommendation {rec_id} is not approved")
            return None
        card = (rec.proposal or {}).get("card")
        if not isinstance(card, dict):
            self.sources.issues.append(f"recommendation {rec_id} has no hydrated card")
            return None
        try:
            return InterventionCard.model_validate(
                {
                    **card,
                    "type": "InterventionCard",
                    "block_id": self.block_id("intervention"),
                    "placement": PLACEHOLDER_TAB.model_dump(),
                    "recommendation_id": rec.id,
                    "status": rec.status,
                }
            )
        except ValueError as exc:
            self.sources.issues.append(f"recommendation {rec_id} card invalid: {exc}")
            return None

    def _catalogue_values(self) -> None:
        src = self.sources
        if src.forecast is not None:
            chart = self.chart()
            first = chart.pay_cycles[0] if chart.pay_cycles else None
            src.add_value("Balance today", chart.summary.starting_balance.money)
            if first is not None:
                src.add_value("Lowest balance before the next payday (likely)", first.low)
                src.add_value("Date of the lowest balance before the next payday",
                              self._date_value(first.low_date, first.low.ref))  # fmt: skip
                src.add_value("Chance of going below your buffer before the next payday",
                              first.chance_below_buffer)  # fmt: skip
            src.add_value("Lowest balance over the forecast (likely)", chart.summary.min_balance)
            src.add_value("Date of the lowest balance over the forecast", chart.summary.min_date)
        for _, block in src.simulations:
            for row in block.comparison_rows:
                src.add_value(f"{row.metric_label}, without the change", row.baseline)
                for value in row.scenarios[:1]:
                    src.add_value(f"{row.metric_label}, with the change", value)
        if src.spending is not None:
            src.add_value("Total spending in the period", src.spending.total)
            for s in src.spending.series[:3]:
                src.add_value(f"Spending on {s.label}", s.value)

    def _date_value(self, on: date, money_ref: str | None) -> Any:
        from backend.app.ui_contracts.primitives import DateValue

        ref = None
        if money_ref and "#" in money_ref:
            base, _, path = money_ref.partition("#")
            ref = f"{base}#{path.rsplit('.low', 1)[0]}.low_date" if ".low" in path else None
        return DateValue(kind="date", value=on, display=views.short_date(on), ref=ref)

    _chart_cache: CashFlowForecastChart | None = None

    def chart(self) -> CashFlowForecastChart:
        if self._chart_cache is None:
            stored = self.sources.forecast
            assert stored is not None
            accounts = views.forecast_accounts(self.ctx)
            data = views.chart_data(
                self.ctx, accounts, stored.result, stored.inputs, stored.calculation.id
            )
            self._chart_cache = CashFlowForecastChart(
                type="CashFlowForecastChart",
                block_id=self.block_id("forecast"),
                title="Balance before each payday",
                currency=stored.result.currency,
                placement=PLACEHOLDER_TAB,
                evidence=[f"{stored.calculation.id}#min_balance_p50_minor"],
                **data.model_dump(by_alias=True),
            )
        return self._chart_cache

    # ------------------------------------------------------------------ choices

    def available_visuals(self) -> list[str]:
        src = self.sources
        can = {
            "CashFlowForecastChart": src.forecast is not None,
            "ScenarioComparison": bool(src.simulations),
            "SpendingBreakdownChart": src.spending is not None,
            "TransactionTable": self.name in TRANSACTION_INTENTS,
            "InterventionCard": bool(src.recommendations),
            "EvidencePanel": bool(src.calcs),
            "FinancialMetricGroup": len(src.values) >= 2,
            "RiskAssessment": src.forecast is not None
            and self.chart().buffer_minor is not None
            and bool(self.chart().pay_cycles),
        }
        return [v for v in MAIN_VISUALS.get(self.name, ()) if can.get(v)]

    def template_output(self) -> ComposerOutput:
        visuals = self.available_visuals()
        keys = [v.key for v in self.sources.values[:3]]
        verdict = (
            self.case.template
            if self.case is not None
            else FALLBACK_VERDICT.get(self.name, "Here is what your data shows.")
        )
        return ComposerOutput(
            verdict=verdict, key_numbers=keys, main_visual=visuals[0] if visuals else ""
        )

    def model_messages(self, question: str) -> list[dict[str, str]]:
        payload = {
            "question": question,
            "intent": self.name,
            "needs_advice": bool(self.intent.get("needs_advice")),
            "checked_recommendations": len(self.sources.recommendations),
            "visual_options": self.available_visuals()[:1],
            "values": [{"key": v.key, "label": v.label} for v in self.sources.values],
        }
        if self.case is not None:
            payload["verdict_category"] = self.case.kind
        return [
            {"role": "system", "content": system_prompt(COMPOSE_PROMPT)},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

    def check_output(self, out: ComposerOutput) -> tuple[ComposerOutput, list[str]]:
        """Keep only valid choices; reject text that breaks the output screen (docs/05 §7.4a)."""
        problems: list[str] = []
        keys = {v.key for v in self.sources.values}
        template = self.template_output()
        verdict = out.verdict.strip()
        unknown = [
            k for k in re.findall(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", verdict) if k not in keys
        ]
        if unknown:
            problems.append(f"unknown placeholders {unknown}")
            verdict = re.sub(r"\{\{\s*[A-Za-z0-9_]+\s*\}\}", "", verdict)
        violations = output_screen(
            verdict, locale_pack=str(self.state.get("locale_pack") or "uk"),
            canary=active_canary(),
        )  # fmt: skip
        self.screen_kinds = sorted({v.kind for v in violations})
        if any(v.kind != "numeral" for v in violations):
            problems.append("output screen: " + ", ".join(self.screen_kinds))
            verdict = ""
        elif violations:
            problems.append("numerals outside placeholders")
            verdict = strip_numeral_sentences(verdict)
        if verdict.strip() and self.case is not None and contradicts(self.case.kind, verdict):
            problems.append(f"verdict contradicts the engine ({self.case.kind})")
            verdict = ""
        if not verdict.strip():
            verdict = template.verdict
        numbers = [k for k in out.key_numbers if k in keys][:3] or template.key_numbers
        # The main visual is the §7a table's choice for the intent, never the model's.
        main = template.main_visual
        return ComposerOutput(verdict=verdict, key_numbers=numbers, main_visual=main), problems

    # ------------------------------------------------------------------ hydration

    def cite(self, ref: str) -> int:
        if ref not in self.citations:
            self.citations[ref] = len(self.citations) + 1
        return self.citations[ref]

    def narrative(self, text: str) -> Narrative:
        segments: list[Segment] = []
        evidence: list[str] = []
        pos = 0
        for match in re.finditer(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", text):
            if match.start() > pos:
                segments.append(TextSegment(kind="text", text=text[pos : match.start()]))
            item = self.sources.value(match.group(1))
            if item is not None:
                segments.append(ValueSegment(kind="value", value=item.value))
                ref = getattr(item.value, "ref", None) or item.cite
                if ref:
                    n = self.cite(ref)
                    segments.append(EntitySegment(kind="entity", ref=ref, label=f"[{n}]"))
                    evidence.append(ref)
            pos = match.end()
        if pos < len(text):
            segments.append(TextSegment(kind="text", text=text[pos:]))
        if not segments:
            segments = [TextSegment(kind="text", text=text or "Here is what your data shows.")]
        currencies = {
            seg.value.currency
            for seg in segments
            if isinstance(seg, ValueSegment) and isinstance(seg.value, MoneyValue)
        }
        return Narrative(
            type="Narrative",
            block_id=self.block_id("verdict"),
            currency=next(iter(currencies)) if len(currencies) == 1 else None,
            placement=_place_overview("verdict"),
            evidence=list(dict.fromkeys(evidence)),
            segments=segments,
        )

    def metrics(self, keys: Sequence[str]) -> FinancialMetricGroup | None:
        items = [v for k in keys if (v := self.sources.value(k)) is not None]
        if not items:
            return None
        chart = self.chart() if self.sources.forecast is not None else None
        buffer = chart.buffer_minor if chart is not None else None
        metrics: list[Metric] = []
        for i, item in enumerate(items):
            value = item.value
            tone = "neutral"
            if isinstance(value, MoneyValue) and buffer is not None and "Lowest" in item.label:
                tone = "negative" if value.minor < buffer else "positive"
            if isinstance(value, PercentValue) and value.value >= 0.5:
                tone = "caution"
            metrics.append(
                Metric(
                    label=item.label[:60],
                    value=value,
                    tone=tone,  # type: ignore[arg-type]
                    emphasis="primary" if i == 0 else "secondary",
                )
            )
        currencies = {v.value.currency for v in items if isinstance(v.value, MoneyValue)}
        return FinancialMetricGroup(
            type="FinancialMetricGroup",
            block_id=self.block_id("metrics"),
            currency=next(iter(currencies)) if len(currencies) == 1 else None,
            placement=_place_overview("key_numbers"),
            evidence=[r for v in items if (r := getattr(v.value, "ref", None))],
            metrics=metrics,
        )

    def transactions(self) -> TransactionTable | None:
        start, end = self._period()
        categories = self._category_filter()
        rows = self._spending_rows(start, end)
        merchant = self.slots.get("merchant") or self.slots.get("counterparty")
        picked: list[tuple[m.Transaction, m.Categorisation | None]] = []
        for txn, cat in rows:
            if txn.currency != self.currency:
                continue
            key = cat.category_key if cat is not None else None
            if categories and key not in categories:
                continue
            if isinstance(merchant, str) and merchant:
                hay = f"{txn.description} {txn.counterparty or ''}".lower()
                if merchant.lower() not in hay:
                    continue
            picked.append((txn, cat))
        shown = picked[:10]
        total = sum(t.amount_minor for t, _ in picked)
        table_rows = [
            TransactionRow(
                txn_id=t.id,
                date=t.posted_on,
                narration_display=_display_narration(t.description),
                counterparty=t.counterparty,
                category=CategoryLabel(
                    key=(c.category_key if c is not None and c.category_key else "uncategorised"),
                    label=(c.category_key if c is not None and c.category_key else "uncategorised")
                    .replace(".", " · ")
                    .replace("_", " ")
                    .capitalize(),
                ),  # fmt: skip
                amount=self.money(t.amount_minor, "exact", None),
                payment_type=t.channel,
            )
            for t, c in shown
        ]
        from backend.app.ui_contracts.primitives import CountValue

        return TransactionTable(
            type="TransactionTable",
            block_id=self.block_id("transactions"),
            title="Transactions",
            currency=self.currency,
            placement=PLACEHOLDER_TAB,
            columns=["date", "narration", "category", "amount"],
            rows=table_rows,
            total=self.money(total, "exact", None),
            count=CountValue(kind="count", value=len(picked), display=str(len(picked))),
            has_more=len(picked) > len(shown),
            query=TxnQuery(
                date_from=start,
                date_to=end,
                category_keys=categories,
                limit=10,
            ),  # fmt: skip
        )

    def risk_assessment(self) -> RiskAssessment | None:
        """docs/08 §5.6 from the forecast's pay cycles (engine values only): every cycle whose
        likely low is below the buffer or below £0, or with a chance of dipping below the buffer of
        at least 10%, up to 4; otherwise the lowest cycle as a low risk."""
        if self.sources.forecast is None:
            return None
        chart = self.chart()
        if chart.buffer_minor is None or not chart.pay_cycles:
            return None
        as_of = self.sources.forecast.result.as_of
        risks: list[Risk] = []
        start = as_of
        for cycle in chart.pay_cycles:
            chance = cycle.chance_below_buffer.value if cycle.chance_below_buffer else 0.0
            negative = cycle.low.minor < 0
            if negative or chance >= 0.5:
                level = "high"
            elif cycle.below_buffer or chance >= 0.1:
                level = "watch"
            else:
                level = "low"
            when = views.short_date(cycle.payday)
            headline = (
                f"Below £0 before your {when} payday"
                if negative
                else f"Below your buffer before your {when} payday"
                if cycle.below_buffer
                else f"Lowest point before your {when} payday"
            )
            window_end = max(start, cycle.payday)
            risks.append(
                Risk(
                    risk_id=f"risk-{cycle.payday.isoformat()}",
                    level=level,  # type: ignore[arg-type]
                    headline=headline,
                    probability=cycle.chance_below_buffer,
                    window=DateRange(**{"from": start, "to": window_end}),
                    impact=cycle.low,
                    status="open",
                )
            )
            start = cycle.payday
        flagged = [r for r in risks if r.level != "low"][:4]
        if not flagged:
            lowest = min(risks, key=lambda r: r.impact.minor if r.impact else 0)
            flagged = [lowest]
        forecast_id = self.sources.forecast.calculation.id
        return RiskAssessment(
            type="RiskAssessment",
            block_id=self.block_id("risk"),
            title="Risk before each payday",
            placement=PLACEHOLDER_TAB,
            evidence=[f"{forecast_id}#pay_cycles"],
            risks=flagged,
        )

    def evidence_panel(self) -> EvidencePanel | None:
        items: list[EvidenceItem] = []
        for calc in list(self.sources.calcs.values())[:8]:
            kind = "forecast" if calc.kind in {"forecast", "simulation"} else "calculation"
            items.append(
                EvidenceItem(
                    ref=calc.id
                    + "#"
                    + (
                        "min_balance_p50_minor"
                        if calc.kind == "forecast"
                        else "simulated.min_balance_p50_minor"
                        if calc.kind == "simulation"
                        else "total_minor"
                    ),
                    kind=kind,  # type: ignore[arg-type]
                    title={
                        "forecast": "Baseline forecast",
                        "simulation": "What-if simulation",
                        "aggregate": "Spending total",
                    }.get(calc.kind, calc.kind.title()),
                    provenance="observed" if calc.kind == "aggregate" else "detected",
                    summary_lines=[
                        f"Engine {calc.engine_version}",
                        f"Data version {calc.data_version}",
                    ],
                    engine_version=calc.engine_version,
                    reproducible=Reproducible(
                        seed=(calc.result or {}).get("seed") if calc.kind == "forecast" else None,
                        inputs_hash=calc.inputs_hash,
                        data_version=calc.data_version,
                    ),
                )  # fmt: skip
            )
        if not items:
            return None
        return EvidencePanel(
            type="EvidencePanel",
            block_id=self.block_id("evidence"),
            title="Where the numbers come from",
            placement=PLACEHOLDER_TAB,
            items=items,
        )

    def pay_today(self) -> bool:
        """The what-if assumed today's date (owner decision 13 Oct 2026, docs/06 §6.2)."""
        spec = self.state.get("scenario_spec") or {}
        return PAY_TODAY in (spec.get("assumptions") or [])

    def with_pay_today(self, verdict: Narrative) -> Narrative:
        """States the assumption and offers "Change date": paying on the next payday instead,
        a concrete date taken from the forecast's own pay cycles."""
        segments = [*verdict.segments, TextSegment(kind="text", text=f" {PAY_TODAY}.")]
        actions = list(verdict.actions)
        spec = self.state.get("scenario_spec") or {}
        amount = next(
            (int(m["amount_minor"]) for m in spec.get("modifiers") or [] if m.get("amount_minor")),
            None,
        )
        payday = next(
            (c.payday for c in (self.chart().pay_cycles if self.sources.forecast else [])),
            None,
        )
        if amount is not None and payday is not None:
            money = self.money(amount, "exact", None).display
            when = f"{payday.day} {payday:%B}"
            actions.append(
                AskAction(
                    action_id="change-date",
                    label="Change date",
                    requires_confirmation=False,
                    kind="ask",
                    payload=AskPayload(question=f"Can I afford {money} on {when}, my payday?"),
                )
            )
        return verdict.model_copy(update={"segments": segments, "actions": actions[:3]})

    def build_blocks(self, choice: ComposerOutput) -> list[Any]:
        src = self.sources
        verdict_block = self.narrative(choice.verdict)
        if self.pay_today():
            verdict_block = self.with_pay_today(verdict_block)
        blocks: list[Any] = [verdict_block]
        metrics = self.metrics(choice.key_numbers)
        if metrics is not None:
            blocks.append(metrics)

        visuals: dict[str, Callable[[], Any]] = {
            "CashFlowForecastChart": lambda: self.chart() if src.forecast is not None else None,
            "ScenarioComparison": lambda: src.simulations[0][1] if src.simulations else None,
            "SpendingBreakdownChart": lambda: src.spending,
            "TransactionTable": self.transactions,
            "EvidencePanel": self.evidence_panel,
            "RiskAssessment": self.risk_assessment,
        }
        main_type = choice.main_visual
        used: set[str] = set()
        if main_type == "InterventionCard" and src.recommendations:
            for card in src.recommendations[:3]:
                blocks.append(card.model_copy(update={"placement": _place_overview("main_visual")}))
            used.add("InterventionCard")
        elif main_type == "FinancialMetricGroup" and metrics is not None:
            # The goal outlook (docs/08 §7a goal_status row, no goal set): the key numbers are
            # the main visual, so the Overview still has exactly one.
            blocks[blocks.index(metrics)] = metrics.model_copy(
                update={"placement": _place_overview("main_visual")}
            )
            used.add("FinancialMetricGroup")
        elif main_type in visuals:
            block = visuals[main_type]()
            if block is not None:
                blocks.append(
                    block.model_copy(update={"placement": _place_overview("main_visual")})
                )
                used.add(main_type)
            elif main_type == "TransactionTable":
                pass
        cards = [self.explain_card(card) for card in src.recommendations]
        src.recommendations = cards
        if self.name in ADVICE_INTENTS and src.recommendations and "InterventionCard" not in used:
            blocks.append(
                src.recommendations[0].model_copy(
                    update={"placement": _place_overview("what_to_do")}
                )
            )
            # ≤ 1 block of each type per tab (docs/08 §7a): further checked options go to the next
            # free tab, as the validator moves Overview overflow; none is dropped.
            for tab, card in zip(
                ("recommendation", "checked"), src.recommendations[1:], strict=False
            ):
                blocks.append(card.model_copy(update={"placement": _place_tab(tab)}))
        for kind in DETAILS.get(self.name, ()):
            if (kind not in used or kind in DETAIL_REPEATS) and kind in visuals:
                block = visuals[kind]()
                if block is not None:
                    blocks.append(block.model_copy(update={"placement": _place_tab("details")}))
                    used.add(kind)
        if src.simulations and "ScenarioComparison" not in used:
            blocks.append(src.simulations[0][1].model_copy(
                update={"placement": _place_tab("recommendation")}))  # fmt: skip
        if self.name in TRANSACTION_INTENTS and "TransactionTable" not in used:
            table = self.transactions()
            if table is not None:
                blocks.append(table.model_copy(update={"placement": _place_tab("transactions")}))
        if (
            self.case is not None
            and self.case.kind in {"goes_negative", "breaches_buffer"}
            and not any(self._removes_shortfall(card) for card in src.recommendations)
        ):
            blocks.append(self.what_else())
        return blocks

    def _short_cycles(self, card: InterventionCard) -> list[Any]:
        """The card's pay cycles that still end below the threshold after the change."""
        threshold = self.case.shortfall_below if self.case is not None else None
        if threshold is None:
            return []
        return [d for d in card.impact.low_deltas if d.after.minor < threshold]

    def _removes_shortfall(self, card: InterventionCard) -> bool:
        return bool(card.impact.low_deltas) and not self._short_cycles(card)

    def explain_card(self, card: InterventionCard) -> InterventionCard:
        """A checked action that narrows the shortfall without removing it says so (templated,
        figures from the card's own engine values)."""
        short = self._short_cycles(card)
        narrowed = [d for d in short if d.after.minor > d.before.minor]
        if not narrowed:
            return card
        worst = min(narrowed, key=lambda d: d.after.minor)
        diff = self.money(worst.after.minor - worst.before.minor, "rounded", None)
        when = worst.cycle_label[:1].lower() + worst.cycle_label[1:]
        line: list[Segment] = [
            TextSegment(kind="text", text=" Reduces the shortfall by "),
            ValueSegment(kind="value", value=diff),
            TextSegment(kind="text", text=f" {when}, but doesn't remove it."),
        ]
        return card.model_copy(update={"rationale_segments": [*card.rationale_segments, *line]})

    def what_else(self) -> Narrative:
        """No checked action removes the shortfall: point to free, impartial help (docs/05 §7.5)."""
        pack = str(self.state.get("locale_pack") or "uk")
        text = WHAT_ELSE.get(pack, WHAT_ELSE["uk"])
        return Narrative(
            type="Narrative",
            block_id=self.block_id("what-else"),
            title="What else",
            placement=_place_tab("recommendation"),
            segments=[TextSegment(kind="text", text=text)],
        )


_SAYS_NEGATIVE = re.compile(
    r"overdrawn|in the red|below (?:£\s?)?0\b|below zero|negative balance|go(?:es)? negative|"
    r"can(?:no|')t afford|cannot afford|not afford|won'?t be able",
    re.IGNORECASE,
)
_SAYS_BELOW_BUFFER = re.compile(r"(?:below|under|dip|drop|fall)\b[^.]{0,30}\bbuffer", re.I)
_SAYS_FINE = re.compile(
    r"\byes\b|can afford|comfortabl|no problem|you'?(?:ll| will) be fine|stay above your buffer",
    re.IGNORECASE,
)


def contradicts(kind: str, text: str) -> bool:
    """Whether a model verdict contradicts the engine's verdict category (docs/08 §5.4)."""
    negative = bool(_SAYS_NEGATIVE.search(text))
    below_buffer = bool(_SAYS_BELOW_BUFFER.search(text))
    fine = bool(_SAYS_FINE.search(text))
    if kind == "goes_negative":
        return not negative or fine
    if kind == "breaches_buffer":
        return negative or not below_buffer or fine
    if kind == "tight":
        return negative
    return negative or below_buffer  # comfortable


def _display_narration(text: str) -> str:
    """Account, card, sort-code and phone-shaped digit runs never reach the client (§5.5)."""
    return re.sub(r"\d[\d -]{5,}\d", "••••", text or "")[:140]


# --------------------------------------------------------------------------- timeline


STATUS_VIEW = {"ok": "ok", "retried": "retried", "failed": "error", "skipped": "skipped"}
TIMELINE_AGENTS = {"coordinator", "ledger", "analyst", "forecaster", "advisor", "verifier"}


def timeline(
    store: Any,
    run_id: str,
    workflow: str,
    detail: str = "full",
    *,
    own_calls: Sequence[Any] = (),
    own_started: datetime | None = None,
) -> AgentExecutionTimeline:
    """`AgentExecutionTimeline` from the run's stored steps (docs/08 §5.10), plus the composing
    step itself (`own_calls`), which is written only after this block is built. Cost and tokens
    appear here and nowhere else in an answer (docs/00 §7)."""
    steps = store.steps(run_id)
    views_: list[AgentStepView] = []
    for s in steps:
        status = STATUS_VIEW.get(s.status, "ok")
        if s.node == "verify" and (s.output or {}).get("verdict") == "reject":
            status = "rejected"
        if s.cached:
            status = "cached"
        views_.append(
            AgentStepView(
                step_id=s.id,
                agent=s.agent if s.agent in TIMELINE_AGENTS else "coordinator",
                node=s.node,
                label=s.label or s.node,
                status=status,  # type: ignore[arg-type]
                started_at=s.started_at,
                duration_ms=max(0, int(s.latency_ms or 0)),
                model=s.model,
                tokens=(s.tokens_in + s.tokens_out) if s.llm_calls else None,
                note=None,
            )
        )
    cost = store.run_cost(run_id)
    now = datetime.now(timezone.utc)
    own_tokens = sum(c.usage.total_tokens for c in own_calls)
    own_costs = [c.cost_estimate for c in own_calls]
    usd = cost.usd_estimate
    if own_calls:
        usd = None if usd is None and cost.model_calls else (usd or 0.0)
        usd = None if usd is None or any(c is None for c in own_costs) else usd + sum(own_costs)
    if own_started is not None:
        views_.append(
            AgentStepView(
                step_id="compose",
                agent="coordinator",
                node="compose",
                label="Composing the answer",
                status="ok",
                started_at=own_started,
                duration_ms=max(0, int((now - own_started).total_seconds() * 1000)),
                model=own_calls[-1].model if own_calls else None,
                tokens=own_tokens or None,
            )
        )
    started = steps[0].started_at if steps else (own_started or now)
    finished = now if own_started is not None else (steps[-1].finished_at if steps else started)
    return AgentExecutionTimeline(
        type="AgentExecutionTimeline",
        block_id="timeline",
        title="How it was checked",
        placement=_place_tab("checked"),
        detail=detail,  # type: ignore[arg-type]
        run_id=run_id,
        workflow=workflow,
        duration_ms=max(0, int((finished - started).total_seconds() * 1000)),
        steps=views_
        or [
            AgentStepView(
                step_id="none",
                agent="coordinator",
                node="compose",
                label="Composing",
                status="ok",
                started_at=started,
                duration_ms=0,
            )  # fmt: skip
        ],
        cost=RunCost(
            model_calls=cost.model_calls + len(own_calls),
            tokens=cost.tokens + own_tokens,
            usd_estimate=round(usd, 8) if usd is not None else None,
            cached=cost.cached > 0,
        ),
    )


def evidence_line(store: Any, run_id: str) -> EvidenceLine:
    steps = store.steps(run_id)
    agents = {
        s.agent for s in steps if s.status in {"ok", "retried"} and s.agent in TIMELINE_AGENTS
    }
    rejected = sum(
        int((s.output or {}).get("rejected_drafts", (s.output or {}).get("verdict") == "reject"))
        for s in steps
        if s.node == "verify"
    )
    return EvidenceLine(agents=len(agents), rejected_drafts=rejected, run_id=run_id)


# --------------------------------------------------------------------------- envelopes


_REF_ID = re.compile(rf"^(rec|fnd)_{ULID}$")


def block_refs(blocks: Iterable[Any]) -> tuple[list[str], list[str]]:
    """The recommendation and finding ids every block names (docs/08 §4.2: provenance is the
    union of all refs): `recommendation_id` / `finding_id` fields and `rec_`/`fnd_` refs."""
    found: dict[str, set[str]] = {"rec": set(), "fnd": set()}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str):
            ident = value.split("#", 1)[0]
            if _REF_ID.match(ident):
                found[ident[:3]].add(ident)

    for block in blocks:
        walk(block.model_dump(mode="json") if hasattr(block, "model_dump") else block)
    return sorted(found["rec"]), sorted(found["fnd"])


def envelope(
    *,
    ctx: WorkspaceContext,
    state: ForesightState,
    run_id: str,
    blocks: list[Any],
    response_id: str,
    status: str = "complete",
    forecast_id: str | None = None,
    evidence: EvidenceLine | None = None,
    follow_ups: list[Any] | None = None,
    calc_ids: Iterable[str] = (),
) -> AgentResponse:
    ws = ctx.workspace
    intent = (state.get("intent") or {}).get("intent")
    question = (state.get("intent") or {}).get("standalone_question") or state.get("user_message")
    recommendations, findings = block_refs(blocks)
    return AgentResponse(
        schema_version="agent_response/1",
        response_id=response_id,
        run_id=run_id,
        thread_id=state.get("thread_id"),
        surface="workspace",
        intent=PLAN_INTENT.get(str(intent)) if intent else None,  # type: ignore[arg-type]
        question=(str(question)[:500] if question else None),
        created_at=datetime.now(timezone.utc),
        as_of=date.fromisoformat(str(state.get("as_of") or date.today().isoformat())),
        workspace_id=ws.id,
        currency=ws.home_currency,
        locale=ws.locale,
        data_version=int(state.get("data_version") or 0),
        prefs_version=int(state.get("prefs_version") or 0),
        forecast_id=forecast_id,
        engine_version=ENGINE_VERSION,
        status=status,  # type: ignore[arg-type]
        blocks=blocks,
        evidence_line=evidence,
        follow_ups=follow_ups or [],
        provenance=ResponseProvenance(
            calc_ids=sorted(set(calc_ids)),
            recommendation_ids=recommendations,
            finding_ids=findings,
        ),
        followup_pending=bool(state.get("followup_pending"))
        and state.get("workflow", "conversation") == "conversation",
        follow_up_of=state.get("follow_up_of"),
    )


def text_response(
    *, ctx: WorkspaceContext, state: ForesightState, run_id: str, text: str, status: str
) -> dict[str, Any]:
    """A one-line templated answer (refusal, unavailable). Never model text."""
    block = Narrative(
        type="Narrative",
        block_id="b1-verdict",
        placement=_place_overview("verdict"),
        segments=[TextSegment(kind="text", text=text)],
    )
    response = envelope(
        ctx=ctx, state=state, run_id=run_id, blocks=[block], response_id=new_id("rsp"),
        status=status,
    )  # fmt: skip
    return response.model_dump(mode="json", by_alias=True)


def paused_response(*, ctx: WorkspaceContext, state: ForesightState, run_id: str) -> dict[str, Any]:
    """AI answers are paused: say so, and still show the deterministic forecast (no model)."""
    from backend.mesh.availability import PAUSED_TEXT

    blocks: list[Any] = [
        Narrative(
            type="Narrative",
            block_id="b1-verdict",
            placement=_place_overview("verdict"),
            segments=[TextSegment(kind="text", text=PAUSED_TEXT)],
        )
    ]
    composer = Composer(ctx, state, run_id)
    composer.sources.forecast = composer._forecast()
    forecast_id = None
    if composer.sources.forecast is not None:
        chart = composer.chart()
        blocks.append(chart.model_copy(update={"placement": _place_overview("main_visual")}))
        forecast_id = views.content_id("fc", composer.sources.forecast.calculation.id)
    response = envelope(
        ctx=ctx, state=state, run_id=run_id, blocks=blocks, response_id=new_id("rsp"),
        status="degraded", forecast_id=forecast_id, calc_ids=composer.sources.calcs.keys(),
    )  # fmt: skip
    return response.model_dump(mode="json", by_alias=True)


EXPLANATION_UNAVAILABLE = "Explanation unavailable. These are the numbers from your forecast."


def clarify_response(
    *, ctx: WorkspaceContext, state: ForesightState, run_id: str, question: str
) -> dict[str, Any]:
    """Low confidence: a question plus 2–4 `ask` options (docs/08 §7a, docs/06 H5)."""
    options = [
        AskAction(
            action_id=f"clarify-{i}",
            label=label,
            requires_confirmation=False,
            kind="ask",
            payload=AskPayload(question=q),
        )
        for i, (label, q) in enumerate(STARTER_QUESTIONS, start=1)
    ]
    block = ClarifyingQuestion(
        type="ClarifyingQuestion",
        block_id="b1-clarify",
        placement=_place_overview("verdict"),
        question=question,
        options=options,
    )
    response = envelope(
        ctx=ctx, state=state, run_id=run_id, blocks=[block], response_id=new_id("rsp"),
    )  # fmt: skip
    return response.model_dump(mode="json", by_alias=True)


# --------------------------------------------------------------------------- the node


NOT_CHECKED_IN_TIME = "No recommendation was checked in time."
CHECKING_AFTER = "A checked recommendation is still being prepared; it will appear below."


def _advice_unchecked(state: ForesightState) -> bool:
    """Advice was asked for or drafted, but nothing was approved before the run stopped."""
    wanted = bool((state.get("intent") or {}).get("needs_advice")) or bool(
        state.get("withdrawn") or state.get("verifications") or state.get("proposals")
    )
    return wanted and not state.get("approved_recs")


def ai_paused(ctx: RunContext) -> bool:
    """True when no model call should be made now (no client, or AI answers are paused)."""
    if ctx.mesh is None:
        return True
    availability = getattr(ctx.mesh, "availability", None)
    return availability is not None and availability.status() == "unavailable"


def compose(state: ForesightState, ctx: RunContext) -> NodeOutput:
    """AGT-10: choose (fast model or template) → hydrate → place → screen → validate."""
    started_at = ctx.clock()
    with ctx.lock:
        wctx = ctx.store.ctx
        composer = Composer(wctx, state, ctx.run_id)
        composer.gather()

    question = str((state.get("intent") or {}).get("standalone_question") or "")
    llm: list[Any] = []
    spend_stopped = False
    strategy = "template"
    problems: list[str] = []
    choice = composer.template_output()
    late = bool(state.get("partial"))  # deadline or budget: deterministic answer, no model call
    if late and _advice_unchecked(state):
        choice = choice.model_copy(update={"verdict": f"{choice.verdict} {NOT_CHECKED_IN_TIME}"})
    pending = bool(state.get("followup_pending")) and not late
    # When the verdict is the engine's own outcome (docs/08 §5.4 verdict case), the blocks come
    # from the §7a table and the key numbers from the catalogue order: there is nothing left for a
    # model to choose, so no model call is made.
    wording_needed = composer.case is None
    if (
        wording_needed
        and not late
        and not state.get("ai_paused")
        and not ai_paused(ctx)
        and composer.sources.values
    ):
        assert ctx.mesh is not None
        from backend.mesh.mesh_client import MeshCallError, MeshSpendLimitError

        try:
            ctx.before_llm()
            result = ctx.mesh.structured(
                tier=ModelTier.FAST,
                messages=composer.model_messages(question),
                output=ComposerOutput,
                name="compose",
                max_tokens=1000,
                locale_pack=str(state.get("locale_pack") or "uk"),
            )
            ctx.charge(result.calls)
            llm = list(result.calls)
            choice, problems = composer.check_output(result.value)
            strategy = "model"
            blocked = [k for k in composer.screen_kinds if k != "numeral"]
            if blocked:
                # The model's text is dropped; the answer uses the template (docs/05 §7.4a L4).
                with ctx.lock:
                    wctx.append_audit(
                        "prompt_leak_blocked" if "canary" in blocked else "output_screen_blocked",
                        "agent_run",
                        ctx.run_id,
                        actor="agent:coordinator",
                        after={"node": "compose", "kinds": blocked},
                        run_id=ctx.run_id,
                    )
        except MeshCallError as exc:
            problems.append(f"model unavailable: {type(exc).__name__}")
            if isinstance(exc, MeshSpendLimitError):
                # Mid-run spend refusal: engine numbers only, labelled, no model text.
                spend_stopped = True
                verdict = EXPLANATION_UNAVAILABLE
                if composer.case is not None:  # the engine's own answer is not model text
                    verdict = f"{composer.case.template} {EXPLANATION_UNAVAILABLE}"
                choice = composer.template_output().model_copy(update={"verdict": verdict})

    if pending:  # fixed wording, after any model choice, so it is always said
        choice = choice.model_copy(update={"verdict": f"{choice.verdict} {CHECKING_AFTER}"})
    with ctx.lock:
        blocks = composer.build_blocks(choice)
        workflow = str(state.get("workflow") or "conversation")
        blocks.append(
            timeline(ctx.store, ctx.run_id, workflow, own_calls=llm, own_started=started_at)
        )
        placed, issues = enforce_skeleton(blocks)
        if any(i.code == "skeleton_main_visual" for i in issues):
            # No main visual could be hydrated: fall back to the intent's template (§9).
            fallback = composer.template_output()
            if fallback.main_visual != choice.main_visual and fallback.main_visual:
                blocks = composer.build_blocks(
                    fallback.model_copy(update={"verdict": choice.verdict})
                )
                blocks.append(
                    timeline(ctx.store, ctx.run_id, workflow, own_calls=llm, own_started=started_at)
                )
                placed, issues = enforce_skeleton(blocks)
        forecast = composer.sources.forecast
        degraded = (
            bool(state.get("partial"))
            or spend_stopped
            or (strategy == "template" and ctx.mesh is None)
        )
        response = envelope(
            ctx=wctx,
            state=state,
            run_id=ctx.run_id,
            blocks=placed,
            response_id=new_id("rsp"),
            status="degraded" if degraded or composer.sources.issues else "complete",
            forecast_id=(views.content_id("fc", forecast.calculation.id) if forecast else None),
            evidence=evidence_line(ctx.store, ctx.run_id),
            calc_ids=composer.sources.calcs.keys(),
        )
    currency_issues = check_currency(response)
    body = response.model_dump(mode="json", by_alias=True)
    all_issues = [*(f"{i.code}: {i.message}" for i in [*issues, *currency_issues]), *problems,
                  *composer.sources.issues]  # fmt: skip
    return NodeOutput(
        update={"response_body": body, "answer_kind": "answer"}
        | ({"partial": True} if spend_stopped else {}),
        output={
            "strategy": strategy,
            "response_id": response.response_id,
            "blocks": [b.get("type") for b in body["blocks"]],
            "main_visual": choice.main_visual or None,
            "citations": len(composer.citations),
            "issues": all_issues[:20],
        },
        llm=llm,
        prompt_version=prompt_version(COMPOSE_PROMPT) if strategy == "model" else None,
        status="retried" if problems and strategy == "model" else "ok",
        label="Composing the answer",
    )
