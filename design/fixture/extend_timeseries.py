"""Add observed history and weekly forecast paths to fixture.json, using the SAME model.

Run after extend_fixture.py:
    python3 build_fixture.py && python3 extend_fixture.py && python3 extend_timeseries.py \
        && python3 export_js.py
Adds:
  history - "observed" balance from the previous payday (Mon 28 Sep) to the 11 Oct statement
            anchor, back-cast from the anchor with the model's recurring bills and seeded
            day-to-day spending noise. The last value equals the statement balance exactly.
            It starts at the payday because the same model puts the pre-payday September low
            below zero, which would contradict the persona; a longer window would need a
            different, unmodelled September.
  weekly  - for each scenario, the balance on today and every 7th day to 31 Mar: P50, P10 and
            P90 across the same 500 seeded paths used for the lows.
Fictional data, design aid only.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import build_fixture as bf

FIXTURE = Path(__file__).with_name("fixture.json")
PREVIOUS_PAYDAY = date(2026, 9, 28)  # 28 Sep 2026 is a Monday


def past_events(start: date, end: date) -> dict[date, float]:
    """Recurring bills and the previous payday that fall in [start, end]."""
    by_day: dict[date, float] = {}
    for y, m in bf.months(start, end):
        for day, amt, *_ in bf.MONTHLY:
            d = date(y, m, day)
            if start <= d <= end:
                by_day[d] = by_day.get(d, 0.0) + amt
    if start <= PREVIOUS_PAYDAY <= end:
        by_day[PREVIOUS_PAYDAY] = by_day.get(PREVIOUS_PAYDAY, 0.0) + bf.PAY
    return by_day


def history(daily: float) -> list[dict[str, float | str]]:
    anchor_day = date.fromisoformat("2026-10-11")
    first = PREVIOUS_PAYDAY
    events = past_events(first, anchor_day)
    rng = random.Random(311)
    days = (anchor_day - first).days + 1
    spend = {first + timedelta(days=i): max(0.0, rng.gauss(daily, 14.0)) for i in range(days)}
    # Walk backwards from the anchor: balance(d - 1) = balance(d) + spend(d) - events(d).
    bal, out, d = bf.START_BALANCE, [], anchor_day
    while d >= first:
        out.append({"date": d.isoformat(), "balance": round(bal, 2)})
        if d == first:
            break
        bal = bal + spend[d] - events.get(d, 0.0)
        d -= timedelta(days=1)
    return list(reversed(out))


def weekly_paths(daily, ev, daily_saving_to_payday=0.0, paths=500, sd=14.0, seed=1729):
    """Balance quantiles on today and every 7th day to END, from seeded paths."""
    rng = random.Random(seed)
    by_day: dict[date, float] = {}
    for ed, amt, *_ in ev:
        by_day[ed] = by_day.get(ed, 0.0) + amt
    sample_days = []
    d = bf.TODAY
    while d <= bf.END:
        sample_days.append(d)
        d += timedelta(days=7)
    if sample_days[-1] != bf.END:
        sample_days.append(bf.END)
    samples: dict[date, list[float]] = {s: [] for s in sample_days}
    for _ in range(paths):
        bal, d = bf.START_BALANCE, bf.TODAY
        while d <= bf.END:
            if d > bf.TODAY:
                bal -= max(0.0, rng.gauss(daily, sd))
                if d <= date(2026, 10, 27):
                    bal += daily_saving_to_payday
            bal += by_day.get(d, 0.0)
            if d in samples:
                samples[d].append(bal)
            d += timedelta(days=1)

    def q(values: list[float], p: float) -> float:
        values = sorted(values)
        return round(values[int(p * (len(values) - 1))], 2)

    return [{"date": s.isoformat(), "p50": q(v, 0.5), "p10": q(v, 0.1), "p90": q(v, 0.9)}
            for s, v in samples.items()]


def main() -> None:
    data = json.loads(FIXTURE.read_text())
    daily = data["daily_spend_model"]
    plan_daily = (data["delivery_pace_to_payday"] - 100.0) / 15
    car = [(date(2026, 10, 14), -650.0, "Car repair", "Transport")]
    hol = car + [(date(2026, 11, 28), -1200.0, "Holiday", "Travel")]
    data["history"] = history(daily)
    data["weekly"] = {
        "current": weekly_paths(daily, bf.events(car)),
        "plan": weekly_paths(daily, bf.events(car, defer_oct_savings=True), plan_daily),
        "holiday_1200_28nov": weekly_paths(daily, bf.events(hol, defer_oct_savings=True), plan_daily),
    }
    FIXTURE.write_text(json.dumps(data, indent=1))
    h = data["history"]
    print("history", h[0], "...", h[-1])
    for k, v in data["weekly"].items():
        print(k, len(v), v[0], v[-1])


if __name__ == "__main__":
    main()
