"""Turn engine and ledger records into the UI contract views (docs/08 §2, §5.3, §5.4).

Every figure comes from a stored calculation or the ledger and carries a `calc_…#path` ref where
one exists. Money is formatted on the server; dates use the en-GB/en-IN short form ("14 Oct").
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from backend.app.ui_contracts.blocks import (
    MAX_POINTS,
    Assumption,
    BalanceHistory,
    BaselineLine,
    CashFlowForecastData,
    ComparisonRow,
    EvidenceInputs,
    EvidenceItem,
    FanSeries,
    ForecastSummary,
    InterventionCard,
    PayCycleLow,
    ScenarioComparisonData,
    ScenarioLine,
    ScenarioSeries,
    ScenarioVerdict,
    SourceChain,
    SourceReconciliation,
    StartingBalance,
    VerificationCheck,
)
from backend.app.ui_contracts.money import money_value
from backend.app.ui_contracts.primitives import (
    DateRange,
    DateValue,
    MoneyAmount,
    MoneyValue,
    PercentValue,
    Precision,
    Scope,
    Tone,
)
from backend.finance_core.calc import content_hash
from backend.finance_core.types import ForecastInputs, ForecastResult, ScenarioSpec
from backend.storage import models as m
from backend.storage.repositories import WorkspaceContext

HISTORY_DAYS = 90
PROVENANCE = {"declared": "declared", "statement_column": "observed", "relative": "default"}


def short_date(d: date) -> str:
    return f"{d.day} {d:%b}"


def content_id(prefix: str, calc_id: str) -> str:
    """fc_/sim_ ids share the hash of the calculation they were computed in."""
    return f"{prefix}_{calc_id.removeprefix('calc_')}"


def scenario_id(spec: ScenarioSpec) -> str:
    return f"scn_{content_hash(spec)[:24]}"


class Formatter:
    def __init__(self, currency: str, locale: str, calc_id: str) -> None:
        self.currency, self.locale, self.calc_id = currency, locale, calc_id

    def money(self, minor: int, precision: Precision, path: str | None = None) -> MoneyValue:
        ref = f"{self.calc_id}#{path}" if path else None
        return money_value(MoneyAmount(amount_minor=minor, currency=self.currency), self.locale,
                           precision, ref)  # fmt: skip

    def day(self, d: date, path: str | None = None) -> DateValue:
        ref = f"{self.calc_id}#{path}" if path else None
        return DateValue(kind="date", value=d, display=short_date(d), ref=ref)

    def percent(self, share: float, path: str | None = None) -> PercentValue:
        ref = f"{self.calc_id}#{path}" if path else None
        return PercentValue(kind="percent", value=share, display=f"{round(share * 100)}%", ref=ref)


def downsample(n: int, keep: Sequence[int] = ()) -> list[int]:
    """Indices of at most MAX_POINTS points: an even stride, plus the first, last and any
    indices that must survive (e.g. the minimum), so the chart's low point is never dropped."""
    if n <= MAX_POINTS:
        return list(range(n))
    must = {0, n - 1, *keep}
    stride = math.ceil(n / (MAX_POINTS - len(must)))
    return sorted(must | set(range(0, n, stride)))[:MAX_POINTS]


def forecast_scope(ctx: WorkspaceContext, account_ids: Sequence[str]) -> Scope:
    accounts = [ctx.account(a) for a in account_ids]
    label = accounts[0].name if len(accounts) == 1 else "All my accounts"
    return Scope(kind="mine", label=label, account_ids=list(account_ids),
                 switchable=len(accounts) > 1)  # fmt: skip


def history(
    ctx: WorkspaceContext, account_ids: Sequence[str], inputs: ForecastInputs
) -> BalanceHistory:
    """End-of-day balances for the last 90 days, walked back from the forecast's starting balance
    (relative mode: relative to today's balance, which is 0)."""
    by_day: dict[date, int] = defaultdict(int)
    start = inputs.as_of - timedelta(days=HISTORY_DAYS - 1)
    for t in ctx.transactions(account_ids=account_ids, currency=inputs.currency):
        if start < t.posted_on <= inputs.as_of:
            by_day[t.posted_on] += t.amount_minor
    days = [start + timedelta(days=i) for i in range(HISTORY_DAYS)]
    balances = [0] * HISTORY_DAYS
    balance = inputs.starting_balance_minor
    for i in range(HISTORY_DAYS - 1, -1, -1):
        balances[i] = balance
        balance -= by_day.get(days[i], 0)
    return BalanceHistory(dates=days, balance_minor=balances)


