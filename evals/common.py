"""Shared plumbing for the deterministic eval suites: datasets, the uk pack and the engine pipeline.

The pipeline here mirrors the product path using `finance_core` only: bytes → `import_file` →
`ParsedRow` → `Transaction` → `categorise` → detectors → `ForecastInputs`. Truth files are read
only to score, never to feed the engine (except the balance anchor at a backtest origin, which
docs/09 §7.1 prescribes).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from backend.finance_core.calendar import holiday_set
from backend.finance_core.categorise.normalise import parse_narration
from backend.finance_core.categorise.pack import CategorisationPack, load_pack
from backend.finance_core.categorise.rules import CategoriseContext, categorise
from backend.finance_core.importers import FileImport, blocking_questions, import_file
from backend.finance_core.locale import LocalePack, load_locale_pack
from backend.finance_core.types import Categorisation, FlowKind, ParsedRow, Transaction
from evals.generator.build import load_truth_transactions

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "evals" / "datasets"
RESULTS = ROOT / "evals" / "results"
UK_PACK_PATH = ROOT / "backend" / "finance_core" / "locale_packs" / "uk.yaml"


# --------------------------------------------------------------------------- packs


@lru_cache
def uk_categorisation_pack() -> CategorisationPack:
    return load_pack(UK_PACK_PATH.read_text(encoding="utf-8"))


@lru_cache
def uk_locale_pack() -> LocalePack:
    """The uk pack's identity fields in the shape `locale.load_locale_pack` validates."""
    data = yaml.safe_load(UK_PACK_PATH.read_text(encoding="utf-8"))
    formats = data.get("formats") or {}
    hol = data.get("holidays") or {}
    return load_locale_pack(
        yaml.safe_dump(
            {
                "key": data["id"],
                "country": data["country"],
                "subdivision": hol.get("subdiv"),
                "default_currency": data["currency"],
                "locale": data["locale"],
                "date_order": (formats.get("date_orders") or ["DMY"])[0],
                "numbers": {
                    "decimal_sep": formats.get("decimal_separator", "."),
                    "group_sep": formats.get("grouping_separator", ","),
                },
            }
        )
    )


@lru_cache
def uk_holidays(first_year: int, last_year: int) -> frozenset[date]:
    pack = uk_categorisation_pack()
    return holiday_set(pack.holiday_country, pack.holiday_subdiv, range(first_year, last_year + 1))


# --------------------------------------------------------------------------- datasets


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@dataclass
class Dataset:
    name: str
    path: Path
    workspace: dict[str, Any]
    accounts: list[dict[str, Any]]
    layout: dict[str, Any]
    truth: list[dict[str, Any]]
    _balances: dict[str, dict[date, int]] | None = field(default=None, repr=False)

    @property
    def as_of(self) -> date:
        return date.fromisoformat(self.workspace["as_of"])

    @property
    def home_currency(self) -> str:
        return str(self.workspace.get("home_currency", "GBP"))

    def file_bytes(self, rel: str) -> bytes:
        return (self.path / rel).read_bytes()

    def truth_json(self, name: str) -> Any:
        return read_json(self.path / name)

    def balances(self, account: str) -> dict[date, int]:
        """Daily end-of-day truth balances for one account."""
        if self._balances is None:
            out: dict[str, dict[date, int]] = {}
            for row in read_jsonl(self.path / "truth_balances.jsonl"):
                out.setdefault(row["account"], {})[date.fromisoformat(row["date"])] = int(
                    row["balance_minor"]
                )
            self._balances = out
        return self._balances.get(account, {})


@lru_cache(maxsize=64)
def load_dataset(name: str) -> Dataset:
    path = DATASETS / name
    if not path.is_dir():
        raise FileNotFoundError(f"dataset {name!r} not found under {DATASETS}")
    return Dataset(
        name=name,
        path=path,
        workspace=read_json(path / "workspace.json"),
        accounts=read_json(path / "truth_accounts.json")["accounts"],
        layout=read_json(path / "truth_layout.json"),
        truth=load_truth_transactions(path),
    )


