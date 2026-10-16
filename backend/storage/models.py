"""SQLAlchemy models. Every row belongs to a workspace (docs/07 §2, §3).

Child rows reference their parents through composite foreign keys that include `workspace_id`,
so the database itself refuses a row that points into another workspace.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Json = dict[str, Any]


class Base(DeclarativeBase):
    pass


def _workspace_fk() -> Any:
    return mapped_column(
        String(32), ForeignKey("workspace.id", ondelete="CASCADE"), index=True, nullable=False
    )


def _created_at() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Workspace(Base):
    """One person's or one household's financial space (docs/00 §6c)."""

    __tablename__ = "workspace"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # wsp_<ULID>
    name: Mapped[str] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(2))  # selects the locale pack: GB, IN
    home_currency: Mapped[str] = mapped_column(String(3))  # ISO 4217
    locale: Mapped[str] = mapped_column(String(10))  # en-GB, en-IN
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kind: Mapped[str] = mapped_column(String(8), server_default="user")  # demo | user
    persona_key: Mapped[str | None] = mapped_column(String(8))  # P1–P4 for demo workspaces
    buffer_minor: Mapped[int | None] = mapped_column(BigInteger)  # home-currency buffer
    # Incremented on every ledger mutation; part of forecast seeds and cache keys.
    data_version: Mapped[int] = mapped_column(Integer, server_default="0")
    # Who may open it (docs/05 §5.9): a signed-in user, or a guest session. Seeded templates
    # (kind demo) have neither and are never served to a browser; guests get a `sample` copy.
    owner_user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    owner_session_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("auth_session.id", ondelete="CASCADE"), index=True
    )
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppUser(Base):
    """A signed-in person (docs/05 §5.9). Identified by the provider's issuer + subject, never by
    an e-mail address alone."""

    __tablename__ = "app_user"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_app_user_identity"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # usr_
    issuer: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    """A browser session: a random token in a cookie, of which only the SHA-256 is stored. A guest
    session has no user; signing in rotates to a new session linked to the user."""

    __tablename__ = "auth_session"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # ses_
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    active_workspace_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (UniqueConstraint("workspace_id", "id", name="uq_account_workspace_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # acct_
    workspace_id: Mapped[str] = _workspace_fk()
    name: Mapped[str] = mapped_column(String(120))
    institution: Mapped[str | None] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(16), server_default="current")
    currency: Mapped[str] = mapped_column(String(3))
    currency_source: Mapped[str] = mapped_column(String(16), server_default="home_default")
    tracked: Mapped[bool] = mapped_column(Boolean, server_default="true")
    include_in_forecast: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Which table of which file format created this account (multi-table files fan out).
    source_key: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class FormatProfileRow(Base):
    """A saved (proposed or user-confirmed) CSV format; built-ins live in code as data."""

    __tablename__ = "format_profile"
    __table_args__ = (UniqueConstraint("workspace_id", "profile_id", name="uq_format_profile"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # fmt_
    workspace_id: Mapped[str] = _workspace_fk()
    profile_id: Mapped[str] = mapped_column(String(80))  # finance_core FormatProfile.profile_id
    label: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(16))  # proposed | user_confirmed
    definition: Mapped[Json] = mapped_column(JSONB)
    confirmations: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = _created_at()


class ImportBatch(Base):
    __tablename__ = "import_batch"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_import_batch_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "account_id"], ["account.workspace_id", "account.id"]
        ),
        Index("ix_import_batch_sha", "workspace_id", "file_sha256"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # imp_
    workspace_id: Mapped[str] = _workspace_fk()
    account_id: Mapped[str | None] = mapped_column(String(32))
    importer: Mapped[str] = mapped_column(String(24))
    filename: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64))
    format_profile_id: Mapped[str | None] = mapped_column(String(80))
    table_index: Mapped[int] = mapped_column(Integer, server_default="0")
    table_title: Mapped[str | None] = mapped_column(String(200))
    detection: Mapped[Json] = mapped_column(JSONB, server_default="{}")
    format_inference: Mapped[Json] = mapped_column(JSONB, server_default="{}")
    counts: Mapped[Json] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(String(16))  # needs_review | committed | rejected
    reconciliation_status: Mapped[str | None] = mapped_column(String(32))
    reconciliation_rows_checked: Mapped[int] = mapped_column(Integer, server_default="0")
    reconciliation_rows_failed: Mapped[int] = mapped_column(Integer, server_default="0")
    reconciliation_failures: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    questions: Mapped[list[Json]] = mapped_column(JSONB, server_default="[]")
    warnings: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class SourceRow(Base):
    __tablename__ = "source_row"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "import_batch_id"],
            ["import_batch.workspace_id", "import_batch.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)  # imp_…:r000123
    workspace_id: Mapped[str] = _workspace_fk()
    import_batch_id: Mapped[str] = mapped_column(String(32), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    raw: Mapped[Json] = mapped_column(JSONB)
    parse_status: Mapped[str] = mapped_column(String(16))  # ok | duplicate | rejected
    reject_reason: Mapped[str | None] = mapped_column(Text)


class Counterparty(Base):
    """The canonical "who" behind narrations; carries merchant memory (docs/07 §3.3)."""

    __tablename__ = "counterparty"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_counterparty_workspace_id"),
        UniqueConstraint("workspace_id", "key", name="uq_counterparty_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # cpty_
    workspace_id: Mapped[str] = _workspace_fk()
    key: Mapped[str] = mapped_column(String(200))  # counterparty text as the parser derives it
    display_name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), server_default="merchant")
    default_category_key: Mapped[str | None] = mapped_column(String(64))  # merchant memory
    memory_source: Mapped[str | None] = mapped_column(String(16))  # user | learned
    created_at: Mapped[datetime] = _created_at()


class Transaction(Base):
    """An immutable ledger fact. Interpretations live in Categorisation (append-only)."""

    __tablename__ = "transaction"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_transaction_workspace_id"),
        UniqueConstraint("account_id", "fingerprint", name="uq_transaction_fingerprint"),
        ForeignKeyConstraint(
            ["workspace_id", "account_id"], ["account.workspace_id", "account.id"]
        ),
        ForeignKeyConstraint(
            ["workspace_id", "import_batch_id"], ["import_batch.workspace_id", "import_batch.id"]
        ),
        ForeignKeyConstraint(
            ["workspace_id", "counterparty_id"], ["counterparty.workspace_id", "counterparty.id"]
        ),
        Index("ix_transaction_workspace_posted", "workspace_id", "posted_on"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # txn_
    workspace_id: Mapped[str] = _workspace_fk()
    account_id: Mapped[str] = mapped_column(String(32))
    import_batch_id: Mapped[str | None] = mapped_column(String(32))
    source_row_id: Mapped[str | None] = mapped_column(String(48))
    posted_on: Mapped[date] = mapped_column(Date)
    posted_time: Mapped[time | None] = mapped_column(Time)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    description: Mapped[str] = mapped_column(Text)  # narration as written
    normalised: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(24))
    counterparty: Mapped[str | None] = mapped_column(String(200))
    counterparty_id: Mapped[str | None] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(120))
    bank_category: Mapped[str | None] = mapped_column(String(80))
    bank_type: Mapped[str | None] = mapped_column(String(80))
    balance_after_minor: Mapped[int | None] = mapped_column(BigInteger)
    source_row_index: Mapped[int | None] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(160))
    entry_method: Mapped[str] = mapped_column(String(16), server_default="import")
    status: Mapped[str] = mapped_column(String(24), server_default="active")
    # Instruction-like narration found at import (docs/05 §7.4a L3, migration 0005): the row is
    # categorised by rules and merchant memory only and is never sent to a model as written.
    suspicious_text: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = _created_at()


class Categorisation(Base):
    """Append-only categorisation history; the latest row (highest seq) wins."""

    __tablename__ = "categorisation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "transaction_id"],
            ["transaction.workspace_id", "transaction.id"],
            ondelete="CASCADE",
        ),
        Index("ix_categorisation_txn_seq", "transaction_id", "seq"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # ctg_
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    workspace_id: Mapped[str] = _workspace_fk()
    transaction_id: Mapped[str] = mapped_column(String(32))
    category_key: Mapped[str] = mapped_column(String(64))
    flow_kind: Mapped[str] = mapped_column(String(32))
    method: Mapped[str] = mapped_column(String(8))  # rule | memory | llm | user
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text, server_default="")
    supersedes: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = _created_at()


class BalanceAnchor(Base):
    __tablename__ = "balance_anchor"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "account_id"], ["account.workspace_id", "account.id"]
        ),
        UniqueConstraint("account_id", "as_of", "source", name="uq_balance_anchor"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # bal_
    workspace_id: Mapped[str] = _workspace_fk()
    account_id: Mapped[str] = mapped_column(String(32))
    as_of: Mapped[date] = mapped_column(Date)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    # file_balance_column | user_entered | demo_seed
    source: Mapped[str] = mapped_column(String(24))
    provenance: Mapped[str] = mapped_column(String(12))  # observed | declared
    import_batch_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = _created_at()


class IncomeStream(Base):
    __tablename__ = "income_stream"
    __table_args__ = (UniqueConstraint("workspace_id", "key", name="uq_income_stream_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # inc_
    workspace_id: Mapped[str] = _workspace_fk()
    key: Mapped[str] = mapped_column(String(120))  # detector key, stable across re-detection
    source_label: Mapped[str] = mapped_column(String(200))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    cadence: Mapped[str] = mapped_column(String(16))
    payday_rule: Mapped[Json | None] = mapped_column(JSONB)
    provenance: Mapped[str] = mapped_column(String(12))  # detected | confirmed | declared
    member_ids: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    irregular_amounts_minor: Mapped[list[int]] = mapped_column(JSONB, server_default="[]")
    created_at: Mapped[datetime] = _created_at()


class RecurringObligation(Base):
    __tablename__ = "recurring_obligation"
    __table_args__ = (UniqueConstraint("workspace_id", "key", name="uq_recurring_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # rob_
    workspace_id: Mapped[str] = _workspace_fk()
    key: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(200))
    category_key: Mapped[str] = mapped_column(String(64))
    flow_kind: Mapped[str] = mapped_column(String(32))
    amount_minor: Mapped[int] = mapped_column(BigInteger)  # negative = outflow
    currency: Mapped[str] = mapped_column(String(3))
    cadence: Mapped[str] = mapped_column(String(16))
    anchor_day: Mapped[int | None] = mapped_column(Integer)
    active_months: Mapped[list[int]] = mapped_column(JSONB)
    member_ids: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    is_commitment: Mapped[bool] = mapped_column(Boolean, server_default="false")
    provenance: Mapped[str] = mapped_column(String(12), server_default="detected")
    # none | next_working_day | previous_working_day (types.WorkingDayShift; migration 0003)
    working_day_shift: Mapped[str] = mapped_column(String(24), server_default="none")
    created_at: Mapped[datetime] = _created_at()


class Calculation(Base):
    """A reproducible engine result (docs/07 §3.4). Identical questions map to the same id."""

    __tablename__ = "calculation"
    __table_args__ = (Index("ix_calculation_kind", "workspace_id", "kind", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # calc_
    workspace_id: Mapped[str] = _workspace_fk()
    kind: Mapped[str] = mapped_column(String(32))
    inputs_hash: Mapped[str] = mapped_column(String(64))
    params: Mapped[Json] = mapped_column(JSONB)
    result: Mapped[Json] = mapped_column(JSONB)
    engine_version: Mapped[str] = mapped_column(String(32))
    data_version: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = _created_at()


class AuditEvent(Base):
    """Append-only, hash-chained per workspace (docs/07 §3.7)."""

    __tablename__ = "audit_event"
    __table_args__ = (UniqueConstraint("workspace_id", "seq", name="uq_audit_event_seq"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # aud_
    workspace_id: Mapped[str] = _workspace_fk()
    seq: Mapped[int] = mapped_column(BigInteger)  # 1, 2, … within the workspace
    actor: Mapped[str] = mapped_column(String(64))  # user | agent:<name> | system
    action: Mapped[str] = mapped_column(String(64))
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(64))
    before: Mapped[Json | None] = mapped_column(JSONB)
    after: Mapped[Json | None] = mapped_column(JSONB)
    run_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[str] = mapped_column(String(40))  # ISO 8601 UTC; part of the hash
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


# ----------------------------------------------------------------------------- agent runtime
# Migration 0004 (docs/06 §7, §10.2, §11; docs/05 §4.2). Runs, steps, verification results and
# answer snapshots are the audit trail; steps, verification results and snapshots are append-only.


class Thread(Base):
    """A conversation in the AI Workspace."""

    __tablename__ = "thread"
    __table_args__ = (UniqueConstraint("workspace_id", "id", name="uq_thread_workspace_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # thr_
    workspace_id: Mapped[str] = _workspace_fk()
    title: Mapped[str] = mapped_column(String(200), server_default="")
    created_at: Mapped[datetime] = _created_at()


class AgentRun(Base):
    """One workflow execution (docs/05 §8): the trace that its AgentSteps are the spans of."""

    __tablename__ = "agent_run"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_agent_run_workspace_id"),
        ForeignKeyConstraint(["workspace_id", "thread_id"], ["thread.workspace_id", "thread.id"]),
        Index("ix_agent_run_started", "workspace_id", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # run_
    workspace_id: Mapped[str] = _workspace_fk()
    workflow: Mapped[str] = mapped_column(String(24))  # ingestion | risk_detection | … (06 §7)
    trigger: Mapped[str] = mapped_column(String(12))  # user | event | cron | eval
    status: Mapped[str] = mapped_column(String(12), server_default="running")
    partial: Mapped[bool] = mapped_column(Boolean, server_default="false")
    thread_id: Mapped[str | None] = mapped_column(String(32))
    data_version: Mapped[int] = mapped_column(Integer)
    prefs_version: Mapped[int] = mapped_column(Integer, server_default="0")
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    llm_calls: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_in: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, server_default="0")
    # Run-level aggregate behind the timeline's cost {model_calls, tokens, usd_estimate, cached}
    # (docs/08 §5.10): sums of its steps, from Mesh `usage` × the price table, never model text.
    cost_estimate_usd: Mapped[float | None] = mapped_column(Float)
    cached_steps: Mapped[int] = mapped_column(Integer, server_default="0")
    revision_count: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = _created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentStep(Base):
    """One node execution (docs/06 §11). Written once; never updated."""

    __tablename__ = "agent_step"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_agent_step_workspace_id"),
        UniqueConstraint("run_id", "seq", name="uq_agent_step_seq"),
        ForeignKeyConstraint(
            ["workspace_id", "run_id"], ["agent_run.workspace_id", "agent_run.id"]
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # step_
    workspace_id: Mapped[str] = _workspace_fk()
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # 1, 2, … within the run (SSE event id)
    node: Mapped[str] = mapped_column(String(64))
    agent: Mapped[str] = mapped_column(String(16))  # coordinator|ledger|…|verifier|system
    kind: Mapped[str] = mapped_column(String(8))  # llm | tool | control
    provider: Mapped[str | None] = mapped_column(String(8))  # mesh, LLM steps only
    model: Mapped[str | None] = mapped_column(String(80))
    tier: Mapped[str | None] = mapped_column(String(12))
    prompt_version: Mapped[str | None] = mapped_column(String(24))
    # The temperature sent, or None when the model rejects one ("model default", docs/06 §13).
    temperature: Mapped[float | None] = mapped_column(Float)
    input_hash: Mapped[str] = mapped_column(String(64))
    output: Mapped[Json] = mapped_column(JSONB)
    tool_calls: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    tokens_in: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_estimate_usd: Mapped[float | None] = mapped_column(Float)  # usage × catalogue price
    llm_calls: Mapped[int] = mapped_column(Integer, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, server_default="0")
    # Model wait on the step's critical path (concurrent judge calls overlap); None = no model
    # call, or a replayed call without a recorded latency.
    model_ms: Mapped[int | None] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, server_default="1")
    cached: Mapped[bool] = mapped_column(Boolean, server_default="false")
    status: Mapped[str] = mapped_column(String(12))  # ok | retried | failed | skipped
    label: Mapped[str | None] = mapped_column(String(200))  # templated, never model text
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Recommendation(Base):
    """A proposed intervention and its final status (docs/06 W4, docs/07)."""

    __tablename__ = "recommendation"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_recommendation_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "run_id"], ["agent_run.workspace_id", "agent_run.id"]
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # rec_
    workspace_id: Mapped[str] = _workspace_fk()
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    proposal_key: Mapped[str] = mapped_column(String(64))  # stable across revision rounds
    status: Mapped[str] = mapped_column(String(12))  # approved|withdrawn|accepted|dismissed|snoozed
    proposal: Mapped[Json] = mapped_column(JSONB)  # the last InterventionProposal
    trigger_refs: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    impact_calc_refs: Mapped[list[Any]] = mapped_column(JSONB, server_default="[]")
    revision_count: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _created_at()


class VerificationResult(Base):
    """One Verifier pass over one proposal (docs/06 §4.5, §5). Append-only."""

    __tablename__ = "verification_result"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_verification_result_workspace_id"),
        UniqueConstraint("recommendation_id", "round", name="uq_verification_round"),
        ForeignKeyConstraint(
            ["workspace_id", "recommendation_id"],
            ["recommendation.workspace_id", "recommendation.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "run_id"], ["agent_run.workspace_id", "agent_run.id"]
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # ver_
    workspace_id: Mapped[str] = _workspace_fk()
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    recommendation_id: Mapped[str] = mapped_column(String(32), index=True)
    round: Mapped[int] = mapped_column(Integer)  # 1..3
    verdict: Mapped[str] = mapped_column(String(8))  # APPROVE | REJECT
    rule_results: Mapped[list[Any]] = mapped_column(JSONB)  # [{rule, passed, reason, refs}]
    critique: Mapped[str | None] = mapped_column(Text)
    judge_step_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = _created_at()


class AgentResponse(Base):
    """An immutable, hydrated answer snapshot (docs/08, docs/00 §13). Reload never recomputes."""

    __tablename__ = "agent_response"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_agent_response_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "run_id"], ["agent_run.workspace_id", "agent_run.id"]
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # rsp_
    workspace_id: Mapped[str] = _workspace_fk()
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    surface: Mapped[str] = mapped_column(String(16))  # workspace | home | lab | digest
    intent: Mapped[str | None] = mapped_column(String(40))
    body: Mapped[Json] = mapped_column(JSONB)  # validated, hydrated AgentResponse contract
    data_version: Mapped[int] = mapped_column(Integer)
    prefs_version: Mapped[int] = mapped_column(Integer, server_default="0")
    engine_version: Mapped[str] = mapped_column(String(32))
    partial: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = _created_at()


class Message(Base):
    """One turn in a thread. The user's question is stored with its standalone rewrite."""

    __tablename__ = "message"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_message_workspace_id"),
        UniqueConstraint("thread_id", "seq", name="uq_message_seq"),
        # A retried POST with the same client_msg_id returns the existing run (docs/05 §6.4).
        UniqueConstraint("thread_id", "client_msg_id", name="uq_message_client_msg_id"),
        ForeignKeyConstraint(["workspace_id", "thread_id"], ["thread.workspace_id", "thread.id"]),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # msg_
    workspace_id: Mapped[str] = _workspace_fk()
    thread_id: Mapped[str] = mapped_column(String(32), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    text: Mapped[str] = mapped_column(Text, server_default="")
    action: Mapped[Json | None] = mapped_column(JSONB)  # structured follow-up {action, refs}
    standalone_question: Mapped[str | None] = mapped_column(Text)
    client_msg_id: Mapped[str | None] = mapped_column(String(64))
    run_id: Mapped[str | None] = mapped_column(String(32))
    response_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = _created_at()


class AnswerCacheEntry(Base):
    """Exact answer cache (docs/05 §4.2 stage 3): key → stored snapshot. No embeddings."""

    __tablename__ = "answer_cache"
    __table_args__ = (
        UniqueConstraint("workspace_id", "cache_key", name="uq_answer_cache_key"),
        ForeignKeyConstraint(
            ["workspace_id", "response_id"], ["agent_response.workspace_id", "agent_response.id"]
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workspace_id: Mapped[str] = _workspace_fk()
    cache_key: Mapped[str] = mapped_column(String(64))
    response_id: Mapped[str] = mapped_column(String(32))
    intent: Mapped[str] = mapped_column(String(40))
    hits: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = _created_at()
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Goal(Base):
    """A save-by-date goal (migration 0009; docs/07 §3.1, §6.7). `residual` funding: no money
    moves; progress is the cash above the buffer at the target month's pre-salary low."""

    __tablename__ = "goal"
    __table_args__ = (CheckConstraint("target_minor > 0", name="ck_goal_target_positive"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # goal_
    workspace_id: Mapped[str] = _workspace_fk()
    name: Mapped[str] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(3))  # the home currency at creation, then fixed
    kind: Mapped[str] = mapped_column(String(16), server_default="save_by_date")
    target_minor: Mapped[int] = mapped_column(BigInteger)
    target_date: Mapped[date] = mapped_column(Date)
    funding_rule: Mapped[str] = mapped_column(String(16), server_default="residual")
    status: Mapped[str] = mapped_column(
        String(12), server_default="active"
    )  # or achieved, abandoned
    created_at: Mapped[datetime] = _created_at()


class AnalysisJob(Base):
    """A queued proactive analysis of one profile (migration 0008, review R2)."""

    __tablename__ = "analysis_job"
    __table_args__ = (
        Index(
            "uq_analysis_job_queued",
            "workspace_id",
            unique=True,
            postgresql_where=text("status = 'queued'"),
        ),
        Index("ix_analysis_job_status_not_before", "status", "not_before"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # job_
    workspace_id: Mapped[str] = _workspace_fk()
    event: Mapped[str] = mapped_column(String(32))  # import_committed | category_corrected | …
    workflow: Mapped[str] = mapped_column(String(24))  # ingestion | risk_detection
    data_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(12), server_default="queued"
    )  # queued|running|done|skipped|failed
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    run_id: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)  # why advice was skipped, or the error
    created_at: Mapped[datetime] = _created_at()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Finding(Base):
    """A deterministic behaviour finding (docs/07 §3.4 `Finding`, docs/06 §4.2).

    Candidates come from `finance_core` detectors; the Behaviour Analyst may rank, word or
    discard them but never creates one. Headlines use `{{calc_…#path|format}}` placeholders only
    (V-07); the figures live in the cited Calculation rows. One row per `dedupe_key`: a later
    refresh confirms (or supersedes) it rather than adding a duplicate.
    """

    __tablename__ = "finding"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id", name="uq_finding_workspace_id"),
        UniqueConstraint("workspace_id", "dedupe_key", name="uq_finding_dedupe"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # fnd_
    workspace_id: Mapped[str] = _workspace_fk()
    kind: Mapped[str] = mapped_column(String(32))  # category_spike | price_change | …
    subject: Mapped[Json] = mapped_column(JSONB, server_default="{}")
    stats: Mapped[Json] = mapped_column(JSONB, server_default="{}")
    strength: Mapped[str] = mapped_column(String(12))  # strong | moderate | weak
    severity: Mapped[str] = mapped_column(String(8), server_default="info")  # info | watch | act
    score: Mapped[float] = mapped_column(Float, server_default="0")
    salience: Mapped[int | None] = mapped_column(Integer)  # 1..5 from the Analyst (or rules)
    headline: Mapped[str] = mapped_column(Text, server_default="")
    detail: Mapped[str] = mapped_column(Text, server_default="")
    wording_source: Mapped[str] = mapped_column(String(12), server_default="template")  # llm
    calc_ids: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    txn_query: Mapped[Json] = mapped_column(JSONB, server_default="{}")
    scope: Mapped[str] = mapped_column(String(48), server_default="mine")
    status: Mapped[str] = mapped_column(String(16), server_default="candidate")
    discard_reason: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    data_version: Mapped[int] = mapped_column(Integer, server_default="0")
    run_id: Mapped[str | None] = mapped_column(String(32))
    first_detected_at: Mapped[datetime] = _created_at()
    last_confirmed_at: Mapped[datetime] = _created_at()