def chart_data(
    ctx: WorkspaceContext,
    account_ids: Sequence[str],
    result: ForecastResult,
    inputs: ForecastInputs,
    calc_id: str,
    path: str = "",
) -> CashFlowForecastData:
    """`path` prefixes calc refs when the result sits inside a larger calculation (simulated)."""
    fmt = Formatter(result.currency, ctx.workspace.locale, calc_id)
    relative = inputs.starting_balance_provenance == "relative"
    buffer = None if relative else result.buffer_minor
    low_index = min(range(len(result.p50)), key=result.p50.__getitem__) if result.p50 else 0
    idx = downsample(len(result.dates), keep=[low_index])
    cycles = []
    for i, c in enumerate(result.pay_cycles):
        chance = c.chance_below_buffer if buffer is not None else None
        cycles.append(
            PayCycleLow(
                payday=c.payday,
                low=fmt.money(c.low.p50, "rounded", f"{path}pay_cycles.{i}.low.p50"),
                low_date=c.low_date,
                below_buffer=buffer is not None and c.low.p50 < buffer,
                chance_below_buffer=(
                    fmt.percent(chance, f"{path}pay_cycles.{i}.chance_below_buffer")
                    if chance is not None
                    else None
                ),
            )
        )
    first = result.pay_cycles[0] if result.pay_cycles else None
    breach = (
        fmt.percent(first.chance_below_buffer, f"{path}pay_cycles.0.chance_below_buffer")
        if first is not None and buffer is not None and first.chance_below_buffer is not None
        else None
    )
    starting = fmt.money(inputs.starting_balance_minor, "exact")
    return CashFlowForecastData(
        as_of=result.as_of,
        scope=forecast_scope(ctx, account_ids),
        balance_mode="relative" if relative else "absolute",
        resolution="daily" if len(idx) == len(result.dates) else "sampled",
        history=history(ctx, account_ids, inputs),
        forecast=FanSeries(
            dates=[result.dates[i] for i in idx],
            p10=[result.p10[i] for i in idx],
            p50=[result.p50[i] for i in idx],
            p90=[result.p90[i] for i in idx],
        ),
        buffer_minor=buffer,
        pay_cycles=cycles,
        summary=ForecastSummary(
            min_balance=fmt.money(
                result.min_balance_p50_minor, "rounded", f"{path}min_balance_p50_minor"
            ),
            min_date=fmt.day(result.min_balance_date, f"{path}min_balance_date"),
            p_breach_buffer=breach,
            breach_window_end=(
                first.payday - timedelta(days=1)
                if first is not None and breach is not None
                else None
            ),
            starting_balance=StartingBalance(
                money=starting,
                provenance=PROVENANCE[inputs.starting_balance_provenance],  # type: ignore[arg-type]
            ),
        ),  # fmt: skip
    )


# --------------------------------------------------------------------------- simulation


def _series(result: ForecastResult) -> ScenarioSeries:
    low_index = min(range(len(result.p50)), key=result.p50.__getitem__) if result.p50 else 0
    idx = downsample(len(result.dates), keep=[low_index])
    return ScenarioSeries(
        dates=[result.dates[i] for i in idx],
        p10=[result.p10[i] for i in idx],
        p50=[result.p50[i] for i in idx],
        p90=[result.p90[i] for i in idx],
    )


def modifier_summary(spec: ScenarioSpec, fmt: Formatter) -> list[str]:
    lines = []
    for mod in spec.modifiers:
        label = f" ({mod.label})" if mod.label else ""
        if mod.type in ("one_off_outflow", "one_off_inflow") and mod.amount_minor and mod.date:
            verb = "Pay" if mod.type == "one_off_outflow" else "Receive"
            amount = fmt.money(mod.amount_minor, "exact").display
            lines.append(f"{verb} {amount} on {short_date(mod.date)}{label}")
        elif mod.type == "income_delay":
            lines.append(f"Income arrives {mod.days} days late{label}")
        else:
            lines.append(mod.type.replace("_", " ").capitalize() + label)
    return lines


