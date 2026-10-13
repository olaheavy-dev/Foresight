"""Export writers: render generated rows in each bank layout, recording where every row landed.

Every writer returns an `Export`: the file text, the (txn, table, data-row) placement used for the
truth files, and a layout truth (table boundaries, column roles, date format, sign convention,
skip rules, currency). Data-row indices are 0-based within their table; header and file rows are
0-based file line numbers.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from evals.generator.model import Txn, pounds, with_thousands

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
REVOLUT_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sept",
    "Oct",
    "Nov",
    "Dec",
)
MONZO_HEADER = (
    "Transaction ID,Date,Time,Type,Name,Emoji,Category,Amount,Currency,Local amount,"
    "Local currency,Notes and #tags,Address,Receipt,Description,Category split,"
    "Money Out,Money In"
)
ID_ALPHABET = list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


@dataclass
class Export:
    path: str  # relative to the dataset folder, e.g. "exports/monzo.csv"
    text: str
    placed: list[tuple[Txn, str, int]] = field(default_factory=list)
    layout: dict[str, Any] = field(default_factory=dict)


@dataclass
class Sheet:
    """Rows being assembled for one file, with table bookkeeping."""

    rows: list[list[str]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    placed: list[tuple[Txn, str, int]] = field(default_factory=list)

    def add(self, *cells: str) -> int:
        self.rows.append(list(cells))
        return len(self.rows) - 1

    def table(
        self,
        table_id: str,
        title: str | None,
        header: Sequence[str],
        txns: Sequence[Txn],
        render: Callable[[Txn], list[str]],
        **meta: Any,
    ) -> None:
        header_row = self.add(*header)
        first = len(self.rows)
        for i, t in enumerate(txns):
            self.add(*render(t))
            self.placed.append((t, table_id, i))
        self.tables.append(
            {
                "table": table_id,
                "title": title,
                "header_row": header_row,
                "first_row": first,
                "last_row": len(self.rows) - 1,
                "n_rows": len(txns),
                "headers": list(header),
                **meta,
            }
        )

    def text(self, delimiter: str = ",") -> str:
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
        w.writerows(self.rows)
        return buf.getvalue()


def balances(txns: Sequence[Txn], opening: int) -> list[int]:
    out, running = [], opening
    for t in txns:
        running += t.amount
        out.append(running)
    return out


def d_dmy(d: date, sep: str = "/", short_year: bool = False) -> str:
    y = f"{d.year % 100:02d}" if short_year else f"{d.year}"
    return f"{d.day:02d}{sep}{d.month:02d}{sep}{y}"


def d_text(
    d: date,
    months: Sequence[str] = MONTHS,
    pad: bool = True,
    short_year: bool = False,
    sep: str = " ",
) -> str:
    day = f"{d.day:02d}" if pad else f"{d.day}"
    y = f"{d.year % 100:02d}" if short_year else f"{d.year}"
    return f"{day}{sep}{months[d.month - 1]}{sep}{y}"


def narration(t: Txn) -> str:
    """Generic UK bank narration: payment code then descriptor (pot transfers become TFR)."""
    code = {"POT": "TFR", "": "DEB"}.get(t.code, t.code)
    return f"{code} {t.desc}"


# --------------------------------------------------------------------------- Monzo


def _monzo_id(rng: np.random.Generator) -> str:
    return "tx_0000" + "".join(rng.choice(ID_ALPHABET, 22))


def monzo(
    txns: Sequence[Txn],
    rng: np.random.Generator,
    path: str = "exports/monzo.csv",
    account: str = "acct_main",
) -> Export:
    sheet = Sheet()

    def render(t: Txn) -> list[str]:
        amount = pounds(t.amount)
        if t.monzo_type == "Card payment":
            city = "LEEDS" if "LEEDS" in t.desc else "LONDON"
            base = t.desc.replace(" LEEDS", "").strip()
            desc = f"{base[:22]:<23}{city:<14}GBR"
        elif t.monzo_type == "Pot transfer":
            desc = "pot_0000" + "".join(rng.choice(ID_ALPHABET, 14))
        else:
            desc = t.desc
        return [
            _monzo_id(rng),
            d_dmy(t.day),
            t.time,
            t.monzo_type,
            t.name,
            "",
            t.monzo_cat,
            amount,
            "GBP",
            amount,
            "GBP",
            "",
            "",
            "",
            desc,
            "",
            amount if t.amount < 0 else "",
            amount if t.amount > 0 else "",
        ]

    sheet.table(
        account,
        None,
        MONZO_HEADER.split(","),
        txns,
        render,
        columns={
            "id": "Transaction ID",
            "date": "Date",
            "time": "Time",
            "type": "Type",
            "description": "Name",
            "bank_category": "Category",
            "amount": "Amount",
            "currency": "Currency",
        },
        date_format="%d/%m/%Y",
        sign_convention="signed",
        decimal=".",
        currency="GBP",
        currency_source="column",
        balance_column=None,
        skip_rules=["zero_amount_card_check"],
    )
    return Export(
        path,
        sheet.text(),
        sheet.placed,
        {"format": "monzo", "delimiter": ",", "tables": sheet.tables},
    )


# --------------------------------------------------------------------------- generic


def generic_signed(
    txns: Sequence[Txn],
    opening: int,
    path: str = "exports/statement.csv",
    account: str = "acct_main",
    describe: Callable[[Txn], str] = narration,
) -> Export:
    sheet = Sheet()
    bal = dict(zip((t.seq for t in txns), balances(txns, opening), strict=True))
    sheet.table(
        account,
        None,
        ("Date", "Description", "Amount", "Balance"),
        txns,
        lambda t: [d_dmy(t.day), describe(t), pounds(t.amount), pounds(bal[t.seq])],
        columns={
            "date": "Date",
            "description": "Description",
            "amount": "Amount",
            "balance": "Balance",
        },
        date_format="%d/%m/%Y",
        sign_convention="signed",
        decimal=".",
        currency="GBP",
        currency_source="home_default",
        balance_column="Balance",
        skip_rules=[],
    )
    return Export(
        path,
        sheet.text(),
        sheet.placed,
        {"format": "generic_signed", "delimiter": ",", "tables": sheet.tables},
    )


def generic_in_out(
    txns: Sequence[Txn],
    opening: int,
    path: str = "exports/statement.csv",
    account: str = "acct_main",
) -> Export:
    sheet = Sheet()
    bal = dict(zip((t.seq for t in txns), balances(txns, opening), strict=True))

    def render(t: Txn) -> list[str]:
        out = pounds(-t.amount) if t.amount < 0 else ""
        inn = pounds(t.amount) if t.amount > 0 else ""
        return [d_text(t.day), narration(t), out, inn, pounds(bal[t.seq])]

    sheet.table(
        account,
        None,
        ("Date", "Details", "Paid out", "Paid in", "Balance"),
        txns,
        render,
        columns={
            "date": "Date",
            "description": "Details",
            "out": "Paid out",
            "in": "Paid in",
            "balance": "Balance",
        },
        date_format="%d %b %Y",
        sign_convention="split_out_in",
        decimal=".",
        currency="GBP",
        currency_source="home_default",
        balance_column="Balance",
        skip_rules=[],
    )
    return Export(
        path,
        sheet.text(),
        sheet.placed,
        {"format": "generic_in_out", "delimiter": ",", "tables": sheet.tables},
    )


# --------------------------------------------------------------------------- Revolut

REVOLUT_CAT = {
    "groceries": "Groceries",
    "food.eating_out": "Restaurants",
    "food.delivery": "Restaurants",
    "transport.public": "Transport",
    "shopping.general": "Shopping",
    "transfer.own": "Transfers",
    "transfer.from_untracked": "Transfers",
    "inflow_unconfirmed": "Transfers",
}
SYMBOL = {"GBP": "£", "EUR": "€", "USD": "$"}


def _rev_money(minor: int, cur: str) -> str:
    sign = "-" if minor < 0 else ""
    return f"{sign}{SYMBOL[cur]}{with_thousands(minor)}"


def revolut(
    pockets: Sequence[tuple[str, str, Sequence[Txn], int]],
    path: str = "exports/revolut_consolidated.csv",
) -> Export:
    """pockets: (account id, currency, txns, opening balance)."""
    sheet = Sheet()
    sheet.add("Current Accounts Summaries")
    sheet.add("Product", "Currency", "Opening balance", "Money out", "Money in", "Closing balance")
    for _acct, cur, txns, opening in pockets:
        out = sum(t.amount for t in txns if t.amount < 0)
        inn = sum(t.amount for t in txns if t.amount > 0)
        sheet.add(
            "Personal Account",
            cur,
            _rev_money(opening, cur),
            _rev_money(out, cur),
            _rev_money(inn, cur),
            _rev_money(opening + out + inn, cur),
        )
    sheet.add("---------")
    header = (
        "Date",
        "Description",
        "Category",
        "Money in/out",
        "Balance",
        "Tax withheld",
        "Other taxes",
        "Fees",
        "",
        "",
        "",
        "",
    )
    for acct, cur, txns, opening in pockets:
        sheet.add(f"Personal Account ({cur})")
        sheet.add("Transaction statement")
        bal = dict(zip((t.seq for t in txns), balances(txns, opening), strict=True))
        zero = _rev_money(0, cur)

        def render(
            t: Txn, cur: str = cur, bal: dict[int, int] = bal, zero: str = zero
        ) -> list[str]:
            return [
                d_text(t.day, REVOLUT_MONTHS, pad=False),
                t.name,
                REVOLUT_CAT.get(t.category or "", "General"),
                _rev_money(t.amount, cur),
                _rev_money(bal[t.seq], cur),
                zero,
                zero,
                zero,
                "",
                "",
                "",
                "",
            ]

        sheet.table(
            acct,
            f"Personal Account ({cur})",
            header,
            txns,
            render,
            columns={
                "date": "Date",
                "description": "Description",
                "bank_category": "Category",
                "amount": "Money in/out",
                "balance": "Balance",
            },
            date_format="%-d %b %Y (Sept)",
            sign_convention="signed",
            decimal=".",
            currency=cur,
            currency_source="table_title",
            balance_column="Balance",
            skip_rules=["total_row", "separator_row", "summary_section"],
        )
        total = sum(t.amount for t in txns)
        sheet.add(
            "Total",
            "",
            "",
            _rev_money(total, cur),
            _rev_money(opening + total, cur),
            zero,
            zero,
            zero,
            "",
            "",
            "",
            "",
        )
        sheet.add("---------")
    return Export(
        path,
        sheet.text(),
        sheet.placed,
        {"format": "revolut_consolidated", "delimiter": ",", "tables": sheet.tables},
    )


# --------------------------------------------------------------------------- held-out layouts


def pennine(
    txns: Sequence[Txn], opening: int, holder: str, path: str = "exports/pennine_statement.csv"
) -> Export:
    """C1: preamble rows, Posting Date/Narrative/Withdrawals/Lodgements/Running Total, dd/mm/yy."""
    sheet = Sheet()
    first, last = txns[0].day, txns[-1].day
    sheet.add("Pennine Building Society")
    sheet.add("Statement for", holder)
    sheet.add("Period", f"{d_dmy(first, short_year=True)} to {d_dmy(last, short_year=True)}")
    sheet.add("Brought forward", pounds(opening))
    sheet.add()
    bal = dict(zip((t.seq for t in txns), balances(txns, opening), strict=True))
    sheet.table(
        "acct_main",
        None,
        ("Posting Date", "Narrative", "Withdrawals", "Lodgements", "Running Total"),
        txns,
        lambda t: [
            d_dmy(t.day, short_year=True),
            t.desc,
            pounds(-t.amount) if t.amount < 0 else "",
            pounds(t.amount) if t.amount > 0 else "",
            pounds(bal[t.seq]),
        ],
        columns={
            "date": "Posting Date",
            "description": "Narrative",
            "out": "Withdrawals",
            "in": "Lodgements",
            "balance": "Running Total",
        },
        date_format="%d/%m/%y",
        sign_convention="split_out_in",
        decimal=".",
        currency="GBP",
        currency_source="home_default",
        balance_column="Running Total",
        skip_rules=["preamble_rows"],
    )
    return Export(
        path,
        sheet.text(),
        sheet.placed,
        {"format": "C1_pennine", "delimiter": ",", "tables": sheet.tables},
    )


def harbour_vale(txns: Sequence[Txn], path: str = "exports/harbour_vale.csv") -> Export:
    """C2: semicolon-delimited, comma decimals, Value Day;Purpose;Debit;Credit, EUR preamble."""
    sheet = Sheet()
    sheet.add("Harbour & Vale")
    sheet.add("Currency", "EUR")
    sheet.add()
    sheet.table(
        "acct_main",
        None,
        ("Value Day", "Purpose", "Debit", "Credit"),
        txns,
        lambda t: [
            d_dmy(t.day, "."),
            t.desc,
            with_thousands(-t.amount, ".", ",") if t.amount < 0 else "",
            with_thousands(t.amount, ".", ",") if t.amount > 0 else "",
        ],
        columns={"date": "Value Day", "description": "Purpose", "out": "Debit", "in": "Credit"},
        date_format="%d.%m.%Y",
        sign_convention="split_out_in",
        decimal=",",
        group=".",
        currency="EUR",
        currency_source="preamble",
        balance_column=None,
        skip_rules=["preamble_rows"],
    )
    return Export(
        path,
        sheet.text(";"),
        sheet.placed,
        {"format": "C2_harbour_vale", "delimiter": ";", "tables": sheet.tables},
    )


def northgate(
    current: Sequence[Txn],
    savings: Sequence[Txn],
    rng: np.random.Generator,
    path: str = "exports/northgate.csv",
) -> Export:
    """C3: two tables (current, savings), Txn Ref/When/What/Out(£)/In(£), DR/CR suffixes,
    trailing totals block."""
    sheet = Sheet()
    sheet.add("Northgate Bank")
    header = ("Txn Ref", "When", "What", "Out(£)", "In(£)")
    totals = []
    for acct, title, txns in (
        ("acct_main", "Current Account", current),
        ("acct_savings", "Savings Account", savings),
    ):
        sheet.add()
        sheet.add(title)
        sheet.table(
            acct,
            title,
            header,
            txns,
            lambda t: [
                f"NG{int(rng.integers(10_000_000, 99_999_999))}",
                d_text(t.day, sep="-", short_year=True),
                t.desc,
                f"{pounds(-t.amount)} DR" if t.amount < 0 else "",
                f"{pounds(t.amount)} CR" if t.amount > 0 else "",
            ],
            columns={
                "id": "Txn Ref",
                "date": "When",
                "description": "What",
                "out": "Out(£)",
                "in": "In(£)",
            },
            date_format="%d-%b-%y",
            sign_convention="dr_cr_suffix",
            decimal=".",
            currency="GBP",
            currency_source="header_symbol",
            balance_column=None,
            skip_rules=["title_rows", "totals_block"],
        )
        totals.append(
            (
                title,
                sum(-t.amount for t in txns if t.amount < 0),
                sum(t.amount for t in txns if t.amount > 0),
            )
        )
    sheet.add()
    sheet.add("Totals")
    for title, out, inn in totals:
        sheet.add(title, "", "", f"{pounds(out)} DR", f"{pounds(inn)} CR")
    return Export(
        path,
        sheet.text(),
        sheet.placed,
        {"format": "C3_northgate", "delimiter": ",", "tables": sheet.tables},
    )


def fenwick(
    txns: Sequence[Txn], opening: int, holder: str, path: str = "exports/fenwick.csv"
) -> Export:
    """C4: address block, header on row 9 (1-based), single Amount with (12.40) debits."""
    sheet = Sheet()
    for line in (
        "Fenwick Bank",
        holder,
        "14 Larkspur Row",
        "Harrowgate Vale",
        "Leeds",
        "LS99 9ZZ",
        "",
        f"Statement {d_text(txns[0].day)} to {d_text(txns[-1].day)}",
    ):
        sheet.add(line)
    bal = dict(zip((t.seq for t in txns), balances(txns, opening), strict=True))

    def money(minor: int) -> str:
        return f"({with_thousands(minor)})" if minor < 0 else with_thousands(minor)

    sheet.table(
        "acct_main",
        None,
        ("Date", "Transaction details", "Amount", "Balance"),
        txns,
        lambda t: [d_text(t.day), t.desc, money(t.amount), money(bal[t.seq])],
        columns={
            "date": "Date",
            "description": "Transaction details",
            "amount": "Amount",
            "balance": "Balance",
        },
        date_format="%d %b %Y",
        sign_convention="brackets_negative",
        decimal=".",
        group=",",
        currency="GBP",
        currency_source="home_default",
        balance_column="Balance",
        skip_rules=["address_block"],
    )
    return Export(
        path,
        sheet.text(),
        sheet.placed,
        {"format": "C4_fenwick", "delimiter": ",", "tables": sheet.tables},
    )


# --------------------------------------------------------------------------- currency variants


def euro_semicolon(
    txns: Sequence[Txn], opening: int, path: str = "exports/statement.csv"
) -> Export:
    """G1: semicolon, comma decimals, dd.mm.yyyy, € in the amounts, no currency column."""
    sheet = Sheet()
    bal = dict(zip((t.seq for t in txns), balances(txns, opening), strict=True))

    def eur(minor: int) -> str:
        return f"{'-' if minor < 0 else ''}{with_thousands(minor, '.', ',')} €"

    sheet.table(
        "acct_main",
        None,
        ("Date", "Description", "Amount", "Balance"),
        txns,
        lambda t: [d_dmy(t.day, "."), t.desc, eur(t.amount), eur(bal[t.seq])],
        columns={
            "date": "Date",
            "description": "Description",
            "amount": "Amount",
            "balance": "Balance",
        },
        date_format="%d.%m.%Y",
        sign_convention="signed",
        decimal=",",
        group=".",
        currency="EUR",
        currency_source="symbol",
        balance_column="Balance",
        skip_rules=[],
    )
    return Export(
        path,
        sheet.text(";"),
        sheet.placed,
        {"format": "G1_eur", "delimiter": ";", "tables": sheet.tables},
    )


def bare_dollar(txns: Sequence[Txn], opening: int, path: str = "exports/statement.csv") -> Export:
    """G3: bare $ amounts (USD/CAD/AUD/... is ambiguous: the importer must ask)."""
    sheet = Sheet()
    bal = dict(zip((t.seq for t in txns), balances(txns, opening), strict=True))

    def usd(minor: int) -> str:
        return f"{'-' if minor < 0 else ''}${with_thousands(minor)}"

    sheet.table(
        "acct_main",
        None,
        ("Date", "Description", "Amount", "Balance"),
        txns,
        lambda t: [d_dmy(t.day), t.desc, usd(t.amount), usd(bal[t.seq])],
        columns={
            "date": "Date",
            "description": "Description",
            "amount": "Amount",
            "balance": "Balance",
        },
        date_format="%d/%m/%Y",
        sign_convention="signed",
        decimal=".",
        group=",",
        currency="USD",
        currency_source="user_confirmed",
        currency_ambiguous=True,
        balance_column="Balance",
        skip_rules=[],
    )
    return Export(
        path,
        sheet.text(),
        sheet.placed,
        {"format": "G3_dollar", "delimiter": ",", "tables": sheet.tables},
    )
