"""Generate the illustrative design fixture from ONE deterministic daily cash-flow model.

Every figure shown in the design screens comes from fixture.json, so all views reconcile by
construction. This is a design aid only: the product's engine (backend/finance_core) computes
real numbers from imported data. Fictional person, fictional amounts.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import holidays

TODAY = date(2026, 10, 12)
END = date(2027, 3, 31)
START_BALANCE = 2184.50  # Monzo statement, as of Sun 11 Oct
PAY = 4050.00
# Paydays follow the same rule as backend/finance_core/calendar.py (uk pack): paid on the 28th,
# moved to the previous working day at weekends and England & Wales bank holidays; December is
# paid early, on the 18th. Bank holidays come from python-holidays (GB, subdiv ENG), so Good
# Friday 26 Mar 2027 moves March pay to Thu 25 Mar.
PAY_DAY, DECEMBER_PAY_DAY = 28, 18
BANK_HOLIDAYS = frozenset(holidays.country_holidays("GB", subdiv="ENG", years=[2026, 2027]))


def previous_working_day(d: date) -> date:
    while d.weekday() >= 5 or d in BANK_HOLIDAYS:
        d -= timedelta(days=1)
    return d


def payday(year: int, month: int) -> date:
    return previous_working_day(date(year, month, DECEMBER_PAY_DAY if month == 12 else PAY_DAY))


PAYDAYS = [payday(y, m) for y, m in ((2026, 10), (2026, 11), (2026, 12),
                                     (2027, 1), (2027, 2), (2027, 3))]
RENT = 1250.00
BUFFER = 500.00
DAILY = None  # calibrated below so the calm baseline low before payday is £812

MONTHLY = [  # (day, amount, label, category)
    (1, -RENT, "Rent · Northside Lettings", "Housing"),
    (1, -27.99, "PureGym", "Subscriptions"),
    (5, -42.00, "Yorkshire Water", "Bills"),
    (9, -31.00, "Broadband", "Bills"),
    (12, -46.00, "Sky TV", "Subscriptions"),
    (15, -162.00, "Leeds City Council tax", "Bills"),
    (15, -250.00, "LemFi · family support", "Family support"),
    (15, -400.00, "Savings pot transfer", "Savings"),
    (17, -12.99, "Netflix", "Subscriptions"),
    (20, -78.00, "Octopus Energy", "Bills"),
    (22, -12.99, "Spotify", "Subscriptions"),
    (24, -31.00, "Other subscriptions", "Subscriptions"),
]


def months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def events(extra=(), defer_oct_savings=False):
    ev = []
    for y, m in months(TODAY, END):
        for day, amt, label, cat in MONTHLY:
            d = date(y, m, day)
            if d <= TODAY:
                continue
            if defer_oct_savings and (y, m) == (2026, 10) and cat == "Savings":
                ev.append((date(2026, 10, 29), amt, label + " (moved after payday)", cat))
                continue
            ev.append((d, amt, label, cat))
    ev += [(p, PAY, "Salary · Acme Analytics Ltd", "Income") for p in PAYDAYS]
    return ev + list(extra)


def simulate(daily, ev, daily_saving_to_payday=0.0):
    """daily_saving_to_payday: lower spending per day from 13 Oct to 27 Oct (a spending cap)."""
    bal, d, out = START_BALANCE, TODAY, {}
    while d <= END:
        if d > TODAY:
            bal -= daily
            if d <= date(2026, 10, 27):
                bal += daily_saving_to_payday
        bal += sum(a for (ed, a, *_ ) in ev if ed == d)
        out[d] = round(bal, 2)
        d += timedelta(days=1)
    return out


def monte_carlo(daily, ev, window, daily_saving_to_payday=0.0, paths=500, sd=14.0, seed=1729):
    """Seeded paths with day-to-day spending noise. Returns the chance the balance dips below the
    buffer inside the window, and the P10/P50/P90 of the lowest balance in that window."""
    rng = random.Random(seed)
    a, b = window
    by_day: dict[date, float] = {}
    for ed, amt, *_ in ev:
        by_day[ed] = by_day.get(ed, 0.0) + amt
    lows = []
    for _ in range(paths):
        bal, d, lo = START_BALANCE, TODAY, None
        while d <= b:
            if d > TODAY:
                bal -= max(0.0, rng.gauss(daily, sd))
                if d <= date(2026, 10, 27):
                    bal += daily_saving_to_payday
            bal += by_day.get(d, 0.0)
            if d >= a:
                lo = bal if lo is None else min(lo, bal)
            d += timedelta(days=1)
        lows.append(lo)
    lows.sort()
    pct = lambda q: round(lows[int(q * (len(lows) - 1))], 2)
    return {
        "chance_below_buffer_pct": round(100 * sum(v < BUFFER for v in lows) / len(lows)),
        "low_p10": pct(0.10), "low_p50": pct(0.50), "low_p90": pct(0.90),
    }


def low(series, a, b):
    k = min((d for d in series if a <= d <= b), key=lambda d: series[d])
    return k, series[k]


def calibrate(target=812.0):
    lo, hi = 0.0, 200.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if low(simulate(mid, events()), TODAY, date(2026, 10, 27))[1] > target:
            lo = mid
        else:
            hi = mid
    return round(mid, 2)


def main() -> None:
    daily = calibrate()
    car = [(date(2026, 10, 14), -650.0, "Car repair · KwikFit Leeds", "Transport")]
    pace = round(286.40 / 30 * 15, 2)  # usual food-delivery pace, 13–27 Oct
    rej_daily = (pace - 40.0) / 15
    plan_daily = (pace - 100.0) / 15
    s_base = simulate(daily, events())
    s_car = simulate(daily, events(car))
    s_rej = simulate(daily, events(car), rej_daily)
    s_plan = simulate(daily, events(car, defer_oct_savings=True), plan_daily)
    hol_nov = car + [(date(2026, 11, 6), -1200.0, "Holiday · booked 6 Nov", "Travel")]
    hol_late = car + [(date(2026, 11, 28), -1200.0, "Holiday · booked 28 Nov", "Travel")]
    s_hn = simulate(daily, events(hol_nov, defer_oct_savings=True), plan_daily)
    s_hl = simulate(daily, events(hol_late, defer_oct_savings=True), plan_daily)
    oct_, nov, dec = (TODAY, date(2026, 10, 27)), (date(2026, 10, 28), date(2026, 11, 26)), (date(2026, 11, 27), date(2026, 12, 17))

    def lowfmt(s, w):
        d, v = low(s, *w)
        return {"date": d.isoformat(), "value": v}

    mc = {
        "baseline_oct": monte_carlo(daily, events(), oct_),
        "car_oct": monte_carlo(daily, events(car), oct_),
        "rejected_oct": monte_carlo(daily, events(car), oct_, rej_daily),
        "plan_oct": monte_carlo(daily, events(car, defer_oct_savings=True), oct_, plan_daily),
        "holiday_6nov_nov": monte_carlo(daily, events(hol_nov, defer_oct_savings=True), nov, plan_daily),
        "holiday_28nov_dec": monte_carlo(daily, events(hol_late, defer_oct_savings=True), dec, plan_daily),
    }
    fixture = {
        "note": "Illustrative design fixture generated by build_fixture.py. Fictional.",
        "person": "Amara Nwosu (fictional)", "account": "Monzo current account",
        "as_of": "2026-10-11", "today": TODAY.isoformat(),
        "balance": START_BALANCE, "salary_net": PAY, "paydays": [p.isoformat() for p in PAYDAYS],
        "rent": RENT, "buffer": BUFFER, "daily_spend_model": daily,
        "food_delivery_30d": 286.40, "food_delivery_median_3m": 203.10,
        "delivery_pace_to_payday": pace,
        "rejected_cap_below_pace_pct": round((1 - 40 / pace) * 100),
        "plan_cap_below_pace_pct": round((1 - 100 / pace) * 100),
        "lows": {
            "baseline_oct": lowfmt(s_base, oct_), "car_oct": lowfmt(s_car, oct_),
            "rejected_oct": lowfmt(s_rej, oct_), "plan_oct": lowfmt(s_plan, oct_),
            "plan_nov": lowfmt(s_plan, nov), "plan_dec": lowfmt(s_plan, dec),
            "holiday_6nov_nov": lowfmt(s_hn, nov), "holiday_28nov_dec": lowfmt(s_hl, dec),
            "holiday_28nov_nov": lowfmt(s_hl, nov),
        },
        "uncertainty": mc,
        "series": {
            "baseline": {d.isoformat(): v for d, v in s_base.items()},
            "car": {d.isoformat(): v for d, v in s_car.items()},
            "plan": {d.isoformat(): v for d, v in s_plan.items()},
            "holiday_6nov": {d.isoformat(): v for d, v in s_hn.items()},
            "holiday_28nov": {d.isoformat(): v for d, v in s_hl.items()},
        },
        "end_of_march": {"plan": s_plan[END], "holiday_28nov": s_hl[END]},
    }
    out = Path(__file__).with_name("fixture.json")
    out.write_text(json.dumps(fixture, indent=1))
    summary = {k: v for k, v in fixture.items() if k != "series"}
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
