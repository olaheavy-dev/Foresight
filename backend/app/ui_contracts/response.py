"""The hydrated envelope `agent_response/1` (docs/08 §4.2) and the engine-only API views."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from backend.app.ui_contracts.blocks import Block, CashFlowForecastData, ScenarioComparisonData
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
    Locale,
    MoneyValue,
    NonEmpty,
    RecommendationId,
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
    read_only: bool  # demo profiles refuse imports


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
