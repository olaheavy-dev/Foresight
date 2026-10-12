"""Find the transaction table(s) inside a CSV, without assuming the header is on row 1.

Real exports put summaries above the table, split one file into several tables (one per currency
pocket), and end tables with `Total` or `---------` rows. The locator scans for header-like rows
and returns each table with its title (the nearest label row above it) and body rows.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

DATE_WORDS = ("date", "posted", "transaction date", "value date", "booking date", "completed")
AMOUNT_WORDS = (
    "amount", "money in", "money out", "paid in", "paid out", "debit", "credit", "in/out",
    "withdrawal", "deposit", "value",
)  # fmt: skip
TEXT_WORDS = (
    "description", "details", "narration", "name", "merchant", "payee", "reference", "memo",
    "particulars", "transaction",
)  # fmt: skip
_SEPARATOR = re.compile(r"^[-=_*\s]{3,}$")
_NUMERICISH = re.compile(r"^[\s£€$₹¥(+\-−]*[\d.,\s]+[)A-Za-z\s]*$")


@dataclass(frozen=True)
class Table:
    title: str | None  # e.g. "Personal Account (GBP)"
    header_row: int  # 0-based row index in the file
    headers: tuple[str, ...]
    rows: tuple[tuple[int, tuple[str, ...]], ...]  # (file row index, cells)


def decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")  # pragma: no cover


def read_rows(text: str) -> list[list[str]]:
    sample = text[:4096]
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        if sample.count(";") > sample.count(","):
            delimiter = ";"
    return [list(r) for r in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _cells(row: list[str]) -> list[str]:
    return [c.strip() for c in row]


def is_header_like(row: list[str]) -> bool:
    cells = [c.lower() for c in _cells(row) if c]
    if len(cells) < 3:
        return False
    if sum(1 for c in cells if _NUMERICISH.match(c)) > len(cells) // 3:
        return False
    has_date = any(c in DATE_WORDS or c.startswith("date") for c in cells)
    has_amount = any(any(w in c for w in AMOUNT_WORDS) for c in cells)
    has_text = any(any(w in c for w in TEXT_WORDS) for c in cells)
    return has_date and has_amount and has_text


def _ends_table(row: list[str]) -> bool:
    cells = _cells(row)
    non_empty = [c for c in cells if c]
    if not non_empty:
        return True
    first = non_empty[0].lower()
    return first in ("total", "totals") or bool(_SEPARATOR.match(non_empty[0]))


_CURRENCY_TITLE = re.compile(r"\(([A-Z]{3})\)")


def _title_above(rows: list[list[str]], header_row: int) -> str | None:
    """The label above a table. A label naming a currency, e.g. "Personal Account (GBP)", wins
    over a generic one such as "Transaction statement"."""
    labels: list[str] = []
    for i in range(header_row - 1, max(header_row - 7, -1), -1):
        non_empty = [c for c in _cells(rows[i]) if c]
        if len(non_empty) == 1 and not _SEPARATOR.match(non_empty[0]):
            labels.append(non_empty[0])
    for label in labels:
        if _CURRENCY_TITLE.search(label):
            return label
    return labels[0] if labels else None


def locate_tables(text: str) -> list[Table]:
    rows = read_rows(text)
    tables: list[Table] = []
    i = 0
    while i < len(rows):
        if not is_header_like(rows[i]):
            i += 1
            continue
        header_row = i
        headers = tuple(_cells(rows[i]))
        body: list[tuple[int, tuple[str, ...]]] = []
        i += 1
        while i < len(rows) and not _ends_table(rows[i]) and not is_header_like(rows[i]):
            cells = _cells(rows[i])
            body.append((i, tuple(cells + [""] * (len(headers) - len(cells)))))
            i += 1
        tables.append(Table(_title_above(rows, header_row), header_row, headers, tuple(body)))
    return tables
