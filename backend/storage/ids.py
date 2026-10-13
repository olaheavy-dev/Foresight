"""Prefixed, time-sortable ids: `<prefix>_<ULID>` (docs/07 §3 conventions).

A ULID is 48 bits of Unix milliseconds followed by 80 random bits, written as 26 Crockford base32
characters, so ids sort by creation time. Implemented here to avoid a dependency.
"""

from __future__ import annotations

import secrets
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

PREFIXES = frozenset(
    {"wsp", "acct", "imp", "txn", "ctg", "cpty", "fmt", "bal", "inc", "rob", "calc", "aud"}
)


def ulid(now_ms: int | None = None) -> str:
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    value = (ms << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix}")
    return f"{prefix}_{ulid()}"
