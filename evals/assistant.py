"""Shared harness for the model-backed Stage 2 suites (E-CTX, E-UI, E-ORC, E-SEC SEC-1).

Model calls go through the product's own Mesh client and prompts, so a recorded exchange is the
exact request the app sends. Mode comes from `FORESIGHT_EVAL_MESH`:

- `replay` (default, CI): answers from `evals/cassettes/`; no key, no network. A request that was
  never recorded is reported as "not recorded", never guessed.
- `record`: re-uses what is recorded and calls Mesh only for new or changed requests (needs
  `MESH_API_KEY`); the cassettes are then committed.

Suites that need whole answers run against a disposable PostgreSQL database seeded with the P1/P2
demo (only when `DATABASE_URL` points at a server); without one they say so.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.agents import prompting
from backend.agents.cache import answer_cache_key, prompt_bundle_version
from backend.agents.contracts import IntentClassification
from backend.agents.coordinator import UNDERSTAND_MAX_TOKENS, _understand_messages
from backend.mesh.cassettes import CassetteMiss
from backend.mesh.mesh_client import MeshCallError, MeshClient, ModelTier
from backend.settings import get_settings
from evals.common import ROOT

CASSETTES = ROOT / "evals" / "cassettes"
MODE_ENV = "FORESIGHT_EVAL_MESH"


def eval_mode() -> str:
    mode = os.environ.get(MODE_ENV, "replay")
    if mode not in {"replay", "record"}:
        raise ValueError(f"{MODE_ENV} must be replay or record, not {mode!r}")
    return mode


HOLD_ENV = "FORESIGHT_EVAL_HOLD"  # e.g. "advisor,verifier_judge": answered from recordings only


class HoldMesh:
    """Record mode, except the structured calls named in FORESIGHT_EVAL_HOLD: those are answered
    only from what is already recorded (a miss stays a miss, never a live call). Used to record
    everything else while a model choice for the held roles is pending."""

    def __init__(self, inner: MeshClient, replay: MeshClient, hold: frozenset[str]) -> None:
        self._inner = inner
        self._replay = replay
        self._hold = hold

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def structured(self, **kwargs: Any) -> Any:
        client = self._replay if kwargs.get("name") in self._hold else self._inner
        return client.structured(**kwargs)


def eval_mesh() -> MeshClient:
    """The product's Mesh client in replay or record mode, on the committed cassettes.

    Recorded and replayed prompts must carry the fixed evaluation canary, never a per-process
    one, or no recording could ever be replayed; the prompts are told so explicitly."""
    prompting.force_eval_canary = True
    settings = get_settings().model_copy(
        update={"mesh_cassette_mode": eval_mode(), "mesh_cassette_dir": str(CASSETTES)}
    )
    client = MeshClient(settings=settings)
    hold = frozenset(n.strip() for n in os.environ.get(HOLD_ENV, "").split(",") if n.strip())
    if hold and eval_mode() == "record":
        replay = MeshClient(settings=settings.model_copy(update={"mesh_cassette_mode": "replay"}))
        return HoldMesh(client, replay, hold)  # type: ignore[return-value]
    return client


USAGE: dict[str, int] = {"calls": 0, "tokens": 0}  # recorded usage of the requests answered


class NotRecorded(LookupError):
    """Replay met a request that has no cassette."""


def fresh_breaker(mesh: Any) -> None:
    """Each eval case starts with a closed circuit breaker: a transient Mesh error while recording
    one case must not pause AI for the next ones, or recording and replay take different paths."""
    from backend.mesh.breaker import CircuitBreaker

    inner = getattr(mesh, "_inner", mesh)
    if hasattr(inner, "breaker"):
        inner.breaker = CircuitBreaker()


def understand(
    mesh: MeshClient, message: str, history: list[dict[str, Any]], as_of: str
) -> IntentClassification:
    """Exactly the request the Understand node sends (same prompt, payload and schema)."""
    state: Any = {"user_message": message, "history": history[-3:], "as_of": as_of}
    try:
        result = mesh.structured(
            tier=ModelTier.FAST,
            messages=_understand_messages(state),
            output=IntentClassification,
            name="understand",
            max_tokens=UNDERSTAND_MAX_TOKENS,
            locale_pack="uk",
        )
    except CassetteMiss as exc:
        raise NotRecorded(str(exc)) from None
    for call in result.calls:
        USAGE["calls"] += 1
        USAGE["tokens"] += call.usage.total_tokens
    return result.value


def cache_key(intent: IntentClassification, *, data_version: int = 0) -> str:
    """The answer-cache key for one understood question, all other versions held fixed."""
    return answer_cache_key(
        workspace_id="wsp_eval",
        intent=intent.intent,
        slots=dict(intent.slots),
        data_version=data_version,
        prefs_version=0,
        advice_state_version="none",
        engine_version="eval",
        as_of="eval",
        locale_pack="uk",
        prompt_bundle=prompt_bundle_version(),
    )


def canonical(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.lower().split())
    if isinstance(value, list):
        return sorted(canonical(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def slots_match(expected: dict[str, Any], got: dict[str, Any]) -> bool:
    """Every labelled slot is present with the same canonical value (extra keys allowed)."""
    return all(canonical(got.get(k)) == canonical(v) for k, v in expected.items())


@contextmanager
def seeded_database() -> Iterator[sessionmaker[Session] | None]:
    """A disposable, migrated database seeded with the demo personas; None without a server."""
    server_url = os.environ.get("DATABASE_URL")
    if not server_url:
        yield None
        return
    from alembic import command
    from alembic.config import Config

    from backend.pipeline.seed_demo import seed_all
    from backend.storage.ids import reproducible_ids

    server = make_url(server_url)
    name = f"foresight_eval_{uuid.uuid4().hex[:12]}"
    admin = create_engine(server.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = server.set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    try:
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(config, "head")
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        # Reproducible ids for the whole database's life (seed and every run on it), so recorded
        # model requests that cite ids replay on the next fresh seed.
        with reproducible_ids():
            with factory() as session:
                seed_all(session)
            yield factory
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


__all__ = [
    "CASSETTES",
    "USAGE",
    "MeshCallError",
    "NotRecorded",
    "cache_key",
    "canonical",
    "eval_mesh",
    "eval_mode",
    "fresh_breaker",
    "seeded_database",
    "slots_match",
    "understand",
]
