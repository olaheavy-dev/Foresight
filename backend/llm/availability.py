"""Whether AI answers can run right now (owner decision, 13 Oct 2026).

`status()` is `ok` or `unavailable`:

- `unavailable` at once while the circuit breaker is open;
- `unavailable` for five minutes after a call is refused for lack of credit (`note_spend_limit`,
  OpenAI's 429 `insufficient_quota`), then calls are tried again;
- `unavailable` once today's model spend reaches `MODEL_DAILY_BUDGET_USD`
  (`backend/llm/spend_guard.py`), until the next UTC day.

OpenAI has no balance a project key can read, so there is no early "low" warning: running out
shows as a refusal. Users never see billing words.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Literal

AiStatus = Literal["ok", "unavailable"]
CACHE_SECONDS = 300.0


class AiAvailability:
    def __init__(
        self,
        breaker_open: Callable[[], bool],
        *,
        ttl_seconds: float = CACHE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        budget_used: Callable[[], bool] = lambda: False,
    ) -> None:
        self._breaker_open = breaker_open
        self._budget_used = budget_used
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._refused_at: float | None = None

    def status(self) -> AiStatus:
        if self._breaker_open() or self._budget_used():
            return "unavailable"
        with self._lock:
            if self._refused_at is not None and self._clock() - self._refused_at < self._ttl:
                return "unavailable"
            return "ok"

    def note_spend_limit(self) -> None:
        """A call was refused for lack of credit: unavailable now, tried again after the TTL."""
        with self._lock:
            self._refused_at = self._clock()


def user_status(status: AiStatus) -> tuple[str, str]:
    """What the UI may show: `ok` or `unavailable`, with plain wording (no billing words)."""
    if status == "unavailable":
        return "unavailable", PAUSED_TEXT
    return "ok", "AI answers are available."


PAUSED_TEXT = "AI answers are paused right now. Your forecast and numbers still work."
