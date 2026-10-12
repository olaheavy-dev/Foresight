from __future__ import annotations

from datetime import date, timedelta

from backend.finance_core.categorise.rules import categorise
from backend.finance_core.detect.recurring import detect_recurring
from backend.finance_core.detect.trends import category_trends, long_pay_gaps
from backend.finance_core.types import Cadence, FlowKind
from tests.unit.categorise.helpers import txn, uk_pack

PACK = uk_pack()


def _monthly(desc: str, amount: int, day: int, months: list[tuple[int, int]]):  # type: ignore[no-untyped-def]
    return [txn(desc, -amount, on=date(y, m, day)) for y, m in months]


def _report(rows):  # type: ignore[no-untyped-def]
    return detect_recurring(rows, [categorise(r, PACK) for r in rows], PACK)


TWELVE = [(2025, m) for m in range(10, 13)] + [(2026, m) for m in range(1, 10)]


def test_monthly_bills_detected_with_anchor_day() -> None:
    rows = _monthly("OCTOPUS ENERGY DD", 7800, 20, TWELVE)
    (ob,) = _report(rows).obligations
    assert ob.cadence == Cadence.MONTHLY
    assert ob.anchor_day == 20
    assert ob.amount_minor == -7800
    assert ob.active_months == frozenset(range(1, 13))


def test_council_tax_active_months_apr_to_jan() -> None:
    months = [(2025, m) for m in range(4, 13)] + [(2026, 1)] + [(2026, m) for m in range(4, 10)]
    (ob,) = _report(_monthly("LEEDS CITY COUNCIL TAX DD", 16200, 15, months)).obligations
    assert ob.category_key == "housing.council_tax"
    assert ob.active_months == frozenset({4, 5, 6, 7, 8, 9, 10, 11, 12, 1})


def test_short_history_council_tax_uses_pack_default_and_flags_it() -> None:
    report = _report(
        _monthly("LEEDS CITY COUNCIL TAX DD", 16200, 15, [(2026, m) for m in (6, 7, 8, 9)])
    )
    (ob,) = report.obligations
    assert ob.active_months == PACK.seasonal_defaults["housing.council_tax"]
    assert report.assumptions


def test_commitment_and_price_change() -> None:
    rows = _monthly("LEMFI", 25000, 15, TWELVE[:6])
    (ob,) = _report(rows).obligations
    assert ob.is_commitment
    assert ob.flow_kind == FlowKind.COMMITMENT
    streaming = _monthly("NETFLIX", 1099, 17, TWELVE[:5]) + _monthly(
        "NETFLIX", 1299, 17, TWELVE[5:6]
    )
    assert _report(streaming).price_changes


def test_variable_bills_do_not_raise_price_changes() -> None:
    rows = [
        txn("OCTOPUS ENERGY DD", -a, on=date(y, m, 20))
        for (y, m), a in zip(
            TWELVE, [7800, 8100, 7600, 8300, 7900, 8000, 7700, 8200, 7850, 8050], strict=False
        )
    ]
    assert _report(rows).price_changes == ()


def test_subscription_overlap_sky_tv_and_now() -> None:
    rows = _monthly("SKY TV DD", 4600, 12, TWELVE[:4]) + _monthly(
        "NOW ENTERTAINMENT", 999, 5, TWELVE[:4]
    )
    (overlap,) = _report(rows).overlaps
    assert overlap.family == "tv_and_streaming"
    assert overlap.monthly_total_minor == 5599


def test_one_offs_are_not_recurring() -> None:
    rows = [txn("KWIKFIT LEEDS", -65000, on=date(2026, 10, 14))]
    assert _report(rows).obligations == ()


def test_food_delivery_spike() -> None:
    as_of = date(2026, 10, 11)
    rows = []
    for k, amount in enumerate([20000, 20500, 20310]):  # three prior windows ≈ £203
        end = as_of - timedelta(days=30 * (k + 1))
        rows += [txn("DELIVEROO", -amount // 10, on=end - timedelta(days=d)) for d in range(10)]
    rows += [txn("DELIVEROO", -2864, on=as_of - timedelta(days=d)) for d in range(10)]
    trends = category_trends(rows, [categorise(r, PACK) for r in rows], as_of)
    (food,) = [t for t in trends if t.category_key == "food.delivery"]
    assert food.recent_minor == 28640
    assert food.is_spike
    assert round(food.change_share, 2) == 0.41


def test_long_january() -> None:
    (gap,) = long_pay_gaps([date(2026, 11, 27), date(2026, 12, 18), date(2027, 1, 28)])
    assert gap.days == 41
