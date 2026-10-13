"""S14 side account: fictional Sam Patel on a Revolut consolidated statement.

GBP pocket: own-name top-ups (£150 on the 1st and 15th), £200/month from T Okafor around the
20th, irregular PayPal credits, no salary, and modest card spending. An empty USD pocket and a
small EUR pocket. Each pocket is its own account with its own running balance.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from evals.generator.model import (
    Streams,
    Txn,
    daterange,
    lognormal_pounds,
    rand_time,
    slug,
    sort_and_number,
)
from evals.generator.salaried import END, PersonaOutput
from evals.generator.ukcalendar import months_between

SPEND = (
    ("Tesco", "groceries", 14.0, 0.25),
    ("Pret A Manger", "food.eating_out", 7.5, 0.15),
    ("TfL Travel", "transport.public", 4.2, 0.2),
    ("Amazon", "shopping.general", 16.0, 0.08),
    ("Deliveroo", "food.delivery", 18.0, 0.06),
)
EUR_SPEND = (
    (date(2026, 5, 22), 1840, "Cafe Central", "food.eating_out"),
    (date(2026, 5, 23), 2560, "Mercadona", "groceries"),
    (date(2026, 5, 24), 1200, "Metro de Madrid", "transport.public"),
)


def build_side_account(key: str, start: date, seed: int) -> PersonaOutput:
    s = Streams(seed, key)
    rng = s["fixed"]
    disc = s["discretionary"]
    out: list[Txn] = []

    def add(d: date, amount: int, name: str, category: str, flow: str, **kw: Any) -> None:
        out.append(
            Txn(
                d,
                rand_time(rng),
                amount,
                name,
                name,
                "",
                "",
                "",
                category,
                flow,
                account=kw.pop("account", "acct_gbp"),
                **kw,
            )
        )

    for y, m in months_between(start, END):
        for day in (1, 15):
            d = date(y, m, day)
            if start <= d <= END:
                add(
                    d,
                    15000,
                    "Transfer from Sam Patel",
                    "transfer.from_untracked",
                    "transfer_from_untracked",
                    recurring="rob_topup",
                    cpty="cpty_self",
                )
        d = date(y, m, int(rng.integers(19, 22)))
        if start <= d <= END:
            add(
                d,
                20000,
                "Transfer from T Okafor",
                "inflow_unconfirmed",
                "inflow_unconfirmed",
                recurring="rob_okafor_in",
                cpty="cpty_okafor",
            )
    span = (END - start).days
    for _ in range(7):
        d = start + timedelta(days=int(rng.integers(0, span + 1)))
        add(
            d,
            int(rng.integers(15, 90)) * 100,
            "Payment from PayPal",
            "inflow_unconfirmed",
            "inflow_unconfirmed",
            cpty="cpty_paypal",
        )
    for d in daterange(start, END):
        for name, cat, median, rate in SPEND:
            for _ in range(int(disc.poisson(rate))):
                amt = round(lognormal_pounds(disc, median, 0.4, 1.0) * 100)
                add(d, -amt, name, cat, "spending", cpty=slug(name))
    # EUR pocket: one exchange in, a short trip's spending.
    ex = date(2026, 5, 21)
    add(ex, -8600, "Exchanged to EUR", "transfer.own", "transfer_own", cpty="cpty_self_eur")
    add(
        ex,
        10000,
        "Exchanged from GBP",
        "transfer.own",
        "transfer_own",
        account="acct_eur",
        currency="EUR",
        cpty="cpty_self_gbp",
    )
    for d, amt, name, cat in EUR_SPEND:
        add(d, -amt, name, cat, "spending", account="acct_eur", currency="EUR", cpty=slug(name))

    txns = sort_and_number(out)
    gbp = [t for t in txns if t.account == "acct_gbp"]
    running, low = 0, 0
    for t in gbp:
        running += t.amount
        low = min(low, running)
    opening = max(8500, 2000 - low)
    recurring = [
        {
            "key": "rob_topup",
            "label": "Own-name top-up",
            "counterparty": "Sam Patel",
            "category": "transfer.from_untracked",
            "flow": "transfer_from_untracked",
            "amount_minor": 15000,
            "cadence": "semimonthly",
            "anchor_day": [1, 15],
            "day_rule": "calendar_day",
            "active_months": list(range(1, 13)),
            "price_changes": [],
            "is_commitment": False,
        },
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
        },
    ]
    return PersonaOutput(
        txns=txns,
        opening_minor=opening,
        income_streams=[],
        recurring=recurring,
        anomalies=[],
        known_flows=[],
    )