def truth_tables(ds: Dataset) -> list[tuple[str, dict[str, Any]]]:
    """(file, table layout) for every truth table, in file order."""
    return [(f, t) for f, spec in ds.layout.items() for t in spec["tables"]]


# --------------------------------------------------------------------------- import


@dataclass(frozen=True)
class ImportedTable:
    file: str
    title: str | None
    table: str | None  # truth table id this import maps to (None if it maps to none)
    profile_id: str | None
    profile: Any
    rows: tuple[ParsedRow, ...]
    currency: str | None
    date_format: str | None
    reconciliation: str
    failures: tuple[str, ...]
    questions: tuple[str, ...]
    answered: tuple[str, ...]  # question kinds answered with the locale default to proceed


def _truth_table_for(ds: Dataset, file: str, title: str | None, position: int) -> str | None:
    tables = ds.layout.get(file, {}).get("tables", [])
    for t in tables:
        if title is not None and t.get("title") == title:
            return str(t["table"])
    non_empty = [t for t in tables if t.get("n_rows", 1)]
    if title is None and position < len(non_empty):
        return str(non_empty[position]["table"])
    return None


def import_bytes(
    file: str,
    data: bytes,
    *,
    home_currency: str,
    answers: Mapping[str, str] | None = None,
    saved_profiles: Sequence[Any] = (),
) -> FileImport:
    return import_file(
        file,
        data,
        pack=uk_locale_pack(),
        home_currency=home_currency,
        answers=answers,
        saved_profiles=saved_profiles,
    )


def import_dataset(ds: Dataset, *, answer_with_defaults: bool = False) -> list[ImportedTable]:
    """Import every export of a dataset. With `answer_with_defaults`, blocking questions are
    answered with their pre-selected (locale default) option, as a user accepting the default
    would; otherwise blocked tables come back with no rows."""
    out: list[ImportedTable] = []
    for file in ds.layout:
        data = ds.file_bytes(file)
        fi = import_bytes(file, data, home_currency=ds.home_currency)
        answered: tuple[str, ...] = ()
        if answer_with_defaults:
            answers = {
                q.kind: q.preselected or (q.options[0] if q.options else "")
                for t in fi.tables
                for q in blocking_questions(t.result)
            }
            if answers:
                fi = import_bytes(file, data, home_currency=ds.home_currency, answers=answers)
                answered = tuple(sorted(answers))
        for i, t in enumerate(fi.tables):
            r = t.result
            out.append(
                ImportedTable(
                    file=file,
                    title=t.title,
                    table=_truth_table_for(ds, file, t.title, i),
                    profile_id=r.format_profile_id,
                    profile=t.profile,
                    rows=r.rows,
                    currency=r.detected_currency,
                    date_format=r.date_format,
                    reconciliation=r.reconciliation.status.value,
                    failures=r.reconciliation.failures,
                    questions=tuple(q.kind for q in r.questions),
                    answered=answered,
                )
            )
    return out


def expected_rows(ds: Dataset, table: str | None = None) -> list[dict[str, Any]]:
    """Truth rows the importer should produce (skip rows such as £0.00 card checks excluded)."""
    return [t for t in ds.truth if not t.get("skip") and (table is None or t.get("table") == table)]


def row_key(on: str, amount_minor: int) -> tuple[str, int]:
    return (on, amount_minor)


def row_precision_recall(
    parsed: Iterable[ParsedRow], truth: Iterable[Mapping[str, Any]]
) -> tuple[float | None, float | None, int, int, int]:
    """Multiset match on (date, amount to the penny, direction): (precision, recall, matched,
    parsed, truth). Direction is implied by the signed amount."""
    p = Counter(row_key(r.posted_on.isoformat(), r.amount_minor) for r in parsed)
    t = Counter(row_key(str(r["date"]), int(r["amount_minor"])) for r in truth)
    matched = sum((p & t).values())
    n_p, n_t = sum(p.values()), sum(t.values())
    return (
        matched / n_p if n_p else None,
        matched / n_t if n_t else None,
        matched,
        n_p,
        n_t,
    )


