"""Add a deterministic food-delivery breakdown to fixture.json (design aid; fictional).

Builds individual delivery orders for the last 90 days so that:
- the last 30 days (12 Sep - 11 Oct 2026) total exactly £286.40 across exactly 23 orders,
- the three 30-day windows have a median of exactly £203.10 (the "usual" month),
and derives the merchant split, the weekly trend and a short recent-orders list from those
orders. Nothing here is typed by hand into the screens: export_js.py ships it to data.js.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
TODAY = date(2026, 10, 12)
MERCHANTS = ["Deliveroo", "Uber Eats", "Just Eat"]
MERCHANT_WEIGHTS = [0.48, 0.34, 0.18]

# Three 30-day windows, newest first: (start, end inclusive, total £, orders).
WINDOWS = [
    (date(2026, 9, 12), date(2026, 10, 11), 286.40, 23),  # last 30 days
    (date(2026, 8, 13), date(2026, 9, 11), 203.10, 16),   # median window
    (date(2026, 7, 14), date(2026, 8, 12), 188.65, 15),
]


def pennies_split(total_p: int, n: int, rng: random.Random) -> list[int]:
    """Split total pennies into n order values in a realistic £7-£22 range, summing exactly."""
    while True:
        raw = [rng.uniform(7.0, 22.0) for _ in range(n)]
        scale = total_p / sum(raw)
        vals = [max(500, round(r * scale)) for r in raw]
        vals[-1] += total_p - sum(vals)
        if all(500 <= v <= 3000 for v in vals):
            return vals


def build() -> dict:
    rng = random.Random(1729)
    orders = []
    for start, end, total, n in WINDOWS:
        span = (end - start).days + 1
        # A gentle rise through the latest window (the change being flagged); earlier windows are
        # even. At most two orders on any one day.
        alpha = 1.35 if total > 250 else 1.0
        while True:
            days = sorted(
                start + timedelta(days=min(span - 1, int(rng.betavariate(alpha, 1.0) * span))) for _ in range(n)
            )
            if max(days.count(d) for d in days) <= 2:
                break
        values = pennies_split(round(total * 100), n, rng)
        for d, v in zip(days, values):
            merchant = rng.choices(MERCHANTS, MERCHANT_WEIGHTS)[0]
            orders.append({"date": d.isoformat(), "merchant": merchant, "amount": v / 100})
    orders.sort(key=lambda o: o["date"])

    def window_total(start: date, end: date) -> tuple[float, int]:
        sel = [o for o in orders if start.isoformat() <= o["date"] <= end.isoformat()]
        return round(sum(o["amount"] for o in sel), 2), len(sel)

    windows = []
    for start, end, *_ in WINDOWS:
        t, c = window_total(start, end)
        windows.append({"start": start.isoformat(), "end": end.isoformat(), "total": t, "orders": c})
    assert windows[0]["total"] == 286.40 and windows[0]["orders"] == 23, windows[0]
    totals = sorted(w["total"] for w in windows)
    assert totals[1] == 203.10, totals

    last30 = [o for o in orders if o["date"] >= WINDOWS[0][0].isoformat()]
    merchants = []
    for m in MERCHANTS:
        sel = [o for o in last30 if o["merchant"] == m]
        merchants.append({"name": m, "orders": len(sel), "amount": round(sum(o["amount"] for o in sel), 2)})
    merchants.sort(key=lambda r: -r["amount"])
    assert round(sum(r["amount"] for r in merchants), 2) == 286.40
    assert sum(r["orders"] for r in merchants) == 23

    # Weekly totals: 13 Monday-start weeks ending with the week that contains 11 Oct.
    last_monday = date(2026, 10, 5)
    weekly = []
    for i in range(12, -1, -1):
        ws = last_monday - timedelta(weeks=i)
        we = ws + timedelta(days=6)
        sel = [o for o in orders if ws.isoformat() <= o["date"] <= min(we, date(2026, 10, 11)).isoformat()]
        weekly.append({
            "week_start": ws.isoformat(),
            "amount": round(sum(o["amount"] for o in sel), 2),
            "orders": len(sel),
            "partial": we > date(2026, 10, 11),
        })

    usual_week = round(203.10 / (30 / 7), 2)  # the usual 30-day total spread over a week
    recent = [o for o in reversed(orders) if o["date"] <= "2026-10-11"][:6]
    return {
        "last_30_days": {"start": WINDOWS[0][0].isoformat(), "end": WINDOWS[0][1].isoformat(), "total": 286.40, "orders": 23},
        "usual_30_days": 203.10,
        "change_pct": round((286.40 / 203.10 - 1) * 100),
        "windows": windows,
        "merchants": merchants,
        "weekly": weekly,
        "usual_week": usual_week,
        "recent": recent,
        "average_order_last_30": round(286.40 / 23, 2),
    }


def main() -> None:
    path = HERE / "fixture.json"
    fixture = json.loads(path.read_text())
    fixture["food_delivery"] = build()
    path.write_text(json.dumps(fixture, indent=1))
    fd = fixture["food_delivery"]
    print(json.dumps({k: v for k, v in fd.items() if k not in ("weekly",)}, indent=1))
    print("weekly:", [(w["week_start"], w["amount"], w["orders"]) for w in fd["weekly"]])


if __name__ == "__main__":
    main()
