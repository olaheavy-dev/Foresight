"""Per-token prices for cost estimates (docs/05 §9), USD per million tokens.

Read from `models.yaml` (configuration), copied from Mesh's catalogue (`GET /v1/models`).
An unknown model gets no estimate rather than a guessed one.
"""

from __future__ import annotations

from backend.mesh import model_config


def _prices() -> dict[str, tuple[float, float]]:
    models = model_config.load()["models"]
    return {
        model: (float(entry["price_in"]), float(entry["price_out"]))
        for model, entry in models.items()
        if "price_in" in entry and "price_out" in entry
    }


def price_for(model: str) -> tuple[float, float] | None:
    """Mesh reports the served model with or without its provider prefix ("gpt-6-luna" for
    "openai/gpt-6-luna"); both name the same catalogue entry."""
    prices = _prices()
    price = prices.get(model)
    if price is not None or "/" in model:
        return price
    matches = [p for key, p in prices.items() if key.split("/", 1)[1] == model]
    return matches[0] if len(matches) == 1 else None


def cost_estimate(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    price = price_for(model)
    if price is None:
        return None
    return round((prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000, 8)
