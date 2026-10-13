from __future__ import annotations

from datetime import date

from backend.finance_core.importers.anchors import (
    anchor_from_rows,
    balance_on,
    daily_balances,
    declared_anchor,
    stale_flags,
)
from backend.finance_core.importers.dedupe import dedupe, fingerprints
from backend.finance_core.types import ParsedRow


def row(day: int, amount: int, desc: str = "TESCO", balance: int | None = None,
        ext: str | None = None) -> ParsedRow:  # fmt: skip
    return ParsedRow(day, date(2026, 10, day), desc, amount, "GBP", balance, ext)


def test_reimport_adds_nothing() -> None:
    rows = [row(1, -500), row(2, -700), row(2, -700)]  # two genuine identical payments
    first = dedupe("acct_1", rows, [])
    assert len(first.new_rows) == 3
    again = dedupe("acct_1", rows, first.new_fingerprints)
    assert again.new_rows == ()
    assert len(again.duplicates) == 3


def test_external_ids_are_the_idempotency_key() -> None:
    a = [row(1, -500, ext="tx_1")]
    b = [row(1, -500, desc="TESCO STORES", ext="tx_1")]
    assert fingerprints("acct_1", a) == fingerprints("acct_1", b)


def test_near_duplicates_are_flagged_not_dropped() -> None:
    existing = [row(1, -500, desc="TESCO STORES 1234567")]
    incoming = [row(2, -500, desc="TESCO STORES 7654321")]
    result = dedupe("acct_1", incoming, fingerprints("acct_1", existing), existing)
    assert len(result.new_rows) == 1
    assert len(result.near_duplicates) == 1


def test_anchor_from_a_balance_column_and_reconstruction() -> None:
    rows = [row(1, -125000, balance=93450), row(2, -4510, balance=88940)]
    anchor = anchor_from_rows("acct_1", rows)
    assert anchor is not None
    assert (anchor.as_of, anchor.amount_minor, anchor.source) == (date(2026, 10, 2), 88940,
                                                                 "statement_column")  # fmt: skip
    assert balance_on(anchor, rows, date(2026, 10, 1)) == 93450


def test_newest_first_same_day_closing_balance() -> None:
    rows = [row(2, -1000, balance=8000), row(2, -500, balance=9000)]  # newest first
    anchor = anchor_from_rows("acct_1", rows)
    assert anchor is not None
    assert anchor.amount_minor == 8000


def test_declared_anchor_and_relative_mode() -> None:
    rows = [row(1, -500), row(3, 1000)]
    anchor = declared_anchor("acct_1", date(2026, 10, 3), 218450, "GBP")
    assert balance_on(anchor, rows, date(2026, 10, 2)) == 217450
    relative = daily_balances(None, rows, date(2026, 10, 1), date(2026, 10, 3))
    assert relative[date(2026, 10, 3)] == 0
    assert relative[date(2026, 10, 2)] == -1000


def test_stale_and_mismatch_flags() -> None:
    rows = [row(1, -500), row(20, -700)]
    anchor = declared_anchor("acct_1", date(2026, 10, 2), 10000, "GBP")
    assert stale_flags(anchor, rows, date(2026, 10, 25))
    assert stale_flags(None, rows, date(2026, 10, 25))
    other = declared_anchor("acct_1", date(2026, 10, 21), 5000, "GBP")
    assert any("imply" in f for f in stale_flags(anchor, rows, date(2026, 10, 3), [other]))
    assert stale_flags(anchor, [row(1, -500)], date(2026, 10, 3)) == []
