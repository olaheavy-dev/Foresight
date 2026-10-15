"""E-ING: the generic `csv_statement` importer (docs/09 §4.1). Deterministic arms only.

C1–C4 run heuristic-only (low by design) and with the Ledger Agent's proposed FormatProfile
(§4.1.3 `heuristic+llm`), replayed from recorded Mesh responses: a proposal counts as a success
only if the file then parses with row precision and recall 1.000; the confirmed profile is then
reused by signature with no model call. Every `pdf_statement` row is Tier 2 and stays null.
"""

from __future__ import annotations

import re
from typing import Any

from backend.agents import format_profile as fp
from backend.finance_core.importers import blocking_questions
from backend.finance_core.importers.table_locator import decode, locate_tables
from backend.mesh.mesh_client import CassetteMiss, MeshCallError, MeshConfigError
from evals.common import (
    DATASETS,
    expected_rows,
    import_bytes,
    import_dataset,
    load_dataset,
    read_json,
    row_precision_recall,
    truth_tables,
)
from evals.metrics import r4, wilson
from evals.suites import Target, target

SUITE_ID = "E-ING"
NAME = "ingestion"

BUILTIN_FORMATS = {"monzo": "monzo_csv", "revolut_consolidated": "revolut_consolidated_csv"}
CLEAN = ["P1-base", "P2-base", "S14-side-account", "S8-salary-split", "G1-eur"]
UNSEEN = ["C1-pennine", "C2-harbour-vale", "C3-northgate", "C4-fenwick"]
FAST_CLEAN = ["P1-base", "P2-base", "S14-side-account"]
_ROW_REF = re.compile(r"^row (\d+):")


def _table_locator(names: list[str]) -> dict[str, Any]:
    pred_total = truth_total = pred_hit = truth_hit = boundary = 0
    junk = 0
    per_file: list[dict[str, Any]] = []
    for name in names:
        ds = load_dataset(name)
        for file in ds.layout:
            truth = [t for f, t in truth_tables(ds) if f == file]
            located = locate_tables(decode(ds.file_bytes(file)))
            pred = [(t.header_row, t.rows[-1][0] if t.rows else t.header_row) for t in located]
            gold = [(int(t["header_row"]), int(t["last_row"])) for t in truth]
            hits = [p for p in pred if p in gold]
            pred_total += len(pred)
            truth_total += len(gold)
            pred_hit += len(hits)
            truth_hit += sum(g in pred for g in gold)
            boundary += sum(g in pred for g in gold)
            # junk: located data rows outside every truth table's data span
            spans = [(int(t["first_row"]), int(t["last_row"])) for t in truth]
            for tb in located:
                junk += sum(not any(a <= r <= b for a, b in spans) for r, _cells in tb.rows)
            per_file.append(
                {
                    "dataset": name,
                    "file": file,
                    "truth_tables": len(gold),
                    "found": len(pred),
                    "correct": len(hits),
                }
            )
    return {
        "precision": r4(pred_hit / pred_total) if pred_total else None,
        "recall": r4(truth_hit / truth_total) if truth_total else None,
        "boundary_acc": r4(boundary / truth_total) if truth_total else None,
        "junk_rows_parsed": junk,
        "files": per_file,
    }


