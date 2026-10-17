"""Goals (docs/07 §3.1 Goal, §6.7; docs/01 F-55, FR-69).

A save-by-date goal with the `residual` funding rule: no money moves, and progress is the cash
above the buffer at the target month's pre-salary low. A new table only: existing rows,
sessions and cookies are untouched, and a profile's goals are deleted with it (ON DELETE
CASCADE). Demo templates and their private copies start with no goal.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "goal",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(32),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="save_by_date"),
        sa.Column("target_minor", sa.BigInteger, nullable=False),
        sa.Column("target_date", sa.Date, nullable=False),
        sa.Column("funding_rule", sa.String(16), nullable=False, server_default="residual"),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("target_minor > 0", name="ck_goal_target_positive"),
    )


def downgrade() -> None:
    op.drop_table("goal")
