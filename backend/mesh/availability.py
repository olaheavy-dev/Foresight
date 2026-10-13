"""Whether AI answers can run right now (owner decision, 13 Oct 2026).

`status()` is `ok`, `low` or `unavailable`:

- from Mesh `GET /v1/balance`, which costs no credit, cached for five minutes: `low` below
  `MESH_LOW_BALANCE_USD`, `unavailable` at or below the per-question worst case
  (`MESH_QUESTION_WORST_CASE_USD`);
- `unavailable` at once while the circuit breaker is open, or after any call is refused for
  spend (`note_spend_limit`), until the next balance check says otherwise.

The balance figure never leaves this module: callers get the status word only, and nothing is
logged. Users never see `low` (it maps to `ok`) and never see billing words.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Literal

AiStatus = Literal["ok", "low", "unavailable"]
CACHE_SECONDS = 300.0


class AiAvailability:
    def __init__(
        self,
        fetch_available_usd: Callable[[], float | None],
        breaker_open: Callable[[], bool],
        *,
        low_usd: float,
        worst_case_usd: float,
        ttl_seconds: float = CACHE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch_available_usd
        self._breaker_open = breaker_open
        self._low = low_usd
        self._worst = worst_case_usd
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: AiStatus | None = None
        self._checked_at = 0.0

    def _from_balance(self) -> AiStatus:
        try:
            available = self._fetch()
        except Exception:  # noqa: BLE001 - an unreadable balance is not a reason to stop answering
            return "ok"
        if available is None:
            return "ok"
        if available <= self._worst:
            return "unavailable"
        if available < self._low:
            return "low"
        return "ok"

    def status(self) -> AiStatus:
        if self._breaker_open():
            return "unavailable"
        with self._lock:
            now = self._clock()
            if self._cached is None or now - self._checked_at >= self._ttl:
                self._cached = self._from_balance()
                self._checked_at = now
            return self._cached

    def note_spend_limit(self) -> None:
        """A call was refused for spend: unavailable now, re-checked when the cache expires."""
        with self._lock:
            self._cached = "unavailable"
            self._checked_at = self._clock()

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None


def user_status(status: AiStatus) -> tuple[str, str]:
    """What the UI may show: `ok` or `unavailable`, with plain wording (no billing words)."""
    if status == "unavailable":
        return "unavailable", PAUSED_TEXT
    return "ok", "AI answers are available."


PAUSED_TEXT = "AI answers are paused right now. Your forecast and numbers still work."
