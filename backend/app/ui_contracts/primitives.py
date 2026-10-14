"""Shared primitives for the generative-UI contracts (docs/08 §3).

References, hydrated values, placement, scope, follow-up actions and the typed transaction query.
Every model forbids unknown fields: the server is the only producer of hydrated JSON, so an
unexpected field is a hydrator bug (docs/08 §6 Step 2), and the plan is LLM output that must
match its schema exactly. Clients stay tolerant of additions within a major version (§11).
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# --- References (§3.1) -------------------------------------------------------------------------

ULID = r"[0-9A-HJKMNP-TV-Z]{26}"
# Entity prefixes from §3.1, plus `calc_` for a whole calculation (EvidencePanel and block
# `evidence` lists cite calculations without a path).
ENTITY_PREFIXES = (
    "calc", "fnd", "fc", "scn", "sim", "rec", "ver", "goal", "rob", "txn", "run", "imp", "acct",
    "bal", "inc", "dob", "cpty", "fmt", "lay", "rcn",
)  # fmt: skip
# Engine records are content-addressed: the same question on the same data always maps to the
# same id (finance_core.calc.record), written as 24 lowercase hex digits instead of a ULID.
CONTENT_HASH = r"[0-9a-f]{24}"
CONTENT_PREFIXES = ("calc", "fc", "scn", "sim")
CALC_BODY = rf"({ULID}|{CONTENT_HASH})"
CALC_PATH = r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*"
CALC_REF_PATTERN = rf"^calc_{CALC_BODY}#{CALC_PATH}$"
ENTITY_REF_BODY = (
    rf"({'|'.join(CONTENT_PREFIXES)})_({ULID}|{CONTENT_HASH})|({'|'.join(ENTITY_PREFIXES)})_{ULID}"
)
ENTITY_REF_PATTERN = rf"^({ENTITY_REF_BODY})$"
REF_PATTERN = rf"^(calc_{CALC_BODY}#{CALC_PATH}|{ENTITY_REF_BODY})$"


def _id(prefix: str) -> StringConstraints:
    body = rf"({ULID}|{CONTENT_HASH})" if prefix in CONTENT_PREFIXES else ULID
    return StringConstraints(pattern=rf"^{prefix}_{body}$")


CalcRef = Annotated[str, StringConstraints(pattern=CALC_REF_PATTERN)]
Ref = Annotated[str, StringConstraints(pattern=REF_PATTERN)]
CalcId = Annotated[str, _id("calc")]
FindingId = Annotated[str, _id("fnd")]
ForecastId = Annotated[str, _id("fc")]
ScenarioId = Annotated[str, _id("scn")]
SimulationId = Annotated[str, _id("sim")]
RecommendationId = Annotated[str, _id("rec")]
VerificationId = Annotated[str, _id("ver")]
GoalId = Annotated[str, _id("goal")]
RecurringObligationId = Annotated[str, _id("rob")]
IncomeStreamId = Annotated[str, _id("inc")]
TransactionId = Annotated[str, _id("txn")]
RunId = Annotated[str, _id("run")]
ImportId = Annotated[str, _id("imp")]
AccountId = Annotated[str, _id("acct")]
ResponseId = Annotated[str, _id("rsp")]
WorkspaceId = Annotated[str, _id("wsp")]

Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Locale = Annotated[str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- Money (§3.2, §3.2b) ----------------------------------------------------------------------


class MoneyAmount(Contract):
    """An exact amount before formatting: ISO 4217 minor units plus the currency."""

    amount_minor: int
    currency: Currency


Precision = Literal["exact", "rounded"]


class MoneyValue(Contract):
    """Hydrated money. `display` is always formatted by the server (§3.2b); clients never
    re-format `minor`."""

    kind: Literal["money"]
    minor: int
    currency: Currency
    display: NonEmpty
    precision: Precision
    ref: Ref | None = None
    depends_on_declared: bool | None = None


class PercentValue(Contract):
    kind: Literal["percent"]
    value: Annotated[float, Field(ge=0, le=1)]
    display: NonEmpty
    ref: Ref | None = None


class PctChangeValue(Contract):
    kind: Literal["pct_change"]
    value: float
    display: NonEmpty
    ref: Ref | None = None


class PpChangeValue(Contract):
    kind: Literal["pp_change"]
    value: float
    display: NonEmpty
    ref: Ref | None = None


class CountValue(Contract):
    kind: Literal["count"]
    value: Annotated[int, Field(ge=0)]
    display: NonEmpty
    ref: Ref | None = None


class DateValue(Contract):
    kind: Literal["date"]
    value: dt.date
    display: NonEmpty
    ref: Ref | None = None


class DaysValue(Contract):
    kind: Literal["days"]
    value: int
    display: NonEmpty
    ref: Ref | None = None


Value = Annotated[
    MoneyValue | PercentValue | PctChangeValue | PpChangeValue | CountValue | DateValue | DaysValue,
    Field(discriminator="kind"),
]
ValueFormat = Literal["money", "percent", "pct_change", "pp_change", "count", "date", "days"]


# --- Scope, provenance, tone (§3.2a, §3.3) -----------------------------------------------------

Provenance = Literal["observed", "detected", "confirmed", "declared", "user_set", "default"]
Tone = Literal["neutral", "positive", "negative", "caution", "accent", "simulated"]


class Scope(Contract):
    kind: Literal["mine", "household", "account"]
    label: NonEmpty
    account_ids: list[AccountId]
    switchable: bool


class DateRange(Contract):
    from_: dt.date = Field(alias="from")
    to: dt.date

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_validator(mode="after")
    def _ordered(self) -> DateRange:
        if self.to < self.from_:
            raise ValueError("date range ends before it starts")
        return self


# --- Placement (§4.3, §7a) ---------------------------------------------------------------------

OverviewSlot = Literal["verdict", "key_numbers", "main_visual", "what_to_do", "evidence"]
TabName = Literal["details", "recommendation", "transactions", "checked"]
SLOT_ORDER: tuple[OverviewSlot, ...] = (
    "verdict", "key_numbers", "main_visual", "what_to_do", "evidence",
)  # fmt: skip
TAB_ORDER: tuple[TabName, ...] = ("details", "recommendation", "transactions", "checked")


class OverviewPlacement(Contract):
    area: Literal["overview"]
    slot: OverviewSlot


class TabPlacement(Contract):
    area: Literal["tab"]
    tab: TabName


Placement = Annotated[OverviewPlacement | TabPlacement, Field(discriminator="area")]


# --- TxnQuery (§3.5) ---------------------------------------------------------------------------


class TxnQuery(Contract):
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    category_keys: list[NonEmpty] | None = None
    counterparties: list[NonEmpty] | None = None
    recurring_obligation_ids: list[RecurringObligationId] | None = None
    direction: Literal["in", "out"] | None = None
    min_minor: Annotated[int, Field(ge=0)] | None = None
    max_minor: Annotated[int, Field(ge=0)] | None = None
    hour_from: Annotated[int, Field(ge=0, le=23)] | None = None
    include_transfers: bool = False
    sort: Literal["date_desc", "amount_desc"] = "date_desc"
    limit: Annotated[int, Field(ge=1, le=50)] = 20


# --- ScenarioSpec (docs/07 §6.5; the engine re-validates every field before running) ----------

ModifierType = Literal[
    "one_off_outflow", "one_off_inflow", "split_outflow", "income_delay", "income_change_pct",
    "recurring_add", "recurring_change", "recurring_cancel", "category_cut_pct", "category_cap",
    "move_to_goal", "buffer_override",
]  # fmt: skip


class ScenarioModifierSpec(BaseModel):
    """One modifier. Per-type fields vary (docs/07 §6.5) and are checked by the engine."""

    model_config = ConfigDict(extra="allow", frozen=True)
    type: ModifierType


class ScenarioSpecPayload(Contract):
    schema_: Literal["scenario_spec/1"] = Field(alias="schema")
    name: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    scope: Literal["mine", "household", "account"]
    scope_account_id: AccountId | None = None
    currency: Currency
    horizon_days: Annotated[int, Field(ge=30, le=365)] | None = None
    assumptions: list[str] = []
    modifiers: Annotated[list[ScenarioModifierSpec], Field(max_length=12)]

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


# --- Follow-up actions (§3.4) ------------------------------------------------------------------


class AskPayload(Contract):
    question: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    context_refs: list[Ref] = []


class SimulatePayload(Contract):
    scenario_spec: ScenarioSpecPayload


class OpenLabPayload(Contract):
    scenario_id: ScenarioId | None = None
    prefill_spec: ScenarioSpecPayload | None = None


class OpenEvidencePayload(Contract):
    ref: Ref


class FilterTransactionsPayload(Contract):
    txn_query: TxnQuery


class RecommendationPayload(Contract):
    recommendation_id: RecommendationId


class AdjustScenarioPayload(Contract):
    scenario_id: ScenarioId
    modifier_index: Annotated[int, Field(ge=0)]
    field: NonEmpty
    min: float
    max: float
    step: Annotated[float, Field(gt=0)]


class SetBufferPayload(Contract):
    suggested_minor: Annotated[int, Field(ge=0)]


class MarkUnusedPayload(Contract):
    recurring_obligation_id: RecurringObligationId


class SwitchScopePayload(Contract):
    scope: Literal["mine", "household", "account"]
    account_id: AccountId | None = None


FollowUpKind = Literal[
    "ask", "simulate", "open_lab", "open_evidence", "filter_transactions",
    "accept_recommendation", "dismiss_recommendation", "adjust_scenario", "set_buffer",
    "mark_unused", "switch_scope",
]  # fmt: skip
# State-changing kinds always need explicit confirmation (§3.4, §12).
CONFIRM_KINDS = frozenset({"accept_recommendation", "dismiss_recommendation", "mark_unused",
                           "set_buffer"})  # fmt: skip

Label = Annotated[str, StringConstraints(min_length=1, max_length=48)]


class _FollowUpPlanBase(Contract):
    """What the LLM may write: a label (no digits except {{ }} placeholders) and a payload."""

    label: Label


class _FollowUpActionBase(Contract):
    action_id: NonEmpty
    label: Label
    requires_confirmation: bool

    @model_validator(mode="after")
    def _confirmation(self) -> _FollowUpActionBase:
        kind = getattr(self, "kind", "")
        if kind in CONFIRM_KINDS and not self.requires_confirmation:
            raise ValueError(f"follow-up kind {kind!r} must require confirmation")
        return self


class _Ask(BaseModel):
    kind: Literal["ask"]
    payload: AskPayload


class _Simulate(BaseModel):
    kind: Literal["simulate"]
    payload: SimulatePayload


class _OpenLab(BaseModel):
    kind: Literal["open_lab"]
    payload: OpenLabPayload


class _OpenEvidence(BaseModel):
    kind: Literal["open_evidence"]
    payload: OpenEvidencePayload


class _FilterTransactions(BaseModel):
    kind: Literal["filter_transactions"]
    payload: FilterTransactionsPayload


class _AcceptRecommendation(BaseModel):
    kind: Literal["accept_recommendation"]
    payload: RecommendationPayload


class _DismissRecommendation(BaseModel):
    kind: Literal["dismiss_recommendation"]
    payload: RecommendationPayload


class _AdjustScenario(BaseModel):
    kind: Literal["adjust_scenario"]
    payload: AdjustScenarioPayload


class _SetBuffer(BaseModel):
    kind: Literal["set_buffer"]
    payload: SetBufferPayload


class _MarkUnused(BaseModel):
    kind: Literal["mark_unused"]
    payload: MarkUnusedPayload


class _SwitchScope(BaseModel):
    kind: Literal["switch_scope"]
    payload: SwitchScopePayload


class AskPlan(_FollowUpPlanBase, _Ask): ...


class SimulatePlan(_FollowUpPlanBase, _Simulate): ...


class OpenLabPlan(_FollowUpPlanBase, _OpenLab): ...


class OpenEvidencePlan(_FollowUpPlanBase, _OpenEvidence): ...


class FilterTransactionsPlan(_FollowUpPlanBase, _FilterTransactions): ...


class AcceptRecommendationPlan(_FollowUpPlanBase, _AcceptRecommendation): ...


class DismissRecommendationPlan(_FollowUpPlanBase, _DismissRecommendation): ...


class AdjustScenarioPlan(_FollowUpPlanBase, _AdjustScenario): ...


class SetBufferPlan(_FollowUpPlanBase, _SetBuffer): ...


class MarkUnusedPlan(_FollowUpPlanBase, _MarkUnused): ...


class SwitchScopePlan(_FollowUpPlanBase, _SwitchScope): ...


class AskAction(_FollowUpActionBase, _Ask): ...


class SimulateAction(_FollowUpActionBase, _Simulate): ...


class OpenLabAction(_FollowUpActionBase, _OpenLab): ...


class OpenEvidenceAction(_FollowUpActionBase, _OpenEvidence): ...


class FilterTransactionsAction(_FollowUpActionBase, _FilterTransactions): ...


class AcceptRecommendationAction(_FollowUpActionBase, _AcceptRecommendation): ...


class DismissRecommendationAction(_FollowUpActionBase, _DismissRecommendation): ...


class AdjustScenarioAction(_FollowUpActionBase, _AdjustScenario): ...


class SetBufferAction(_FollowUpActionBase, _SetBuffer): ...


class MarkUnusedAction(_FollowUpActionBase, _MarkUnused): ...


class SwitchScopeAction(_FollowUpActionBase, _SwitchScope): ...


FollowUpPlan = Annotated[
    AskPlan
    | SimulatePlan
    | OpenLabPlan
    | OpenEvidencePlan
    | FilterTransactionsPlan
    | AcceptRecommendationPlan
    | DismissRecommendationPlan
    | AdjustScenarioPlan
    | SetBufferPlan
    | MarkUnusedPlan
    | SwitchScopePlan,
    Field(discriminator="kind"),
]
FollowUpAction = Annotated[
    AskAction
    | SimulateAction
    | OpenLabAction
    | OpenEvidenceAction
    | FilterTransactionsAction
    | AcceptRecommendationAction
    | DismissRecommendationAction
    | AdjustScenarioAction
    | SetBufferAction
    | MarkUnusedAction
    | SwitchScopeAction,
    Field(discriminator="kind"),
]
