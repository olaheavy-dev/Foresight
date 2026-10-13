"""Synthetic generator: determinism, manifests, export layouts, calendar rules, truth alignment."""

from __future__ import annotations

import csv
import difflib
import io
import json
import re
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from evals.generator import PRIMARY_SEED
from evals.generator.__main__ import main
from evals.generator.build import (
    ALL_NAMES,
    CORRUPT,
    DATASETS,
    DATASETS_DIR,
    file_hashes,
    load_truth_transactions,
    render_dataset,
)
from evals.generator.corrupt import GENERIC_DEFECTS, MONZO_DEFECTS, build_corrupt, to_csv
from evals.generator.ukcalendar import is_working_day
from evals.generator.writers import MONZO_HEADER

P1 = DATASETS_DIR / "P1-base"
END = date(2026, 10, 11)


def _walk(obj: Any) -> list[Any]:
    if isinstance(obj, dict):
        return [x for v in obj.values() for x in _walk(v)]
    if isinstance(obj, list):
        return [x for v in obj for x in _walk(v)]
    return [obj]


# --------------------------------------------------------------------------- determinism


def test_same_seed_gives_identical_bytes() -> None:
    assert render_dataset("P1-base", PRIMARY_SEED) == render_dataset("P1-base", PRIMARY_SEED)
    assert render_dataset(CORRUPT, PRIMARY_SEED) == render_dataset(CORRUPT, PRIMARY_SEED)


def test_different_seed_changes_output() -> None:
    a = render_dataset("P2-base", PRIMARY_SEED)
    b = render_dataset("P2-base", PRIMARY_SEED + 1)
    assert a["exports/statement.csv"] != b["exports/statement.csv"]


# --------------------------------------------------------------------------- manifests


