"""Duplicate detection and idempotent re-import (ING-03, docs/07 §4.4).

Exact duplicates are identified by the bank's transaction ID when it exists, otherwise by a
fingerprint of (account, date, amount, normalised narration, balance) plus an occurrence index, so
two genuine identical payments on the same day are both kept and re-importing the same file adds
nothing. Near-duplicates (same amount, ±1 day, similar narration) are flagged for review, never
dropped.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta

from backend.finance_core.types import ParsedRow


def normalise_narration(text: str) -> str:
    """Uppercase, drop long digit runs (references) and punctuation, collapse spaces."""
    text = re.sub(r"\d{4,}", " ", text.upper())
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _base_key(account_id: str, row: ParsedRow) -> str:
    balance = "" if row.balance_after_minor is None else str(row.balance_after_minor)
    parts = (
        account_id,
        row.posted_on.isoformat(),
        str(row.amount_minor),
        normalise_narration(row.description),
        balance,
    )
    return "|".join(parts)


def fingerprints(account_id: str, rows: Sequence[ParsedRow]) -> list[str]:
    """One stable fingerprint per row, in order."""
    seen: Counter[str] = Counter()
    out: list[str] = []
    for row in rows:
        if row.external_id:
            out.append(f"id:{account_id}:{row.external_id}")
            continue
        base = _base_key(account_id, row)
        seen[base] += 1
        digest = hashlib.sha256(f"{base}|{seen[base]}".encode()).hexdigest()
        out.append(f"fp:{digest}")
    return out


@dataclass(frozen=True)
class DedupeResult:
    new_rows: tuple[ParsedRow, ...]
    new_fingerprints: tuple[str, ...]
    duplicates: tuple[ParsedRow, ...]
    near_duplicates: tuple[tuple[ParsedRow, ParsedRow], ...]  # (incoming, existing)


def dedupe(
    account_id: str,
    incoming: Sequence[ParsedRow],
    existing_fingerprints: Iterable[str],
    existing_rows: Sequence[ParsedRow] = (),
) -> DedupeResult:
    existing = set(existing_fingerprints)
    keep: list[ParsedRow] = []
    keep_fp: list[str] = []
    dupes: list[ParsedRow] = []
    for row, fp in zip(incoming, fingerprints(account_id, incoming), strict=True):
        if fp in existing:
            dupes.append(row)
        else:
            keep.append(row)
            keep_fp.append(fp)
            existing.add(fp)
    near: list[tuple[ParsedRow, ParsedRow]] = []
    for row in keep:
        for old in existing_rows:
            if (
                old.amount_minor == row.amount_minor
                and abs(old.posted_on - row.posted_on) <= timedelta(days=1)
                and normalise_narration(old.description) == normalise_narration(row.description)
            ):
                near.append((row, old))
                break
    return DedupeResult(tuple(keep), tuple(keep_fp), tuple(dupes), tuple(near))
