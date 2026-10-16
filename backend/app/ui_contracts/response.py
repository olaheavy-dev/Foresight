"""The hydrated envelope `agent_response/1` (docs/08 §4.2) and the engine-only API views."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from backend.app.ui_contracts.blocks import (
    Block,
    CashFlowForecastData,
    InterventionCard,
    ScenarioComparisonData,
)
from backend.app.ui_contracts.plan import PlanIntent
from backend.app.ui_contracts.primitives import (
    AccountId,
    CalcId,
    Contract,
    Currency,
    DateRange,
    FindingId,
    FollowUpAction,
    ForecastId,
    ImportId,
    IncomeStreamId,
    Locale,
    MoneyValue,
    NonEmpty,
    RecommendationId,
    RecurringObligationId,
    ResponseId,
    RunId,
    ScenarioId,
    SimulationId,
    TransactionId,
    WorkspaceId,
)


class EvidenceLine(Contract):
    """The Overview's one line: "Checked by N agents · M drafts rejected · View how"."""

    agents: Annotated[int, Field(ge=0)]
    rejected_drafts: Annotated[int, Field(ge=0)]
    run_id: RunId


class RecommendationVerdict(Contract):
    recommendation_id: RecommendationId
    verdict: Literal["approve", "revise", "reject"]
    revisions: Annotated[int, Field(ge=0)]


class ResponseVerification(Contract):
    recommendations: list[RecommendationVerdict]


class ResponseProvenance(Contract):
    calc_ids: list[CalcId] = []
    finding_ids: list[FindingId] = []
    recommendation_ids: list[RecommendationId] = []


class AgentResponse(Contract):
    schema_version: Literal["agent_response/1"]
    response_id: ResponseId
    run_id: RunId
    thread_id: str | None = None
    surface: Literal["workspace", "home", "insight", "lab", "digest"]
    intent: PlanIntent | None = None
    question: str | None = None
    created_at: dt.datetime
    as_of: dt.date
    workspace_id: WorkspaceId
    currency: Currency
    locale: Locale
    data_version: Annotated[int, Field(ge=0)]
    prefs_version: Annotated[int, Field(ge=0)]
    forecast_id: ForecastId | None = None
    engine_version: NonEmpty
    status: Literal["complete", "degraded"]
    blocks: Annotated[list[Block], Field(min_length=1, max_length=10)]
    evidence_line: EvidenceLine | None = None
    follow_ups: Annotated[list[FollowUpAction], Field(max_length=4)] = []
    verification: ResponseVerification | None = None
    provenance: ResponseProvenance
    # The advice loop ran out of question time: a checked recommendation follows in this thread
    # (docs/06 §13). The follow-up answer names the answer it follows up.
    followup_pending: bool = False
    follow_up_of: ResponseId | None = None


# --- Engine-only API (API-00): the same hydrated shapes, without an agent run ------------------


class Healthz(Contract):
    status: Literal["ok", "unavailable"]
    sha: str | None
    database: bool | None


class Feature(Contract):
    key: NonEmpty
    stage: int
    title: NonEmpty
    enabled: bool


class FeaturesPayload(Contract):
    features: list[Feature]


class ImportReconciliation(Contract):
    status: Literal["passed", "failed", "not_possible"]
    method: NonEmpty


class ImportQuestion(Contract):
    """Something only the user can answer before (or after) a file is used (docs/06 H13)."""

    kind: NonEmpty
    prompt: NonEmpty
    options: list[str] = []
    preselected: str | None = None
    # "columns" only: an example cell per option (same order) and the roles already recognised.
    examples: list[Annotated[str, StringConstraints(max_length=24)]] = []
    proposed: dict[str, str] | None = None
    # "columns" only: options are opaque column ids (c0, c1, …); these are what to show for
    # each, with long digit runs masked; and the table the question is about.
    labels: list[Annotated[str, StringConstraints(max_length=60)]] = []
    table_id: str | None = None


class ImportedFile(Contract):
    filename: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    source_type: Literal["csv", "xlsx", "xls", "pdf"]
    status: Literal["imported", "needs_mapping", "rejected"]
    currency: Currency | None = None
    rows_read: Annotated[int, Field(ge=0)]
    rows_imported: Annotated[int, Field(ge=0)]
    rows_rejected: Annotated[int, Field(ge=0)]
    reconciliation: ImportReconciliation | None = None
    messages: list[str] = []
    # API-00 detail: one import batch per table found in the file.
    import_ids: list[ImportId] = []
    already_imported: bool = False  # the same file was imported before; nothing added
    duplicates: Annotated[int, Field(ge=0)] = 0
    matched_profile: str | None = None
    period: DateRange | None = None  # first and last date of the rows imported
    rejections: list[str] = []  # row-level reasons a file doesn't add up
    questions: list[ImportQuestion] = []


