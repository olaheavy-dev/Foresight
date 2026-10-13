"""E-LOC deterministic rows 1–7 and 13 (docs/09 §4A) on the datasets generated in Stage 1.

G2 (yen), G4 (EUR pocket forecast), P4 (India) and the XLS/XLSX exports are not generated yet, so
E-LOC-6 and E-LOC-7 are null ("not run") and the other rows cover the files that exist.
"""

from __future__ import annotations

from typing import Any

from backend.finance_core.importers import blocking_questions
from backend.finance_core.money import exponent
from evals.common import (
    expected_rows,
    import_bytes,
    import_dataset,
    load_dataset,
    row_precision_recall,
    truth_tables,
)
from evals.metrics import r4
from evals.suites import Target, target

SUITE_ID = "E-LOC"
NAME = "locales"

CURRENCY_SETS = ["P1-base", "G1-eur", "S14-side-account"]
FORMAT_SETS = ["P1-base", "P2-base", "G1-eur", "S14-side-account"]
AMBIGUOUS = {"G3-dollar": "currency", "G5-ambiguous-date": "date_order"}


def _order(strptime: str) -> str:
    """'%d/%m/%Y' → 'DMY' (the answer a user gives to a date-order question)."""
    letters = [c for c in strptime.replace("%-", "%").split("%")[1:] if c]
    return "".join(
        {"d": "D", "m": "M", "b": "M", "Y": "Y", "y": "Y"}.get(c[0], "") for c in letters
    )


def _currency_detection() -> dict[str, Any]:
    hit = total = 0
    rows: list[dict[str, Any]] = []
    for name in CURRENCY_SETS:
        ds = load_dataset(name)
        imports = {i.table: i for i in import_dataset(ds)}
        for _file, t in truth_tables(ds):
            if not t.get("n_rows"):
                continue  # an empty pocket is skipped by the importer, nothing to detect
            got = imports.get(str(t["table"]))
            want = str(t.get("currency") or ds.accounts[0]["currency"])
            ok = got is not None and got.currency == want
            hit += ok
            total += 1
            rows.append(
                {
                    "dataset": name,
                    "table": t["table"],
                    "expected": want,
                    "detected": got.currency if got else None,
                    "ok": ok,
                }
            )
    return {"accuracy": r4(hit / total) if total else None, "n": total, "tables": rows}


def _formats_and_units() -> dict[str, Any]:
    """E-LOC-3/4/5: a file's number and date formats are right iff every truth row parses to the
    same date and the exact minor-unit amount (recall and precision 1.0)."""
    files: list[dict[str, Any]] = []
    for name in FORMAT_SETS:
        ds = load_dataset(name)
        imports = import_dataset(ds)
        for file in ds.layout:
            rows = [r for i in imports if i.file == file for r in i.rows]
            truth = [t for t in expected_rows(ds) if t["file"] == file]
            p, r, *_ = row_precision_recall(rows, truth)
            days_over_12 = any(int(str(t["date"])[8:10]) > 12 for t in truth)
            exp = {exponent(str(t["currency"])) for t in truth}
            files.append(
                {
                    "dataset": name,
                    "file": file,
                    "row_precision": r4(p),
                    "row_recall": r4(r),
                    "has_day_over_12": days_over_12,
                    "exponents": sorted(exp),
                    "exact": p == 1.0 and r == 1.0,
                }
            )
    exact = [f["exact"] for f in files]
    dated = [f["exact"] for f in files if f["has_day_over_12"]]
    return {
        "number_format_acc": r4(sum(exact) / len(exact)) if exact else None,
        "date_order_acc": r4(sum(dated) / len(dated)) if dated else None,
        "minor_unit_exact": all(exact) if exact else None,
        "files": files,
    }


