"""Dataset assembly: personas → exports + truth files + manifests (docs/09 §3.1, §16)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from evals.generator import GENERATOR_VERSION
from evals.generator.corrupt import build_corrupt, to_csv
from evals.generator.freelance import FreelanceConfig, build_freelance
from evals.generator.model import Streams, Txn, daterange, sort_and_number
from evals.generator.salaried import END, PersonaOutput, SalariedConfig, build_salaried
from evals.generator.sideaccount import build_side_account
from evals.generator.ukcalendar import months_between
from evals.generator.writers import (
    Export,
    bare_dollar,
    euro_semicolon,
    fenwick,
    generic_in_out,
    generic_signed,
    harbour_vale,
    monzo,
    narration,
    northgate,
    pennine,
    revolut,
)

DATASETS_DIR = Path(__file__).resolve().parents[1] / "datasets"
TODAY = END + timedelta(days=1)


def months_back(n: int) -> date:
    """First day of the n-month history ending on END (e.g. 12 → 12 Oct 2025)."""
    y, m = END.year, END.month - n
    while m < 1:
        y, m = y - 1, m + 12
    return date(y, m, END.day + 1)


@dataclass
class Account:
    id: str
    label: str
    institution: str
    currency: str
    txns: list[Txn]
    opening: int
    has_balance_column: bool


@dataclass
class Built:
    display_name: str
    persona: PersonaOutput
    accounts: list[Account]
    exports: list[Export]
    declared: bool = True  # Monzo-style: today's balance declared by the user
    notes: tuple[str, ...] = ()


def _data(txns: list[Txn]) -> list[Txn]:
    return [t for t in txns if not t.skip]


def _relabel(txns: list[Txn], **kw: Any) -> list[Txn]:
    return sort_and_number([replace(t, **kw) for t in txns])


# --------------------------------------------------------------------------- builders


def _monzo_built(name: str, cfg: SalariedConfig, seed: int, declared: bool = True) -> Built:
    p = build_salaried(cfg, seed)
    ids = Streams(seed, name + ":export")["ids"]
    acct = Account(
        "acct_main", "Monzo current account", "Monzo", "GBP", p.txns, p.opening_minor, False
    )
    return Built("Amara Nwosu", p, [acct], [monzo(p.txns, ids)], declared=declared)


def p1(name: str, seed: int, months: int = 12, **kw: Any) -> Built:
    return _monzo_built(name, SalariedConfig(key=name, start=months_back(months), **kw), seed)


@lru_cache(maxsize=4)
def p1_scale(seed: int) -> float:
    """P1-base's calibrated discretionary scale, reused so variants spend at the same level."""
    return build_salaried(SalariedConfig(key="P1-base", start=months_back(12)), seed).disc_scale


# P1/P2 twins: month totals per discretionary category within ±5% of the usual month (any two
# months then differ by under the detector's 15% materiality floor, docs/00 §13), so
# E-ANOM's clean twins hold no chance spikes (gen-1.1.0). Other datasets keep the raw noise.
STEADY = 0.05


@lru_cache(maxsize=4)
def p1_steady_scale(seed: int) -> float:
    """p1_scale for the steadied P1-base, shared by P1-clean."""
    cfg = SalariedConfig(key="P1-base", start=months_back(12), steady=STEADY)
    return build_salaried(cfg, seed).disc_scale


def p1_clean(name: str, seed: int) -> Built:
    return _monzo_built(
        name,
        SalariedConfig(
            key=name,
            start=months_back(12),
            netflix=False,
            spotify_rise=False,
            food_anomaly=False,
            known_car_repair=False,
            stream_key="P1-base",
            disc_scale=p1_steady_scale(seed),
            steady=STEADY,
        ),
        seed,
    )


def s2_noanchor(name: str, seed: int) -> Built:
    return _monzo_built(name, SalariedConfig(key=name, start=months_back(6)), seed, declared=False)


