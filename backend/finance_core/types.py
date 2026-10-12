"""Shared value types for the deterministic engine (docs/07 §3, §6).

These are the contracts between importers, categorisation, detectors, the forecast engine and the
evaluation harness. Pure data: no I/O, no models. Money is always integer minor units plus an
ISO 4217 currency code; never floats for stored amounts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from enum import Enum

# --------------------------------------------------------------------------- money


@dataclass(frozen=True)
class Money:
    amount_minor: int  # negative = money out, positive = money in
    currency: str  # ISO 4217, e.g. "GBP"


# --------------------------------------------------------------------------- enums


class FlowKind(str, Enum):
    """How a row counts (docs/07 §3.2 flow_kind table)."""

    SPENDING = "spending"
    INCOME = "income"
    REFUND = "refund"
    REIMBURSEMENT = "reimbursement"
    SPLIT_SETTLEMENT = "split_settlement"
    COMMITMENT = "commitment"
    TRANSFER_OWN = "transfer_own"
    TRANSFER_TO_UNTRACKED = "transfer_to_untracked"
    TRANSFER_FROM_UNTRACKED = "transfer_from_untracked"
    INFLOW_UNCONFIRMED = "inflow_unconfirmed"
    CARD_SETTLEMENT = "card_settlement"
    CREDIT_CARD_BILL_UNITEMISED = "credit_card_bill_unitemised"
    PARTNER_CONTRIBUTION = "partner_contribution"
    SAVINGS_INVESTMENT = "savings_investment"
    LOAN_REPAYMENT = "loan_repayment"
    BETTING = "betting"
    BETTING_RETURN = "betting_return"
    FEE = "fee"
    TAX = "tax"


class Channel(str, Enum):
    """Payment channel parsed from the narration / bank type (UK codes via the uk locale pack)."""

    CARD = "card"  # DEB, Monzo "Card payment"
    DIRECT_DEBIT = "direct_debit"  # DD
    STANDING_ORDER = "standing_order"  # SO
    FASTER_PAYMENT_OUT = "faster_payment_out"  # FPO
    FASTER_PAYMENT_IN = "faster_payment_in"  # FPI
    BACS_CREDIT = "bacs_credit"  # BGC, "Bacs (Direct Credit)"
    TRANSFER = "transfer"  # TFR
    CASH = "cash"  # CPT / ATM
    UPI = "upi"  # in pack
    OTHER = "other"


class CategorisationMethod(str, Enum):
    RULE = "rule"
    MEMORY = "memory"
    LLM = "llm"
    USER = "user"


class Provenance(str, Enum):
    DETECTED = "detected"
    CONFIRMED = "confirmed"
    DECLARED = "declared"


class Cadence(str, Enum):
    WEEKLY = "weekly"
    FOUR_WEEKLY = "four_weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    IRREGULAR = "irregular"


class ReconciliationStatus(str, Enum):
    RECONCILED = "reconciled"  # every row chains on the running balance
    NOT_RECONCILABLE = "not_reconcilable_no_balance"  # no balance column: internal checks only
    FAILED = "failed"  # batch must not be committed


# --------------------------------------------------------------------------- import


@dataclass(frozen=True)
class ParsedRow:
    """One statement row after parsing, before interpretation (an immutable fact)."""

    source_row_index: int  # 0-based row index in the source table (provenance)
    posted_on: date
    description: str
    amount_minor: int
    currency: str
    balance_after_minor: int | None = None
    external_id: str | None = None  # e.g. Monzo Transaction ID (idempotency key)
    bank_category: str | None = None  # a feature only, never ground truth
    bank_type: str | None = None  # e.g. "DD", "Card payment"
    posted_time: time | None = None


@dataclass(frozen=True)
class Question:
    """A gap or ambiguity the user must answer (docs/06 H13, docs/00 §6a). Never guessed."""

    kind: str  # "currency" | "date_order" | "decimal_separator" | "balance_today" | "columns"
    prompt: str
    options: tuple[str, ...] = ()
    preselected: str | None = None


@dataclass(frozen=True)
class ReconciliationResult:
    status: ReconciliationStatus
    rows_checked: int
    rows_failed: int
    failures: tuple[str, ...] = ()  # human-readable, row-level


@dataclass(frozen=True)
class ImportResult:
    rows: tuple[ParsedRow, ...]
    format_profile_id: str | None  # built-in / saved / proposed profile used
    detected_currency: str | None
    currency_provenance: str  # "column" | "symbol" | "profile" | "home_default" | "user_confirmed"
    date_format: str | None  # strptime pattern
    reconciliation: ReconciliationResult
    questions: tuple[Question, ...] = ()  # non-empty ⇒ the batch is not committed yet
    warnings: tuple[str, ...] = ()
    file_sha256: str = ""


# --------------------------------------------------------------------------- ledger interpretation


@dataclass(frozen=True)
class Transaction:
    id: str  # txn_<...>
    account_id: str
    posted_on: date
    amount_minor: int
    currency: str
    description: str
    normalised: str  # cleaned narration (uppercase, codes/refs stripped)
    channel: Channel
    counterparty: str | None
    external_id: str | None = None
    balance_after_minor: int | None = None
    bank_category: str | None = None
    source_row_index: int | None = None


@dataclass(frozen=True)
class Categorisation:
    transaction_id: str
    category_key: str  # stable key from docs/07 taxonomy, e.g. "food.delivery"
    flow_kind: FlowKind
    method: CategorisationMethod
    confidence: float  # 0..1
    rationale: str = ""


@dataclass(frozen=True)
class BalanceAnchor:
    account_id: str
    as_of: date
    amount_minor: int
    currency: str
    source: str  # "statement_column" | "declared"


@dataclass(frozen=True)
class PaydayRule:
    """When pay lands. kind: 'fixed_day' (day_of_month, moved to the previous working day),
    'last_working_day', or 'four_weekly' (anchor_date + 28n). december_day optionally overrides
    December (e.g. early Christmas pay), learned from history."""

    kind: str
    day_of_month: int | None = None
    anchor_date: date | None = None
    december_day: int | None = None


@dataclass(frozen=True)
class IncomeStream:
    key: str  # inc_<...> or a stable slug in tests
    source: str  # counterparty, e.g. "Acme Analytics Ltd"
    amount_minor: int  # robust median net amount
    currency: str
    cadence: Cadence
    payday_rule: PaydayRule | None
    provenance: Provenance
    member_ids: tuple[str, ...] = ()
    irregular_amounts_minor: tuple[int, ...] = ()  # observed distribution when IRREGULAR


@dataclass(frozen=True)
class RecurringObligation:
    key: str  # rob_<...>
    label: str
    category_key: str
    flow_kind: FlowKind
    amount_minor: int  # negative (outflow); robust median
    currency: str
    cadence: Cadence
    anchor_day: int | None  # day of month for monthly cadence
    active_months: frozenset[int] = field(default_factory=lambda: frozenset(range(1, 13)))
    member_ids: tuple[str, ...] = ()
    is_commitment: bool = False


@dataclass(frozen=True)
class KnownFlow:
    """A dated, certain flow in the horizon (e.g. an entered car repair invoice)."""

    on: date
    amount_minor: int
    label: str
    category_key: str | None = None


# --------------------------------------------------------------------------- forecast


@dataclass(frozen=True)
class ForecastInputs:
    as_of: date  # the last data date ("today")
    currency: str
    starting_balance_minor: int
    starting_balance_provenance: str  # "statement_column" | "declared" | "relative"
    income_streams: tuple[IncomeStream, ...]
    obligations: tuple[RecurringObligation, ...]
    known_flows: tuple[KnownFlow, ...]
    # discretionary history: (date, category_key, amount_minor<0) rows from the last W days,
    # excluding recurring, one-offs and transfers (docs/07 §6.1)
    discretionary_history: tuple[tuple[date, str, int], ...]
    holidays: frozenset[date]  # from the workspace's locale pack
    buffer_minor: int | None
    horizon_days: int = 90
    n_paths: int = 500
    seed: int = 0


@dataclass(frozen=True)
class Quantiles:
    p10: int
    p50: int
    p90: int


@dataclass(frozen=True)
class PayCycleLow:
    payday: date  # the payday that ends the cycle
    low: Quantiles
    low_date: date  # modal date of the path minimum
    chance_below_buffer: float | None


@dataclass(frozen=True)
class ForecastResult:
    as_of: date
    currency: str
    horizon_days: int
    dates: tuple[date, ...]
    p10: tuple[int, ...]
    p50: tuple[int, ...]
    p90: tuple[int, ...]
    pay_cycles: tuple[PayCycleLow, ...]
    min_balance_p50_minor: int
    min_balance_date: date
    buffer_minor: int | None
    n_paths: int
    seed: int
    inputs_hash: str
    engine_version: str


@dataclass(frozen=True)
class ScenarioModifier:
    """docs/07 §6.5. v1 types: one_off_outflow, one_off_inflow, income_delay."""

    type: str
    date: date | None = None
    amount_minor: int | None = None  # positive magnitude
    label: str = ""
    category_key: str | None = None
    income_stream_key: str | None = None
    days: int | None = None
    occurrences: int | None = None  # None = all


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    currency: str
    modifiers: tuple[ScenarioModifier, ...]
    horizon_days: int | None = None


@dataclass(frozen=True)
class SimulationResult:
    scenario: ScenarioSpec
    baseline: ForecastResult
    simulated: ForecastResult
    # per pay cycle: (payday, baseline P50 low, simulated P50 low)
    delta_lows: tuple[tuple[date, int, int], ...]
