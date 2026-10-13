"""The LLM-facing plan, `response_plan/1` (docs/08 §4.1, §5 "Plan" rows).

A plan carries references only: calculation paths (`calc_…#path`), entity ids (`fnd_`, `rec_`,
`fc_`, `sim_`, `run_` …) and typed transaction queries. It never carries a number, a tone or a
placement; the server hydrates those from persisted records (§8) and places blocks (§7a).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from backend.app.ui_contracts.primitives import (
    CalcRef,
    Contract,
    DateRange,
    FindingId,
    FollowUpPlan,
    ForecastId,
    GoalId,
    Label,
    NonEmpty,
    RecommendationId,
    RecurringObligationId,
    Ref,
    RunId,
    ScenarioId,
    SimulationId,
    TxnQuery,
    ValueFormat,
)

PlanIntent = Literal[
    "spending_question", "affordability", "scenario", "risk_review", "goal_check",
    "transaction_lookup", "recommendation_review", "explain_number", "smalltalk_or_unsupported",
]  # fmt: skip


class NarrativePlan(Contract):
    """Markdown-lite text with `{{calc_…#path|format}}` value placeholders and `{{fnd_…}}`,
    `{{rec_…}}`, `{{ver_…}}` mentions. No financial numerals outside placeholders (§5.0)."""

    type: Literal["Narrative"]
    text: Annotated[str, StringConstraints(min_length=1, max_length=900)]


class ClarifyingOption(Contract):
    label: Label
    question: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class ClarifyingQuestionPlan(Contract):
    type: Literal["ClarifyingQuestion"]
    question: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    options: Annotated[list[ClarifyingOption], Field(min_length=2, max_length=4)]


class MetricPlan(Contract):
    label: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    value_ref: CalcRef
    format: ValueFormat
    compare_ref: CalcRef | None = None
    compare_label: Annotated[str, StringConstraints(min_length=1, max_length=60)] | None = None


class FinancialMetricGroupPlan(Contract):
    type: Literal["FinancialMetricGroup"]
    metrics: Annotated[list[MetricPlan], Field(min_length=2, max_length=4)]


class SpendingQuery(Contract):
    group_by: Literal["category", "week", "month", "counterparty"]
    period: DateRange
    category_keys: list[NonEmpty] | None = None
    compare_to: Literal["median_3m", "previous_period"] | None = None


class SpendingBreakdownChartPlan(Contract):
    type: Literal["SpendingBreakdownChart"]
    mode: Literal["by_category", "by_merchant", "over_time", "vs_baseline"]
    source_ref: CalcRef | None = None
    query: SpendingQuery | None = None
    highlight_keys: list[NonEmpty] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> SpendingBreakdownChartPlan:
        if (self.source_ref is None) == (self.query is None):
            raise ValueError("give exactly one of source_ref or query")
        return self


class CashFlowForecastChartPlan(Contract):
    type: Literal["CashFlowForecastChart"]
    forecast_ref: ForecastId
    history_days: Annotated[int, Field(ge=0, le=90)] = 30
    horizon_days: Annotated[int, Field(ge=1)] | None = None
    annotate: Annotated[list[RecurringObligationId | ScenarioId], Field(max_length=6)] = []
    highlight_window: DateRange | None = None


class ScenarioComparisonPlan(Contract):
    type: Literal["ScenarioComparison"]
    baseline_ref: ForecastId
    simulation_refs: Annotated[list[SimulationId], Field(min_length=1, max_length=3)]
    emphasis_metric: Literal["min_balance", "p_breach_buffer", "goal_progress", "month_end"]


TxnColumn = Literal[
    "date", "narration", "counterparty", "category", "amount", "payment_type", "source"
]


class TransactionTablePlan(Contract):
    type: Literal["TransactionTable"]
    query: TxnQuery
    columns: list[TxnColumn] | None = None


class RiskPlan(Contract):
    finding_ref: FindingId | None = None
    metric_ref: CalcRef | None = None

    @model_validator(mode="after")
    def _something(self) -> RiskPlan:
        if self.finding_ref is None and self.metric_ref is None:
            raise ValueError("a risk needs a finding_ref or a metric_ref")
        return self


class RiskAssessmentPlan(Contract):
    type: Literal["RiskAssessment"]
    risks: Annotated[list[RiskPlan], Field(min_length=1, max_length=4)]


class InterventionCardPlan(Contract):
    type: Literal["InterventionCard"]
    recommendation_ref: RecommendationId


class GoalProjectionPlan(Contract):
    type: Literal["GoalProjection"]
    goal_ref: GoalId
    projection_ref: CalcRef
    scenario_projection_refs: Annotated[list[CalcRef], Field(max_length=2)] = []


class EvidencePanelPlan(Contract):
    type: Literal["EvidencePanel"]
    refs: Annotated[list[Ref], Field(min_length=1, max_length=8)]


class AgentExecutionTimelinePlan(Contract):
    type: Literal["AgentExecutionTimeline"]
    run_ref: RunId
    detail: Literal["inline", "summary", "full"]


BlockPlan = Annotated[
    NarrativePlan
    | ClarifyingQuestionPlan
    | FinancialMetricGroupPlan
    | SpendingBreakdownChartPlan
    | CashFlowForecastChartPlan
    | ScenarioComparisonPlan
    | TransactionTablePlan
    | RiskAssessmentPlan
    | InterventionCardPlan
    | GoalProjectionPlan
    | EvidencePanelPlan
    | AgentExecutionTimelinePlan,
    Field(discriminator="type"),
]


class ResponsePlan(Contract):
    schema_: Literal["response_plan/1"] = Field(alias="schema")
    intent: PlanIntent
    blocks: Annotated[list[BlockPlan], Field(min_length=1, max_length=8)]
    follow_ups: Annotated[list[FollowUpPlan], Field(max_length=4)] = []

    model_config = Contract.model_config | {"populate_by_name": True}
