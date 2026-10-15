"""Prefixed, time-sortable ids: `<prefix>_<ULID>` (docs/07 §3 conventions).

A ULID is 48 bits of Unix milliseconds followed by 80 random bits, written as 26 Crockford base32
characters, so ids sort by creation time. Implemented here to avoid a dependency.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

PREFIXES = frozenset(
    {
        "wsp",
        "usr",
        "ses",
        "acct",
        "imp",
        "txn",
        "ctg",
        "cpty",
        "fmt",
        "bal",
        "inc",
        "rob",
        "calc",
        "aud",
        # agent runtime (migration 0004)
        "run",
        "step",
        "ver",
        "rec",
        "rsp",
        "thr",
        "msg",
        # behaviour findings (migration 0005)
        "fnd",
    }
)


def ulid(now_ms: int | None = None) -> str:
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    value = (ms << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


# Reproducible mode (evaluation databases only): ids come from a fixed epoch and a counter per
# prefix, so a demo seeded twice gets the same workspace, transaction, finding and calculation ids,
# and model requests that cite them can be recorded once and replayed (docs/09 §16). Ids keep the
# ULID shape and still sort by creation order. Production never enables it.
_REPRO_LOCK = threading.Lock()
_repro_counters: dict[str, int] | None = None
_REPRO_EPOCH_MS = 1_760_000_000_000


@contextmanager
def reproducible_ids() -> Iterator[None]:
    global _repro_counters
    with _REPRO_LOCK:
        previous, _repro_counters = _repro_counters, {}
    try:
        yield
    finally:
        with _REPRO_LOCK:
            _repro_counters = previous


def _reproducible_ulid(prefix: str) -> str | None:
    with _REPRO_LOCK:
        if _repro_counters is None:
            return None
        n = _repro_counters.get(prefix, 0) + 1
        _repro_counters[prefix] = n
    value = ((_REPRO_EPOCH_MS + n) << 80) | n
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix}")
    return f"{prefix}_{_reproducible_ulid(prefix) or ulid()}"
