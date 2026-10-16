"""Ask: threads, questions and the run event stream (docs/05 §4.2, §6.4; docs/06 W5).

    POST /api/threads                        → 201 {thread_id}
    GET  /api/threads                        → the profile's threads, newest first
    GET  /api/threads/{id}                   → one thread and its messages
    POST /api/threads/{id}/messages          {text, client_msg_id, action?} → 202 {run_id}
    GET  /api/runs/{id}/events               SSE: run.started · step · clarify · answer · error ·
                                             heartbeat; `Last-Event-ID` (or ?last_event_id=)
                                             replays what was missed
    GET  /api/responses/{id}                 a stored answer snapshot; runs nothing (ORC-12)

A question runs in the background, independent of the connection: closing the tab doesn't stop
it, and the answer is in the thread next time. Everything is scoped to the session's profile;
another profile's thread, run or answer is "not found". Asking never changes financial data, so
it is allowed on the read-only demo profiles.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import StringConstraints

from backend.agents.runner import ask, run_followup
from backend.app import network_cap
from backend.app.session import Profile
from backend.app.ui_contracts.primitives import Contract
from backend.app.ui_contracts.response import AgentResponse
from backend.mesh.availability import PAUSED_TEXT, AiStatus, user_status
from backend.mesh.breaker import BreakerState
from backend.mesh.mesh_client import MeshClient, MeshConfigError
from backend.settings import get_settings
from backend.storage import models as m
from backend.storage.agent_repo import AgentStore
from backend.storage.db import session_factory
from backend.storage.repositories import WorkspaceContext

router = APIRouter(prefix="/api", tags=["ask"])

# --------------------------------------------------------------------------- limits (05 §6.4)

MAX_CONCURRENT_RUNS = 2  # per profile
RATE_WINDOW = timedelta(minutes=10)
RATE_MAX = 10  # questions per profile per window (owner decision, 13 Oct 2026)
RUN_START_TIMEOUT_S = 10.0
POLL_S = 0.25
HEARTBEAT_S = 15.0
LOST_AFTER = timedelta(seconds=60)  # past the run deadline with no finish: the run was lost


@dataclass
class Limits:
    lock: threading.Lock = field(default_factory=threading.Lock)
    active: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    recent: dict[str, deque[datetime]] = field(default_factory=lambda: defaultdict(deque))

    def admit(self, workspace_id: str, now: datetime) -> str | None:
        with self.lock:
            window = self.recent[workspace_id]
            while window and now - window[0] > RATE_WINDOW:
                window.popleft()
            if len(window) >= RATE_MAX:
                return "Too many questions in a short time. Please wait a few minutes."
            if self.active[workspace_id] >= MAX_CONCURRENT_RUNS:
                return "Two questions are already running for this profile. Please wait."
            window.append(now)
            self.active[workspace_id] += 1
            return None

    def release(self, workspace_id: str) -> None:
        with self.lock:
            self.active[workspace_id] = max(0, self.active[workspace_id] - 1)


limits = Limits()

# --------------------------------------------------------------------------- Mesh


_mesh_lock = threading.Lock()
_mesh: MeshClient | None = None


def get_mesh() -> MeshClient | None:
    """One Mesh client per process (it carries the circuit breaker). None when no key is set:
    questions then degrade honestly instead of failing (docs/06 §10.1)."""
    global _mesh
    with _mesh_lock:
        if _mesh is None:
            try:
                _mesh = MeshClient()
            except MeshConfigError:
                return None
        return _mesh


Mesh = Annotated[MeshClient | None, Depends(get_mesh)]


def ai_status(mesh: MeshClient | None) -> AiStatus:
    """`ok` | `low` | `unavailable` (a word only; never a balance figure)."""
    if mesh is None:
        return "unavailable"
    try:
        return mesh.availability.status()
    except Exception:  # noqa: BLE001 - availability must never break a request
        return "ok"


class AiStatusView(Contract):
    status: Literal["ok", "degraded", "unavailable"]
    message: str


@router.get("/ai-status", response_model=AiStatusView)
def get_ai_status(mesh: Mesh) -> AiStatusView:
    """For the UI. `low` is reported as `ok`: users never see billing."""
    status_, message = user_status(ai_status(mesh))
    if status_ == "ok" and mesh is not None and mesh.breaker.state is BreakerState.HALF_OPEN:
        return AiStatusView(status="degraded", message="AI answers may be slower right now.")
    return AiStatusView(status=status_, message=message)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- bodies


class ThreadCreated(Contract):
    thread_id: str


class ThreadSummary(Contract):
    thread_id: str
    title: str
    created_at: datetime


class ThreadList(Contract):
    threads: list[ThreadSummary]


class MessageView(Contract):
    message_id: str
    role: Literal["user", "assistant"]
    text: str
    standalone_question: str | None = None
    run_id: str | None = None
    response_id: str | None = None
    created_at: datetime


class ThreadView(Contract):
    thread_id: str
    title: str
    messages: list[MessageView]


class ActionBody(Contract):
    kind: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    payload: dict[str, Any] = {}
    action_id: str | None = None
    label: str | None = None
    requires_confirmation: bool | None = None


class MessageBody(Contract):
    text: Annotated[str, StringConstraints(max_length=2000)] = ""
    client_msg_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    action: ActionBody | None = None


class RunAccepted(Contract):
    run_id: str
    thread_id: str
    reused: bool = False


# --------------------------------------------------------------------------- threads


def _thread(ctx: WorkspaceContext, thread_id: str) -> m.Thread:
    thread = ctx.get(m.Thread, thread_id)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such conversation.")
    return thread


@router.post("/threads", status_code=status.HTTP_201_CREATED, response_model=ThreadCreated)
def create_thread(ctx: Profile) -> ThreadCreated:
    thread = AgentStore(ctx).create_thread()
    ctx.session.commit()
    return ThreadCreated(thread_id=thread.id)


@router.get("/threads", response_model=ThreadList)
def list_threads(ctx: Profile, limit: int = Query(default=30, ge=1, le=100)) -> ThreadList:
    rows = ctx.session.scalars(
        ctx.select(m.Thread).order_by(m.Thread.created_at.desc()).limit(limit)
    )
    return ThreadList(
        threads=[
            ThreadSummary(thread_id=t.id, title=t.title, created_at=t.created_at) for t in rows
        ]
    )


@router.get("/threads/{thread_id}", response_model=ThreadView)
def get_thread(ctx: Profile, thread_id: str) -> ThreadView:
    thread = _thread(ctx, thread_id)
    messages = AgentStore(ctx).messages(thread.id)
    return ThreadView(
        thread_id=thread.id,
        title=thread.title,
        messages=[
            MessageView(
                message_id=msg.id,
                role=msg.role,  # type: ignore[arg-type]
                text=msg.text,
                standalone_question=msg.standalone_question,
                run_id=msg.run_id,
                response_id=msg.response_id,
                created_at=msg.created_at,
            )
            for msg in messages
        ],
    )


# --------------------------------------------------------------------------- questions


def _question(body: MessageBody) -> tuple[str, dict[str, Any] | None]:
    """The text to run and, for a structured follow-up, the action (docs/06 W5)."""
    action = body.action
    if action is None:
        text = body.text.strip()
        if not text:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ask a question first.")
        return text, None
    if action.kind == "ask":
        # An `ask` chip is just a question: it is screened and understood like typed text.
        question = str(action.payload.get("question") or "").strip()
        if not question:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The follow-up is empty.")
        return question[:2000], None
    if isinstance(action.payload.get("intent"), str):
        return (body.text or action.label or action.kind)[:2000], {
            "kind": action.kind,
            **action.payload,
        }
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        f"The {action.kind!r} follow-up is handled by the app, not as a question.",
    )


def _run_in_background(
    *,
    database_url: str,
    workspace_id: str,
    thread_id: str,
    text: str,
    client_msg_id: str,
    action: dict[str, Any] | None,
    mesh: MeshClient | None,
    created: Callable[[str], None],
    failed: Callable[[BaseException], None],
) -> None:
    def work() -> None:
        try:
            with session_factory(database_url)() as session:
                store = AgentStore(WorkspaceContext.open(session, workspace_id))
                outcome = ask(
                    store,
                    thread_id=thread_id,
                    text=text,
                    client_msg_id=client_msg_id,
                    mesh=mesh,
                    action=action,
                    on_run_created=created,
                )
                # The answer is saved and streamed; a question that ran out of time for its
                # advice loop carries it on here (docs/06 §13), its answer added to the thread.
                run_followup(store, outcome, mesh=mesh)
        except BaseException as exc:  # noqa: BLE001 - recorded on the run; reported to the caller
            failed(exc)
        finally:
            limits.release(workspace_id)

    threading.Thread(target=work, name=f"ask-{client_msg_id}", daemon=True).start()


@router.post(
    "/threads/{thread_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunAccepted,
)
def post_message(
    request: Request, ctx: Profile, mesh: Mesh, thread_id: str, body: MessageBody
) -> RunAccepted:
    thread = _thread(ctx, thread_id)
    store = AgentStore(ctx)
    existing = store.message_by_client_id(thread.id, body.client_msg_id)
    if existing is not None and existing.run_id:
        # A retried POST returns the run already started (docs/05 §6.4).
        return RunAccepted(run_id=existing.run_id, thread_id=thread.id, reused=True)
    text, action = _question(body)
    # A guest's questions also count per network, which a fresh guest profile doesn't reset.
    if ctx.workspace.owner_user_id is None and not network_cap.allowance.take(
        request, "question", get_settings().guest_network_daily_questions
    ):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, network_cap.REFUSED)
    refusal = limits.admit(ctx.workspace_id, datetime.now(timezone.utc))
    if refusal is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, refusal)
    if not thread.title:
        thread.title = text[:80]
    ctx.session.commit()

    started = threading.Event()
    holder: dict[str, Any] = {}

    def created(run_id: str) -> None:
        holder["run_id"] = run_id
        started.set()

    def failed(exc: BaseException) -> None:
        holder.setdefault("error", exc)
        started.set()

    url = get_settings().database_url
    assert url  # db_session already refused requests without a database
    _run_in_background(
        database_url=url,
        workspace_id=ctx.workspace_id,
        thread_id=thread.id,
        text=text,
        client_msg_id=body.client_msg_id,
        action=action,
        mesh=mesh,
        created=created,
        failed=failed,
    )
    started.wait(RUN_START_TIMEOUT_S)
    run_id = holder.get("run_id")
    if run_id is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The question couldn't be started. Try again."
        )
    return RunAccepted(run_id=run_id, thread_id=thread.id)


# --------------------------------------------------------------------------- answers


@router.get(
    "/responses/{response_id}",
    response_model=None,
    responses={200: {"description": "An `agent_response/1` snapshot (docs/08 §4.2; its JSON "
                     "Schema is frontend/src/ui-contracts/schema.json)"}},
)  # fmt: skip
def get_response(ctx: Profile, response_id: str) -> JSONResponse:
    """The nested block unions are beyond what OpenAPI generation accepts, so the body is
    validated against `AgentResponse` here and documented by the exported JSON Schema."""
    snapshot = AgentStore(ctx).response(response_id)
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such answer.")
    body = AgentResponse.model_validate(snapshot.body)
    return JSONResponse(body.model_dump(mode="json", by_alias=True))


# --------------------------------------------------------------------------- run events

STEP_STATUS = {"ok": "done", "retried": "done", "failed": "skipped", "skipped": "skipped"}
UNDERSTOOD_NODES = frozenset({"understand", "triage", "refuse", "clarify", "persist_response"})


def sse(event: str, data: dict[str, Any], event_id: str | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, separators=(',', ':'), default=str)}\n\n"


def step_event(step: m.AgentStep) -> dict[str, Any]:
    """One checklist line. Label and reason are server templates, never model text."""
    output = step.output or {}
    status_ = STEP_STATUS.get(step.status, "done")
    reason: str | None = None
    if step.cached:
        status_ = "cached"
    elif step.node == "verify" and output.get("verdict") == "reject":
        status_ = "rejected"
        failed = output.get("failed_checks")
        if isinstance(failed, list) and failed:
            reason = str(failed[0])[:200]
    elif step.node == "revise":
        status_ = "revised"
    if status_ == "skipped" and isinstance(output.get("reason"), str):
        reason = str(output["reason"])[:200]
    return {
        "step_id": step.id,
        "seq": step.seq,
        "node": step.node,
        "agent": step.agent,
        "label": step.label or step.node,
        "status": status_,
        "reason": reason,
        "at": step.finished_at.isoformat(),
    }


def _last_event_id(header: str | None, query: str | None) -> int:
    raw = header or query
    try:
        return max(0, int(raw)) if raw is not None else 0
    except ValueError:
        return 0


def _standalone(steps: list[m.AgentStep]) -> str | None:
    for step in steps:
        if step.node == "understand":
            value = (step.output or {}).get("standalone_question")
            return str(value) if isinstance(value, str) else None
    return None


def _terminal(run: m.AgentRun, store: AgentStore) -> tuple[str, dict[str, Any]] | None:
    """The run's final event, once it has finished (or was lost)."""
    now = datetime.now(timezone.utc)
    if run.status == "running":
        deadline = run.deadline_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now - deadline > LOST_AFTER:
            return "error", {"code": "run_lost", "retryable": True, "partial_rsp_id": None}
        return None
    answer = next(
        (
            msg
            for msg in (store.messages(run.thread_id) if run.thread_id else [])
            if msg.run_id == run.id and msg.role == "assistant"
        ),
        None,
    )
    if run.status == "failed" or answer is None or answer.response_id is None:
        return "error", {"code": "run_failed", "retryable": True, "partial_rsp_id": None}
    snapshot = store.response(answer.response_id)
    if snapshot is None:
        return "error", {"code": "answer_missing", "retryable": True, "partial_rsp_id": None}
    persisted = next((s for s in store.steps(run.id) if s.node == "persist_response"), None)
    if persisted is not None and (persisted.output or {}).get("kind") == "unavailable":
        # AI answers are paused: say so at once; the partial answer holds the forecast.
        return "error", {"code": "ai_unavailable", "retryable": True,
                         "partial_rsp_id": snapshot.id, "message": PAUSED_TEXT}  # fmt: skip
    body = snapshot.body or {}
    blocks = body.get("blocks") or []
    clarifier = next((b for b in blocks if b.get("type") == "ClarifyingQuestion"), None)
    if clarifier is not None:
        return "clarify", {
            "rsp_id": snapshot.id,
            "question": clarifier.get("question"),
            "options": clarifier.get("options") or [],
        }
    return "answer", {"rsp_id": snapshot.id, "response_id": snapshot.id, "snapshot": body}


