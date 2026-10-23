"""Model spend totals across every workspace, for the daily spend guard (backend/llm)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select

from backend.storage import models as m
from backend.storage.db import session_factory


def spent_on(database_url: str, day: date) -> float:
    """Sum of `AgentStep.cost_estimate_usd` for steps started on `day` (UTC)."""
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    stmt = select(func.coalesce(func.sum(m.AgentStep.cost_estimate_usd), 0.0)).where(
        m.AgentStep.started_at >= start, m.AgentStep.started_at < start + timedelta(days=1)
    )
    with session_factory(database_url)() as session:
        return float(session.scalar(stmt) or 0.0)
