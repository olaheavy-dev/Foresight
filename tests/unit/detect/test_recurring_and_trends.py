from __future__ import annotations

from datetime import date, timedelta

from backend.finance_core.calendar import holiday_set, next_working_day
from backend.finance_core.categorise.rules import categorise
from backend.finance_core.detect.recurring import detect_recurring
from backend.finance_core.detect.trends import category_trends, long_pay_gaps
from backend.finance_core.types import Cadence, FlowKind, WorkingDayShift
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


def _windows(desc: str, totals: list[int], as_of: date, per_window: int = 10):  # type: ignore[no-untyped-def]
    """`per_window` equal purchases in each 30-day window; totals[0] is the latest window."""
    rows = []
    for k, total in enumerate(totals):
        end = as_of - timedelta(days=30 * k)
        rows += [
            txn(desc, -(total // per_window), on=end - timedelta(days=d)) for d in range(per_window)
        ]
    return rows


def _spikes(rows, as_of):  # type: ignore[no-untyped-def]
    cats = [categorise(r, PACK) for r in rows]
    return {t.category_key for t in category_trends(rows, cats, as_of) if t.is_spike}


def test_category_with_no_baseline_is_not_a_trend() -> None:
    as_of = date(2026, 10, 11)
    rows = [txn("DELIVEROO", -9000, on=as_of - timedelta(days=d)) for d in range(3)]
    assert _spikes(rows, as_of) == set()  # a first purchase is a new-merchant finding


def test_a_rare_large_purchase_is_a_one_off_not_a_trend() -> None:
    as_of = date(2026, 10, 11)
    rows = _windows("DELIVEROO", [20000, 20500, 20310, 20100], as_of)
    rows.append(txn("DELIVEROO", -27000, on=as_of - timedelta(days=2)))  # one big party order
    assert _spikes(rows, as_of) == set()


def test_uncategorised_spend_is_never_a_trend() -> None:
    as_of = date(2026, 10, 11)
    rows = _windows("ZQX 4471 PAYMENT", [40000, 10000, 10500, 9800], as_of)
    cats = [categorise(r, PACK) for r in rows]
    assert {c.category_key for c in cats} == {"uncategorised"}
    assert _spikes(rows, as_of) == set()


def test_long_january() -> None:
    (gap,) = long_pay_gaps([date(2026, 11, 27), date(2026, 12, 18), date(2027, 1, 28)])
    assert gap.days == 41


def _collected(desc: str, amount: int, day: int, months: list[tuple[int, int]], moved: bool):  # type: ignore[no-untyped-def]
    """A bill due on `day`; when `moved`, weekend/holiday dates are collected the next working
    day, as a bank does for direct debits."""
    hol = holiday_set(PACK.holiday_country, PACK.holiday_subdiv, range(2025, 2028))
    rows = []
    for y, m in months:
        due = date(y, m, day)
        rows.append(txn(desc, -amount, on=next_working_day(due, hol) if moved else due))
    return rows, hol


def test_direct_debit_learns_nominal_day_and_next_working_day_shift() -> None:
    rows, hol = _collected("DD SEVERN TRENT WATER", 3100, 1, TWELVE, moved=True)
    (ob,) = detect_recurring(rows, [categorise(r, PACK) for r in rows], PACK, hol).obligations
    assert ob.anchor_day == 1
    assert ob.shift is WorkingDayShift.NEXT


def test_card_payment_never_shifts() -> None:
    rows, hol = _collected("DEB SPOTIFY", 1199, 1, TWELVE, moved=True)
    (ob,) = detect_recurring(rows, [categorise(r, PACK) for r in rows], PACK, hol).obligations
    assert ob.shift is WorkingDayShift.NONE


def test_direct_debit_on_fixed_dates_keeps_no_shift() -> None:
    rows, hol = _collected("DD SEVERN TRENT WATER", 3100, 20, TWELVE, moved=False)
    (ob,) = detect_recurring(rows, [categorise(r, PACK) for r in rows], PACK, hol).obligations
    assert (ob.anchor_day, ob.shift) == (20, WorkingDayShift.NONE)


def test_one_payee_recurring_in_two_categories_gets_two_unique_keys() -> None:
    """Rent and a parking space paid to the same landlord: both are recurring, keys stay unique
    (the larger group keeps the plain key), so storing them never collides."""
    from backend.finance_core.types import Categorisation, CategorisationMethod

    rows, cats = [], []
    for month in range(1, 7):
        rent = txn("DD HARBOURSIDE HOMES", -90000, date(2026, month, 1))
        rows.append(rent)
        cats.append(Categorisation(rent.id, "housing.rent", FlowKind.SPENDING,
                                   CategorisationMethod.RULE, 0.95))  # fmt: skip
        if month < 6:
            parking = txn("DD HARBOURSIDE HOMES", -6000, date(2026, month, 2))
            rows.append(parking)
            cats.append(Categorisation(parking.id, "transport.car", FlowKind.SPENDING,
                                       CategorisationMethod.RULE, 0.95))  # fmt: skip
    keys = [o.key for o in detect_recurring(rows, cats, PACK).obligations]
    assert len(keys) == len(set(keys)) == 2
    assert keys.count("rob_harbourside_homes") == 1
    assert any(k.startswith("rob_harbourside_homes_transport") for k in keys)


def test_low_volume_category_jump_is_not_a_trend() -> None:
    """Fewer than MIN_BASE_COUNT purchases in a typical month is not a behaviour: a few extra
    taxi rides are not a trend, but the same jump in a regular habit is (docs/07 §6.6)."""
    as_of = date(2026, 10, 11)
    # 2 rides a month for three months (MAD 0), then 4 rides at the same fare: +100%.
    rare = _windows("UBER", [8000, 4000, 4000, 4000], as_of, per_window=2)
    assert _spikes(rare, as_of) == set()
    regular = _windows("DELIVEROO", [40000, 20000, 20000, 20000], as_of, per_window=10)
    assert _spikes(regular, as_of) == {"food.delivery"}