def _freelance_built(name: str, cfg: FreelanceConfig, seed: int) -> Built:
    p = build_freelance(cfg, seed)
    acct = Account(
        "acct_main", "Current account", "Generic bank", "GBP", p.txns, p.opening_minor, True
    )
    return Built(
        "Jamie Clarke", p, [acct], [generic_signed(p.txns, p.opening_minor)], declared=False
    )


def p2(name: str, seed: int, anomalies: bool = True) -> Built:
    cfg = FreelanceConfig(name, months_back(18), anomalies=anomalies, steady=STEADY)
    return _freelance_built(name, cfg, seed)


def s4_shock(name: str, seed: int) -> Built:
    return _freelance_built(
        name,
        FreelanceConfig(name, months_back(12), anomalies=False, shock_from=date(2026, 6, 12)),
        seed,
    )


TYPOS = (
    ("TESCO", "TECSO"),
    ("SAINSBURYS", "SAINSBRYS"),
    ("DELIVEROO", "DELIVROO"),
    ("PRET A MANGER", "PRET A MANGR"),
    ("AMAZON", "AMAZN"),
    ("COSTA", "COSTTA"),
)


def s5_noisy(name: str, seed: int) -> Built:
    p = build_salaried(SalariedConfig(key=name, start=months_back(6), card_checks=False), seed)
    rng = Streams(seed, name + ":export")["narration"]

    def noisy(t: Txn) -> str:
        text = narration(t)
        roll = float(rng.random())
        if roll < 0.15:
            text = text[:18]
        elif roll < 0.30:
            text = text.title() if roll < 0.22 else text.lower()
        elif roll < 0.40:
            for a, b in TYPOS:
                text = text.replace(a, b)
        elif roll < 0.55:
            text = f"{text} {int(rng.integers(1, 9999)):04d}"
        return text

    acct = Account(
        "acct_main", "Current account", "Generic bank", "GBP", p.txns, p.opening_minor, True
    )
    return Built(
        "Amara Nwosu",
        p,
        [acct],
        [generic_signed(p.txns, p.opening_minor, describe=noisy)],
        declared=False,
        notes=(
            "Descriptions truncated, re-cased, misspelt or suffixed with store "
            "numbers; gold labels unchanged.",
        ),
    )


def s8_salary_split(name: str, seed: int) -> Built:
    p = build_salaried(
        SalariedConfig(key=name, start=months_back(6), pay_mode="split", bonus_and_arrears=True),
        seed,
    )
    rng = Streams(seed, name + ":second")["extra"]
    second = list(p.second_account)
    for y, m in months_between(months_back(6), END):
        d = date(y, m, 23)
        if months_back(6) <= d <= END:
            second.append(
                Txn(
                    d,
                    "06:00:00",
                    -1800,
                    "Lyca Mobile",
                    "LYCAMOBILE",
                    "DD",
                    "",
                    "",
                    "utilities.mobile",
                    "spending",
                    recurring="rob_mobile",
                    cpty="cpty_lyca",
                    account="acct_second",
                )
            )
        for _ in range(3):
            d = date(y, m, int(rng.integers(1, 29)))
            if months_back(6) <= d <= END:
                second.append(
                    Txn(
                        d,
                        "12:00:00",
                        -int(rng.integers(500, 4000)),
                        "Tesco",
                        "TESCO STORES 2290",
                        "DEB",
                        "",
                        "",
                        "groceries",
                        "spending",
                        cpty="cpty_tesco",
                        account="acct_second",
                    )
                )
    second = sort_and_number(second)
    p.recurring.append(
        {
            "key": "rob_mobile",
            "label": "Mobile",
            "counterparty": "Lyca Mobile",
            "category": "utilities.mobile",
            "flow": "spending",
            "amount_minor": -1800,
            "cadence": "monthly",
            "anchor_day": 23,
            "day_rule": "next_working_day",
            "account": "acct_second",
            "active_months": list(range(1, 13)),
            "price_changes": [],
            "is_commitment": False,
        }
    )
    ids = Streams(seed, name + ":export")["ids"]
    main = Account(
        "acct_main", "Monzo current account", "Monzo", "GBP", p.txns, p.opening_minor, False
    )
    sec = Account(
        "acct_second", "Second current account", "Generic bank", "GBP", second, 30000, True
    )
    return Built(
        "Amara Nwosu",
        p,
        [main, sec],
        [
            monzo(p.txns, ids),
            generic_in_out(second, 30000, path="exports/second_account.csv", account="acct_second"),
        ],
    )


