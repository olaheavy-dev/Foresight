"""Behaviour findings and the import-time suspicious-text flag (docs/06 §4.2, docs/05 §7.4a).

`finding` holds deterministic finding candidates and the Analyst's ranking and wording.
`transaction.suspicious_text` marks rows whose narration looks like an instruction to a model;
they are categorised by rules and merchant memory only and never sent to a model as written.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transaction",
        sa.Column("suspicious_text", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_table(
        "finding",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("subject", postgresql.JSONB, server_default="{}", nullable=False),
        sa.Column("stats", postgresql.JSONB, server_default="{}", nullable=False),
        sa.Column("strength", sa.String(length=12), nullable=False),
        sa.Column("severity", sa.String(length=8), server_default="info", nullable=False),
        sa.Column("score", sa.Float(), server_default="0", nullable=False),
        sa.Column("salience", sa.Integer(), nullable=True),
        sa.Column("headline", sa.Text(), server_default="", nullable=False),
        sa.Column("detail", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "wording_source", sa.String(length=12), server_default="template", nullable=False
        ),
        sa.Column("calc_ids", postgresql.JSONB, server_default="[]", nullable=False),
        sa.Column(
            "txn_query",
            postgresql.JSONB,
            server_default="{}",
            nullable=False,
        ),
        sa.Column("scope", sa.String(length=48), server_default="mine", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="candidate", nullable=False),
        sa.Column("discard_reason", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("data_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.Column(
            "first_detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_finding_workspace_id"),
        sa.UniqueConstraint("workspace_id", "dedupe_key", name="uq_finding_dedupe"),
    )
    op.create_index(op.f("ix_finding_workspace_id"), "finding", ["workspace_id"], unique=False)
    op.create_check_constraint("ck_finding_id_prefix", "finding", "id LIKE 'fnd\\_%'")


def downgrade() -> None:
    op.drop_index(op.f("ix_finding_workspace_id"), table_name="finding")
    op.drop_table("finding")
    op.drop_column("transaction", "suspicious_text")