def run_events(
    database_url: str,
    workspace_id: str,
    run_id: str,
    after: int,
    *,
    poll_s: float = POLL_S,
    heartbeat_s: float = HEARTBEAT_S,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[str]:
    """Replay what was missed, then follow the run until it ends. Event ids: `0` run.started, the
    step sequence for steps, one past the last step for the final event."""
    factory = session_factory(database_url)
    sent_started = after > 0
    last = after
    quiet = 0.0
    while True:
        with factory() as session:
            store = AgentStore(WorkspaceContext.open(session, workspace_id))
            run = store.run(run_id)
            if run is None:
                yield sse("error", {"code": "run_missing", "retryable": False})
                return
            steps = store.steps(run_id)
            new = [s for s in steps if s.seq > last]
            terminal = _terminal(run, store)
            if not sent_started and (
                terminal is not None or any(s.node in UNDERSTOOD_NODES for s in steps)
            ):
                yield sse(
                    "run.started",
                    {"run_id": run_id, "standalone_question": _standalone(steps),
                     "at": run.started_at.isoformat()},
                    "0",
                )  # fmt: skip
                sent_started = True
            if sent_started:
                for step in new:
                    yield sse("step", step_event(step), str(step.seq))
                    last = step.seq
                    quiet = 0.0
            if terminal is not None:
                kind, data = terminal
                yield sse(kind, data, str(max((s.seq for s in steps), default=0) + 1))
                return
        sleep(poll_s)
        quiet += poll_s
        if quiet >= heartbeat_s:
            yield sse("heartbeat", {})
            quiet = 0.0


@router.get("/runs/{run_id}/events")
def events(
    request: Request,
    ctx: Profile,
    run_id: str,
    last_event_id: str | None = Query(default=None, max_length=20),
    last_event_header: str | None = Header(default=None, alias="Last-Event-ID", max_length=20),
) -> StreamingResponse:
    if AgentStore(ctx).run(run_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such run.")
    url = get_settings().database_url
    assert url
    stream = run_events(
        url,
        ctx.workspace_id,
        run_id,
        _last_event_id(last_event_header, last_event_id),
        poll_s=request.app.state.__dict__.get("sse_poll_s", POLL_S),
        heartbeat_s=request.app.state.__dict__.get("sse_heartbeat_s", HEARTBEAT_S),
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


__all__ = ["ai_status", "get_mesh", "limits", "router", "run_events"]