def s14_side(name: str, seed: int) -> Built:
    p = build_side_account(name, months_back(12), seed)
    gbp = [t for t in p.txns if t.account == "acct_gbp"]
    eur = [t for t in p.txns if t.account == "acct_eur"]
    accounts = [
        Account("acct_gbp", "Revolut GBP", "Revolut", "GBP", gbp, p.opening_minor, True),
        Account("acct_usd", "Revolut USD", "Revolut", "USD", [], 0, True),
        Account("acct_eur", "Revolut EUR", "Revolut", "EUR", eur, 0, True),
    ]
    exp = revolut([(a.id, a.currency, a.txns, a.opening) for a in accounts])
    return Built("Sam Patel", p, accounts, [exp], declared=False)


def _plain(name: str, seed: int, months: int, **kw: Any) -> PersonaOutput:
    return build_salaried(
        SalariedConfig(
            key=name,
            start=months_back(months),
            netflix=False,
            spotify_rise=False,
            food_anomaly=False,
            known_car_repair=False,
            card_checks=False,
            disc_scale=p1_scale(seed),
            closing_free=True,
            **kw,
        ),
        seed,
    )


def c1(name: str, seed: int) -> Built:
    p = _plain(name, seed, 12)
    acct = Account(
        "acct_main", "Pennine current account", "Pennine BS", "GBP", p.txns, p.opening_minor, True
    )
    return Built(
        "Priya Shah", p, [acct], [pennine(p.txns, p.opening_minor, "Priya Shah")], declared=False
    )


def c2(name: str, seed: int) -> Built:
    p = _plain(name, seed, 12)
    p.txns = _relabel(p.txns, currency="EUR")
    acct = Account(
        "acct_main",
        "Harbour & Vale account",
        "Harbour & Vale",
        "EUR",
        p.txns,
        p.opening_minor,
        False,
    )
    return Built("Lena Hartmann", p, [acct], [harbour_vale(p.txns)])


def c3(name: str, seed: int) -> Built:
    p = _plain(name, seed, 12)
    rng = Streams(seed, name + ":export")["ids"]
    current = _relabel(
        [
            replace(
                t,
                category="transfer.own",
                flow="transfer_own",
                desc="TFR TO SAVINGS",
                recurring=None,
                cpty="cpty_self_savings",
            )
            if t.flow == "savings_investment"
            else t
            for t in p.txns
        ]
    )
    savings = [
        replace(
            t,
            amount=-t.amount,
            account="acct_savings",
            desc="TFR FROM CURRENT",
            cpty="cpty_self_current",
        )
        for t in current
        if t.flow == "transfer_own"
    ]
    for y, m in months_between(months_back(12), END):
        d = date(y, m, 1)
        if months_back(12) <= d <= END:
            savings.append(
                Txn(
                    d,
                    "03:00:00",
                    int(rng.integers(300, 1600)),
                    "Interest",
                    "INTEREST PAID",
                    "BGC",
                    "",
                    "",
                    "income.interest",
                    "income",
                    income="inc_interest",
                    account="acct_savings",
                )
            )
    savings = sort_and_number(savings)
    p.txns = current
    accts = [
        Account(
            "acct_main", "Northgate current", "Northgate", "GBP", current, p.opening_minor, False
        ),
        Account("acct_savings", "Northgate savings", "Northgate", "GBP", savings, 250000, False),
    ]
    p.recurring = [r for r in p.recurring if r["key"] != "rob_savings"]
    return Built("Tom Whitfield", p, accts, [northgate(current, savings, rng)])


