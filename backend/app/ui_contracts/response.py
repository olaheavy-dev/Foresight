"""The hydrated envelope `agent_response/1` (docs/08 §4.2) and the engine-only API views."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from backend.app.ui_contracts.blocks import Block, CashFlowForecastData, ScenarioComparisonData
from backend.app.ui_contracts.plan import PlanIntent
from backend.app.ui_contracts.primitives import (
    CalcId,
    Contract,
    Currency,
    FindingId,
    FollowUpAction,
    ForecastId,
    ImportId,
    Locale,
    NonEmpty,
    RecommendationId,
    ResponseId,
    RunId,
    ScenarioId,
    SimulationId,
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


class ImportSummary(Contract):
    import_id: ImportId
    workspace_id: WorkspaceId
    data_version: Annotated[int, Field(ge=0)]
    files: Annotated[list[ImportedFile], Field(min_length=1)]


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
