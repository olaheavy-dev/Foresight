"""Add per-pay-cycle lows and holiday what-if variants to fixture.json, using the SAME model.

Run after build_fixture.py:  python3 design/fixture/build_fixture.py && python3 design/fixture/extend_fixture.py
Adds:
  cycles   - for each scenario, the lowest balance before each payday (P50 from the deterministic
             path, P10/P90 and chance below the buffer from the seeded 500-path simulation)
  what_if  - holiday variants (£800 / £1,200 / £1,500 paid 28 Nov; £1,200 paid 6 Nov; none)
  end_of_march - end-of-March balance for every scenario
Fictional data, design aid only.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import build_fixture as bf

FIXTURE = Path(__file__).with_name("fixture.json")


def windows():
    """Pay cycles: today .. day before each payday."""
    out, start = [], bf.TODAY
    for pay in bf.PAYDAYS:
        out.append((start, pay - timedelta(days=1)))
        start = pay
    return out


def main() -> None:
    data = json.loads(FIXTURE.read_text())
    daily = data["daily_spend_model"]
    pace = data["delivery_pace_to_payday"]
    plan_daily = (pace - 100.0) / 15
    car = [(date(2026, 10, 14), -650.0, "Car repair · KwikFit Leeds", "Transport")]

    def holiday(amount: float, when: date):
        return car + [(when, -amount, f"Holiday · booked {when:%-d %b}", "Travel")]

    scenarios = {
        # name: (extra events, defer October savings, daily saving to payday)
        "current": (car, False, 0.0),
        "plan": (car, True, plan_daily),
        "holiday_800_28nov": (holiday(800, date(2026, 11, 28)), True, plan_daily),
        "holiday_1200_28nov": (holiday(1200, date(2026, 11, 28)), True, plan_daily),
        "holiday_1500_28nov": (holiday(1500, date(2026, 11, 28)), True, plan_daily),
        "holiday_1200_6nov": (holiday(1200, date(2026, 11, 6)), True, plan_daily),
    }

    cycles, end_of_march = {}, {}
    for name, (extra, defer, saving) in scenarios.items():
        ev = bf.events(extra, defer_oct_savings=defer)
        series = bf.simulate(daily, ev, saving)
        rows = []
        for a, b in windows():
            d, v = bf.low(series, a, b)
            mc = bf.monte_carlo(daily, ev, (a, b), saving)
            rows.append({
                # "low" is the median of the 500 simulated lowest balances (same statistic as
                # fixture["uncertainty"]); the date comes from the expected path.
                "cycle_end": b.isoformat(), "low_date": d.isoformat(), "low": mc["low_p50"],
                "p10": mc["low_p10"], "p90": mc["low_p90"],
                "chance_below_buffer_pct": mc["chance_below_buffer_pct"],
            })
        cycles[name] = rows
        end_of_march[name] = series[bf.END]

    def overall(name: str):
        r = min(cycles[name], key=lambda r: r["low"])
        return {"lowest": r["low"], "date": r["low_date"],
                "vs_buffer": round(r["low"] - bf.BUFFER, 2),
                "chance_below_buffer_pct": max(x["chance_below_buffer_pct"] for x in cycles[name]),
                "end_of_march": end_of_march[name]}

    # The pay cycle each option is judged on: the cycle in which the holiday is paid.
    def judged(name: str, cycle_end: str):
        r = next(r for r in cycles[name] if r["cycle_end"] == cycle_end)
        return {"lowest": r["low"], "date": r["low_date"], "p10": r["p10"], "p90": r["p90"],
                "vs_buffer": round(r["low"] - bf.BUFFER, 2),
                "chance_below_buffer_pct": r["chance_below_buffer_pct"],
                "end_of_march": end_of_march[name]}

    data["cycles"] = cycles
    data["end_of_march_all"] = end_of_march
    data["what_if"] = {
        "no_holiday_dec": judged("plan", "2026-12-17"),
        "no_holiday_nov": judged("plan", "2026-11-26"),
        "800_after_payday": judged("holiday_800_28nov", "2026-12-17"),
        "1200_after_payday": judged("holiday_1200_28nov", "2026-12-17"),
        "1500_after_payday": judged("holiday_1500_28nov", "2026-12-17"),
        "1200_on_6nov": judged("holiday_1200_6nov", "2026-11-26"),
    }
    data["overall"] = {k: overall(k) for k in scenarios}
    FIXTURE.write_text(json.dumps(data, indent=1))
    print(json.dumps({"what_if": data["what_if"], "end_of_march": end_of_march}, indent=1))
    for name, rows in cycles.items():
        print(name, [(r["low_date"], r["low"], r["p10"], r["p90"], r["chance_below_buffer_pct"]) for r in rows])


if __name__ == "__main__":
    main()
