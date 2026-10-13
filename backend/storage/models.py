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
