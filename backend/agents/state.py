"""LangGraph state (docs/06 §7). Heavy data lives in the database; the state carries references.

Everything here is JSON-serialisable so the Postgres checkpointer can store it.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

Workflow = Literal[
    "ingestion", "risk_detection", "scenario", "recommendation", "conversation", "digest"
]
Trigger = Literal["user", "event", "cron", "eval"]


class StepError(TypedDict):
    node: str
    error: str


class ForesightState(TypedDict, total=False):
    # identity & control
    run_id: str
    workspace_id: str
    workflow: Workflow
    trigger: Trigger
    event: str | None  # system trigger name, e.g. "import_committed" (docs/06 §6.1)
    data_version: int
    prefs_version: int
    currency: str
    as_of: str  # ISO date
    scope: str  # mine | household | account:<id>
    locale_pack: str
    home_currency: str
    errors: Annotated[list[StepError], operator.add]
    partial: Annotated[bool, operator.or_]  # parallel branches may both set it

    # inputs
    thread_id: str | None
    user_message: str | None
    history: list[dict[str, Any]]  # last ≤3 user turns: {question, intent, slots, block_types}
    import_id: str | None
    scenario_input: dict[str, Any] | str | None

    # coordinator
    route: list[str]  # planned specialist nodes for this run
    intent: dict[str, Any] | None  # IntentClassification.model_dump()
    screen_verdict: Literal["allow", "suspicious", "block"] | None
    screen_rules: list[str]
    ai_paused: bool
    snapshot_id: str | None
    cache_key: str | None
    cache_hit: bool

    # specialist outputs (refs only)
    findings: list[str]
    forecast_id: str | None
    simulation_ids: list[str]
    txn_queries: list[str]  # calc_ ids of saved transaction queries (ledger_query)
    risk_flags: list[dict[str, Any]]
    proposals: list[dict[str, Any]]
    verifications: list[str]
    verdict: Literal["approve", "reject", "none"] | None
    revision_round: int
    approved_recs: list[str]
    withdrawn: list[str]

    # output
    block_plan: dict[str, Any] | None
    response_body: dict[str, Any] | None
    answer_kind: Literal["answer", "refusal", "clarify", "unavailable"] | None
    response_id: str | None
    needs_user_input: dict[str, Any] | None
