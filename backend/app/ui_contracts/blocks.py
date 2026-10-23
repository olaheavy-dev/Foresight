"""Hydrated blocks: what the client receives (docs/08 §4.3, §5). Every field here is filled by
the server from persisted records; the LLM never supplies a number, tone or placement."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from backend.app.ui_contracts.primitives import (
    AskAction,
    Contract,
    CountValue,
    Currency,
    DateRange,
    DateValue,
    FollowUpAction,
    GoalId,
    ImportId,
    MoneyValue,
    NonEmpty,
    PercentValue,
    Placement,
    Provenance,
    RecommendationId,
    Ref,
    RunId,
    ScenarioId,
    Scope,
    SimulationId,
    Tone,
    TransactionId,
    TxnQuery,
    Value,
    VerificationId,
)

MAX_POINTS = 200  # per chart series (§5.3); the server downsamples with min/max preservation

Title = Annotated[str, StringConstraints(min_length=1, max_length=80)]
Caption = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Points = Annotated[list[int], Field(max_length=MAX_POINTS)]
Dates = Annotated[list[dt.date], Field(max_length=MAX_POINTS)]


class _BlockCore(Contract):
    block_id: NonEmpty
    title: Title | None = None
    caption: Caption | None = None
    currency: Currency | None = None  # set on every block that contains money; one per block
    placement: Placement
    evidence: list[Ref] = []


class BlockBase(_BlockCore):
    actions: Annotated[list[FollowUpAction], Field(max_length=3)] = []


# --- 5.0 Narrative -----------------------------------------------------------------------------


class TextSegment(Contract):
    kind: Literal["text"]
    text: str


class ValueSegment(Contract):
    kind: Literal["value"]
    value: Value


class EntitySegment(Contract):
    kind: Literal["entity"]
    ref: Ref
    label: NonEmpty


Segment = Annotated[TextSegment | ValueSegment | EntitySegment, Field(discriminator="kind")]


class Narrative(BlockBase):
    type: Literal["Narrative"]
    segments: Annotated[list[Segment], Field(min_length=1)]


# --- ClarifyingQuestion (low-confidence routing, §7a: a question plus 2–4 `ask` options) ------


class ClarifyingQuestion(BlockBase):
    type: Literal["ClarifyingQuestion"]
    question: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    options: Annotated[list[AskAction], Field(min_length=2, max_length=4)]


# --- 5.1 FinancialMetricGroup ------------------------------------------------------------------


class MetricCompare(Contract):
    label: NonEmpty
    value: Value
    delta: Value


class Metric(Contract):
    label: NonEmpty
    value: Value
    compare: MetricCompare | None = None
    tone: Tone
    emphasis: Literal["primary", "secondary"]


class FinancialMetricGroup(BlockBase):
    type: Literal["FinancialMetricGroup"]
    # 2–4 in general (§5.1); the skeleton trim can leave a single overflow metric in a tab.
    metrics: Annotated[list[Metric], Field(min_length=1, max_length=4)]


# --- 5.2 SpendingBreakdownChart ----------------------------------------------------------------

Nature = Literal["essential", "commitment", "discretionary", "debt", "savings", "tax"]


class CategorySeries(Contract):
    key: NonEmpty
    label: NonEmpty
    nature: Nature
    value: MoneyValue
    baseline: MoneyValue | None = None
    share: PercentValue | None = None
    tone: Tone


class TimeSeries(Contract):
    key: NonEmpty
    label: NonEmpty
    values: Annotated[list[int], Field(max_length=26)]


class _SpendingBase(BlockBase):
    type: Literal["SpendingBreakdownChart"]
    period: DateRange
    total: MoneyValue
    highlight_keys: list[str] = []


class SpendingByCategory(_SpendingBase):
    """Part-to-whole: by category, by merchant (§7a) or a category vs its baseline."""

    mode: Literal["by_category", "by_merchant", "vs_baseline"]
    series: Annotated[list[CategorySeries], Field(min_length=1, max_length=8)]


class SpendingOverTime(_SpendingBase):
    mode: Literal["over_time"]
    x: Annotated[list[NonEmpty], Field(min_length=1, max_length=26)]
    series: Annotated[list[TimeSeries], Field(min_length=1, max_length=8)]
    baseline: MoneyValue | None = None

    @model_validator(mode="after")
    def _aligned(self) -> SpendingOverTime:
        if any(len(s.values) != len(self.x) for s in self.series):
            raise ValueError("every series needs one value per x bucket")
        return self


SpendingBreakdownChart = Annotated[
    SpendingByCategory | SpendingOverTime, Field(discriminator="mode")
]


# --- 5.3 CashFlowForecastChart -----------------------------------------------------------------


class BalanceHistory(Contract):
    dates: Dates
    balance_minor: Points

    @model_validator(mode="after")
    def _aligned(self) -> BalanceHistory:
        if len(self.dates) != len(self.balance_minor):
            raise ValueError("history dates and balances differ in length")
        return self


class FanSeries(Contract):
    dates: Dates
    p10: Points
    p50: Points
    p90: Points

    @model_validator(mode="after")
    def _aligned(self) -> FanSeries:
        if not len(self.dates) == len(self.p10) == len(self.p50) == len(self.p90):
            raise ValueError("forecast dates and quantiles differ in length")
        return self


class ForecastEvent(Contract):
    date: dt.date
    label: NonEmpty
    amount: MoneyValue
    kind: Literal["income", "obligation", "commitment", "one_off", "scenario"]


class PayCycleLow(Contract):
    payday: dt.date
    low: MoneyValue
    low_date: dt.date
    below_buffer: bool
    # Share of simulated paths whose low in this cycle is under the buffer; null in relative
    # mode or without a same-currency buffer.
    chance_below_buffer: PercentValue | None = None


class StartingBalance(Contract):
    money: MoneyValue
    provenance: Provenance


class ForecastSummary(Contract):
    min_balance: Value
    min_date: Value
    p_breach_buffer: Value | None = None
    breach_window_end: dt.date | None = None
    starting_balance: StartingBalance


class CashFlowForecastData(Contract):
    """The chart content without block fields, shared with the engine-only forecast API."""

    as_of: dt.date
    scope: Scope
    balance_mode: Literal["absolute", "relative"]
    resolution: Literal["daily", "weekly", "sampled"]
    history: BalanceHistory
    forecast: FanSeries
    buffer_minor: int | None  # null in relative mode or without a same-currency buffer
    events: list[ForecastEvent] = []
    pay_cycles: list[PayCycleLow] = []
    summary: ForecastSummary
    highlight_window: DateRange | None = None


class CashFlowForecastChart(BlockBase, CashFlowForecastData):
    type: Literal["CashFlowForecastChart"]


# --- 5.4 ScenarioComparison --------------------------------------------------------------------


class ScenarioSeries(Contract):
    dates: Dates
    p50: Points
    p10: Points | None = None
    p90: Points | None = None

    @model_validator(mode="after")
    def _aligned(self) -> ScenarioSeries:
        n = len(self.dates)
        if any(s is not None and len(s) != n for s in (self.p10, self.p50, self.p90)):
            raise ValueError("scenario dates and quantiles differ in length")
        return self


class BaselineLine(Contract):
    label: NonEmpty
    series: ScenarioSeries


class ScenarioLine(Contract):
    simulation_id: SimulationId
    scenario_id: ScenarioId
    label: NonEmpty
    series: ScenarioSeries
    modifiers_summary: list[str]


class ComparisonRow(Contract):
    metric_label: NonEmpty
    baseline: Value
    scenarios: list[Value]
    delta: list[Value]
    tone: list[Tone]

    @model_validator(mode="after")
    def _aligned(self) -> ComparisonRow:
        if not len(self.scenarios) == len(self.delta) == len(self.tone):
            raise ValueError("comparison row needs one value, delta and tone per scenario")
        return self


class ScenarioVerdict(Contract):
    kind: Literal["comfortable", "tight", "breaches_buffer", "goes_negative"]
    text: NonEmpty


class Assumption(Contract):
    label: NonEmpty
    value: NonEmpty
    source: NonEmpty


class ScenarioComparisonData(Contract):
    scope: Scope
    baseline: BaselineLine
    scenarios: Annotated[list[ScenarioLine], Field(min_length=1, max_length=3)]
    comparison_rows: list[ComparisonRow] = []
    verdict: ScenarioVerdict | None = None  # omitted in relative mode or without a buffer
    assumptions: list[Assumption] = []

    @model_validator(mode="after")
    def _rows_match_scenarios(self) -> ScenarioComparisonData:
        if any(len(r.scenarios) != len(self.scenarios) for r in self.comparison_rows):
            raise ValueError("each comparison row needs one value per scenario")
        return self


class ScenarioComparison(BlockBase, ScenarioComparisonData):
    type: Literal["ScenarioComparison"]


# --- 5.5 TransactionTable ----------------------------------------------------------------------

Column = Literal[
    "date", "narration", "counterparty", "category", "amount", "payment_type", "source"
]


class CategoryLabel(Contract):
    key: NonEmpty
    label: NonEmpty


class RowSource(Contract):
    import_id: ImportId
    row_number: Annotated[int, Field(ge=1)]
    page: Annotated[int, Field(ge=1)] | None = None


class TransactionRow(Contract):
    txn_id: TransactionId
    date: dt.date
    narration_display: str  # redacted: no account, sort code, card or phone numbers or emails
    counterparty: str | None = None
    category: CategoryLabel
    amount: MoneyValue
    payment_type: str | None = None
    source: RowSource | None = None


class TransactionTable(BlockBase):
    type: Literal["TransactionTable"]
    columns: Annotated[list[Column], Field(min_length=1)]
    rows: Annotated[list[TransactionRow], Field(max_length=50)]
    total: MoneyValue
    count: CountValue
    has_more: bool
    query: TxnQuery


# --- 5.6 RiskAssessment ------------------------------------------------------------------------


class RiskDriver(Contract):
    label: NonEmpty
    impact: MoneyValue
    ref: Ref


class Risk(Contract):
    risk_id: NonEmpty
    level: Literal["low", "watch", "high"]
    headline: NonEmpty
    probability: PercentValue | None = None
    window: DateRange | None = None
    impact: MoneyValue | None = None
    drivers: list[RiskDriver] = []
    status: Literal["open", "acknowledged"]


class RiskAssessment(BlockBase):
    type: Literal["RiskAssessment"]
    risks: Annotated[list[Risk], Field(min_length=1, max_length=4)]


# --- 5.7 InterventionCard ----------------------------------------------------------------------

# Never renderable (§5.7): only versions with a persisted APPROVE verdict reach the card.
UNRENDERABLE_STATUSES = frozenset({"drafting", "rejected", "withdrawn", "expired"})


class RecommendationAction(Contract):
    type: NonEmpty
    label: NonEmpty
    detail: str


class LowDelta(Contract):
    cycle_label: NonEmpty
    before: MoneyValue
    after: MoneyValue


class InterventionImpact(Contract):
    monthly_saving: MoneyValue | None = None  # timing-only changes save nothing per month
    p_breach_before: PercentValue
    p_breach_after: PercentValue
    p_breach_window: DateRange
    low_deltas: list[LowDelta] = []
    goal_delta: MoneyValue | None = None


class CheckedVerification(Contract):
    verdict: Literal["approved"]
    revisions: Annotated[int, Field(ge=0)]
    checks_passed: Annotated[int, Field(ge=0)]
    checks_total: Annotated[int, Field(ge=0)]
    verification_id: VerificationId


class InterventionCard(_BlockCore):
    type: Literal["InterventionCard"]
    recommendation_id: RecommendationId
    version_id: NonEmpty
    title: Title
    rationale_segments: list[Segment]
    # The recommendation's own steps (§5.7). The card's controls (Accept, Simulate in Lab,
    # Not for me) are fixed by the renderer, so this block has no follow-up `actions`.
    actions: Annotated[list[RecommendationAction], Field(min_length=1)]
    impact: InterventionImpact
    verification: CheckedVerification
    triggered_by: list[Ref] = []
    status: NonEmpty

    @model_validator(mode="after")
    def _checked_only(self) -> InterventionCard:
        if self.status in UNRENDERABLE_STATUSES:
            raise ValueError(f"a {self.status} recommendation cannot be shown as checked")
        return self


# --- 5.8 GoalProjection ------------------------------------------------------------------------

StatusBand = Literal["on_track", "at_risk", "off_track"]


class GoalSummary(Contract):
    goal_id: GoalId
    name: NonEmpty
    target: MoneyValue
    target_date: DateValue
    funding_rule: NonEmpty


class GoalOutcome(Contract):
    p10: MoneyValue
    p50: MoneyValue
    p90: MoneyValue
    p_achieve: PercentValue
    status_band: StatusBand


class GoalScenario(Contract):
    label: NonEmpty
    p50: MoneyValue
    p_achieve: PercentValue
    status_band: StatusBand


class GoalProjection(BlockBase):
    type: Literal["GoalProjection"]
    scope: Scope
    goal: GoalSummary
    progress_now: MoneyValue
    projection: GoalOutcome
    trajectory: FanSeries
    scenarios: Annotated[list[GoalScenario], Field(max_length=2)] = []
    required_monthly_change: MoneyValue | None = None


# --- 5.9 EvidencePanel -------------------------------------------------------------------------

EvidenceKind = Literal[
    "calculation", "finding", "recommendation", "forecast", "transactions", "verification",
    "income_stream", "declared_obligation", "balance_anchor", "reconciliation", "format_profile",
    "layout_profile", "account_coverage",
]  # fmt: skip


class EvidenceInputs(Contract):
    transaction_count: Annotated[int, Field(ge=0)] | None = None
    date_range: DateRange | None = None
    params: dict[str, object] | None = None


class SourceProfile(Contract):
    kind: Literal["format", "layout"]
    id: NonEmpty
    name: NonEmpty
    source: Literal["builtin", "proposed", "user_confirmed"]


class SourceReconciliation(Contract):
    status: NonEmpty
    method: NonEmpty


class FormatInference(Contract):
    decimal_sep: str
    group_sep: str
    grouping: Literal["thousands", "lakh"]
    date_order: NonEmpty
    date_format: NonEmpty
    source: NonEmpty


class SourceChain(Contract):
    import_id: ImportId
    filename: NonEmpty
    importer: Literal["csv_statement", "pdf_statement", "manual"]
    source_type: Literal["csv", "xlsx", "xls", "pdf"] | None = None
    profile: SourceProfile | None = None
    rows: NonEmpty
    reconciliation: SourceReconciliation | None = None
    format_inference: FormatInference | None = None


class VerificationCheck(Contract):
    name: NonEmpty
    passed: bool
    kind: Literal["deterministic", "model"] | None = None
    detail: str | None = None


class Reproducible(Contract):
    seed: int | None = None
    inputs_hash: NonEmpty
    data_version: Annotated[int, Field(ge=0)]


class EvidenceItem(Contract):
    ref: Ref
    kind: EvidenceKind
    title: NonEmpty
    provenance: Provenance
    summary_lines: list[str]
    scope: Scope | None = None
    engine_version: str | None = None
    inputs: EvidenceInputs | None = None
    source_chain: SourceChain | None = None
    checks: list[VerificationCheck] | None = None
    critique: str | None = None
    reproducible: Reproducible | None = None
    # An app page listing what this evidence counts (e.g. a finding's transactions).
    link: Annotated[str, StringConstraints(pattern=r"^/[a-z]")] | None = None

    @model_validator(mode="after")
    def _checks_on_verification_only(self) -> EvidenceItem:
        if (self.checks is not None or self.critique is not None) and self.kind != "verification":
            raise ValueError("checks and critique belong on verification items only")
        return self


class EvidencePanel(BlockBase):
    type: Literal["EvidencePanel"]
    items: Annotated[list[EvidenceItem], Field(min_length=1, max_length=8)]


# --- 5.10 AgentExecutionTimeline ---------------------------------------------------------------

Agent = Literal["coordinator", "ledger", "analyst", "forecaster", "advisor", "verifier"]


class AgentStepView(Contract):
    step_id: NonEmpty
    agent: Agent
    node: NonEmpty
    label: NonEmpty
    # skipped: not run (deadline, budget, or a slot not built yet); cached: reused a stored answer
    status: Literal["ok", "rejected", "retried", "error", "skipped", "cached"]
    started_at: dt.datetime
    duration_ms: Annotated[int, Field(ge=0)]
    model: str | None = None
    tokens: Annotated[int, Field(ge=0)] | None = None
    outputs: list[Ref] = []
    note: str | None = None


class LoopAttempt(Contract):
    version_id: NonEmpty
    verdict: Literal["approve", "revise", "reject"]
    failed_checks: list[str] = []


class VerificationLoop(Contract):
    kind: Literal["verification"]
    recommendation_id: RecommendationId
    attempts: Annotated[list[LoopAttempt], Field(min_length=1)]


class RunCost(Contract):
    """Sums of the run's AgentStep usage (docs/08 §5.10, docs/00 §7). Shown only in How it was
    checked; `usd_estimate` = provider-reported tokens × catalogue price, labelled estimated."""

    model_calls: Annotated[int, Field(ge=0)]
    tokens: Annotated[int, Field(ge=0)]
    usd_estimate: Annotated[float, Field(ge=0)] | None  # null only if a model's price is missing
    cached: bool  # the answer was reused from the answer cache


class AgentExecutionTimeline(BlockBase):
    """`inline` is the compact checklist shown in the conversation while and after a run
    (step labels and status only); `summary` and `full` are the How-it-was-checked views."""

    type: Literal["AgentExecutionTimeline"]
    detail: Literal["inline", "summary", "full"]
    run_id: RunId
    workflow: NonEmpty
    duration_ms: Annotated[int, Field(ge=0)]
    steps: Annotated[list[AgentStepView], Field(min_length=1)]
    loops: list[VerificationLoop] = []
    cost: RunCost


# --- The block union ---------------------------------------------------------------------------

Block = Annotated[
    Narrative
    | ClarifyingQuestion
    | FinancialMetricGroup
    | SpendingBreakdownChart
    | CashFlowForecastChart
    | ScenarioComparison
    | TransactionTable
    | RiskAssessment
    | InterventionCard
    | GoalProjection
    | EvidencePanel
    | AgentExecutionTimeline,
    Field(discriminator="type"),
]
# SpendingBreakdownChart is itself a union on `mode` (a nested discriminated union).

BLOCK_TYPES = (
    "Narrative", "ClarifyingQuestion", "FinancialMetricGroup", "SpendingBreakdownChart",
    "CashFlowForecastChart", "ScenarioComparison", "TransactionTable", "RiskAssessment",
    "InterventionCard", "GoalProjection", "EvidencePanel", "AgentExecutionTimeline",
)  # fmt: skip