def first_row_of(ds: Dataset, table: str) -> int:
    for _f, t in truth_tables(ds):
        if t["table"] == table:
            return int(t["first_row"])
    raise KeyError(table)


def truth_by_source_row(ds: Dataset, table: str) -> dict[int, dict[str, Any]]:
    """Truth rows keyed by file row index (truth `row` is the 0-based data row)."""
    first = first_row_of(ds, table)
    return {first + int(t["row"]): t for t in ds.truth if t.get("table") == table}


# --------------------------------------------------------------------------- ledger


def bank_for(profile_id: str | None) -> str | None:
    """The bank key used for bank-category priors, from a built-in profile id."""
    if profile_id and profile_id.startswith("builtin."):
        return profile_id.split(".")[1].split("_")[0]
    return None


@dataclass(frozen=True)
class Ledger:
    """Transactions plus categorisations for one dataset, with truth labels attached by id."""

    txns: tuple[Transaction, ...]
    cats: tuple[Categorisation, ...]
    truth: Mapping[str, Mapping[str, Any]]  # txn id → truth row
    currency: str


def to_transactions(
    rows: Sequence[ParsedRow], account_id: str, pack: CategorisationPack, prefix: str
) -> list[Transaction]:
    out = []
    for r in rows:
        parsed = parse_narration(r.description, r.bank_type, pack)
        out.append(
            Transaction(
                id=f"txn_{prefix}_{r.source_row_index}",
                account_id=account_id,
                posted_on=r.posted_on,
                amount_minor=r.amount_minor,
                currency=r.currency,
                description=r.description,
                normalised=parsed.normalised,
                channel=parsed.channel,
                counterparty=parsed.counterparty,
                external_id=r.external_id,
                balance_after_minor=r.balance_after_minor,
                bank_category=r.bank_category,
                source_row_index=r.source_row_index,
            )
        )
    return out


def build_ledger(ds: Dataset, currency: str | None = None) -> Ledger:
    """Import → transactions → rules-only categorisation, for every table in `currency`
    (default: the workspace home currency). Blocking questions are answered with defaults."""
    pack = uk_categorisation_pack()
    want = currency or ds.home_currency
    txns: list[Transaction] = []
    cats: list[Categorisation] = []
    truth: dict[str, Mapping[str, Any]] = {}
    for imp in import_dataset(ds, answer_with_defaults=True):
        if imp.table is None or imp.currency != want:
            continue
        by_row = truth_by_source_row(ds, imp.table)
        ctx = CategoriseContext(bank=bank_for(imp.profile_id))
        for t in to_transactions(imp.rows, imp.table, pack, imp.table):
            txns.append(t)
            cats.append(categorise(t, pack, ctx))
            if t.source_row_index in by_row:
                truth[t.id] = by_row[t.source_row_index]
    order = sorted(range(len(txns)), key=lambda i: (txns[i].posted_on, txns[i].id))
    return Ledger(
        txns=tuple(txns[i] for i in order),
        cats=tuple(cats[i] for i in order),
        truth=truth,
        currency=want,
    )


TRANSFER_FLOWS = frozenset(
    {
        FlowKind.TRANSFER_OWN,
        FlowKind.TRANSFER_TO_UNTRACKED,
        FlowKind.TRANSFER_FROM_UNTRACKED,
        FlowKind.CARD_SETTLEMENT,
        FlowKind.SAVINGS_INVESTMENT,
    }
)


# --------------------------------------------------------------------------- helpers


def stable_seed(*parts: object) -> int:
    """docs/09 §7.1: int(sha256(canonical_json(parts))[:8], 16), stable across processes."""
    text = json.dumps([str(p) for p in parts], sort_keys=True, separators=(",", ":"))
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def months_back(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + (d.month - 1) - months, 12)
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError(d)


def categorisation_test_start(as_of: date) -> date:
    """docs/09 §3.8: the last 3 months are the categorisation test split."""
    return months_back(as_of, 3) + timedelta(days=1)


def majority(values: Iterable[str | None]) -> str | None:
    c = Counter(v for v in values if v)
    return c.most_common(1)[0][0] if c else None
