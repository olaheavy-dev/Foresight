"""Circuit breaker for model calls (docs/05 §6.4).

Opens after 5 consecutive failures, or when more than half of the calls in the last 60 s failed
(with at least 4 calls in the window). While open, callers skip straight to their degraded path
instead of each waiting for a timeout. After 60 s one probe call is let through; success closes it.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from enum import Enum


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        *,
        consecutive_limit: int = 5,
        window_seconds: float = 60.0,
        window_min_calls: int = 4,
        failure_ratio: float = 0.5,
        open_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._consecutive_limit = consecutive_limit
        self._window = window_seconds
        self._window_min_calls = window_min_calls
        self._ratio = failure_ratio
        self._open_seconds = open_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._events: deque[tuple[float, bool]] = deque()
        self._consecutive = 0
        self._opened_at: float | None = None
        self._probing = False
        self.openings = 0

    @property
    def state(self) -> BreakerState:
        with self._lock:
            return self._state_locked()

    def _state_locked(self) -> BreakerState:
        if self._opened_at is None:
            return BreakerState.CLOSED
        if self._clock() - self._opened_at >= self._open_seconds:
            return BreakerState.HALF_OPEN
        return BreakerState.OPEN

    def allow(self) -> bool:
        """True if a call may go ahead now. In half-open state only one probe is allowed."""
        with self._lock:
            state = self._state_locked()
            if state is BreakerState.CLOSED:
                return True
            if state is BreakerState.HALF_OPEN and not self._probing:
                self._probing = True
                return True
            return False

    def record(self, ok: bool) -> None:
        with self._lock:
            now = self._clock()
            self._events.append((now, ok))
            while self._events and now - self._events[0][0] > self._window:
                self._events.popleft()
            if self._opened_at is not None:
                # The half-open probe decides.
                self._probing = False
                if ok:
                    self._opened_at = None
                    self._consecutive = 0
                    self._events.clear()
                else:
                    self._opened_at = now
                return
            self._consecutive = 0 if ok else self._consecutive + 1
            failures = sum(1 for _, good in self._events if not good)
            too_many_in_window = (
                len(self._events) >= self._window_min_calls
                and failures / len(self._events) > self._ratio
            )
            if self._consecutive >= self._consecutive_limit or too_many_in_window:
                self._opened_at = now
                self.openings += 1