def c4(name: str, seed: int) -> Built:
    p = _plain(name, seed, 12)
    acct = Account(
        "acct_main", "Fenwick current account", "Fenwick", "GBP", p.txns, p.opening_minor, True
    )
    return Built(
        "Grace Okoro", p, [acct], [fenwick(p.txns, p.opening_minor, "Grace Okoro")], declared=False
    )


def g1(name: str, seed: int) -> Built:
    p = _plain(name, seed, 6)
    p.txns = _relabel(p.txns, currency="EUR")
    acct = Account(
        "acct_main", "Euro account", "Generic bank", "EUR", p.txns, p.opening_minor, True
    )
    return Built(
        "Lena Hartmann", p, [acct], [euro_semicolon(p.txns, p.opening_minor)], declared=False
    )


def g3(name: str, seed: int) -> Built:
    p = _plain(name, seed, 3)
    p.txns = _relabel(p.txns, currency="USD")
    acct = Account(
        "acct_main", "Dollar account", "Generic bank", "USD", p.txns, p.opening_minor, True
    )
    return Built(
        "Alex Morgan",
        p,
        [acct],
        [bare_dollar(p.txns, p.opening_minor)],
        declared=False,
        notes=(
            "Bare $: the currency must be asked, never guessed; "
            "truth assumes the user answers USD.",
        ),
    )


def g5(name: str, seed: int) -> Built:
    p = build_salaried(
        SalariedConfig(
            key=name,
            start=date(2026, 7, 1),
            netflix=False,
            spotify_rise=False,
            food_anomaly=False,
            known_car_repair=False,
            card_checks=False,
            disc_scale=p1_scale(seed),
            closing_free=True,
        ),
        seed,
    )
    # Fold every day onto 1–12 of the same month so no date reveals the day/month order.
    kept = sort_and_number(
        [replace(t, day=t.day.replace(day=(t.day.day - 1) % 12 + 1)) for t in p.txns]
    )
    p.txns = kept
    for r in p.recurring:
        r["anchor_day"] = (r["anchor_day"] - 1) % 12 + 1
        r["day_rule"] = "folded_to_1_12"
    for st in p.income_streams:
        st["paydays"] = sorted({d[:8] + f"{(int(d[8:]) - 1) % 12 + 1:02d}" for d in st["paydays"]})
    acct = Account(
        "acct_main", "Current account", "Generic bank", "GBP", kept, p.opening_minor, True
    )
    exp = generic_signed(kept, p.opening_minor)
    for t in exp.layout["tables"]:
        t["date_ambiguous"] = True
    return Built(
        "Alex Morgan",
        p,
        [acct],
        [exp],
        declared=False,
        notes=(
            "Every day is 1–12: DD/MM vs MM/DD cannot be inferred; the importer "
            "must ask. Truth is DD/MM.",
        ),
    )


DATASETS: dict[str, Callable[[str, int], Built]] = {
    "P1-base": lambda n, s: p1(n, s, steady=STEADY),
    "P1-clean": p1_clean,
    "P2-base": lambda n, s: p2(n, s),
    "P2-clean": lambda n, s: p2(n, s, anomalies=False),
    "S1-sparse": lambda n, s: p1(n, s, months=3),
    "S2-noanchor": s2_noanchor,
    "S4-shock": s4_shock,
    "S5-noisy": s5_noisy,
    "S8-salary-split": s8_salary_split,
    "S9-settle-up": lambda n, s: p1(
        n, s, months=6, settle_up="heavy", disc_scale=p1_scale(s), closing_free=True
    ),
    "S10-untracked-salary": lambda n, s: p1(n, s, months=6, pay_mode="untracked"),
    "S11-fourweekly": lambda n, s: p1(n, s, pay_mode="fourweekly"),
    "S13-unconfirmed-inflows": lambda n, s: p1(
        n, s, unconfirmed_inflows=True, disc_scale=p1_scale(s), closing_free=True
    ),
    "S14-side-account": s14_side,
    "C1-pennine": c1,
    "C2-harbour-vale": c2,
    "C3-northgate": c3,
    "C4-fenwick": c4,
    "G1-eur": g1,
    "G3-dollar": g3,
    "G5-ambiguous-date": g5,
}
CORRUPT = "CSV-CORRUPT"
ALL_NAMES = (*DATASETS, CORRUPT)
ALIASES = {"P1": ("P1-base", "P1-clean"), "P2": ("P2-base", "P2-clean")}


