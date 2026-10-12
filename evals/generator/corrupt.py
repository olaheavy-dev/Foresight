"""CSV-CORRUPT: 20 small files, each with exactly one injected defect (docs/09 §3.1).

Ten generic files with a running balance (broken balance ×4, dropped row ×3, shifted column ×3)
and ten Monzo-style files without a balance (duplicated row ×4, shifted column ×3, wrong sign
convention ×3). Each file has a truth JSON naming the defect, the first failing data row (0-based)
and the expected outcome.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from evals.generator.model import Streams, pounds
from evals.generator.writers import ID_ALPHABET, MONZO_HEADER

MERCHANTS = (
    ("TESCO STORES 3021", "Tesco", "Groceries", 1800),
    ("PRET A MANGER 0412", "Pret", "Eating out", 650),
    ("NORTHERN TRAINS", "Northern", "Transport", 540),
    ("AMAZON.CO.UK*K2B7Q", "Amazon", "Shopping", 2299),
    ("OCTOPUS ENERGY", "Octopus Energy", "Bills", 7800),
    ("DELIVEROO", "Deliveroo", "Eating out", 1690),
    ("BOOTS 1180", "Boots", "Personal care", 1125),
    ("COSTA COFFEE 22", "Costa", "Eating out", 395),
)
GENERIC_DEFECTS = ["broken_balance"] * 4 + ["dropped_row"] * 3 + ["shifted_column"] * 3
MONZO_DEFECTS = ["duplicated_row"] * 4 + ["shifted_column"] * 3 + ["wrong_sign_convention"] * 3
OUTCOME = {
    "broken_balance": "rejected",
    "dropped_row": "rejected",
    "shifted_column": "rejected",
    "duplicated_row": "flagged",
    "wrong_sign_convention": "flagged",
}


@dataclass(frozen=True)
class CorruptCase:
    name: str
    kind: str  # generic | monzo
    defect: str
    clean_rows: list[list[str]]  # including header
    rows: list[list[str]]  # including header
    first_failing_row: int  # 0-based data row

    def truth(self) -> dict[str, object]:
        return {
            "file": f"{self.name}.csv",
            "format": self.kind,
            "defect": self.defect,
            "first_failing_row": self.first_failing_row,
            "expected_outcome": OUTCOME[self.defect],
            "data_rows": len(self.rows) - 1,
            "clean_data_rows": len(self.clean_rows) - 1,
        }


def to_csv(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def _base_rows(rng: np.random.Generator, n: int) -> list[tuple[date, str, str, str, int]]:
    d = date(2026, 9, 1)
    out = []
    for i in range(n):
        d += timedelta(days=int(rng.integers(0, 3)))
        if i == 3:
            out.append((d, "ACME ANALYTICS LTD SALARY", "Acme Analytics Ltd", "Income", 210000))
            continue
        desc, name, cat, typical = MERCHANTS[int(rng.integers(0, len(MERCHANTS)))]
        amt = -max(100, int(typical * float(rng.uniform(0.6, 1.4))))
        out.append((d, desc, name, cat, amt))
    return out


def _generic(rng: np.random.Generator, defect: str, name: str) -> CorruptCase:
    base = _base_rows(rng, int(rng.integers(12, 19)))
    bal = 84000
    clean = [["Date", "Description", "Amount", "Balance"]]
    for d, desc, _, _, amt in base:
        bal += amt
        clean.append([d.strftime("%d/%m/%Y"), f"DEB {desc}", pounds(amt), pounds(bal)])
    k = int(rng.integers(4, len(base) - 2))  # data row that fails
    rows = [r[:] for r in clean]
    if defect == "broken_balance":
        off = int(rng.choice([-1000, 1000, -1, 1, 250]))
        minor = round(float(rows[k + 1][3]) * 100) + off
        rows[k + 1][3] = pounds(minor)
    elif defect == "dropped_row":
        del rows[k + 1]  # row k is now the original k+1, whose balance no longer chains
    else:  # shifted_column: an unquoted comma split the description into two cells
        r = rows[k + 1]
        rows[k + 1] = [r[0], r[1][:8].rstrip(), r[1][8:].lstrip(), r[2], r[3]]
    return CorruptCase(name, "generic", defect, clean, rows, k)


def _monzo(rng: np.random.Generator, defect: str, name: str) -> CorruptCase:
    base = _base_rows(rng, int(rng.integers(12, 19)))
    clean = [MONZO_HEADER.split(",")]
    for i, (d, desc, nm, cat, amt) in enumerate(base):
        tid = "tx_0000" + "".join(rng.choice(ID_ALPHABET, 22))
        a = pounds(amt)
        typ = "Bacs (Direct Credit)" if amt > 0 else "Card payment"
        clean.append(
            [
                tid,
                d.strftime("%d/%m/%Y"),
                f"{9 + i % 12:02d}:{(7 * i) % 60:02d}:00",
                typ,
                nm,
                "",
                cat,
                a,
                "GBP",
                a,
                "GBP",
                "",
                "",
                "",
                desc,
                "",
                a if amt < 0 else "",
                a if amt > 0 else "",
            ]
        )
    k = int(rng.integers(4, len(base) - 2))
    rows = [r[:] for r in clean]
    if defect == "duplicated_row":
        rows.insert(k + 1, rows[k][:])  # data row k-1 repeated: the copy (data row k) fails
    elif defect == "shifted_column":
        r = rows[k + 1]
        rows[k + 1] = r[:4] + [r[4][:3], r[4][3:]] + r[5:]
    else:  # wrong_sign_convention: every Amount inverted, contradicting Money Out / Money In
        for r in rows[1:]:
            r[7] = r[9] = pounds(-round(float(r[7]) * 100))
        k = 0
    return CorruptCase(name, "monzo", defect, clean, rows, k)


def build_corrupt(seed: int) -> list[CorruptCase]:
    out = []
    for i, defect in enumerate(GENERIC_DEFECTS):
        rng = Streams(seed, f"CSV-CORRUPT:generic:{i}")["fixed"]
        out.append(_generic(rng, defect, f"generic_{i + 1:02d}_{defect}"))
    for i, defect in enumerate(MONZO_DEFECTS):
        rng = Streams(seed, f"CSV-CORRUPT:monzo:{i}")["fixed"]
        out.append(_monzo(rng, defect, f"monzo_{i + 1:02d}_{defect}"))
    return out