def test_committed_datasets_match_manifest() -> None:
    manifest = json.loads((DATASETS_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == PRIMARY_SEED
    assert file_hashes(DATASETS_DIR) == manifest["files"]
    sha_lines = (DATASETS_DIR / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines()
    assert {rel: h for h, _, rel in (ln.partition("  ") for ln in sha_lines)} == manifest["files"]
    assert {Path(k).parts[0] for k in manifest["files"]} == set(ALL_NAMES)
    assert manifest["total_bytes"] < 5_500_000


def test_verify_manifest_passes_then_detects_tampering(tmp_path: Path) -> None:
    assert main(["--all", "--out", str(tmp_path)]) == 0
    assert main(["--verify-manifest", "--out", str(tmp_path)]) == 0
    target = tmp_path / "P1-base" / "exports" / "monzo.csv"
    target.write_bytes(target.read_bytes().replace(b"-12", b"-13", 1) + b"\n")
    assert main(["--verify-manifest", "--out", str(tmp_path)]) == 1


def test_alias_p1_generates_base_and_clean(tmp_path: Path) -> None:
    assert main(["--persona", "P1", "--out", str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_dir()) == ["P1-base", "P1-clean"]


def test_json_outputs_have_no_floats() -> None:
    for path in DATASETS_DIR.rglob("*.json*"):
        text = path.read_text(encoding="utf-8")
        docs = (
            [json.loads(ln) for ln in text.splitlines()]
            if path.suffix == ".jsonl"
            else [json.loads(text)]
        )
        assert not [x for d in docs for x in _walk(d) if isinstance(x, float)], path
        assert "\r" not in text


# --------------------------------------------------------------------------- Monzo export


def test_monzo_header_exact_and_no_balance_column() -> None:
    first = (P1 / "exports" / "monzo.csv").read_text(encoding="utf-8").splitlines()[0]
    assert first == MONZO_HEADER
    assert "balance" not in first.lower()


def test_monzo_card_checks_are_zero_and_skipped() -> None:
    truth = load_truth_transactions(P1)
    skips = [r for r in truth if r.get("skip")]
    assert len(skips) == 2
    assert all(r["amount_minor"] == 0 and r["category"] is None for r in skips)


# --------------------------------------------------------------------------- P1 calendar rules


def test_p1_salary_previous_working_day_and_early_december() -> None:
    truth = load_truth_transactions(P1)
    paydays = [date.fromisoformat(r["date"]) for r in truth if r.get("income") == "inc_salary"]
    assert len(paydays) == 12
    assert all(r["amount_minor"] == 405000 for r in truth if r.get("income") == "inc_salary")
    assert all(is_working_day(d) for d in paydays)
    assert date(2026, 2, 27) in paydays  # 28 Feb 2026 is a Saturday
    assert date(2026, 6, 26) in paydays  # 28 Jun 2026 is a Sunday
    assert date(2025, 12, 18) in paydays  # Christmas pay comes early
    for d in paydays:
        if d.month != 12:
            assert d.day == 28 or all(
                not is_working_day(d + timedelta(days=i)) for i in range(1, 29 - d.day)
            )


def test_p1_council_tax_absent_in_february_and_march() -> None:
    truth = load_truth_transactions(P1)
    months = {r["date"][5:7] for r in truth if r.get("recurring") == "rob_council_tax"}
    assert months == {"04", "05", "06", "07", "08", "09", "10", "11", "12", "01"}


def test_p1_food_delivery_last_30_days_and_prior_median() -> None:
    food = [r for r in load_truth_transactions(P1) if r["category"] == "food.delivery"]
    totals = []
    for k in range(4):
        lo, hi = END - timedelta(days=29 + 30 * k), END - timedelta(days=30 * k)
        totals.append(
            [-r["amount_minor"] for r in food if lo <= date.fromisoformat(r["date"]) <= hi]
        )
    assert sum(totals[0]) == 28640
    assert len(totals[0]) == 23
    assert statistics.median(sum(t) for t in totals[1:]) == 20310
    last = [r for r in food if date.fromisoformat(r["date"]) >= END - timedelta(days=29)]
    by_app = {c: sum(-r["amount_minor"] for r in last if r["cpty"] == c) for c in
              ("cpty_deliveroo", "cpty_uber_eats", "cpty_just_eat")}  # fmt: skip
    assert by_app == {"cpty_deliveroo": 13637, "cpty_uber_eats": 10901, "cpty_just_eat": 4102}


def test_p1_declared_balance_and_car_repair() -> None:
    ws = json.loads((P1 / "workspace.json").read_text(encoding="utf-8"))
    assert ws["declared_balance"] == {"account": "acct_main", "amount_minor": 218450,
                                      "as_of": "2026-10-11"}  # fmt: skip
    truth = load_truth_transactions(P1)
    assert ws["opening_balance_minor"] + sum(r["amount_minor"] for r in truth) == 218450
    known = json.loads((P1 / "truth_known_flows.json").read_text(encoding="utf-8"))["known_flows"]
    assert known[0]["amount_minor"] == -65000
    assert known[0]["date"] == "2026-10-14"
    assert "KWIKFIT" not in (P1 / "exports" / "monzo.csv").read_text(encoding="utf-8").upper()
    clean = json.loads((DATASETS_DIR / "P1-clean" / "truth_anomalies.json").read_text())
    assert [a["key"] for a in clean["anomalies"]] == ["food_delivery_windows"]


# --------------------------------------------------------------------------- truth ↔ rows


def _parse_date(text: str, fmt: str) -> date:
    if "(Sept)" in fmt:
        return datetime.strptime(text.replace("Sept", "Sep"), "%d %b %Y").date()
    return datetime.strptime(text, fmt).date()


def _parse_amount(text: str, table: dict[str, Any]) -> int:
    t = re.sub(r"[£€$\s]", "", text)
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")")) or t.endswith("DR")
    t = t.strip("-()").removesuffix("DR").removesuffix("CR")
    t = t.replace(table.get("group", ","), "").replace(table["decimal"], ".")
    whole, _, frac = t.partition(".")
    minor = int(whole) * 100 + int(frac.ljust(2, "0"))
    return -minor if neg else minor


def _row_amount(cells: dict[str, str], table: dict[str, Any]) -> int:
    cols = table["columns"]
    if "amount" in cols:
        return _parse_amount(cells[cols["amount"]], table)
    out = cells[cols["out"]]
    inn = cells[cols["in"]]
    if out:
        return -abs(_parse_amount(out, table))
    return _parse_amount(inn, table) if inn else 0


@pytest.mark.parametrize("name", list(DATASETS))
def test_truth_rows_align_with_export_rows(name: str) -> None:
    ds = DATASETS_DIR / name
    layouts = json.loads((ds / "truth_layout.json").read_text(encoding="utf-8"))
    truth = load_truth_transactions(ds)
    balances = {
        (b["account"], b["date"]): b["balance_minor"]
        for b in map(json.loads, (ds / "truth_balances.jsonl").read_text().splitlines())
    }
    seen = 0
    for path, layout in layouts.items():
        rows = list(csv.reader(io.StringIO((ds / path).read_text(encoding="utf-8")),
                               delimiter=layout["delimiter"]))  # fmt: skip
        for table in layout["tables"]:
            header = rows[table["header_row"]]
            assert header == table["headers"]
            mine = [r for r in truth if r["file"] == path and r["table"] == table["table"]]
            assert [r["row"] for r in mine] == list(range(table["n_rows"]))
            last_balance: dict[str, int] = {}
            for r in mine:
                cells = dict(zip(header, rows[table["first_row"] + r["row"]], strict=False))
                got_date = _parse_date(cells[table["columns"]["date"]], table["date_format"])
                assert got_date.isoformat() == r["date"], (path, r)
                assert _row_amount(cells, table) == r["amount_minor"], (path, r)
                if table.get("balance_column"):
                    bal = _parse_amount(cells[table["balance_column"]], table)
                    last_balance[r["date"]] = bal
            for d, bal in last_balance.items():  # end-of-day balance = the day's last row
                assert balances[(table["table"], d)] == bal, (path, d)
            seen += len(mine)
    assert seen == len(truth)


# --------------------------------------------------------------------------- CSV-CORRUPT


def test_corrupt_set_has_twenty_files_with_expected_mix() -> None:
    cases = build_corrupt(PRIMARY_SEED)
    assert len(cases) == 20
    assert [c.defect for c in cases if c.kind == "generic"] == GENERIC_DEFECTS
    assert [c.defect for c in cases if c.kind == "monzo"] == MONZO_DEFECTS
    for c in cases:
        on_disk = DATASETS_DIR / CORRUPT / f"{c.name}.csv"
        assert on_disk.read_text(encoding="utf-8") == to_csv(c.rows)
        truth = json.loads((DATASETS_DIR / CORRUPT / f"{c.name}.truth.json").read_text())
        assert truth["defect"] == c.defect
        assert truth["expected_outcome"] in ("rejected", "flagged")


@pytest.mark.parametrize("case", build_corrupt(PRIMARY_SEED), ids=lambda c: c.name)
def test_each_corrupt_file_has_exactly_one_defect(case: Any) -> None:
    clean = [",".join(r) for r in case.clean_rows]
    bad = [",".join(r) for r in case.rows]
    if case.defect == "wrong_sign_convention":
        # One defect affecting one column: only Amount / Local amount differ, on every row.
        assert len(clean) == len(bad)
        for c_row, b_row in zip(case.clean_rows[1:], case.rows[1:], strict=True):
            diff = {i for i, (x, y) in enumerate(zip(c_row, b_row, strict=True)) if x != y}
            assert diff == {7, 9}
        assert case.first_failing_row == 0
        return
    ops = [op for op in difflib.SequenceMatcher(a=clean, b=bad).get_opcodes() if op[0] != "equal"]
    assert len(ops) == 1
    tag, i1, i2, j1, j2 = ops[0]
    assert max(i2 - i1, j2 - j1) == 1  # a single row changed, dropped or inserted
    failing = (j1 if tag != "delete" else i1) - 1  # file row → 0-based data row
    if case.defect == "dropped_row":
        assert tag == "delete"
    elif case.defect == "duplicated_row":
        assert tag == "insert"
        # difflib may mark either twin as inserted; the failure is the second of the pair.
        twins = [i for i in range(2, len(bad)) if bad[i] == bad[i - 1]]
        assert len(twins) == 1
        failing = twins[0] - 1
    else:
        assert tag == "replace"
    assert failing == case.first_failing_row