# --------------------------------------------------------------------------- serialisation


def dump_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def dump_jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
        for r in rows
    )


def _truth_row(t: Txn, table: str, row: int, file: str) -> dict[str, Any]:
    r: dict[str, Any] = {
        "row": row,
        "table": table,
        "file": file,
        "date": t.day.isoformat(),
        "amount_minor": t.amount,
        "currency": t.currency,
        "category": t.category,
        "flow": t.flow,
    }
    for k, v in (
        ("recurring", t.recurring),
        ("income", t.income),
        ("cpty", t.cpty),
        ("anomaly", t.anomaly),
    ):
        if v is not None:
            r[k] = v
    if t.one_off:
        r["one_off"] = True
    if t.skip:
        r["skip"] = True
    return r


def _daily_balances(acct: Account) -> tuple[list[dict[str, Any]], int, int]:
    if not acct.txns:
        return [], acct.opening, acct.opening
    by_day: dict[date, int] = {}
    for t in acct.txns:
        by_day[t.day] = by_day.get(t.day, 0) + t.amount
    start = min(by_day)
    running, low = acct.opening, acct.opening
    out = []
    for d in daterange(start, END):
        running += by_day.get(d, 0)
        low = min(low, running)
        out.append({"account": acct.id, "date": d.isoformat(), "balance_minor": running})
    return out, running, low


def render_dataset(name: str, seed: int) -> dict[str, str]:
    """All files of one dataset: relative path → text."""
    if name == CORRUPT:
        files: dict[str, str] = {}
        index = []
        for case in build_corrupt(seed):
            files[f"{case.name}.csv"] = to_csv(case.rows)
            files[f"{case.name}.truth.json"] = dump_json(case.truth())
            index.append(case.truth())
        files["index.json"] = dump_json(
            {"cases": index, "seed": seed, "generator_version": GENERATOR_VERSION}
        )
        return files

    b = DATASETS[name](name, seed)
    p = b.persona
    files = {e.path: e.text for e in b.exports}
    truth_rows = [
        _truth_row(t, table, row, e.path) for e in b.exports for t, table, row in e.placed
    ]
    # Concise rows: file/table/currency are omitted where they equal the dataset defaults
    # (recorded in truth_accounts.json; `load_truth_transactions` fills them back in).
    defaults = {
        "file": b.exports[0].path,
        "table": b.exports[0].layout["tables"][0]["table"],
        "currency": b.accounts[0].currency,
    }
    files["truth_transactions.jsonl"] = dump_jsonl(
        [{k: v for k, v in r.items() if defaults.get(k, object()) != v} for r in truth_rows]
    )

    bal_rows: list[dict[str, Any]] = []
    accounts = []
    closing_main = low_main = 0
    for i, a in enumerate(b.accounts):
        rows, closing, low = _daily_balances(a)
        bal_rows += rows
        if i == 0:
            closing_main, low_main = closing, low
        exp = next(
            (e for e in b.exports if any(tb["table"] == a.id for tb in e.layout["tables"])), None
        )
        accounts.append(
            {
                "id": a.id,
                "label": a.label,
                "institution": a.institution,
                "currency": a.currency,
                "file": exp.path if exp else None,
                "has_balance_column": a.has_balance_column,
                "opening_balance_minor": a.opening,
                "closing_balance_minor": closing,
                "min_balance_minor": low,
                "n_transactions": len(_data(a.txns)),
            }
        )
    files["truth_balances.jsonl"] = dump_jsonl(bal_rows)
    files["truth_accounts.json"] = dump_json({"accounts": accounts, "row_defaults": defaults})
    files["truth_layout.json"] = dump_json({e.path: e.layout for e in b.exports})
    files["truth_income_streams.json"] = dump_json({"income_streams": p.income_streams})
    files["truth_recurring.json"] = dump_json({"recurring": p.recurring})
    files["truth_anomalies.json"] = dump_json({"anomalies": p.anomalies})
    files["truth_known_flows.json"] = dump_json({"known_flows": p.known_flows})
    main = b.accounts[0]
    files["workspace.json"] = dump_json(
        {
            "dataset": name,
            "display_name": b.display_name,
            "country": "GB",
            "home_currency": "GBP",
            "locale": "en-GB",
            "timezone": "Europe/London",
            "buffer_minor": 50000,
            "as_of": END.isoformat(),
            "today": TODAY.isoformat(),
            "declared_balance": {
                "as_of": END.isoformat(),
                "amount_minor": closing_main,
                "account": main.id,
            }
            if b.declared
            else None,
            "opening_balance_minor": main.opening,
            "closing_balance_minor": closing_main,
            "min_balance_minor": low_main,
            "history_start": min(
                (t.day for a in b.accounts for t in a.txns), default=END
            ).isoformat(),
            "discretionary_scale": str(p.disc_scale),
            "seed": seed,
            "generator_version": GENERATOR_VERSION,
            "notes": list(b.notes),
        }
    )
    return files


