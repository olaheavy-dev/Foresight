"""Per-token prices for cost estimates (docs/05 §9), USD per million tokens.

Read from `models.yaml` (configuration). The prices were copied from Mesh's catalogue
(`GET /v1/models`, 13 Oct 2026); gpt-6-luna and gpt-6.1-sol matched OpenAI's list prices on 16 Oct
(docs/11), and gpt-6-sol's price has not been checked against OpenAI's yet.
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
    """The provider reports the served model without its prefix ("gpt-6-luna" for
    "openai/gpt-6-luna"; recordings made through Mesh may have either); both name the same
    catalogue entry."""
    prices = _prices()
    price = prices.get(model)
    if price is not None:
        return price
    matches = [p for key, p in prices.items() if key.split("/", 1)[1] == model]
    if len(matches) == 1:
        return matches[0]
    # Some served names differ only in punctuation ("openai-gpt-56-luna-pro" for
    # "openai/gpt-5.6-luna-pro", seen 13 Oct 2026): compare letters and digits only.
    squash = _squash(model)
    loose = [
        p for key, p in prices.items() if squash in (_squash(key), _squash(key.split("/", 1)[1]))
    ]
    return loose[0] if len(loose) == 1 else None


def _squash(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def cost_estimate(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    price = price_for(model)
    if price is None:
        return None
    return round((prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000, 8)
