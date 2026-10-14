"""Freelancer persona builder (P2 Jamie Clarke, Bristol) and the S4 income-shock variant.

Irregular client invoices (2–5 a month, £900–£6,500), a monthly retainer, Self Assessment on
31 Jan and 31 Jul, ordinary bills, and discretionary spending. Exported with a running balance.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from evals.generator.model import Streams, Txn, sort_and_number
from evals.generator.salaried import (
    END,
    Bill,
    PersonaOutput,
    discretionary_base,
    steady_months,
)
from evals.generator.ukcalendar import collection_date, months_between, previous_working_day

P2_BILLS: tuple[Bill, ...] = (
    Bill(
        "rob_rent",
        "Rent",
        "Harbourside Homes",
        "HARBOURSIDE HOMES",
        "SO",
        "housing.rent",
        110000,
        1,
    ),
    Bill(
        "rob_council_tax",
        "Council tax",
        "Bristol City Council",
        "BRISTOL CITY COUNCIL",
        "DD",
        "housing.council_tax",
        17800,
        10,
        active_months=(4, 5, 6, 7, 8, 9, 10, 11, 12, 1),
    ),
    Bill("rob_energy", "Energy", "OVO Energy", "OVO ENERGY", "DD", "utilities.energy", 8400, 18),
    Bill("rob_water", "Water", "Bristol Water", "BRISTOL WATER", "DD", "utilities.water", 3800, 6),
    Bill(
        "rob_broadband",
        "Broadband",
        "Virgin Media",
        "VIRGIN MEDIA",
        "DD",
        "utilities.broadband_tv",
        3500,
        11,
    ),
    Bill("rob_mobile", "Mobile", "giffgaff", "GIFFGAFF", "DD", "utilities.mobile", 1200, 23),
    Bill(
        "rob_adobe",
        "Adobe",
        "Adobe",
        "ADOBE *CREATIVE CLD",
        "DEB",
        "subscriptions.software_cloud",
        5698,
        4,
    ),
    Bill(
        "rob_spotify", "Spotify", "Spotify", "SPOTIFY", "DEB", "subscriptions.streaming", 1299, 22
    ),
)

CLIENTS = (
    ("Brightwater Media", "BRIGHTWATER MEDIA LTD", 3.0),
    ("Kestrel Design Co", "KESTREL DESIGN CO", 2.0),
    ("Severn Studio", "SEVERN STUDIO LTD", 2.0),
    ("Oakfield Events", "OAKFIELD EVENTS", 1.0),
)
RETAINER = ("Lumen Labs", "LUMEN LABS LTD", 200000, 5)  # monthly retainer, ~5th

# Self Assessment: (due date, normal amount, base amount with the jump)
SA_PAYMENTS = (
    (date(2025, 7, 31), 240000, 240000),
    (date(2026, 1, 31), 310000, 590000),
    (date(2026, 7, 31), 295000, 295000),
)
LATE_PAYMENT = (date(2026, 6, 5), 45)  # the June retainer arrives 45 days late
CAMERA_KIT = (date(2026, 8, 14), 245000)


@dataclass
class FreelanceConfig:
    key: str
    start: date
    end: date = END
    anomalies: bool = True
    shock_from: date | None = None  # S4: income −60% from this date
    steady: float | None = None  # steady_months(max_dev) on discretionary spend (P2 twins)
    min_balance_minor: int = 60000


def _slug(name: str) -> str:
    return name.lower().split()[0]


def _sweep(txns: list[Txn], opening: int, cfg: FreelanceConfig, extra: int) -> list[Txn]:
    """Monthly sweep of the surplus above a working float to an untracked ISA (keeping a larger
    float ahead of the Self Assessment months)."""
    sweep_days = {collection_date(y, m, 27): m for y, m in months_between(cfg.start, cfg.end)}
    out: list[Txn] = []
    running = opening
    for t in txns:
        while sweep_days and min(sweep_days) < t.day:
            d = min(sweep_days)
            keep = extra + (900000 if sweep_days.pop(d) in (12, 6) else 450000)
            amount = (running - keep) // 25000 * 25000
            if amount > 0 and cfg.start <= d <= cfg.end:
                out.append(
                    Txn(
                        d,
                        "07:00:00",
                        -amount,
                        "Jamie Clarke ISA",
                        "JAMIE CLARKE ISA TFR",
                        "TFR",
                        "",
                        "",
                        "transfer.untracked",
                        "transfer_to_untracked",
                        recurring="rob_isa_sweep",
                        cpty="cpty_self_isa",
                    )
                )
                running -= amount
        out.append(t)
        running += t.amount
    return sort_and_number(out)


def build_freelance(cfg: FreelanceConfig, seed: int) -> PersonaOutput:
    s = Streams(seed, cfg.key)
    rng = s["fixed"]
    txns: list[Txn] = []
    recurring: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []

    def inside(d: date) -> bool:
        return cfg.start <= d <= cfg.end

    def shock(amount: int, d: date) -> int:
        return round(amount * 0.4) if cfg.shock_from and d >= cfg.shock_from else amount

    for b in P2_BILLS:
        for y, m in months_between(cfg.start, cfg.end):
            if m not in b.active_months:
                continue
            d = date(y, m, b.day) if b.code == "DEB" else collection_date(y, m, b.day)
            if inside(d):
                txns.append(
                    Txn(
                        d,
                        "06:00:00",
                        -b.amount,
                        b.name,
                        b.desc,
                        b.code,
                        "",
                        "",
                        b.category,
                        b.flow,
                        recurring=b.key,
                        cpty=f"cpty_{b.key[4:]}",
                    )
                )
        recurring.append(
            {
                "key": b.key,
                "label": b.label,
                "counterparty": b.name,
                "category": b.category,
                "flow": b.flow,
                "amount_minor": -b.amount,
                "cadence": "monthly",
                "anchor_day": b.day,
                "day_rule": "calendar_day" if b.code == "DEB" else "next_working_day",
                "active_months": list(b.active_months),
                "price_changes": [],
                "is_commitment": False,
            }
        )

    # Client invoices: irregular, 2–5 a month.
    invoice_amounts: list[int] = []
    for y, m in months_between(cfg.start, cfg.end):
        for _ in range(int(rng.integers(2, 6))):
            d = date(y, m, int(rng.integers(1, 29)))
            if not inside(d):
                continue
            w = [c[2] for c in CLIENTS]
            name, desc, _ = CLIENTS[int(rng.choice(len(CLIENTS), p=[x / sum(w) for x in w]))]
            pounds_ = min(6500.0, max(900.0, float(rng.lognormal(7.5, 0.55))))  # median ~£1.8k
            amt = shock(round(pounds_ / 50) * 5000, d)  # £900–£6,500 in £50 steps
            invoice_amounts.append(amt)
            txns.append(
                Txn(
                    d,
                    "09:00:00",
                    amt,
                    name,
                    f"{desc} INV{int(rng.integers(100, 999))}",
                    "FPI",
                    "",
                    "",
                    "income.self_employed",
                    "income",
                    income=f"inc_client_{_slug(name)}",
                    cpty=f"cpty_{_slug(name)}",
                )
            )
    retainer_days = []
    for y, m in months_between(cfg.start, cfg.end):
        due = collection_date(y, m, RETAINER[3])
        d = due
        if cfg.anomalies and due.replace(day=5) == LATE_PAYMENT[0]:
            d = due + timedelta(days=LATE_PAYMENT[1])
        if inside(d):
            retainer_days.append(d)
            txns.append(
                Txn(
                    d,
                    "08:30:00",
                    shock(RETAINER[2], d),
                    RETAINER[0],
                    RETAINER[1],
                    "BGC",
                    "",
                    "",
                    "income.self_employed",
                    "income",
                    income="inc_client_lumen",
                    cpty="cpty_lumen",
                    anomaly="late_payment" if d != due else None,
                )
            )
    if cfg.anomalies:
        anomalies.append(
            {
                "key": "late_payment",
                "type": "late_income",
                "subject": "inc_client_lumen",
                "expected_on": LATE_PAYMENT[0].isoformat(),
                "arrived_on": (LATE_PAYMENT[0] + timedelta(days=LATE_PAYMENT[1])).isoformat(),
                "days_late": LATE_PAYMENT[1],
                "expected_findings": ["income_late"],
            }
        )

    for due, normal, jumped in SA_PAYMENTS:
        d = previous_working_day(due)
        if inside(d):
            amt = jumped if cfg.anomalies else normal
            txns.append(
                Txn(
                    d,
                    "10:00:00",
                    -amt,
                    "HMRC",
                    "HMRC SELF ASSESSMENT",
                    "FPO",
                    "",
                    "",
                    "tax.self_assessment",
                    "tax",
                    recurring="rob_self_assessment",
                    cpty="cpty_hmrc",
                    anomaly="tax_jump" if amt != normal else None,
                )
            )
    recurring.append(
        {
            "key": "rob_self_assessment",
            "label": "Self Assessment",
            "counterparty": "HMRC",
            "category": "tax.self_assessment",
            "flow": "tax",
            "amount_minor": -295000,
            "cadence": "semiannual",
            "anchor_day": 31,
            "day_rule": "previous_working_day",
            "active_months": [1, 7],
            "price_changes": [],
            "is_commitment": False,
        }
    )
    if cfg.anomalies and inside(previous_working_day(SA_PAYMENTS[1][0])):
        anomalies.append(
            {
                "key": "tax_jump",
                "type": "amount_jump",
                "subject": "rob_self_assessment",
                "normal_minor": -310000,
                "actual_minor": -590000,
                "expected_findings": ["amount_jump"],
            }
        )
    if cfg.anomalies and inside(CAMERA_KIT[0]):
        txns.append(
            Txn(
                CAMERA_KIT[0],
                "14:12:09",
                -CAMERA_KIT[1],
                "Wex Photo Video",
                "WEX PHOTO VIDEO NORWICH",
                "DEB",
                "",
                "",
                "shopping.general",
                "spending",
                cpty="cpty_wex",
                one_off=True,
                anomaly="new_merchant_spike",
            )
        )
        anomalies.append(
            {
                "key": "new_merchant_spike",
                "type": "new_merchant",
                "subject": "cpty_wex",
                "date": CAMERA_KIT[0].isoformat(),
                "amount_minor": -CAMERA_KIT[1],
                "expected_findings": ["new_merchant"],
            }
        )
    if cfg.shock_from:
        anomalies.append(
            {
                "key": "income_shock",
                "type": "income_drop",
                "from": cfg.shock_from.isoformat(),
                "magnitude_pct": -60,
                "expected_findings": ["income_drop"],
            }
        )

    base = discretionary_base(s, cfg.start, cfg.end, retainer_days, city="BRISTOL")
    if cfg.steady is not None:
        base = steady_months(base, cfg.end, cfg.steady)
    disc = [
        replace(t, amount=-max(1, round(a * 100)), monzo_type="", monzo_cat="") for t, a in base
    ]
    txns = sort_and_number(txns + disc)
    opening, extra = 420000, 0
    for _ in range(40):
        swept = _sweep(txns, opening, cfg, extra)
        first_sweep = min((t.day for t in swept if t.recurring == "rob_isa_sweep"), default=END)
        running, low, low_day = opening, opening, cfg.start
        for t in swept:
            running += t.amount
            if running < low:
                low, low_day = running, t.day
        if low >= cfg.min_balance_minor:
            break
        bump = (cfg.min_balance_minor - low + 9999) // 10000 * 10000
        if low_day <= first_sweep:
            opening += bump
        else:
            extra += bump
    txns = swept
    recurring.append(
        {
            "key": "rob_isa_sweep",
            "label": "Savings sweep",
            "counterparty": "Jamie Clarke ISA",
            "category": "transfer.untracked",
            "flow": "transfer_to_untracked",
            "amount_minor": None,
            "cadence": "monthly",
            "anchor_day": 27,
            "day_rule": "next_working_day",
            "active_months": list(range(1, 13)),
            "price_changes": [],
            "is_commitment": False,
            "variable_amount": True,
        }
    )

    streams: list[dict[str, Any]] = [
        {
            "key": f"inc_client_{_slug(c[0])}",
            "source": c[0],
            "account": "acct_main",
            "cadence": "irregular",
            "provenance_expected": "detected",
        }
        for c in CLIENTS
    ]
    streams.append(
        {
            "key": "inc_client_lumen",
            "source": RETAINER[0],
            "account": "acct_main",
            "cadence": "monthly",
            "net_amount_minor": RETAINER[2],
            "payday_rule": {
                "kind": "fixed_day",
                "day_of_month": RETAINER[3],
                "next_working_day": True,
            },
            "provenance_expected": "detected",
            "paydays": [d.isoformat() for d in retainer_days],
        }
    )
    for st in streams[: len(CLIENTS)]:
        st["invoice_range_minor"] = [min(invoice_amounts), max(invoice_amounts)]
    return PersonaOutput(
        txns=txns,
        opening_minor=opening,
        income_streams=streams,
        recurring=recurring,
        anomalies=anomalies,
        known_flows=[],
    )
