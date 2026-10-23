"""Project-wide daily spend guard for live model calls (owner decision, 13 Oct 2026).

Model spend for the current UTC day is the sum of `AgentStep.cost_estimate_usd` (`usage` × the
price table) over every workspace, read at most once a minute; calls made since the last read are
added in process so a burst can't overshoot. Once it reaches `MODEL_DAILY_BUDGET_USD`, AI answers
pause (`AiAvailability` reports `unavailable`, live calls are refused) until the next UTC day.

Like the balance, the figure never leaves this module: callers get a yes/no.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timezone

CACHE_SECONDS = 60.0


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


class DailySpendGuard:
    def __init__(
        self,
        spent_on: Callable[[date], float | None],
        *,
        budget_usd: float,
        today: Callable[[], date] = utc_today,
        ttl_seconds: float = CACHE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._spent_on = spent_on
        self._budget = budget_usd
        self._today = today
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._day: date | None = None
        self._stored = 0.0  # last read from the store for `_day`
        self._since = 0.0  # charged in process since that read
        self._read_at = 0.0

    def _refresh(self) -> None:
        day = self._today()
        if day != self._day or self._clock() - self._read_at >= self._ttl:
            try:
                stored = self._spent_on(day)
            except Exception:  # noqa: BLE001 - an unreadable total keeps the last known one
                stored = None
            if day != self._day:
                self._day, self._stored, self._since = day, 0.0, 0.0
            if stored is not None:
                self._stored, self._since = stored, 0.0
            self._read_at = self._clock()

    def exhausted(self) -> bool:
        """True once today's spend has reached the budget (a budget ≤ 0 disables the guard)."""
        if self._budget <= 0:
            return False
        with self._lock:
            self._refresh()
            return self._stored + self._since >= self._budget

    def charge(self, usd: float | None) -> None:
        """A live call just cost `usd` (not yet in the store until its step is written)."""
        if usd:
            with self._lock:
                self._refresh()
                self._since += usd
