"""LangGraph checkpointing in the same PostgreSQL database, in its own tables (docs/06 §7).

Runs are checkpointed under `thread_id = run_id`, so human-review interrupts (docs/06 §9) can
resume. `setup()` creates the checkpointer's tables idempotently; they are owned by LangGraph, not
by our Alembic migrations.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver


def libpq_url(database_url: str) -> str:
    """SQLAlchemy URL (`postgresql+psycopg://…`) → the plain libpq URL psycopg expects."""
    for prefix in ("postgresql+psycopg://", "postgresql+psycopg2://"):
        if database_url.startswith(prefix):
            return "postgresql://" + database_url[len(prefix) :]
    return database_url


@contextmanager
def postgres_checkpointer(database_url: str) -> Iterator[PostgresSaver]:
    with PostgresSaver.from_conn_string(libpq_url(database_url)) as saver:
        saver.setup()
        yield saver