def _h13() -> dict[str, Any]:
    """E-LOC-2 and E-LOC-13 on G3 (bare $) and G5 (no day > 12)."""
    out: dict[str, Any] = {}
    all_ok = True
    for name, kind in AMBIGUOUS.items():
        ds = load_dataset(name)
        file = next(iter(ds.layout))
        data = ds.file_bytes(file)
        first = import_bytes(file, data, home_currency=ds.home_currency)
        asked = [q.kind for t in first.tables for q in blocking_questions(t.result)]
        committed = sum(len(t.result.rows) for t in first.tables)
        spec = ds.layout[file]["tables"][0]
        answer = str(spec["currency"]) if kind == "currency" else _order(str(spec["date_format"]))
        answered = import_bytes(file, data, home_currency=ds.home_currency, answers={kind: answer})
        rows = [r for t in answered.tables for r in t.result.rows]
        p, r, *_ = row_precision_recall(rows, expected_rows(ds))
        saved = [t.profile for t in answered.tables if t.profile is not None]
        again = import_bytes(file, data, home_currency=ds.home_currency, saved_profiles=saved)
        repeat = [q.kind for t in again.tables for q in blocking_questions(t.result)]
        ok = asked == [kind] and committed == 0 and p == 1.0 and r == 1.0 and not repeat
        all_ok &= ok
        out[name] = {
            "expected_question": kind,
            "questions_raised": asked,
            "rows_committed_before_answer": committed,
            "answer": answer,
            "row_precision_after_answer": r4(p),
            "row_recall_after_answer": r4(r),
            "repeat_questions_with_saved_profile": len(repeat),
            "ok": ok,
        }
    return {"cases": out, "all_ok": all_ok}


def run(fast: bool = False) -> dict[str, Any]:
    cur = _currency_detection()
    fmt = _formats_and_units()
    h13 = _h13()
    g3 = h13["cases"]["G3-dollar"]
    ambiguous_asked = (
        g3["questions_raised"] == ["currency"] and g3["rows_committed_before_answer"] == 0
    )
    uncommitted = all(c["rows_committed_before_answer"] == 0 for c in h13["cases"].values())
    repeats = sum(c["repeat_questions_with_saved_profile"] for c in h13["cases"].values())
    metrics: dict[str, Any] = {
        "currency_detection_acc": cur["accuracy"],
        "ambiguous_symbol_asked": ambiguous_asked,
        "number_format_acc": fmt["number_format_acc"],
        "date_order_acc": fmt["date_order_acc"],
        "minor_unit_exact": fmt["minor_unit_exact"],
        "cross_currency_violations": None,
        "xls_csv_parity": None,
        "h13": {
            "uncommitted_until_answered": uncommitted,
            "llm_calls": 0,
            "repeat_questions": repeats,
            "all_clauses_ok": h13["all_ok"],
        },
        "detail": {"currency": cur, "formats": fmt, "h13": h13["cases"]},
        "not_run": {
            "E-LOC-6": "G4 (EUR pocket forecast) not generated yet",
            "E-LOC-7": "XLS/XLSX exports not generated yet (Tier 1 XLSX is a later task)",
        },
    }
    targets: list[Target] = [
        target(
            "E-LOC-1", "Currency detection", cur["accuracy"], ">=", 1.0, ", ".join(CURRENCY_SETS)
        ),
        target(
            "E-LOC-2", "Ambiguous $ asked, nothing committed", float(ambiguous_asked), "==", 1, "G3"
        ),
        target(
            "E-LOC-3",
            "Number format inference",
            fmt["number_format_acc"],
            ">=",
            1.0,
            ", ".join(FORMAT_SETS),
        ),
        target(
            "E-LOC-4",
            "Date order inference (files with day > 12)",
            fmt["date_order_acc"],
            ">=",
            1.0,
            ", ".join(FORMAT_SETS),
        ),
        target(
            "E-LOC-5",
            "Minor units exact",
            float(bool(fmt["minor_unit_exact"])),
            "==",
            1,
            ", ".join(FORMAT_SETS),
        ),
        target(
            "E-LOC-13",
            "H13: uncommitted until answered · 0 LLM calls · 0 repeat questions",
            float(h13["all_ok"]),
            "==",
            1,
            "G3, G5",
        ),
    ]
    notes = [
        "E-LOC-6 and E-LOC-7 are null: G4 and the XLS/XLSX exports are not generated yet.",
        "E-LOC-13 answers with the truth value (USD for G3, the file's real date order for G5).",
        "LLM calls are 0 by construction: finance_core has no model client.",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