def verdict(
    simulated: ForecastResult, buffer: int | None, fmt: Formatter
) -> ScenarioVerdict | None:
    """docs/08 §5.4: a rule over every pay cycle in the horizon, naming the cycle."""
    if buffer is None or not simulated.pay_cycles:
        return None
    cycles = simulated.pay_cycles
    negative = next((c for c in cycles if c.low.p50 < 0), None)
    if negative is not None:
        return ScenarioVerdict(
            kind="goes_negative",
            text=f"Likely overdrawn before the {short_date(negative.payday)} payday "
            f"(lowest about {fmt.money(negative.low.p50, 'rounded').display}).",
        )
    breach = next((c for c in cycles if c.low.p50 < buffer), None)
    if breach is not None:
        return ScenarioVerdict(
            kind="breaches_buffer",
            text=f"Likely below your buffer before the {short_date(breach.payday)} payday "
            f"(lowest about {fmt.money(breach.low.p50, 'rounded').display}).",
        )
    tight = next((c for c in cycles if c.low.p10 < buffer), None)
    if tight is not None:
        return ScenarioVerdict(
            kind="tight",
            text=f"Tight before the {short_date(tight.payday)} payday: a bad month could take "
            "you under your buffer.",
        )
    return ScenarioVerdict(
        kind="comfortable", text="Stays above your buffer before every payday in the forecast."
    )


def _tone(delta: int) -> Tone:
    return "positive" if delta > 0 else "negative" if delta < 0 else "neutral"


def comparison_data(
    ctx: WorkspaceContext,
    account_ids: Sequence[str],
    spec: ScenarioSpec,
    baseline: ForecastResult,
    simulated: ForecastResult,
    inputs: ForecastInputs,
    baseline_calc_id: str,
    sim_calc_id: str,
) -> ScenarioComparisonData:
    locale = ctx.workspace.locale
    base_fmt = Formatter(baseline.currency, locale, baseline_calc_id)
    sim_fmt = Formatter(simulated.currency, locale, sim_calc_id)
    relative = inputs.starting_balance_provenance == "relative"
    buffer = None if relative else simulated.buffer_minor
    delta_min = simulated.min_balance_p50_minor - baseline.min_balance_p50_minor
    rows = [
        ComparisonRow(
            metric_label="Lowest balance (likely)",
            baseline=base_fmt.money(baseline.min_balance_p50_minor, "rounded",
                                    "min_balance_p50_minor"),
            scenarios=[sim_fmt.money(simulated.min_balance_p50_minor, "rounded",
                                     "simulated.min_balance_p50_minor")],
            delta=[sim_fmt.money(delta_min, "rounded")],
            tone=[_tone(delta_min)],
        ),
        ComparisonRow(
            metric_label="Balance at the end (likely)",
            baseline=base_fmt.money(baseline.p50[-1], "rounded"),
            scenarios=[sim_fmt.money(simulated.p50[-1], "rounded")],
            delta=[sim_fmt.money(simulated.p50[-1] - baseline.p50[-1], "rounded")],
            tone=[_tone(simulated.p50[-1] - baseline.p50[-1])],
        ),
    ]  # fmt: skip
    return ScenarioComparisonData(
        scope=forecast_scope(ctx, account_ids),
        baseline=BaselineLine(label="Current path", series=_series(baseline)),
        scenarios=[
            ScenarioLine(
                simulation_id=content_id("sim", sim_calc_id),
                scenario_id=scenario_id(spec),
                label=spec.name,
                series=_series(simulated),
                modifiers_summary=modifier_summary(spec, sim_fmt),
            )
        ],
        comparison_rows=rows,
        verdict=verdict(simulated, buffer, sim_fmt),
        assumptions=[
            Assumption(label="Simulated paths", value=str(simulated.n_paths),
                       source="Forecast engine " + simulated.engine_version),
            Assumption(label="Starting balance",
                       value=base_fmt.money(inputs.starting_balance_minor, "exact").display,
                       source=PROVENANCE[inputs.starting_balance_provenance]),
            Assumption(label="Same random seed", value=str(simulated.seed),
                       source="Baseline and scenario share it, so the gap is the scenario's"),
            *_beyond_confident(simulated),
        ],
    )  # fmt: skip


CONFIDENT_DAYS = 90  # the usual horizon; past it the band is lower-confidence


def _beyond_confident(result: ForecastResult) -> list[Assumption]:
    """A what-if extended past 90 days to reach its dates says where the range gets less certain
    (docs/00 §3: beyond 90 days the band is labelled lower-confidence)."""
    if result.horizon_days <= CONFIDENT_DAYS:
        return []
    start = result.as_of + timedelta(days=CONFIDENT_DAYS + 1)  # beyond day 90, not on it
    return [
        Assumption(label="Lower confidence", value=f"From {short_date(start)}",
                   source="More than 90 days out, the range is wider and less certain"),
    ]  # fmt: skip