def _unseen_with_llm(names: list[str]) -> dict[str, Any]:
    """§4.1.3 heuristic+llm: propose columns for tables the heuristic can't read, confirm, parse."""
    from evals.suites.categorisation import eval_mesh

    mesh = eval_mesh()
    ok = calls = proposals = reused = 0
    files: list[dict[str, Any]] = []
    for name in names:
        ds = load_dataset(name)
        for file in ds.layout:
            data = ds.file_bytes(file)
            first = import_bytes(file, data, home_currency=ds.home_currency)
            located = [t for t in locate_tables(decode(data)) if t.rows]
            saved = []
            entry: dict[str, Any] = {"dataset": name, "file": file, "problems": []}
            for i, t in enumerate(first.tables):
                if not any(q.kind == "columns" for q in blocking_questions(t.result)):
                    continue
                try:
                    proposal = fp.propose(
                        located[i].headers, [c for _r, c in located[i].rows], mesh
                    )
                except (CassetteMiss, MeshConfigError, MeshCallError) as exc:
                    return {
                        "success": None,
                        "llm_calls_per_file": None,
                        "reuse_rate": None,
                        "note": f"not measured: no recorded Mesh response ({type(exc).__name__}); "
                        "re-record with MESH_CASSETTE_MODE=record",
                    }
                calls += len(proposal.calls)
                proposals += 1
                entry["problems"] += proposal.problems
                if proposal.profile is not None:
                    saved.append(fp.confirmed(proposal.profile))
            fi = import_bytes(file, data, home_currency=ds.home_currency, saved_profiles=saved)
            answers = {
                q.kind: q.preselected or (q.options[0] if q.options else "")
                for t in fi.tables
                for q in blocking_questions(t.result)
                if q.kind != "columns"
            }
            if answers:
                fi = import_bytes(
                    file, data, home_currency=ds.home_currency, saved_profiles=saved,
                    answers=answers,
                )  # fmt: skip
            rows = [r for t in fi.tables for r in t.result.rows]
            truth = [t for t in expected_rows(ds) if t["file"] == file]
            _p, _r, matched, n_p, n_t = row_precision_recall(rows, truth)
            success = bool(n_p) and matched == n_p == n_t
            ok += success
            # Re-import: the confirmed profile matches by header signature (0 model calls).
            again = import_bytes(file, data, home_currency=ds.home_currency, saved_profiles=saved)
            reuse = bool(saved) and not any(
                q.kind == "columns" for t in again.tables for q in t.result.questions
            )
            reused += reuse
            entry.update(
                row_precision=r4(matched / n_p) if n_p else None,
                row_recall=r4(matched / n_t) if n_t else None,
                success=success,
                profiles=[p.profile_id for p in saved],
                reused_without_model=reuse,
            )
            files.append(entry)
    n = len(files)
    return {
        "success": r4(ok / n) if n else None,
        "files": n,
        "llm_calls_per_file": r4(calls / n) if n else None,
        "proposals": proposals,
        "reuse_rate": r4(reused / n) if n else None,
        "per_file": files,
    }


