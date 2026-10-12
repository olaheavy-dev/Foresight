"""Balance anchors and reconstruction (ING-04, docs/00 §6.5, docs/07 §4.1).

No opening balance is ever required: a dated balance comes from the statement's balance column or
the user's declared "balance today". The balance on any day is the nearest anchor ± transactions.
With no anchor the forecast runs in relative mode ("£X more/less than today").
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from backend.finance_core.types import BalanceAnchor, ParsedRow

STALE_AFTER_DAYS = 7
MISMATCH_TOLERANCE = 0.01  # 1%


def anchor_from_rows(account_id: str, rows: Sequence[ParsedRow]) -> BalanceAnchor | None:
    """End-of-day balance on the latest date that has a balance (statement column)."""
    with_balance = [r for r in rows if r.balance_after_minor is not None]
    if not with_balance:
        return None
    latest = max(r.posted_on for r in with_balance)
    same_day = [r for r in with_balance if r.posted_on == latest]
    # The day's closing balance belongs to the row that no other same-day row builds on
    # (works for oldest-first and newest-first files); fall back to file order.
    closing = same_day[-1]
    for r in same_day:
        builds_on_r = any(
            o is not r and (o.balance_after_minor or 0) - o.amount_minor == r.balance_after_minor
            for o in same_day
        )
        if not builds_on_r:
            closing = r
            break
    assert closing.balance_after_minor is not None
    return BalanceAnchor(
        account_id=account_id,
        as_of=latest,
        amount_minor=closing.balance_after_minor,
        currency=closing.currency,
        source="statement_column",
    )


def declared_anchor(account_id: str, on: date, amount_minor: int, currency: str) -> BalanceAnchor:
    return BalanceAnchor(account_id, on, amount_minor, currency, source="declared")


def balance_on(anchor: BalanceAnchor, rows: Sequence[ParsedRow], on: date) -> int:
    """End-of-day balance on `on`, reconstructed from the anchor and the rows between."""
    if on >= anchor.as_of:
        delta = sum(r.amount_minor for r in rows if anchor.as_of < r.posted_on <= on)
        return anchor.amount_minor + delta
    delta = sum(r.amount_minor for r in rows if on < r.posted_on <= anchor.as_of)
    return anchor.amount_minor - delta


def daily_balances(
    anchor: BalanceAnchor | None, rows: Sequence[ParsedRow], start: date, end: date
) -> dict[date, int]:
    """End-of-day balances from start to end. Without an anchor: relative to the end date (0)."""
    base = anchor or BalanceAnchor("", end, 0, rows[0].currency if rows else "", "relative")
    out: dict[date, int] = {}
    day = start
    while day <= end:
        out[day] = balance_on(base, rows, day)
        day += timedelta(days=1)
    return out


def stale_flags(
    anchor: BalanceAnchor | None,
    rows: Sequence[ParsedRow],
    today: date,
    other_anchors: Sequence[BalanceAnchor] = (),
) -> list[str]:
    """Reasons the balance may be out of date, or [] if fine."""
    if anchor is None:
        return ["no dated balance: forecast runs in relative mode until a balance is added"]
    flags: list[str] = []
    later = [r for r in rows if r.posted_on > anchor.as_of]
    if (today - anchor.as_of).days > STALE_AFTER_DAYS and later:
        flags.append(f"balance is from {anchor.as_of.isoformat()}, with newer transactions since")
    for other in other_anchors:
        expected = balance_on(anchor, rows, other.as_of)
        scale = max(abs(other.amount_minor), 1)
        if abs(expected - other.amount_minor) / scale > MISMATCH_TOLERANCE:
            flags.append(
                f"balance on {other.as_of.isoformat()} is {other.amount_minor} but transactions "
                f"imply {expected}"
            )
    return flags