def calc_currency(calc: m.Calculation) -> str | None:
    result = calc.result or {}
    if isinstance(result.get("currency"), str):
        return str(result["currency"])
    scenario = result.get("scenario")
    if isinstance(scenario, dict) and isinstance(scenario.get("currency"), str):
        return str(scenario["currency"])
    return None


def forecast_accounts(ctx: WorkspaceContext) -> list[str]:
    """The accounts the baseline forecast covers (the same rule as pipeline.forecast)."""
    home = ctx.workspace.home_currency
    return [
        a.id
        for a in ctx.all(m.Account)
        if a.include_in_forecast and a.tracked and a.currency == home
    ]


_PLACEHOLDER = re.compile(r"\{\{\s*(calc_[0-9a-zA-Z]+)#([a-z_]+)\|([a-z_]+)\s*\}\}")


def finding_text(text: str, ctx: WorkspaceContext) -> str | None:
    """Fill each `{{calc_…#path|format}}` from the stored calculation; None if any can't be
    (a finding is then left out rather than shown with a gap or a guessed number)."""
    missing = False

    def one(match: re.Match[str]) -> str:
        nonlocal missing
        calc_id, path, fmt = match.groups()
        calc = ctx.calculation(calc_id)
        result: dict[str, Any] = calc.result if calc is not None else {}
        value = result.get(path)
        if value is None:
            missing = True
            return ""
        if fmt == "money":
            currency = str(result.get("currency") or ctx.workspace.home_currency)
            amount = MoneyAmount(amount_minor=int(value), currency=currency)
            return money_value(amount, ctx.workspace.locale, "rounded").display
        if fmt == "pct_change":
            return f"{round(abs(float(value)) * 100)}%"
        if fmt == "count":
            return str(int(value))
        if fmt == "date":
            return short_date(date.fromisoformat(str(value)))
        missing = True
        return ""

    filled = _PLACEHOLDER.sub(one, text)
    return None if missing or "{{" in filled else filled


def finding_link(finding_id: str) -> str:
    """Where exactly a finding's transactions are listed (Home, the evidence chain): the ledger
    filtered to its rows, for every kind of finding (#62 review)."""
    return f"/transactions?finding={finding_id}"


def finding_transactions(ctx: WorkspaceContext, query: dict[str, Any]) -> list[m.Transaction]:
    """The transactions a finding counts (its `txn_query`): a category over a window, or the
    payments of one or more recurring bills. The Evidence drawer shows these as its source."""
    if query.get("txn_ids"):  # the detector's exact rows (category findings)
        ids = set(query["txn_ids"])
    else:
        keys = {*(query.get("obligation_keys") or []), *filter(None, [query.get("obligation_key")])}
        obligations = ctx.select(m.RecurringObligation).where(m.RecurringObligation.key.in_(keys))
        ids = {i for o in ctx.session.scalars(obligations) for i in o.member_ids} if keys else set()
    if ids:
        # Only the referenced rows, workspace-scoped: never the whole ledger (#62 review).
        rows = ctx.select(m.Transaction).where(m.Transaction.id.in_(sorted(ids)))
        return list(ctx.session.scalars(rows))
    # A category finding stored before its rows were (no `txn_ids`): no count is shown rather
    # than a looser re-query that could contradict the detector's own (#62 review).
    return []


# Each Verifier rule in plain words, as the evidence chain lists its checks (docs/06 §5).
RULE_NAMES = {
    "V-01": "Its evidence exists in your profile",
    "V-02": "It rests on a finding or the forecast",
    "V-03": "What it changes is in your data",
    "V-04": "It's achievable, not too big a cut",
    "V-05": "It changes enough to matter",
    "V-06": "Its figure matches the engine's",
    "V-07": "Every number traces to a calculation",
    "V-08": "It doesn't set back a goal or your buffer",
    "V-09": "It isn't a repeat of other advice",
    "V-10": "It's specific to your data",
    "V-11": "Its reasoning is grounded in the evidence",
    "V-12": "You could act on it today",
    "V-13": "Its tone is fair and not judgemental",
    "V-14": "It isn't regulated financial advice",
    "V-15": "It's framed for a shared account",
    "V-16": "It counts only your own money",
    "V-17": "It leaves protected savings alone",
    "V-18": "Betting is handled only as you chose",
    "V-19": "It holds without unconfirmed income",
    "V-20": "It doesn't mix currencies",
}
EVIDENCE_ITEMS = 8  # EvidencePanel.items max_length


