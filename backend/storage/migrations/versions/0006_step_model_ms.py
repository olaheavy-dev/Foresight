"""Time each agent step spent waiting on Mesh (docs/06 §11, docs/09 E-EFF).

`agent_step.model_ms` is the step's model wait on its critical path: the sum of its calls'
latencies, or for concurrent judge calls the time the slowest worker was busy. Null when the step
made no model call or a replayed call had no recorded latency.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_step", sa.Column("model_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_step", "model_ms")