def write_all(out_dir: Path, names: list[str], seed: int) -> dict[str, str]:
    """Render datasets into out_dir and rewrite both manifests from what is on disk."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        ds = out_dir / name
        if ds.exists():
            for f in sorted(ds.rglob("*"), reverse=True):
                f.unlink() if f.is_file() else f.rmdir()
        for rel, text in render_dataset(name, seed).items():
            path = ds / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
    return write_manifests(out_dir, seed)


def file_hashes(out_dir: Path) -> dict[str, str]:
    return {
        f.relative_to(out_dir).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(out_dir.rglob("*"))
        if f.is_file()
        and not f.name.startswith("MANIFEST")
        and f.parent != out_dir
        and f.relative_to(out_dir).parts[0] in ALL_NAMES
    }


def write_manifests(out_dir: Path, seed: int) -> dict[str, str]:
    hashes = file_hashes(out_dir)
    (out_dir / "MANIFEST.json").write_bytes(
        dump_json(
            {
                "generator_version": GENERATOR_VERSION,
                "seed": seed,
                "files": hashes,
                "total_bytes": sum((out_dir / k).stat().st_size for k in hashes),
            }
        ).encode("utf-8")
    )
    (out_dir / "MANIFEST.sha256").write_bytes(
        "".join(f"{v}  {k}\n" for k, v in hashes.items()).encode("utf-8")
    )
    return hashes


def resolve(names: list[str]) -> list[str]:
    out: list[str] = []
    for n in names:
        for x in ALIASES.get(n, (n,)):
            if x not in ALL_NAMES:
                raise SystemExit(f"unknown dataset {x!r}; choose from {', '.join(ALL_NAMES)}")
            if x not in out:
                out.append(x)
    return out


def load_truth_transactions(dataset_dir: Path) -> list[dict[str, Any]]:
    """Read truth_transactions.jsonl with the omitted default keys restored."""
    defaults = json.loads((dataset_dir / "truth_accounts.json").read_text(encoding="utf-8"))[
        "row_defaults"
    ]
    lines = (dataset_dir / "truth_transactions.jsonl").read_text(encoding="utf-8").splitlines()
    return [{**defaults, **json.loads(line)} for line in lines if line]
