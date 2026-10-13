"""Ledger, interpretations, calculations and the audit log (docs/07 §3).

Children point at parents through (workspace_id, id) foreign keys, so a row can never reference
another workspace's data. Categorisation and AuditEvent are append-only: a trigger refuses UPDATE,
and DELETE unless the session sets `foresight.purge = on` (workspace deletion, docs/07 §8).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

PREFIXES = {
    "account": "acct",
    "import_batch": "imp",
    "transaction": "txn",
    "categorisation": "ctg",
    "counterparty": "cpty",
    "format_profile": "fmt",
    "balance_anchor": "bal",
    "income_stream": "inc",
    "recurring_obligation": "rob",
    "calculation": "calc",
    "audit_event": "aud",
}
APPEND_ONLY = ("categorisation", "audit_event")

APPEND_ONLY_FUNCTION = """
CREATE FUNCTION foresight_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('foresight.purge', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql
"""

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("institution", sa.String(length=80), nullable=True),
        sa.Column("type", sa.String(length=16), server_default="current", nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "currency_source", sa.String(length=16), server_default="home_default", nullable=False
        ),
        sa.Column("tracked", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("include_in_forecast", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("source_key", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_account_workspace_id"),
    )
    op.create_index(op.f("ix_account_workspace_id"), "account", ["workspace_id"], unique=False)
    op.create_table(
        "audit_event",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column("before", postgresql.JSONB, nullable=True),
        sa.Column("after", postgresql.JSONB, nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.String(length=40), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "seq", name="uq_audit_event_seq"),
    )
    op.create_index(
        op.f("ix_audit_event_workspace_id"), "audit_event", ["workspace_id"], unique=False
    )
    op.create_table(
        "calculation",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("inputs_hash", sa.String(length=64), nullable=False),
        sa.Column("params", postgresql.JSONB, nullable=False),
        sa.Column("result", postgresql.JSONB, nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("data_version", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_calculation_kind", "calculation", ["workspace_id", "kind", "created_at"], unique=False
    )
    op.create_index(
        op.f("ix_calculation_workspace_id"), "calculation", ["workspace_id"], unique=False
    )
    op.create_table(
        "counterparty",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), server_default="merchant", nullable=False),
        sa.Column("default_category_key", sa.String(length=64), nullable=True),
        sa.Column("memory_source", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_counterparty_workspace_id"),
        sa.UniqueConstraint("workspace_id", "key", name="uq_counterparty_key"),
    )
    op.create_index(
        op.f("ix_counterparty_workspace_id"), "counterparty", ["workspace_id"], unique=False
    )
    op.create_table(
        "format_profile",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("definition", postgresql.JSONB, nullable=False),
        sa.Column("confirmations", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "profile_id", name="uq_format_profile"),
    )
    op.create_index(
        op.f("ix_format_profile_workspace_id"), "format_profile", ["workspace_id"], unique=False
    )
    op.create_table(
        "income_stream",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("source_label", sa.String(length=200), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("cadence", sa.String(length=16), nullable=False),
        sa.Column("payday_rule", postgresql.JSONB, nullable=True),
        sa.Column("provenance", sa.String(length=12), nullable=False),
        sa.Column(
            "member_ids",
            postgresql.JSONB,
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "irregular_amounts_minor",
            postgresql.JSONB,
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "key", name="uq_income_stream_key"),
    )
    op.create_index(
        op.f("ix_income_stream_workspace_id"), "income_stream", ["workspace_id"], unique=False
    )
    op.create_table(
        "recurring_obligation",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("category_key", sa.String(length=64), nullable=False),
        sa.Column("flow_kind", sa.String(length=32), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("cadence", sa.String(length=16), nullable=False),
        sa.Column("anchor_day", sa.Integer(), nullable=True),
        sa.Column("active_months", postgresql.JSONB, nullable=False),
        sa.Column(
            "member_ids",
            postgresql.JSONB,
            server_default="[]",
            nullable=False,
        ),
        sa.Column("is_commitment", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("provenance", sa.String(length=12), server_default="detected", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "key", name="uq_recurring_key"),
    )
    op.create_index(
        op.f("ix_recurring_obligation_workspace_id"),
        "recurring_obligation",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "balance_anchor",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("provenance", sa.String(length=12), nullable=False),
        sa.Column("import_batch_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "account_id"],
            ["account.workspace_id", "account.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "as_of", "source", name="uq_balance_anchor"),
    )
    op.create_index(
        op.f("ix_balance_anchor_workspace_id"), "balance_anchor", ["workspace_id"], unique=False
    )
    op.create_table(
        "import_batch",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=True),
        sa.Column("importer", sa.String(length=24), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("format_profile_id", sa.String(length=80), nullable=True),
        sa.Column("table_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("table_title", sa.String(length=200), nullable=True),
        sa.Column(
            "detection",
            postgresql.JSONB,
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "format_inference",
            postgresql.JSONB,
            server_default="{}",
            nullable=False,
        ),
        sa.Column("counts", postgresql.JSONB, server_default="{}", nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reconciliation_status", sa.String(length=32), nullable=True),
        sa.Column("reconciliation_rows_checked", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reconciliation_rows_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "reconciliation_failures",
            postgresql.JSONB,
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "questions",
            postgresql.JSONB,
            server_default="[]",
            nullable=False,
        ),
        sa.Column("warnings", postgresql.JSONB, server_default="[]", nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "account_id"],
            ["account.workspace_id", "account.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_import_batch_workspace_id"),
    )
    op.create_index(
        "ix_import_batch_sha", "import_batch", ["workspace_id", "file_sha256"], unique=False
    )
    op.create_index(
        op.f("ix_import_batch_workspace_id"), "import_batch", ["workspace_id"], unique=False
    )
    op.create_table(
        "source_row",
        sa.Column("id", sa.String(length=48), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("import_batch_id", sa.String(length=32), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw", postgresql.JSONB, nullable=False),
        sa.Column("parse_status", sa.String(length=16), nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "import_batch_id"],
            ["import_batch.workspace_id", "import_batch.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_source_row_import_batch_id"), "source_row", ["import_batch_id"], unique=False
    )
    op.create_index(
        op.f("ix_source_row_workspace_id"), "source_row", ["workspace_id"], unique=False
    )
    op.create_table(
        "transaction",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("import_batch_id", sa.String(length=32), nullable=True),
        sa.Column("source_row_id", sa.String(length=48), nullable=True),
        sa.Column("posted_on", sa.Date(), nullable=False),
        sa.Column("posted_time", sa.Time(), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("normalised", sa.Text(), nullable=False),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("counterparty", sa.String(length=200), nullable=True),
        sa.Column("counterparty_id", sa.String(length=32), nullable=True),
        sa.Column("external_id", sa.String(length=120), nullable=True),
        sa.Column("bank_category", sa.String(length=80), nullable=True),
        sa.Column("bank_type", sa.String(length=80), nullable=True),
        sa.Column("balance_after_minor", sa.BigInteger(), nullable=True),
        sa.Column("source_row_index", sa.Integer(), nullable=True),
        sa.Column("fingerprint", sa.String(length=160), nullable=False),
        sa.Column("entry_method", sa.String(length=16), server_default="import", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "account_id"],
            ["account.workspace_id", "account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "counterparty_id"],
            ["counterparty.workspace_id", "counterparty.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "import_batch_id"],
            ["import_batch.workspace_id", "import_batch.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "fingerprint", name="uq_transaction_fingerprint"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_transaction_workspace_id"),
    )
    op.create_index(
        op.f("ix_transaction_workspace_id"), "transaction", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_transaction_workspace_posted",
        "transaction",
        ["workspace_id", "posted_on"],
        unique=False,
    )
    op.create_table(
        "categorisation",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("transaction_id", sa.String(length=32), nullable=False),
        sa.Column("category_key", sa.String(length=64), nullable=False),
        sa.Column("flow_kind", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=8), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), server_default="", nullable=False),
        sa.Column("supersedes", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "transaction_id"],
            ["transaction.workspace_id", "transaction.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index(
        "ix_categorisation_txn_seq", "categorisation", ["transaction_id", "seq"], unique=False
    )
    op.create_index(
        op.f("ix_categorisation_workspace_id"), "categorisation", ["workspace_id"], unique=False
    )
    op.add_column(
        "workspace", sa.Column("kind", sa.String(length=8), server_default="user", nullable=False)
    )
    op.add_column("workspace", sa.Column("persona_key", sa.String(length=8), nullable=True))
    op.add_column("workspace", sa.Column("buffer_minor", sa.BigInteger(), nullable=True))
    op.add_column(
        "workspace", sa.Column("data_version", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_index(
        "uq_workspace_demo_persona",
        "workspace",
        ["persona_key"],
        unique=True,
        postgresql_where=sa.text("kind = 'demo'"),
    )
    for table, prefix in PREFIXES.items():
        op.create_check_constraint(f"ck_{table}_id_prefix", table, f"id LIKE '{prefix}\\_%'")
    op.execute(APPEND_ONLY_FUNCTION)
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION foresight_append_only()"
        )


def downgrade() -> None:
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.execute("DROP FUNCTION foresight_append_only()")
    op.drop_index("uq_workspace_demo_persona", table_name="workspace")
    op.drop_column("workspace", "data_version")
    op.drop_column("workspace", "buffer_minor")
    op.drop_column("workspace", "persona_key")
    op.drop_column("workspace", "kind")
    op.drop_index(op.f("ix_categorisation_workspace_id"), table_name="categorisation")
    op.drop_index("ix_categorisation_txn_seq", table_name="categorisation")
    op.drop_table("categorisation")
    op.drop_index("ix_transaction_workspace_posted", table_name="transaction")
    op.drop_index(op.f("ix_transaction_workspace_id"), table_name="transaction")
    op.drop_table("transaction")
    op.drop_index(op.f("ix_source_row_workspace_id"), table_name="source_row")
    op.drop_index(op.f("ix_source_row_import_batch_id"), table_name="source_row")
    op.drop_table("source_row")
    op.drop_index(op.f("ix_import_batch_workspace_id"), table_name="import_batch")
    op.drop_index("ix_import_batch_sha", table_name="import_batch")
    op.drop_table("import_batch")
    op.drop_index(op.f("ix_balance_anchor_workspace_id"), table_name="balance_anchor")
    op.drop_table("balance_anchor")
    op.drop_index(op.f("ix_recurring_obligation_workspace_id"), table_name="recurring_obligation")
    op.drop_table("recurring_obligation")
    op.drop_index(op.f("ix_income_stream_workspace_id"), table_name="income_stream")
    op.drop_table("income_stream")
    op.drop_index(op.f("ix_format_profile_workspace_id"), table_name="format_profile")
    op.drop_table("format_profile")
    op.drop_index(op.f("ix_counterparty_workspace_id"), table_name="counterparty")
    op.drop_table("counterparty")
    op.drop_index(op.f("ix_calculation_workspace_id"), table_name="calculation")
    op.drop_index("ix_calculation_kind", table_name="calculation")
    op.drop_table("calculation")
    op.drop_index(op.f("ix_audit_event_workspace_id"), table_name="audit_event")
    op.drop_table("audit_event")
    op.drop_index(op.f("ix_account_workspace_id"), table_name="account")
    op.drop_table("account")
