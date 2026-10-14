"""Salaried UK persona builder (P1 Amara Nwosu and the single-account S-variants).

One current account; salary by Bacs; rent by standing order; bills by direct debit; card
subscriptions; a monthly savings-pot transfer; family support abroad (a commitment); and a
discretionary layer with food delivery controlled exactly over the last four 30-day windows so the
food-delivery finding is known in advance (docs/00 §10a).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

import numpy as np

from evals.generator.model import (
    Streams,
    Txn,
    daterange,
    lognormal_pounds,
    rand_time,
    scale_to_total,
    slug,
    sort_and_number,
)
from evals.generator.ukcalendar import (
    collection_date,
    fixed_day_payday,
    four_weekly_paydays,
    months_between,
)

END = date(2026, 10, 11)  # last data day (Sun); "today" is Mon 12 Oct 2026


@dataclass(frozen=True)
class Bill:
    key: str
    label: str
    name: str
    desc: str
    code: str  # DD | SO | DEB
    category: str
    amount: int  # positive magnitude, minor units
    day: int
    flow: str = "spending"
    monzo_cat: str = "Bills"
    active_months: tuple[int, ...] = tuple(range(1, 13))
    price_change: tuple[date, int] | None = None  # (from date, new amount)
    commitment: bool = False


P1_BILLS: tuple[Bill, ...] = (
    Bill(
        "rob_rent",
        "Rent",
        "Northside Lettings",
        "NORTHSIDE LETTINGS RENT",
        "SO",
        "housing.rent",
        125000,
        1,
    ),
    Bill(
        "rob_council_tax",
        "Council tax",
        "Leeds City Council",
        "LEEDS CITY COUNCIL",
        "DD",
        "housing.council_tax",
        16200,
        15,
        active_months=(4, 5, 6, 7, 8, 9, 10, 11, 12, 1),
    ),
    Bill(
        "rob_water", "Water", "Yorkshire Water", "YORKSHIRE WATER", "DD", "utilities.water", 4200, 5
    ),
    Bill(
        "rob_broadband",
        "Broadband",
        "Plusnet",
        "PLUSNET PLC",
        "DD",
        "utilities.broadband_tv",
        3100,
        9,
    ),
    Bill("rob_sky", "Sky TV", "Sky", "SKY DIGITAL", "DD", "utilities.broadband_tv", 4600, 12),
    Bill(
        "rob_energy",
        "Energy",
        "Octopus Energy",
        "OCTOPUS ENERGY",
        "DD",
        "utilities.energy",
        7800,
        20,
    ),
    Bill(
        "rob_gym",
        "PureGym",
        "PureGym",
        "PUREGYM",
        "DEB",
        "subscriptions.fitness",
        2799,
        1,
        monzo_cat="Personal care",
    ),
    Bill(
        "rob_netflix",
        "Netflix",
        "Netflix",
        "NETFLIX.COM",
        "DEB",
        "subscriptions.streaming",
        1299,
        17,
        monzo_cat="Entertainment",
    ),
    Bill(
        "rob_spotify",
        "Spotify",
        "Spotify",
        "SPOTIFY",
        "DEB",
        "subscriptions.streaming",
        1199,
        22,
        monzo_cat="Entertainment",
    ),
    Bill(
        "rob_now",
        "NOW",
        "NOW",
        "NOWTV.COM",
        "DEB",
        "subscriptions.streaming",
        999,
        3,
        monzo_cat="Entertainment",
    ),
    Bill(
        "rob_disney",
        "Disney+",
        "Disney+",
        "DISNEYPLUS",
        "DEB",
        "subscriptions.streaming",
        899,
        8,
        monzo_cat="Entertainment",
    ),
    Bill(
        "rob_prime",
        "Amazon Prime",
        "Amazon Prime",
        "AMAZON PRIME*",
        "DEB",
        "subscriptions.streaming",
        899,
        26,
        monzo_cat="Shopping",
    ),
    Bill(
        "rob_icloud",
        "iCloud+",
        "Apple",
        "APPLE.COM/BILL",
        "DEB",
        "subscriptions.software_cloud",
        299,
        2,
        monzo_cat="Bills",
    ),
    Bill(
        "rob_savings",
        "Savings pot",
        "Savings",
        "Savings",
        "POT",
        "savings_investment",
        40000,
        15,
        flow="savings_investment",
        monzo_cat="Savings",
    ),
)

SPOTIFY_RISE = (date(2026, 6, 22), 1299)


@dataclass(frozen=True)
class Disc:
    category: str
    rate: float  # expected transactions per day
    median: float  # £
    sigma: float
    merchants: tuple[tuple[str, str, float], ...]  # (name, descriptor template, weight)
    monzo_cat: str
    weekend_boost: float = 1.0
    payday_boost: float = 1.0
    hours: tuple[float, ...] | None = None


EVENING = tuple([0.2] * 7 + [0.5, 1, 1, 1, 1, 1.5, 1.5, 1, 1, 1, 1.2, 2, 2.5, 2, 1.5, 0.8, 0.4])
DAYTIME = tuple(
    [0.05] * 7 + [1, 1.5, 1.5, 1.5, 2, 2.5, 2, 1.5, 1.5, 1.5, 1.5, 1.2, 0.8, 0.5, 0.3, 0.1, 0.05]
)

DISCRETIONARY: tuple[Disc, ...] = (
    Disc(
        "groceries",
        0.55,
        26.0,
        0.6,
        (
            ("Tesco", "TESCO STORES {n} LEEDS", 4),
            ("Sainsbury's", "SAINSBURYS S/MKT {n}", 3),
            ("Aldi", "ALDI {n} LEEDS", 2),
            ("Lidl", "LIDL GB LEEDS", 2),
            ("Co-op", "CO-OP GROUP {n}", 1),
        ),
        "Groceries",
        weekend_boost=1.4,
        hours=DAYTIME,
    ),
    Disc(
        "food.eating_out",
        0.40,
        11.0,
        0.6,
        (
            ("Pret A Manger", "PRET A MANGER {n}", 3),
            ("Costa Coffee", "COSTA COFFEE {n}", 3),
            ("Nando's", "NANDOS LEEDS", 1),
            ("Wagamama", "WAGAMAMA {n}", 1),
            ("The Brewery Tap", "BREWERY TAP LEEDS", 1),
        ),
        "Eating out",
        weekend_boost=1.5,
        payday_boost=1.3,
        hours=DAYTIME,
    ),
    Disc(
        "transport.public",
        0.30,
        5.5,
        0.5,
        (
            ("Northern", "NORTHERN TRAINS", 2),
            ("First Bus", "FIRST WEST YORKSHIRE", 2),
        ),
        "Transport",
        weekend_boost=0.6,
        hours=DAYTIME,
    ),
    Disc(
        "transport.taxi",
        0.06,
        13.0,
        0.4,
        (("Uber", "UBER *TRIP", 3), ("Bolt", "BOLT.EU", 1)),
        "Transport",
        weekend_boost=1.6,
        hours=EVENING,
    ),
    Disc(
        "shopping.general",
        0.20,
        24.0,
        0.8,
        (
            ("Amazon", "AMAZON.CO.UK*{c}", 4),
            ("Boots", "BOOTS {n} LEEDS", 1),
            ("John Lewis", "JOHN LEWIS {n}", 1),
            ("Wilko", "WILKO {n}", 1),
        ),
        "Shopping",
        payday_boost=1.3,
    ),
    Disc(
        "shopping.clothing",
        0.05,
        38.0,
        0.6,
        (
            ("Primark", "PRIMARK LEEDS", 2),
            ("ASOS", "ASOS.COM", 2),
            ("Uniqlo", "UNIQLO LEEDS", 1),
        ),
        "Shopping",
        weekend_boost=1.5,
        payday_boost=1.5,
    ),
    Disc(
        "entertainment",
        0.05,
        18.0,
        0.5,
        (
            ("Vue Cinemas", "VUE BSL LTD", 2),
            ("Ticketmaster", "TICKETMASTER UK", 1),
        ),
        "Entertainment",
        weekend_boost=2.0,
        hours=EVENING,
    ),
    Disc(
        "health", 0.03, 11.0, 0.5, (("Boots Pharmacy", "BOOTS PHARMACY {n}", 1),), "Personal care"
    ),
    Disc(
        "personal_care",
        0.03,
        24.0,
        0.4,
        (("Toni & Guy", "TONI AND GUY LEEDS", 1),),
        "Personal care",
        weekend_boost=1.4,
    ),
    Disc("cash.withdrawal", 0.025, 40.0, 0.3, (("ATM", "CASH LEEDS STATION", 1),), "Cash"),
)

FOOD_APPS = (
    ("Deliveroo", "DELIVEROO", 0.45),
    ("Uber Eats", "UBER *EATS", 0.40),
    ("Just Eat", "JUST EAT.CO.UK", 0.15),
)
# Canonical last-30-day split (docs/00 §10a): app → (orders, total minor)
FOOD_W0 = {"Deliveroo": (11, 13637), "Uber Eats": (9, 10901), "Just Eat": (3, 4102)}
FOOD_PRIOR = ((15, 19870), (16, 20310), (16, 21140))  # W1, W2, W3 → median £203.10


@dataclass
class SalariedConfig:
    key: str
    start: date
    end: date = END
    closing_minor: int = 218450  # Monzo has no balance: the user declares today's balance
    target_opening_minor: int = 150000
    min_balance_minor: int = 15000  # calibration floor for the lowest end-of-row balance
    disc_scale: float | None = None  # fixed discretionary scale (skips calibration)
    steady: float | None = None  # steady_months(max_dev) on discretionary spend (P1 twins)
    closing_free: bool = False  # with disc_scale: fix the opening, let the closing follow
    stream_key: str | None = None  # share random streams with another dataset
    salary_minor: int = 405000
    pay_mode: str = "fixed"  # fixed | fourweekly | untracked | split
    four_weekly_minor: int = 373800
    bills: tuple[Bill, ...] = P1_BILLS
    family_support: bool = True
    food_anomaly: bool = True
    spotify_rise: bool = True
    netflix: bool = True
    one_offs: bool = True
    refunds: bool = True
    settle_up: str = "light"  # light | heavy | none
    unconfirmed_inflows: bool = False
    card_checks: bool = True
    known_car_repair: bool = True
    bonus_and_arrears: bool = False
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class PersonaOutput:
    txns: list[Txn]
    opening_minor: int
    income_streams: list[dict[str, Any]]
    recurring: list[dict[str, Any]]
    anomalies: list[dict[str, Any]]
    known_flows: list[dict[str, Any]]
    second_account: list[Txn] = field(default_factory=list)
    disc_scale: float = 1.0


def _txn(
    day: date,
    time: str,
    amount: int,
    name: str,
    desc: str,
    code: str,
    monzo_type: str,
    monzo_cat: str,
    category: str | None,
    flow: str | None,
    **kw: Any,
) -> Txn:
    return Txn(
        day=day,
        time=time,
        amount=amount,
        name=name,
        desc=desc,
        code=code,
        monzo_type=monzo_type,
        monzo_cat=monzo_cat,
        category=category,
        flow=flow,
        **kw,
    )


MONZO_TYPE = {
    "DD": "Direct Debit",
    "SO": "Faster payment",
    "DEB": "Card payment",
    "POT": "Pot transfer",
    "BGC": "Bacs (Direct Credit)",
    "FPI": "Faster payment",
    "FPO": "Faster payment",
}


def _fill(rng: np.random.Generator, template: str) -> str:
    return template.replace("{n}", f"{int(rng.integers(1000, 9999))}").replace(
        "{c}", "".join(rng.choice(list("ABCDEFGHJKLMNPQRSTUVWXYZ23456789"), 6))
    )


def _bills(cfg: SalariedConfig, s: Streams) -> tuple[list[Txn], list[dict[str, Any]]]:
    rng = s["fixed"]
    out: list[Txn] = []
    truth: list[dict[str, Any]] = []
    for b in cfg.bills:
        if b.key == "rob_netflix" and not cfg.netflix:
            continue
        price_change = b.price_change
        if b.key == "rob_spotify" and cfg.spotify_rise:
            price_change = SPOTIFY_RISE
        for y, m in months_between(cfg.start, cfg.end):
            if m not in b.active_months:
                continue
            d = date(y, m, b.day) if b.code in ("DEB", "POT") else collection_date(y, m, b.day)
            if not (cfg.start <= d <= cfg.end):
                continue
            amount = b.amount
            if price_change and d >= price_change[0]:
                amount = price_change[1]
            hour = "06" if b.code in ("DD", "SO", "POT") else "0" + str(int(rng.integers(1, 8)))
            out.append(
                _txn(
                    d,
                    f"{hour}:{int(rng.integers(0, 60)):02d}:{int(rng.integers(0, 60)):02d}",
                    -amount,
                    b.name,
                    b.desc,
                    "DEB" if b.code == "POT" else b.code,
                    MONZO_TYPE[b.code],
                    b.monzo_cat,
                    b.category,
                    b.flow,
                    recurring=b.key,
                    cpty=f"cpty_{b.key[4:]}",
                )
            )
        truth.append(
            {
                "key": b.key,
                "label": b.label,
                "counterparty": b.name,
                "category": b.category,
                "flow": b.flow,
                "amount_minor": -b.amount,
                "cadence": "monthly",
                "anchor_day": b.day,
                "day_rule": "calendar_day" if b.code in ("DEB", "POT") else "next_working_day",
                "active_months": list(b.active_months),
                "price_changes": [
                    {"from": price_change[0].isoformat(), "amount_minor": -price_change[1]}
                ]
                if price_change
                else [],
                "is_commitment": False,
            }
        )
    if cfg.family_support:
        for y, m in months_between(cfg.start, cfg.end):
            d = date(y, m, int(rng.integers(14, 17)))
            if not (cfg.start <= d <= cfg.end):
                continue
            amt = int(rng.integers(46, 55)) * 500  # £230–£270 in £5 steps
            out.append(
                _txn(
                    d,
                    rand_time(rng),
                    -amt,
                    "LemFi",
                    "LEMFI LONDON",
                    "DEB",
                    "Card payment",
                    "General",
                    "family_support_abroad",
                    "commitment",
                    recurring="rob_family_support",
                    cpty="cpty_lemfi",
                )
            )
        truth.append(
            {
                "key": "rob_family_support",
                "label": "Family support abroad",
                "counterparty": "LemFi",
                "category": "family_support_abroad",
                "flow": "commitment",
                "amount_minor": -25000,
                "cadence": "monthly",
                "anchor_day": 15,
                "day_rule": "jitter_14_16",
                "active_months": list(range(1, 13)),
                "price_changes": [],
                "is_commitment": True,
            }
        )
    return out, truth


def _income(cfg: SalariedConfig, s: Streams) -> tuple[list[Txn], list[Txn], list[dict[str, Any]]]:
    main: list[Txn] = []
    second: list[Txn] = []
    rng = s["fixed"]
    streams: list[dict[str, Any]] = []
    if cfg.pay_mode == "fourweekly":
        days = four_weekly_paydays(date(2025, 10, 24), cfg.start, cfg.end)
        amount = cfg.four_weekly_minor
        rule = {"kind": "four_weekly", "anchor_date": "2025-10-24", "prev_working_day": True}
    else:
        days = [fixed_day_payday(y, m, 28, 18) for y, m in months_between(cfg.start, cfg.end)]
        days = [d for d in days if cfg.start <= d <= cfg.end]
        amount = cfg.salary_minor
        rule = {
            "kind": "fixed_day",
            "day_of_month": 28,
            "prev_working_day": True,
            "december_day": 18,
        }
    for d in days:
        t = f"06:{int(rng.integers(0, 60)):02d}:{int(rng.integers(0, 60)):02d}"
        if cfg.pay_mode == "untracked":
            top = d + timedelta(days=1)
            if top <= cfg.end:
                main.append(
                    _txn(
                        top,
                        t,
                        380000,
                        "Amara Nwosu",
                        "AMARA NWOSU",
                        "FPI",
                        "Faster payment",
                        "Transfers",
                        "transfer.from_untracked",
                        "transfer_from_untracked",
                        cpty="cpty_self",
                    )
                )
            continue
        if cfg.pay_mode == "split":
            part2 = round(amount * 0.3)
            main.append(
                _txn(
                    d,
                    t,
                    amount - part2,
                    "Acme Analytics Ltd",
                    "ACME ANALYTICS LTD SALARY",
                    "BGC",
                    "Bacs (Direct Credit)",
                    "Income",
                    "income.salary",
                    "income",
                    income="inc_salary",
                    cpty="cpty_acme",
                )
            )
            second.append(
                _txn(
                    d,
                    t,
                    part2,
                    "Acme Analytics Ltd",
                    "ACME ANALYTICS LTD SAL PT2",
                    "BGC",
                    "",
                    "",
                    "income.salary",
                    "income",
                    income="inc_salary",
                    cpty="cpty_acme",
                    account="acct_second",
                )
            )
            continue
        main.append(
            _txn(
                d,
                t,
                amount,
                "Acme Analytics Ltd",
                "ACME ANALYTICS LTD SALARY",
                "BGC",
                "Bacs (Direct Credit)",
                "Income",
                "income.salary",
                "income",
                income="inc_salary",
                cpty="cpty_acme",
            )
        )
    streams.append(
        {
            "key": "inc_salary",
            "source": "Acme Analytics Ltd",
            "account": "untracked" if cfg.pay_mode == "untracked" else "acct_main",
            "net_amount_minor": amount,
            "cadence": "four_weekly" if cfg.pay_mode == "fourweekly" else "monthly",
            "payday_rule": rule,
            "split_pct": {"acct_main": 70, "acct_second": 30} if cfg.pay_mode == "split" else None,
            "provenance_expected": "declared" if cfg.pay_mode == "untracked" else "detected",
            "paydays": [d.isoformat() for d in days],
        }
    )
    if cfg.bonus_and_arrears:
        for d, amt, desc, key in (
            (date(2026, 7, 28), 150000, "ACME ANALYTICS LTD BONUS", "bonus"),
            (date(2026, 5, 28), 22000, "ACME ANALYTICS ARREARS", "arrears"),
        ):
            if cfg.start <= d <= cfg.end:
                main.append(
                    _txn(
                        d,
                        "06:20:00",
                        amt,
                        "Acme Analytics Ltd",
                        desc,
                        "BGC",
                        "Bacs (Direct Credit)",
                        "Income",
                        "income.salary",
                        "income",
                        income=f"inc_salary_{key}",
                        cpty="cpty_acme",
                        one_off=True,
                    )
                )
                streams.append(
                    {
                        "key": f"inc_salary_{key}",
                        "source": "Acme Analytics Ltd",
                        "account": "acct_main",
                        "net_amount_minor": amt,
                        "cadence": "one_off",
                        "date": d.isoformat(),
                    }
                )
    return main, second, streams


def _food(cfg: SalariedConfig, s: Streams) -> tuple[list[Txn], dict[str, Any]]:
    rng = s["food"]
    out: list[Txn] = []
    e = cfg.end
    windows = [(e - timedelta(days=29 + 30 * k), e - timedelta(days=30 * k)) for k in range(4)]
    # Only windows that fit entirely inside the history are controlled; earlier days are natural.
    controlled = [k for k in range(4) if windows[k][0] >= cfg.start]
    natural_end = windows[max(controlled)][0] if controlled else e + timedelta(days=1)

    def order(d: date, app: tuple[str, str, float], amount_minor: int) -> Txn:
        hour_w = [0.1] * 11 + [0.6, 1.2, 0.8, 0.3, 0.3, 0.4, 0.8, 1.5, 2, 2.2, 3, 2.6, 1.4]
        return _txn(
            d,
            rand_time(rng, hour_w),
            -amount_minor,
            app[0],
            app[1],
            "DEB",
            "Card payment",
            "Eating out",
            "food.delivery",
            "spending",
            cpty=slug(app[0]),
        )

    for d in daterange(cfg.start, natural_end - timedelta(days=1)):
        for _ in range(int(rng.poisson(16 / 30))):
            app = FOOD_APPS[int(rng.choice(3, p=[a[2] for a in FOOD_APPS]))]
            out.append(order(d, app, round(lognormal_pounds(rng, 12.5, 0.35, 6.0) * 100)))
    totals: dict[str, int] = {}
    prior = FOOD_PRIOR
    for k in sorted(controlled, reverse=True):
        lo, hi = windows[k]
        days = daterange(lo, hi)
        if k == 0 and cfg.food_anomaly:
            for app in FOOD_APPS:
                n, total = FOOD_W0[app[0]]
                raw = [lognormal_pounds(rng, 12.5, 0.35, 6.0) for _ in range(n)]
                picks = sorted(int(x) for x in rng.choice(len(days), size=n))
                for idx, amt in zip(picks, scale_to_total(raw, total), strict=True):
                    out.append(
                        replace(order(days[int(idx)], app, amt), anomaly="food_delivery_spike")
                    )
            totals["w0"] = sum(v[1] for v in FOOD_W0.values())
            continue
        n, total = prior[k - 1] if k > 0 else (16, 20490)
        apps = [FOOD_APPS[int(rng.choice(3, p=[a[2] for a in FOOD_APPS]))] for _ in range(n)]
        raw = [lognormal_pounds(rng, 12.5, 0.35, 6.0) for _ in range(n)]
        picks = sorted(int(x) for x in rng.choice(len(days), size=n))
        for idx, app, amt in zip(picks, apps, scale_to_total(raw, total), strict=True):
            out.append(order(days[int(idx)], app, amt))
        totals[f"w{k}"] = total
    finding = {
        "window_last_30": [windows[0][0].isoformat(), windows[0][1].isoformat()],
        "last_30_total_minor": totals.get("w0"),
        "prior_window_totals_minor": [totals.get("w1"), totals.get("w2"), totals.get("w3")],
        "orders_last_30": 23 if cfg.food_anomaly else 16,
    }
    return out, finding


STEADY_WINDOW_DAYS = 30


def steady_months(
    base: list[tuple[Txn, float]], end: date, max_dev: float
) -> list[tuple[Txn, float]]:
    """Scale each category's amounts window by window (30-day windows ending at `end`) so every
    full window's total lies within ±max_dev of that category's median window total. A clean
    persona then holds no chance month far from its usual spending, so any category spike in it
    is a detector false positive, and the base twin's only spikes are the injected ones
    (gen-1.1.0, owner-approved 14 Oct 2026). Counts and dates are unchanged."""
    windows: dict[tuple[str, int], float] = {}
    first = min((t.day for t, _a in base), default=end)
    full = ((end - first).days + 1) // STEADY_WINDOW_DAYS
    for t, a in base:
        k = (end - t.day).days // STEADY_WINDOW_DAYS
        if k < full:
            windows[(t.category or "", k)] = windows.get((t.category or "", k), 0.0) + a
    factor: dict[tuple[str, int], float] = {}
    for cat in {c for c, _k in windows}:
        totals = sorted(v for (c, _k), v in windows.items() if c == cat)
        if len(totals) < 3:
            continue
        mid = len(totals) // 2
        median = totals[mid] if len(totals) % 2 else (totals[mid - 1] + totals[mid]) / 2
        lo, hi = median * (1 - max_dev), median * (1 + max_dev)
        for k in range(full):
            total = windows.get((cat, k), 0.0)
            if total and not lo <= total <= hi:
                factor[(cat, k)] = min(max(total, lo), hi) / total
    out = []
    for t, a in base:
        k = (end - t.day).days // STEADY_WINDOW_DAYS
        out.append((t, a * factor.get((t.category or "", k), 1.0)))
    return out


def discretionary_base(
    s: Streams, start: date, end: date, paydays: list[date], city: str = "LEEDS"
) -> list[tuple[Txn, float]]:
    """Unscaled discretionary card spending: (row with amount 0, amount in £) pairs."""
    rng = s["discretionary"]
    nar = s["narration"]
    base: list[tuple[Txn, float]] = []
    for d in daterange(start, end):
        since_pay = min(((d - p).days for p in paydays if p <= d), default=99)
        weekend = d.weekday() >= 5
        for spec in DISCRETIONARY:
            lam = spec.rate * (spec.weekend_boost if weekend else 1.0)
            lam *= spec.payday_boost if since_pay <= 3 else 1.0
            for _ in range(int(rng.poisson(lam))):
                w = np.asarray([m[2] for m in spec.merchants], dtype=float)
                name, tmpl, _ = spec.merchants[int(rng.choice(len(w), p=w / w.sum()))]
                amount = lognormal_pounds(rng, spec.median, spec.sigma, 1.0)
                t = _txn(
                    d,
                    rand_time(rng, list(spec.hours) if spec.hours else None),
                    0,
                    name,
                    _fill(nar, tmpl).replace("LEEDS", city),
                    "CPT" if spec.category == "cash.withdrawal" else "DEB",
                    "Card payment",
                    spec.monzo_cat,
                    spec.category,
                    "spending",
                    cpty=slug(name),
                )
                base.append((t, amount))
    return base


def _extras(cfg: SalariedConfig, s: Streams) -> tuple[list[Txn], list[dict[str, Any]]]:
    rng = s["extra"]
    out: list[Txn] = []
    anomalies: list[dict[str, Any]] = []

    def inside(d: date) -> bool:
        return cfg.start <= d <= cfg.end

    if cfg.one_offs:
        for d, amt, name, desc, cat in (
            (date(2026, 2, 9), 41000, "Admiral", "ADMIRAL INSURANCE", "insurance"),
            (date(2026, 3, 14), 89900, "Currys", "CURRYS PC WORLD LEEDS", "shopping.general"),
            (date(2026, 7, 3), 34000, "Ryanair", "RYANAIR", "travel"),
            (date(2026, 7, 5), 61000, "Booking.com", "BOOKING.COM HOTEL", "travel"),
        ):
            if inside(d):
                out.append(
                    _txn(
                        d,
                        rand_time(rng),
                        -amt,
                        name,
                        desc,
                        "DEB",
                        "Card payment",
                        "Holidays" if cat == "travel" else "Shopping",
                        cat,
                        "spending",
                        one_off=True,
                        cpty=slug(name),
                    )
                )
    if cfg.refunds:
        for d, amt in (
            (date(2025, 11, 20), 2399),
            (date(2026, 1, 9), 4500),
            (date(2026, 4, 16), 1799),
            (date(2026, 8, 27), 3250),
        ):
            if inside(d):
                out.append(
                    _txn(
                        d,
                        rand_time(rng),
                        amt,
                        "Amazon",
                        "AMAZON.CO.UK REFUND",
                        "DEB",
                        "Card payment",
                        "Shopping",
                        "refund",
                        "refund",
                        cpty="cpty_amazon",
                    )
                )
    people = (("Jo Reid", "J REID"), ("Kemi Bello", "K BELLO"), ("Sam Lee", "S LEE"))
    if cfg.settle_up != "none":
        n_settle = 4 if cfg.settle_up == "light" else 14
        span = (cfg.end - cfg.start).days
        for i in range(n_settle):
            d = cfg.start + timedelta(days=int(rng.integers(0, span + 1)))
            name, desc = people[i % 3]
            out.append(
                _txn(
                    d,
                    rand_time(rng),
                    int(rng.integers(4, 10)) * 500,
                    name,
                    f"{desc} DINNER",
                    "FPI",
                    "Faster payment",
                    "Transfers",
                    "transfer.reimbursement",
                    "split_settlement",
                    cpty=slug(name),
                )
            )
    if cfg.settle_up == "heavy":
        for _ in range(5):
            d = cfg.start + timedelta(days=int(rng.integers(0, (cfg.end - cfg.start).days + 1)))
            out.append(
                _txn(
                    d,
                    "06:40:00",
                    int(rng.integers(40, 181)) * 100,
                    "Acme Analytics Ltd",
                    "ACME ANALYTICS EXPENSES",
                    "BGC",
                    "Bacs (Direct Credit)",
                    "Expenses",
                    "transfer.reimbursement",
                    "reimbursement",
                    cpty="cpty_acme",
                )
            )
        for i in range(8):
            d = cfg.start + timedelta(days=int(rng.integers(0, (cfg.end - cfg.start).days + 1)))
            out.append(
                _txn(
                    d,
                    rand_time(rng),
                    -int(rng.integers(2, 6)) * 500,
                    "Sky Bet",
                    "SKY BETTING AND GAMING",
                    "DEB",
                    "Card payment",
                    "Entertainment",
                    "betting",
                    "betting",
                    cpty="cpty_skybet",
                )
            )
            if i % 3 == 0:
                out.append(
                    _txn(
                        d + timedelta(days=1),
                        rand_time(rng),
                        int(rng.integers(5, 30)) * 100,
                        "Sky Bet",
                        "SKY BETTING AND GAMING",
                        "DEB",
                        "Card payment",
                        "Entertainment",
                        "betting_return",
                        "betting_return",
                        cpty="cpty_skybet",
                    )
                )
    if cfg.unconfirmed_inflows:
        for y, m in months_between(cfg.start, cfg.end):
            d = date(y, m, int(rng.integers(19, 22)))
            if inside(d):
                out.append(
                    _txn(
                        d,
                        rand_time(rng),
                        20000,
                        "T Okafor",
                        "T OKAFOR",
                        "FPI",
                        "Faster payment",
                        "Transfers",
                        "inflow_unconfirmed",
                        "inflow_unconfirmed",
                        recurring="rob_okafor_in",
                        cpty="cpty_okafor",
                    )
                )
            d2 = date(y, m, 2)
            if inside(d2) and m % 2 == 0:
                out.append(
                    _txn(
                        d2,
                        rand_time(rng),
                        30000,
                        "Amara Nwosu",
                        "AMARA NWOSU",
                        "FPI",
                        "Faster payment",
                        "Transfers",
                        "transfer.from_untracked",
                        "transfer_from_untracked",
                        cpty="cpty_self",
                    )
                )
        span = (cfg.end - cfg.start).days
        for _ in range(6):
            d = cfg.start + timedelta(days=int(rng.integers(0, span + 1)))
            out.append(
                _txn(
                    d,
                    rand_time(rng),
                    int(rng.integers(40, 121)) * 100,
                    "PayPal",
                    "PAYPAL *TRANSFER",
                    "FPI",
                    "Faster payment",
                    "Transfers",
                    "inflow_unconfirmed",
                    "inflow_unconfirmed",
                    cpty="cpty_paypal",
                )
            )
        for d, amt, name, desc in (
            (date(2026, 2, 7), 7500, "K Adeyemi", "K ADEYEMI"),
            (date(2026, 6, 13), 12000, "M Osei", "M OSEI"),
        ):
            if inside(d):
                out.append(
                    _txn(
                        d,
                        rand_time(rng),
                        amt,
                        name,
                        desc,
                        "FPI",
                        "Faster payment",
                        "Transfers",
                        "inflow_unconfirmed",
                        "inflow_unconfirmed",
                        cpty=slug(name),
                    )
                )
    if cfg.card_checks:
        for d, name, desc in (
            (cfg.start + timedelta(days=1), "Amazon", "AMAZON EU AMAZON.CO.UK"),
            (cfg.end - timedelta(days=40), "Apple", "APPLE.COM/BILL"),
        ):
            out.append(
                _txn(
                    d,
                    rand_time(rng),
                    0,
                    name,
                    desc,
                    "DEB",
                    "Card payment",
                    "Shopping",
                    None,
                    None,
                    skip=True,
                )
            )
    if cfg.food_anomaly:
        anomalies.append(
            {
                "key": "food_delivery_spike",
                "type": "category_trend",
                "subject": "food.delivery",
                "magnitude_pct": 41,
                "expected_findings": ["category_spike"],
            }
        )
    if cfg.netflix:
        anomalies.append(
            {
                "key": "subscription_overlap",
                "type": "subscription_overlap",
                "subject": ["rob_netflix", "rob_sky"],
                "expected_findings": ["subscription_overlap"],
            }
        )
    if cfg.spotify_rise:
        anomalies.append(
            {
                "key": "spotify_price_rise",
                "type": "price_change",
                "subject": "rob_spotify",
                "from": SPOTIFY_RISE[0].isoformat(),
                "old_minor": -1199,
                "new_minor": -1299,
                "expected_findings": ["price_change"],
            }
        )
    return out, anomalies


def build_salaried(cfg: SalariedConfig, seed: int) -> PersonaOutput:
    s = Streams(seed, cfg.stream_key or cfg.key)
    bills, recurring = _bills(cfg, s)
    income, second, streams = _income(cfg, s)
    food, food_finding = _food(cfg, s)
    extras, anomalies = _extras(cfg, s)
    paydays = [t.day for t in income if t.flow == "income"] or [
        date.fromisoformat(d) for d in streams[0]["paydays"]
    ]
    base = discretionary_base(s, cfg.start, cfg.end, paydays)
    if cfg.steady is not None:
        base = steady_months(base, cfg.end, cfg.steady)
    if cfg.unconfirmed_inflows:
        recurring.append(
            {
                "key": "rob_okafor_in",
                "label": "T Okafor",
                "counterparty": "T Okafor",
                "category": "inflow_unconfirmed",
                "flow": "inflow_unconfirmed",
                "amount_minor": 20000,
                "cadence": "monthly",
                "anchor_day": 20,
                "day_rule": "jitter_19_21",
                "active_months": list(range(1, 13)),
                "price_changes": [],
                "is_commitment": False,
            }
        )
    fixed = bills + income + food + extras
    fixed_sum = sum(t.amount for t in fixed)
    base_total = sum(a for _, a in base) * 100
    target_open = cfg.target_opening_minor
    disc: list[Txn] = []
    factor = cfg.disc_scale or 1.0

    def low_of(rows: list[Txn], opening: int) -> int:
        running, low = opening, opening
        for t in rows:
            running += t.amount
            low = min(low, running)
        return low

    if cfg.disc_scale is not None:
        # Fixed spending level (shared with P1-base); only the balances move.
        disc = [replace(t, amount=-max(1, round(a * factor * 100))) for t, a in base]
        txns = sort_and_number(fixed + disc)
        if cfg.closing_free:
            opening = target_open
            opening += max(0, cfg.min_balance_minor - low_of(txns, opening))
        else:
            opening = cfg.closing_minor - sum(t.amount for t in txns)
    else:
        for _ in range(60):  # converges geometrically: extra spend partly offsets the opening
            net_needed = cfg.closing_minor - target_open
            factor = (fixed_sum - net_needed) / base_total if base_total else 1.0
            disc = [replace(t, amount=-max(1, round(a * factor * 100))) for t, a in base]
            txns = sort_and_number(fixed + disc)
            low = low_of(txns, cfg.closing_minor - sum(t.amount for t in txns))
            if low >= cfg.min_balance_minor:
                break
            target_open += cfg.min_balance_minor - low + 100
        txns = sort_and_number(fixed + disc)
        opening = cfg.closing_minor - sum(t.amount for t in txns)
    known: list[dict[str, Any]] = []
    if cfg.known_car_repair and cfg.end == END:
        known.append(
            {
                "date": "2026-10-14",
                "amount_minor": -65000,
                "label": "Car repair",
                "counterparty": "KwikFit Leeds",
                "category": "transport.car",
                "entered_on": "2026-10-12",
                "is_one_off": True,
            }
        )
    anomalies.append({"key": "food_delivery_windows", "type": "reference", **food_finding})
    return PersonaOutput(
        txns=txns,
        opening_minor=opening,
        income_streams=streams,
        recurring=recurring,
        anomalies=anomalies,
        known_flows=known,
        second_account=sort_and_number(second),
        disc_scale=round(factor, 4),
    )