def _profiles_and_parse(names: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    builtin_files = builtin_hit = other_files = false_match = 0
    by_format: dict[str, dict[str, int]] = {}
    honest_violations = 0
    clean_rejected = 0
    files: list[dict[str, Any]] = []
    for name in names:
        ds = load_dataset(name)
        imports = import_dataset(ds)
        for file, spec in ds.layout.items():
            fmt = str(spec.get("format"))
            imps = [i for i in imports if i.file == file]
            pids = {i.profile_id for i in imps}
            if fmt in BUILTIN_FORMATS:
                builtin_files += 1
                builtin_hit += any(p and BUILTIN_FORMATS[fmt] in p for p in pids)
            else:
                other_files += 1
                false_match += any(p and p.startswith("builtin.") for p in pids)
            rows = [r for i in imps for r in i.rows]
            truth = [t for t in expected_rows(ds) if t["file"] == file]
            _p, _r, matched, n_p, n_t = row_precision_recall(rows, truth)
            agg = by_format.setdefault(fmt, {"matched": 0, "parsed": 0, "truth": 0, "files": 0})
            agg["matched"] += matched
            agg["parsed"] += n_p
            agg["truth"] += n_t
            agg["files"] += 1
            has_balance = any(t.get("balance_column") for t in spec["tables"])
            for i in imps:
                if not has_balance and i.reconciliation == "reconciled":
                    honest_violations += 1
                if i.reconciliation == "failed":
                    clean_rejected += 1
            files.append(
                {
                    "dataset": name,
                    "file": file,
                    "format": fmt,
                    "profiles": sorted(p for p in pids if p),
                    "questions": sorted({q for i in imps for q in i.questions}),
                    "reconciliation": sorted({i.reconciliation for i in imps}),
                    "row_precision": r4(matched / n_p) if n_p else None,
                    "row_recall": r4(matched / n_t) if n_t else None,
                }
            )
    profile = {
        "match_rate": r4(builtin_hit / builtin_files) if builtin_files else None,
        "false_match_rate": r4(false_match / other_files) if other_files else None,
        "n_builtin_files": builtin_files,
        "n_other_files": other_files,
    }
    parse = {
        fmt: {
            "row_precision": r4(a["matched"] / a["parsed"]) if a["parsed"] else None,
            "row_recall": r4(a["matched"] / a["truth"]) if a["truth"] else None,
            "files": a["files"],
            "truth_rows": a["truth"],
        }
        for fmt, a in sorted(by_format.items())
    }
    extra = {
        "files": files,
        "no_balance_labelled_reconciled": honest_violations,
        "clean_tables_rejected": clean_rejected,
    }
    return {"builtin_profile": profile, "parse": parse}, extra


def _first_failing_data_row(failures: tuple[str, ...], header_row: int) -> int | None:
    for f in failures:
        m = _ROW_REF.match(f)
        if m:
            return int(m.group(1)) - header_row - 1
    return None


def _corrupted() -> dict[str, Any]:
    root = DATASETS / "CSV-CORRUPT"
    cases = read_json(root / "index.json")["cases"]
    detected = correct_row = rejected_cases = 0
    rows_committed_on_reject = 0
    out: list[dict[str, Any]] = []
    for case in cases:
        data = (root / case["file"]).read_bytes()
        fi = import_bytes(case["file"], data, home_currency="GBP")
        answered: dict[str, str] = {}
        blocking = [q for t in fi.tables for q in t.result.questions if q.kind != "balance_today"]
        if blocking:  # the user accepts the locale default, as in the product
            answered = {
                q.kind: q.preselected or (q.options[0] if q.options else "") for q in blocking
            }
            fi = import_bytes(case["file"], data, home_currency="GBP", answers=answered)
        table = fi.tables[0] if fi.tables else None
        status = table.result.reconciliation.status.value if table else "no_table"
        failures = table.result.reconciliation.failures if table else ()
        is_detected = status == "failed"
        detected += is_detected
        header = locate_tables(decode(data))[0].header_row if table else 0
        first = _first_failing_data_row(failures, header) if is_detected else None
        if case["expected_outcome"] == "rejected":
            rejected_cases += 1
            correct_row += first == case["first_failing_row"]
        if is_detected and table and table.result.rows:
            rows_committed_on_reject += len(table.result.rows)
        out.append(
            {
                "file": case["file"],
                "defect": case["defect"],
                "expected": case["expected_outcome"],
                "status": status,
                "detected": is_detected,
                "first_failing_row": first,
                "expected_first_failing_row": case["first_failing_row"],
                "answered_with_default": sorted(answered),
            }
        )
    n = len(cases)
    ci = wilson(detected, n)
    return {
        "detected": detected,
        "total": n,
        "detection_rate": r4(detected / n) if n else None,
        "detection_rate_ci95": [r4(ci[0]), r4(ci[1])] if ci else None,
        "correct_first_row": correct_row,
        "rejected_cases": rejected_cases,
        "rows_committed_from_failed_files": rows_committed_on_reject,
        "cases": out,
    }


def run(fast: bool = False) -> dict[str, Any]:
    clean = FAST_CLEAN if fast else CLEAN
    locator_builtin = _table_locator([n for n in clean])
    locator_unseen = _table_locator(UNSEEN)
    unseen_llm = _unseen_with_llm(UNSEEN)
    profiles_parse, extra = _profiles_and_parse(clean + UNSEEN)
    corrupt = _corrupted()
    builtin_parse = [v for k, v in profiles_parse["parse"].items() if k in BUILTIN_FORMATS]
    builtin_p = min(
        (v["row_precision"] for v in builtin_parse if v["row_precision"] is not None), default=None
    )
    builtin_r = min(
        (v["row_recall"] for v in builtin_parse if v["row_recall"] is not None), default=None
    )
    unseen_ok = sum(
        1
        for f in extra["files"]
        if f["dataset"] in UNSEEN and f["row_precision"] == 1.0 and f["row_recall"] == 1.0
    )
    metrics: dict[str, Any] = {
        "csv_statement": {
            "table_locator": {
                "builtin_and_common": locator_builtin,
                "unseen_C1_C4": locator_unseen,
            },
            **profiles_parse,
            "format_profile_unseen": {
                "heuristic_only": {"success": r4(unseen_ok / len(UNSEEN)), "files": len(UNSEEN)},
                "heuristic_llm": unseen_llm,
            },
            "reconciliation": {
                "corrupted_csv": corrupt,
                "clean_tables_rejected": extra["clean_tables_rejected"],
                "no_balance_labelled_reconciled": extra["no_balance_labelled_reconciled"],
            },
            "files": extra["files"],
        },
        "pdf_statement": {"note": "Tier 2, not shipped"},
    }
    corrupt_rate = corrupt["detection_rate"]
    targets: list[Target] = [
        target(
            "ING-format-unseen-llm",
            "FormatProfile success, unseen layouts (heuristic + Ledger Agent)",
            unseen_llm.get("success"),
            ">=",
            0.85,
            "C1–C4",
            stage1=False,
        ),
        target(
            "ING-locator-P",
            "Table locator precision (built-in + common)",
            locator_builtin["precision"],
            ">=",
            1.0,
            ", ".join(clean),
        ),
        target(
            "ING-locator-R",
            "Table locator recall (built-in + common)",
            locator_builtin["recall"],
            ">=",
            1.0,
            ", ".join(clean),
        ),
        target(
            "ING-locator-unseen",
            "Table locator recall (C1–C4)",
            locator_unseen["recall"],
            ">=",
            0.95,
            "C1–C4",
        ),
        target(
            "ING-junk",
            "Junk rows parsed as transactions",
            float(locator_builtin["junk_rows_parsed"] + locator_unseen["junk_rows_parsed"]),
            "==",
            0,
            "all",
        ),
        target(
            "ING-builtin-match",
            "Built-in profile match rate",
            profiles_parse["builtin_profile"]["match_rate"],
            ">=",
            1.0,
            "Monzo, Revolut",
        ),
        target(
            "ING-false-match",
            "Built-in false match rate",
            profiles_parse["builtin_profile"]["false_match_rate"],
            "<=",
            0.0,
            "generic, C1–C4",
        ),
        target(
            "ING-parse-P",
            "Row precision (built-in formats)",
            builtin_p,
            ">=",
            1.0,
            "Monzo, Revolut",
        ),
        target(
            "ING-parse-R", "Row recall (built-in formats)", builtin_r, ">=", 1.0, "Monzo, Revolut"
        ),
        target(
            "ING-corrupt",
            "CSV-CORRUPT defects detected",
            corrupt_rate,
            ">=",
            1.0,
            "CSV-CORRUPT (20)",
        ),
        target(
            "ING-clean-rejected",
            "Clean tables rejected",
            float(extra["clean_tables_rejected"]),
            "==",
            0,
            ", ".join(clean),
        ),
        target(
            "ING-honest",
            "Balance-free files labelled reconciled",
            float(extra["no_balance_labelled_reconciled"]),
            "==",
            0,
            ", ".join(clean),
        ),
        target(
            "ING-heuristic+llm",
            "FormatProfile success, heuristic+LLM",
            unseen_llm["success"],
            ">=",
            0.85,
            "C1–C4",
            stage1=False,
        ),
    ]
    notes = [
        "C1–C4 also run heuristic+llm: the Ledger Agent's proposed FormatProfile, replayed from "
        "recorded Mesh responses, with the user's confirmation simulated (§4.1.3).",
        "CSV-CORRUPT files that raise a blocking question are re-imported with the locale default "
        "answer, as a user accepting the pre-selected option would.",
        "Truth row match = equal date and signed amount to the penny (multiset).",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