class ImportSummary(Contract):
    import_id: ImportId | None  # the first import batch this request created; null if none
    workspace_id: WorkspaceId
    data_version: Annotated[int, Field(ge=0)]
    files: Annotated[list[ImportedFile], Field(min_length=1)]


class SessionAccount(Contract):
    """Who the session belongs to: a guest, or a signed-in Google account."""

    kind: Literal["guest", "google"]
    name: str | None = None
    email: str | None = None


class ProfileView(Contract):
    """The profile (workspace) the session cookie points at."""

    workspace_id: WorkspaceId
    name: NonEmpty
    kind: Literal["demo", "user"]
    persona: str | None = None
    country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]
    home_currency: Currency
    locale: Locale
    timezone: NonEmpty
    data_version: Annotated[int, Field(ge=0)]
    read_only: bool  # edits refused (the shared template only); demo profiles never take imports
    account: SessionAccount | None = None
    # The balance the forecast keeps above (home-currency minor units); None when not set.
    buffer_minor: Annotated[int, Field(ge=0)] | None = None


class ProfileUpdate(Contract):
    """Settings: rename the profile or set its buffer. Fields left out are unchanged; an explicit
    `buffer_minor: null` clears the buffer."""

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)] | (
        None
    ) = None
    buffer_minor: Annotated[int, Field(ge=0, le=10_000_000_000)] | None = None


class TransactionRow(Contract):
    transaction_id: TransactionId
    account_id: AccountId
    import_id: ImportId | None = None
    posted_on: dt.date
    narration: str
    counterparty: str | None = None
    channel: NonEmpty
    amount: MoneyValue
    category_key: str | None = None
    flow_kind: str | None = None
    categorised_by: Literal["rule", "memory", "llm", "user"] | None = None
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None


class TransactionPage(Contract):
    workspace_id: WorkspaceId
    total: Annotated[int, Field(ge=0)]
    limit: Annotated[int, Field(ge=1)]
    offset: Annotated[int, Field(ge=0)]
    items: list[TransactionRow]


class CalculationView(Contract):
    """A stored engine calculation, for the Evidence drawer (docs/07 §6, docs/08 §8)."""

    calc_id: CalcId
    kind: NonEmpty
    workspace_id: WorkspaceId
    currency: Currency | None = None
    inputs_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    result_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    engine_version: NonEmpty
    data_version: Annotated[int, Field(ge=0)]
    duration_ms: Annotated[int, Field(ge=0)]
    created_at: dt.datetime
    params: dict[str, Any]
    result: dict[str, Any]


class ForecastView(Contract):
    forecast_id: ForecastId
    workspace_id: WorkspaceId
    currency: Currency
    locale: Locale
    engine_version: NonEmpty
    data_version: Annotated[int, Field(ge=0)]
    chart: CashFlowForecastData


class SimulationView(Contract):
    simulation_id: SimulationId
    scenario_id: ScenarioId
    workspace_id: WorkspaceId
    currency: Currency
    locale: Locale
    engine_version: NonEmpty
    comparison: ScenarioComparisonData


# --- Financial data (`/start` "Check what we found", Transactions tabs) --------------------------


class AccountBalance(Contract):
    """The latest known balance of an account and where it came from (docs/01 F-10)."""

    money: MoneyValue
    as_of: dt.date
    provenance: Literal["statement_column", "declared"]


class AccountView(Contract):
    account_id: AccountId
    name: NonEmpty
    institution: str | None = None
    type: NonEmpty
    currency: Currency
    tracked: bool
    transactions: Annotated[int, Field(ge=0)]
    period: DateRange | None = None
    balance: AccountBalance | None = None  # None: no balance column and none declared yet


class AccountList(Contract):
    workspace_id: WorkspaceId
    accounts: list[AccountView]


class BalanceDeclaration(Contract):
    """The user's "balance today" for an account (provenance declared)."""

    as_of: dt.date
    amount_minor: int


class IncomeStreamView(Contract):
    income_stream_id: IncomeStreamId
    source: NonEmpty
    amount: MoneyValue
    cadence: NonEmpty
    # rejected: the user said "this isn't income", so the forecast doesn't count it (R4)
    provenance: Literal["detected", "confirmed", "declared", "rejected"]
    payments: Annotated[int, Field(ge=0)]
    last_paid: dt.date | None = None


class IncomeDecision(Contract):
    """The user's word on a detected income stream (review R4)."""

    decision: Literal["confirm", "reject", "undo"]


