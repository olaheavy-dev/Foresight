"""Per-token prices for cost estimates (docs/05 §9), USD per million tokens.

Copied from Mesh's model catalogue (`GET /v1/models`, 13 Oct 2026) for the configured models only.
An unknown model gets no estimate rather than a guessed one.
"""

from __future__ import annotations

PRICES_USD_PER_1M: dict[str, tuple[float, float]] = {
    # model id: (input, output)
    "openai/gpt-6-luna": (0.10, 0.50),
    "anthropic/claude-haiku-5.5": (0.10, 0.50),
    "anthropic/claude-sonnet-5.5": (2.00, 10.00),
    "openai/gpt-6.1-sol": (2.00, 10.00),
    "google/gemini-3.1-pro": (2.00, 12.00),
    "google/gemini-3.8-flash": (0.75, 3.75),
    "openai/gpt-5.6-luna-pro": (0.25, 1.50),
}


def price_for(model: str) -> tuple[float, float] | None:
    """Mesh reports the served model with or without its provider prefix ("gpt-6-luna" for
    "openai/gpt-6-luna"); both name the same catalogue entry."""
    price = PRICES_USD_PER_1M.get(model)
    if price is not None or "/" in model:
        return price
    matches = [p for key, p in PRICES_USD_PER_1M.items() if key.split("/", 1)[1] == model]
    if len(matches) == 1:
        return matches[0]
    # Some served names differ only in punctuation ("openai-gpt-56-luna-pro" for
    # "openai/gpt-5.6-luna-pro", seen 13 Oct 2026): compare letters and digits only.
    squash = _squash(model)
    loose = [
        p
        for key, p in PRICES_USD_PER_1M.items()
        if squash in (_squash(key), _squash(key.split("/", 1)[1]))
    ]
    return loose[0] if len(loose) == 1 else None


def _squash(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def cost_estimate(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    price = price_for(model)
    if price is None:
        return None
    return round((prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000, 8)
