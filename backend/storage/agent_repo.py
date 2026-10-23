"""Workspace-scoped access to the agent runtime's records (docs/06 §10.2, §11; docs/05 §4.2, §8).

Built on `WorkspaceContext`, so every read is limited to one workspace and every new row is stamped
with it. Steps, verification results and answer snapshots are append-only in the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.storage import models as m
from backend.storage.ids import new_id
from backend.storage.repositories import WorkspaceContext


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RunCost:
    """The timeline's cost block (docs/08 §5.10): only ever from usage × the price table."""

    model_calls: int
    tokens: int
    usd_estimate: float | None
    cached: int

    def as_json(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "tokens": self.tokens,
            "usd_estimate": self.usd_estimate,
            "cached": self.cached,
        }


class AgentStore:
    def __init__(self, ctx: WorkspaceContext) -> None:
        self.ctx = ctx

    @property
    def session(self) -> Session:
        return self.ctx.session

    # ------------------------------------------------------------------ runs and steps

    def create_run(
        self,
        *,
        workflow: str,
        trigger: str,
        data_version: int,
        prefs_version: int,
        deadline_at: datetime,
        thread_id: str | None = None,
        run_id: str | None = None,
    ) -> m.AgentRun:
        run = m.AgentRun(
            id=run_id or new_id("run"),
            workflow=workflow,
            trigger=trigger,
            status="running",
            partial=False,
            thread_id=thread_id,
            data_version=data_version,
            prefs_version=prefs_version,
            deadline_at=deadline_at,
            llm_calls=0,
            tokens_in=0,
            tokens_out=0,
            cost_estimate_usd=None,
            cached_steps=0,
            revision_count=0,
            started_at=_now(),
        )
        self.ctx.add(run)
        self.session.flush()
        return run

    def run(self, run_id: str) -> m.AgentRun | None:
        return self.ctx.get(m.AgentRun, run_id)

    def add_step(self, run_id: str, **fields: Any) -> m.AgentStep:
        """Append a step and fold its usage into the run's aggregate."""
        run = self.run(run_id)
        if run is None:
            raise LookupError(f"no run {run_id} in {self.ctx.workspace_id}")
        seq = (
            int(
                self.session.scalar(
                    select(func.coalesce(func.max(m.AgentStep.seq), 0)).where(
                        m.AgentStep.run_id == run_id
                    )
                )
                or 0
            )
            + 1
        )
        step = m.AgentStep(id=new_id("step"), run_id=run_id, seq=seq, **fields)
        self.ctx.add(step)
        run.llm_calls += int(step.llm_calls or 0)
        run.tokens_in += int(step.tokens_in or 0)
        run.tokens_out += int(step.tokens_out or 0)
        if step.cost_estimate_usd is not None:
            run.cost_estimate_usd = round(
                (run.cost_estimate_usd or 0.0) + step.cost_estimate_usd, 8
            )
        if step.cached:
            run.cached_steps += 1
        self.session.flush()
        return step

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        partial: bool = False,
        error: str | None = None,
        revision_count: int | None = None,
    ) -> m.AgentRun:
        run = self.run(run_id)
        if run is None:
            raise LookupError(run_id)
        run.status = status
        run.partial = partial
        run.error = error
        if revision_count is not None:
            run.revision_count = revision_count
        run.finished_at = _now()
        self.session.flush()
        return run

    def steps(self, run_id: str, *, after_seq: int = 0) -> list[m.AgentStep]:
        """A run's steps in order; `after_seq` serves SSE `Last-Event-ID` replay (docs/05 §4.2)."""
        stmt = (
            self.ctx.select(m.AgentStep)
            .where(m.AgentStep.run_id == run_id, m.AgentStep.seq > after_seq)
            .order_by(m.AgentStep.seq)
        )
        return list(self.session.scalars(stmt))

    def step_count(self) -> int:
        stmt = select(func.count()).where(m.AgentStep.workspace_id == self.ctx.workspace_id)
        return int(self.session.scalar(stmt) or 0)

    def run_cost(self, run_id: str) -> RunCost:
        run = self.run(run_id)
        if run is None:
            raise LookupError(run_id)
        return RunCost(
            model_calls=run.llm_calls,
            tokens=run.tokens_in + run.tokens_out,
            usd_estimate=run.cost_estimate_usd,
            cached=run.cached_steps,
        )

    # ------------------------------------------------------------------ threads and messages

    def create_thread(self, title: str = "") -> m.Thread:
        thread = m.Thread(id=new_id("thr"), title=title)
        self.ctx.add(thread)
        self.session.flush()
        return thread

    def message_by_client_id(self, thread_id: str, client_msg_id: str) -> m.Message | None:
        stmt = self.ctx.select(m.Message).where(
            m.Message.thread_id == thread_id, m.Message.client_msg_id == client_msg_id
        )
        return self.session.scalars(stmt).first()

    def add_message(self, thread_id: str, *, role: str, **fields: Any) -> m.Message:
        if self.ctx.get(m.Thread, thread_id) is None:
            raise LookupError(f"no thread {thread_id} in {self.ctx.workspace_id}")
        seq = (
            int(
                self.session.scalar(
                    select(func.coalesce(func.max(m.Message.seq), 0)).where(
                        m.Message.thread_id == thread_id
                    )
                )
                or 0
            )
            + 1
        )
        message = m.Message(id=new_id("msg"), thread_id=thread_id, seq=seq, role=role, **fields)
        self.ctx.add(message)
        self.session.flush()
        return message

    def messages(self, thread_id: str) -> list[m.Message]:
        stmt = (
            self.ctx.select(m.Message)
            .where(m.Message.thread_id == thread_id)
            .order_by(m.Message.seq)
        )
        return list(self.session.scalars(stmt))

    # ------------------------------------------------------------------ answers and cache

    def save_response(
        self,
        *,
        run_id: str,
        surface: str,
        intent: str | None,
        body: dict[str, Any],
        data_version: int,
        prefs_version: int,
        engine_version: str,
        partial: bool = False,
        response_id: str | None = None,
    ) -> m.AgentResponse:
        response = m.AgentResponse(
            id=response_id or new_id("rsp"),
            run_id=run_id,
            surface=surface,
            intent=intent,
            body=body,
            data_version=data_version,
            prefs_version=prefs_version,
            engine_version=engine_version,
            partial=partial,
        )
        self.ctx.add(response)
        self.session.flush()
        return response

    def response(self, response_id: str) -> m.AgentResponse | None:
        """Read a stored snapshot. Runs nothing: reload never recomputes (ORC-12)."""
        return self.ctx.get(m.AgentResponse, response_id)

    def cache_get(self, cache_key: str) -> m.AgentResponse | None:
        stmt = self.ctx.select(m.AnswerCacheEntry).where(m.AnswerCacheEntry.cache_key == cache_key)
        entry = self.session.scalars(stmt).first()
        if entry is None:
            return None
        entry.hits += 1
        entry.last_hit_at = _now()
        self.session.flush()
        return self.response(entry.response_id)

    def cache_put(self, cache_key: str, *, response_id: str, intent: str) -> m.AnswerCacheEntry:
        entry = m.AnswerCacheEntry(cache_key=cache_key, response_id=response_id, intent=intent)
        self.ctx.add(entry)
        self.session.flush()
        return entry

    # ------------------------------------------------------------------ recommendations

    def add_recommendation(
        self, *, run_id: str, proposal_key: str, **fields: Any
    ) -> m.Recommendation:
        rec = m.Recommendation(id=new_id("rec"), run_id=run_id, proposal_key=proposal_key, **fields)
        self.ctx.add(rec)
        self.session.flush()
        return rec

    def advice_state_version(self) -> str:
        """Changes whenever a recommendation is added or accepted/dismissed/snoozed, so cached
        answers that show advice are never served after the advice state moved (docs/05 §4.2)."""
        count, latest = self.session.execute(
            select(func.count(), func.max(m.Recommendation.updated_at)).where(
                m.Recommendation.workspace_id == self.ctx.workspace_id
            )
        ).one()
        return f"{int(count or 0)}:{latest.isoformat() if latest else '-'}"

    def recommendation(self, rec_id: str) -> m.Recommendation | None:
        return self.ctx.get(m.Recommendation, rec_id)

    def set_recommendation_status(self, rec_id: str, status: str) -> m.Recommendation:
        rec = self.recommendation(rec_id)
        if rec is None:
            raise LookupError(rec_id)
        rec.status = status
        rec.updated_at = _now()
        self.session.flush()
        return rec

    def add_verification(
        self,
        *,
        run_id: str,
        recommendation_id: str,
        round: int,
        verdict: str,
        rule_results: list[dict[str, Any]],
        critique: str | None = None,
        judge_step_id: str | None = None,
    ) -> m.VerificationResult:
        result = m.VerificationResult(
            id=new_id("ver"),
            run_id=run_id,
            recommendation_id=recommendation_id,
            round=round,
            verdict=verdict,
            rule_results=rule_results,
            critique=critique,
            judge_step_id=judge_step_id,
        )
        self.ctx.add(result)
        self.session.flush()
        return result

    def verifications(self, recommendation_id: str) -> list[m.VerificationResult]:
        stmt = (
            self.ctx.select(m.VerificationResult)
            .where(m.VerificationResult.recommendation_id == recommendation_id)
            .order_by(m.VerificationResult.round)
        )
        return list(self.session.scalars(stmt))