class RecurringView(Contract):
    recurring_id: RecurringObligationId
    label: NonEmpty
    category_key: NonEmpty
    amount: MoneyValue  # the outflow as a positive amount
    cadence: NonEmpty
    day_of_month: Annotated[int, Field(ge=1, le=31)] | None = None
    is_commitment: bool
    provenance: NonEmpty
    payments: Annotated[int, Field(ge=0)]
    last_paid: dt.date | None = None


class DetectedFlows(Contract):
    workspace_id: WorkspaceId
    income: list[IncomeStreamView]
    recurring: list[RecurringView]


# --- Transactions page (docs/01 F-07, F-11, F-51) ------------------------------------------------


class CategoryOption(Contract):
    key: NonEmpty
    nature: NonEmpty
    flow_kind: NonEmpty


class CategoryList(Contract):
    categories: list[CategoryOption]


class CategoryCorrection(Contract):
    category_key: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    apply_to_merchant: bool = False


class CategoryCorrected(Contract):
    category_key: NonEmpty
    transaction_ids: list[TransactionId]
    data_version: Annotated[int, Field(ge=0)]


class ImportBatchView(Contract):
    import_id: ImportId
    filename: NonEmpty
    status: NonEmpty  # committed | needs_review | rejected
    account_id: AccountId | None = None
    format_profile: str | None = None
    rows_read: Annotated[int, Field(ge=0)]
    rows_imported: Annotated[int, Field(ge=0)]
    duplicates: Annotated[int, Field(ge=0)]
    reconciliation: str | None = None
    imported_at: dt.datetime
    message: str | None = None


class ImportHistory(Contract):
    workspace_id: WorkspaceId
    imports: list[ImportBatchView]


class InsightFinding(Contract):
    """A deterministic behaviour finding, with every figure filled from its stored calculation."""

    finding_id: FindingId
    kind: NonEmpty
    severity: Literal["info", "watch", "act"]
    headline: NonEmpty
    detail: str = ""
    link: str | None = None  # an app path to the supporting transactions


class HomeInsights(Contract):
    """Home's proactive insights (review R2): findings always; checked recommendations from the
    latest proactive run; the state of that run and why advice is paused, if it is."""

    workspace_id: WorkspaceId
    status: Literal["empty", "checking", "ready", "paused", "failed"]
    reason: Literal["ai_paused", "daily_limit", "not_run"] | None = None
    data_version: int
    checked_data_version: int | None = None
    checked_at: dt.datetime | None = None
    findings: list[InsightFinding] = []
    recommendations: list[InterventionCard] = []
    can_check: bool = False


class ActivityStep(Contract):
    """One step of an agent run: what ran and what it cost. Never the prompt or the output."""

    seq: Annotated[int, Field(ge=0)]
    node: NonEmpty
    agent: NonEmpty
    kind: NonEmpty  # llm | tool | control
    label: str = ""
    model: str | None = None  # vendor/model behind the Mesh gateway, for model calls
    status: NonEmpty
    cached: bool = False
    latency_ms: Annotated[int, Field(ge=0)] | None = None
    tokens_in: Annotated[int, Field(ge=0)] = 0
    tokens_out: Annotated[int, Field(ge=0)] = 0
    cost_usd: Annotated[float, Field(ge=0)] | None = None


class ActivityRun(Contract):
    """An agent run as a trace (docs/05 "Traces stay in-house"): its steps are the spans."""

    run_id: RunId
    workflow: NonEmpty
    trigger: NonEmpty  # user | event | cron | eval
    status: NonEmpty
    partial: bool = False
    question: str | None = None  # the user's own question, for a conversation run
    started_at: dt.datetime
    duration_ms: Annotated[int, Field(ge=0)] | None = None
    llm_calls: Annotated[int, Field(ge=0)] = 0
    tokens_in: Annotated[int, Field(ge=0)] = 0
    tokens_out: Annotated[int, Field(ge=0)] = 0
    cost_usd: Annotated[float, Field(ge=0)] | None = None
    revisions: Annotated[int, Field(ge=0)] = 0
    approved: Annotated[int, Field(ge=0)] = 0  # Verifier verdicts in this run
    rejected: Annotated[int, Field(ge=0)] = 0
    steps: list[ActivityStep] = []


class ActivityEvent(Contract):
    """One entry of the profile's hash-chained audit log, in words."""

    seq: Annotated[int, Field(ge=1)]
    occurred_at: NonEmpty
    actor: NonEmpty
    action: NonEmpty
    summary: NonEmpty


class ActivityFeed(Contract):
    workspace_id: WorkspaceId
    runs: list[ActivityRun] = []
    events: list[ActivityEvent] = []
    audit_events: Annotated[int, Field(ge=0)] = 0
    audit_chain_intact: bool
