"""Working-day shift on recurring obligations (docs/07 §4.3).

A direct debit or standing order whose date falls on a weekend or bank holiday is collected on
the next working day; card payments are taken on the day. The detector learns which applies and
the forecast projects the moved date. Payday shifts live inside income_stream.payday_rule (JSONB),
so they need no schema change.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recurring_obligation",
        sa.Column("working_day_shift", sa.String(24), server_default="none", nullable=False),
    )
    op.create_check_constraint(
        "ck_recurring_obligation_working_day_shift",
        "recurring_obligation",
        "working_day_shift IN ('none', 'next_working_day', 'previous_working_day')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_recurring_obligation_working_day_shift", "recurring_obligation", type_="check"
    )
    op.drop_column("recurring_obligation", "working_day_shift")
