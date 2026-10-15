"""Proactive analysis jobs (review R2, owner decision 15 Oct 2026).

A change to a profile's data (an import, a category correction, a declared balance) queues one
`analysis_job` in the same transaction, so a restart never loses it. Changes close together
collapse into the single queued job of that profile (partial unique index); a worker runs it
after a short quiet period: deterministic findings always, the checked-advice workflow when AI
is available and the profile's daily allowance allows.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_job",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("workflow", sa.String(24), nullable=False),
        sa.Column("data_version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("run_id", sa.String(32), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_analysis_job_queued",
        "analysis_job",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index("ix_analysis_job_status_not_before", "analysis_job", ["status", "not_before"])


def downgrade() -> None:
    op.drop_index("ix_analysis_job_status_not_before", table_name="analysis_job")
    op.drop_index("uq_analysis_job_queued", table_name="analysis_job")
    op.drop_table("analysis_job")
