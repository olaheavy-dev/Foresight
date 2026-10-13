"""Per-run model budget (docs/01 FR-60, docs/06 §10.1): 12 LLM calls or 60k tokens."""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_LLM_CALLS = 12
MAX_TOKENS = 60_000


class BudgetExceeded(RuntimeError):
    """The run has used its model budget; compose from what exists and flag the answer partial."""


@dataclass
class Budget:
    max_calls: int = MAX_LLM_CALLS
    max_tokens: int = MAX_TOKENS
    calls: int = 0
    tokens: int = 0
    exceeded: bool = field(default=False)

    def check(self) -> None:
        """Before a model call: refuse if the next call would go over the limits."""
        if self.exceeded or self.calls >= self.max_calls or self.tokens >= self.max_tokens:
            self.exceeded = True
            raise BudgetExceeded(
                f"run budget used: {self.calls}/{self.max_calls} calls, "
                f"{self.tokens}/{self.max_tokens} tokens"
            )

    def charge(self, calls: int, tokens: int) -> None:
        self.calls += calls
        self.tokens += tokens
