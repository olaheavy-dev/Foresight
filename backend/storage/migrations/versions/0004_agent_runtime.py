"""Agent runtime: threads, runs, steps, recommendations, verification, answer snapshots and the
exact answer cache (docs/05 §4.2, §8; docs/06 §7, §10.2, §11).

AgentStep, VerificationResult and AgentResponse are append-only (the audit trail and immutable
snapshots, docs/00 §13), using the trigger function from 0002.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

PREFIXES = {
    "thread": "thr",
    "agent_run": "run",
    "agent_step": "step",
    "recommendation": "rec",
    "verification_result": "ver",
    "agent_response": "rsp",
    "message": "msg",
}
APPEND_ONLY = ("agent_step", "verification_result", "agent_response")

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "thread",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_thread_workspace_id"),
    )
    op.create_index(op.f("ix_thread_workspace_id"), "thread", ["workspace_id"], unique=False)
    op.create_table(
        "agent_run",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("workflow", sa.String(length=24), nullable=False),
        sa.Column("trigger", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=12), server_default="running", nullable=False),
        sa.Column("partial", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("thread_id", sa.String(length=32), nullable=True),
        sa.Column("data_version", sa.Integer(), nullable=False),
        sa.Column("prefs_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("llm_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_estimate_usd", sa.Float(), nullable=True),
        sa.Column("cached_steps", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revision_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "thread_id"],
            ["thread.workspace_id", "thread.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_agent_run_workspace_id"),
    )
    op.create_index(
        "ix_agent_run_started", "agent_run", ["workspace_id", "started_at"], unique=False
    )
    op.create_index(op.f("ix_agent_run_workspace_id"), "agent_run", ["workspace_id"], unique=False)
    op.create_table(
        "message",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("thread_id", sa.String(length=32), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("action", postgresql.JSONB, nullable=True),
        sa.Column("standalone_question", sa.Text(), nullable=True),
        sa.Column("client_msg_id", sa.String(length=64), nullable=True),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.Column("response_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "thread_id"],
            ["thread.workspace_id", "thread.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", "client_msg_id", name="uq_message_client_msg_id"),
        sa.UniqueConstraint("thread_id", "seq", name="uq_message_seq"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_message_workspace_id"),
    )
    op.create_index(op.f("ix_message_thread_id"), "message", ["thread_id"], unique=False)
    op.create_index(op.f("ix_message_workspace_id"), "message", ["workspace_id"], unique=False)
    op.create_table(
        "agent_response",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("surface", sa.String(length=16), nullable=False),
        sa.Column("intent", sa.String(length=40), nullable=True),
        sa.Column("body", postgresql.JSONB, nullable=False),
        sa.Column("data_version", sa.Integer(), nullable=False),
        sa.Column("prefs_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("partial", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_run.workspace_id", "agent_run.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_agent_response_workspace_id"),
    )
    op.create_index(op.f("ix_agent_response_run_id"), "agent_response", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_agent_response_workspace_id"), "agent_response", ["workspace_id"], unique=False
    )
    op.create_table(
        "agent_step",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("node", sa.String(length=64), nullable=False),
        sa.Column("agent", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("provider", sa.String(length=8), nullable=True),
        sa.Column("model", sa.String(length=80), nullable=True),
        sa.Column("tier", sa.String(length=12), nullable=True),
        sa.Column("prompt_version", sa.String(length=24), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output", postgresql.JSONB, nullable=False),
        sa.Column(
            "tool_calls",
            postgresql.JSONB,
            server_default="[]",
            nullable=False,
        ),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_estimate_usd", sa.Float(), nullable=True),
        sa.Column("llm_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("cached", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_run.workspace_id", "agent_run.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "seq", name="uq_agent_step_seq"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_agent_step_workspace_id"),
    )
    op.create_index(op.f("ix_agent_step_run_id"), "agent_step", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_agent_step_workspace_id"), "agent_step", ["workspace_id"], unique=False
    )
    op.create_table(
        "recommendation",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("proposal_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("proposal", postgresql.JSONB, nullable=False),
        sa.Column(
            "trigger_refs",
            postgresql.JSONB,
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "impact_calc_refs",
            postgresql.JSONB,
            server_default="[]",
            nullable=False,
        ),
        sa.Column("revision_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_run.workspace_id", "agent_run.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_recommendation_workspace_id"),
    )
    op.create_index(op.f("ix_recommendation_run_id"), "recommendation", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_recommendation_workspace_id"), "recommendation", ["workspace_id"], unique=False
    )
    op.create_table(
        "answer_cache",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("response_id", sa.String(length=32), nullable=False),
        sa.Column("intent", sa.String(length=40), nullable=False),
        sa.Column("hits", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "response_id"],
            ["agent_response.workspace_id", "agent_response.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "cache_key", name="uq_answer_cache_key"),
    )
    op.create_index(
        op.f("ix_answer_cache_workspace_id"), "answer_cache", ["workspace_id"], unique=False
    )
    op.create_table(
        "verification_result",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("recommendation_id", sa.String(length=32), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(length=8), nullable=False),
        sa.Column("rule_results", postgresql.JSONB, nullable=False),
        sa.Column("critique", sa.Text(), nullable=True),
        sa.Column("judge_step_id", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "recommendation_id"],
            ["recommendation.workspace_id", "recommendation.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id"],
            ["agent_run.workspace_id", "agent_run.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recommendation_id", "round", name="uq_verification_round"),
        sa.UniqueConstraint("workspace_id", "id", name="uq_verification_result_workspace_id"),
    )
    op.create_index(
        op.f("ix_verification_result_recommendation_id"),
        "verification_result",
        ["recommendation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verification_result_run_id"), "verification_result", ["run_id"], unique=False
    )
    op.create_index(
        op.f("ix_verification_result_workspace_id"),
        "verification_result",
        ["workspace_id"],
        unique=False,
    )
    for table, prefix in PREFIXES.items():
        op.create_check_constraint(f"ck_{table}_id_prefix", table, f"id LIKE '{prefix}\\_%'")
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION foresight_append_only()"
        )


def downgrade() -> None:
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER {table}_append_only ON {table}")
    op.drop_index(op.f("ix_verification_result_workspace_id"), table_name="verification_result")
    op.drop_index(op.f("ix_verification_result_run_id"), table_name="verification_result")
    op.drop_index(
        op.f("ix_verification_result_recommendation_id"), table_name="verification_result"
    )
    op.drop_table("verification_result")
    op.drop_index(op.f("ix_answer_cache_workspace_id"), table_name="answer_cache")
    op.drop_table("answer_cache")
    op.drop_index(op.f("ix_recommendation_workspace_id"), table_name="recommendation")
    op.drop_index(op.f("ix_recommendation_run_id"), table_name="recommendation")
    op.drop_table("recommendation")
    op.drop_index(op.f("ix_agent_step_workspace_id"), table_name="agent_step")
    op.drop_index(op.f("ix_agent_step_run_id"), table_name="agent_step")
    op.drop_table("agent_step")
    op.drop_index(op.f("ix_agent_response_workspace_id"), table_name="agent_response")
    op.drop_index(op.f("ix_agent_response_run_id"), table_name="agent_response")
    op.drop_table("agent_response")
    op.drop_index(op.f("ix_message_workspace_id"), table_name="message")
    op.drop_index(op.f("ix_message_thread_id"), table_name="message")
    op.drop_table("message")
    op.drop_index(op.f("ix_agent_run_workspace_id"), table_name="agent_run")
    op.drop_index("ix_agent_run_started", table_name="agent_run")
    op.drop_table("agent_run")
    op.drop_index(op.f("ix_thread_workspace_id"), table_name="thread")
    op.drop_table("thread")