def recommendation_evidence(
    ctx: WorkspaceContext, cards: Sequence[InterventionCard], limit: int = EVIDENCE_ITEMS
) -> list[EvidenceItem]:
    """The chain behind shown recommendations (docs/06 §10.2, mandatory F), from stored records
    only: each card's Verifier item first (its citation must resolve), then the findings that
    triggered them, with the transactions each counts and the imports they came from; at most
    `limit` items, so a panel always validates (#62 review)."""
    checks = [c for c in (_verification_item(ctx, card) for card in cards) if c is not None]
    findings: list[EvidenceItem] = []
    seen: set[str] = set()
    for card in cards:
        for ref in card.triggered_by:
            fid = ref.split("#")[0]
            if fid.startswith("fnd_") and fid not in seen:
                seen.add(fid)
                item = _finding_item(ctx, fid)
                if item is not None:
                    findings.append(item)
    return [*checks, *findings][:limit]


def _verification_item(ctx: WorkspaceContext, card: InterventionCard) -> EvidenceItem | None:
    stmt = ctx.select(m.VerificationResult).where(
        m.VerificationResult.recommendation_id == card.recommendation_id
    )
    rounds = sorted(ctx.session.scalars(stmt), key=lambda v: v.round)
    final = next((v for v in rounds if v.id == card.verification.verification_id), None)
    if final is None:
        return None
    rejected = sum(1 for v in rounds if v.round < final.round and v.verdict == "REJECT")
    lines = [f"Approved by the Verifier in round {final.round}."]
    if rejected:
        lines.append(
            f"Earlier {'draft was' if rejected == 1 else 'drafts were'} rejected and revised "
            "before you saw it."
        )
    return EvidenceItem(
        ref=final.id,
        kind="verification",
        title="How the Verifier checked it",
        provenance="detected",
        summary_lines=lines,
        checks=[
            VerificationCheck(
                # Judge rules carry their prompt version: "V-11@judge-1.2".
                name=RULE_NAMES.get(str(r.get("rule")).split("@")[0], str(r.get("rule"))),
                passed=bool(r.get("passed")),
                kind="model" if r.get("kind") == "judge" else "deterministic",
            )
            for r in final.rule_results or []
        ],
    )


def _finding_item(ctx: WorkspaceContext, finding_id: str) -> EvidenceItem | None:
    finding = ctx.get(m.Finding, finding_id)
    headline = finding_text(finding.headline, ctx) if finding else None
    if finding is None or not headline:
        return None
    detail = finding_text(finding.detail, ctx) if finding.detail else None
    txns = finding_transactions(ctx, finding.txn_query or {})
    chain, files = _source_chain(ctx, txns)
    lines = [detail] if detail else []
    if len(files) > 1:  # every contributing import named, not only the largest (#62 review)
        lines.append(
            f"From {len(files)} files: "
            + ", ".join(f"{name} ({n} {'row' if n == 1 else 'rows'})" for name, n in files)
            + "."
        )
    return EvidenceItem(
        ref=finding.id,
        kind="finding",
        title=headline[:80],
        provenance="detected",
        summary_lines=lines,
        inputs=(
            EvidenceInputs(
                transaction_count=len(txns),
                date_range=DateRange(
                    **{
                        "from": min(t.posted_on for t in txns),
                        "to": max(t.posted_on for t in txns),
                    }
                ),
            )
            if txns
            else None
        ),
        source_chain=chain,
        link=finding_link(finding.id),
    )


def _source_chain(
    ctx: WorkspaceContext, txns: list[m.Transaction]
) -> tuple[SourceChain | None, list[tuple[str, int]]]:
    """The import most of these transactions came from (its file, how many of them, whether its
    balances reconciled), and every contributing file with its count."""
    counts: dict[str, int] = {}
    for t in txns:
        if t.import_batch_id:
            counts[t.import_batch_id] = counts.get(t.import_batch_id, 0) + 1
    batches = {b: ctx.get(m.ImportBatch, b) for b in counts}
    files = sorted(
        ((batch.filename, counts[b]) for b, batch in batches.items() if batch is not None),
        key=lambda f: -f[1],
    )
    if not files:
        return None, []
    main_id = max((b for b in batches if batches[b] is not None), key=lambda b: counts[b])
    main = batches[main_id]
    assert main is not None
    n = counts[main_id]
    return (
        SourceChain(
            import_id=main.id,
            filename=main.filename,
            importer=main.importer,  # type: ignore[arg-type]
            rows=f"{n} {'row' if n == 1 else 'rows'} of this file",
            reconciliation=(
                SourceReconciliation(status=main.reconciliation_status, method="balances")
                if main.reconciliation_status
                else None
            ),
        ),
        files,
    )
