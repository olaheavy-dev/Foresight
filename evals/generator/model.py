"""Core generator data model: rows with gold labels, seeded random streams, money helpers."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, replace
from datetime import date, timedelta

import numpy as np

LAYERS = ("fixed", "discretionary", "food", "narration", "ids", "extra")


class Streams:
    """One independent PCG64 stream per generator layer, derived from (seed, dataset key)."""

    def __init__(self, seed: int, key: str) -> None:
        root = np.random.SeedSequence([seed, zlib.crc32(key.encode("utf-8"))])
        self._rngs = {
            name: np.random.Generator(np.random.PCG64(child))
            for name, child in zip(LAYERS, root.spawn(len(LAYERS)), strict=True)
        }

    def __getitem__(self, layer: str) -> np.random.Generator:
        return self._rngs[layer]


@dataclass(frozen=True)
class Txn:
    """One generated bank row plus its gold labels (the truth for evaluation)."""

    day: date
    time: str  # HH:MM:SS
    amount: int  # minor units; negative = money out
    name: str  # merchant / counterparty display name (Monzo "Name")
    desc: str  # raw bank descriptor
    code: str  # UK payment-type code: DEB, DD, SO, FPO, FPI, BGC, TFR, CPT
    monzo_type: str
    monzo_cat: str
    category: str | None  # gold category key (docs/07 taxonomy); None for skip rows
    flow: str | None  # gold flow_kind
    recurring: str | None = None  # gold recurring obligation key
    income: str | None = None  # gold income stream key
    cpty: str | None = None  # gold counterparty key
    one_off: bool = False
    anomaly: str | None = None
    skip: bool = False  # e.g. Monzo £0.00 card checks: not a transaction
    currency: str = "GBP"
    account: str = "acct_main"
    seq: int = 0

    def sort_key(self) -> tuple[date, str, int]:
        return (self.day, self.time, self.seq)


def pounds(minor: int, *, signed: bool = True) -> str:
    """12345 → '123.45'; -1240 → '-12.40' (no thousands separator)."""
    sign = "-" if minor < 0 and signed else ""
    v = abs(minor)
    return f"{sign}{v // 100}.{v % 100:02d}"


def with_thousands(minor: int, sep: str = ",", dec: str = ".") -> str:
    v = abs(minor)
    whole = f"{v // 100:,}".replace(",", sep)
    return f"{whole}{dec}{v % 100:02d}"


def sort_and_number(txns: list[Txn]) -> list[Txn]:
    ordered = sorted(txns, key=lambda t: (t.day, t.time, t.name, t.amount))
    return [replace(t, seq=i) for i, t in enumerate(ordered)]


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def rand_time(rng: np.random.Generator, hour_weights: list[float] | None = None) -> str:
    if hour_weights is None:
        hour = int(rng.integers(8, 22))
    else:
        w = np.asarray(hour_weights, dtype=float)
        hour = int(rng.choice(24, p=w / w.sum()))
    return f"{hour:02d}:{int(rng.integers(0, 60)):02d}:{int(rng.integers(0, 60)):02d}"


def lognormal_pounds(rng: np.random.Generator, median: float, sigma: float, lo: float) -> float:
    return max(lo, float(rng.lognormal(np.log(median), sigma)))


def scale_to_total(amounts: list[float], total_minor: int) -> list[int]:
    """Scale positive amounts so they round to exactly total_minor (remainder on the last)."""
    s = sum(amounts)
    out = [max(1, round(a / s * total_minor)) for a in amounts]
    out[-1] += total_minor - sum(out)
    return out


def slug(name: str) -> str:
    """Counterparty key: 'Toni & Guy' → 'cpty_toni_guy'."""
    return "cpty_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
