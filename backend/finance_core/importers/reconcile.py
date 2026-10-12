"""Reconciliation gate (ING-15, docs/07 §5).

With a running-balance column, every row must chain exactly: balance[i] = balance[i-1] + amount[i]
in chronological order. Any break fails the batch (it must not be committed), with a row-level
report. Without a balance column the file is NOT_RECONCILABLE: only internal checks run, and it is
never labelled "reconciled".
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from backend.finance_core.types import ParsedRow, ReconciliationResult, ReconciliationStatus


def _chain_failures(rows: Sequence[ParsedRow]) -> list[str]:
    failures: list[str] = []
    for prev, cur in zip(rows, rows[1:], strict=False):
        assert prev.balance_after_minor is not None
        assert cur.balance_after_minor is not None
        expected = prev.balance_after_minor + cur.amount_minor
        if expected != cur.balance_after_minor:
            failures.append(
                f"row {cur.source_row_index}: balance {cur.balance_after_minor} but previous "
                f"balance {prev.balance_after_minor} + amount {cur.amount_minor} = {expected}"
            )
    return failures


def internal_failures(rows: Sequence[ParsedRow]) -> list[str]:
    failures: list[str] = []
    ids = Counter(r.external_id for r in rows if r.external_id)
    failures += [f"transaction id {i} appears {n} times" for i, n in ids.items() if n > 1]
    failures += [f"row {r.source_row_index}: zero amount" for r in rows if r.amount_minor == 0]
    currencies = {r.currency for r in rows}
    if len(currencies) > 1:
        failures.append(f"more than one currency in one table: {sorted(currencies)}")
    return failures


def reconcile(rows: Sequence[ParsedRow], has_balance: bool) -> ReconciliationResult:
    """Check a parsed table. Rows may be oldest-first or newest-first; both orders are tried and
    the one that chains is used (ties keep file order)."""
    if not rows:
        return ReconciliationResult(ReconciliationStatus.NOT_RECONCILABLE, 0, 0, ("no rows",))
    internal = internal_failures(rows)
    if not has_balance:
        status = ReconciliationStatus.FAILED if internal else ReconciliationStatus.NOT_RECONCILABLE
        return ReconciliationResult(status, len(rows), len(internal), tuple(internal))
    missing = [
        f"row {r.source_row_index}: no balance" for r in rows if r.balance_after_minor is None
    ]
    if missing:
        return ReconciliationResult(
            ReconciliationStatus.FAILED, len(rows), len(missing), tuple(missing)
        )
    forward = _chain_failures(rows)
    backward = _chain_failures(list(reversed(rows))) if forward else []
    failures = forward if not forward or len(forward) <= len(backward) else backward
    failures = failures + internal
    status = ReconciliationStatus.FAILED if failures else ReconciliationStatus.RECONCILED
    return ReconciliationResult(status, len(rows), len(failures), tuple(failures))
