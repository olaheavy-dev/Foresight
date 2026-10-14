"""Regression gate (docs/09 §16): compare the latest results with the accepted baseline.

    python -m evals.regression [--latest evals/results/latest.json]
                               [--baseline evals/results/baseline.json]

Fails when a headline metric gets worse by more than its tolerance. Improvements are allowed. To
accept a deliberate trade-off, replace baseline.json with the new summary **and** add a line to
evals/CHANGELOG.md naming the new baseline's run_id and why; a baseline whose run_id is not in the
changelog fails the gate, so silent re-baselining is impossible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evals.common import RESULTS, ROOT
from evals.headline import headline, target_met

CATEGORISATION_DROP = 0.01  # accuracy or macro-F1 down > 1 pt
MAE_RISE = 0.05  # forecast MAE(30) up > 5 %
COVERAGE_DRIFT = 0.03  # P10–P90 coverage further from 0.80 by > 3 pts
NOMINAL_COVERAGE = 0.80
CHANGELOG = ROOT / "evals" / "CHANGELOG.md"
LOC_DETERMINISTIC = {f"E-LOC-{i}" for i in (*range(1, 10), 11, 12, 13)}


def _missing(name: str, fast: bool) -> list[str]:
    return [] if fast else [f"{name}: measured in the baseline but not in this run"]


def compare(latest: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Human-readable regressions; empty means the gate passes."""
    problems: list[str] = []
    fast = bool(latest.get("fast"))
    lh, bh = headline(latest), headline(baseline)

    for key in ("categorisation.accuracy", "categorisation.macro_f1"):
        b, cur = bh[key], lh[key]
        if b is None:
            continue
        if cur is None:
            problems += _missing(key, fast)
        elif cur < b - CATEGORISATION_DROP:
            problems.append(f"{key} fell from {b:.4f} to {cur:.4f} (tolerance 1 pt)")

    for key in ("reconciliation.corrupt_detection_rate",):
        b, cur = bh[key], lh[key]
        if b is None:
            continue
        if cur is None:
            problems += _missing(key, fast)
        elif cur < b:
            problems.append(f"{key} fell from {b} to {cur} (no drop allowed)")
    b_rej, l_rej = (
        bh["reconciliation.clean_tables_rejected"],
        lh["reconciliation.clean_tables_rejected"],
    )
    if b_rej is not None and l_rej is not None and l_rej > b_rej:
        problems.append(f"clean tables rejected rose from {b_rej} to {l_rej} (no rise allowed)")

    for ds, b in (bh["forecast.mae30_gbp_by_dataset"] or {}).items():
        cur = (lh["forecast.mae30_gbp_by_dataset"] or {}).get(ds)
        if b is None:
            continue
        if cur is None:
            problems += _missing(f"forecast MAE(30) {ds}", fast)
        elif cur > b * (1 + MAE_RISE):
            problems.append(f"forecast MAE(30) on {ds} rose from £{b} to £{cur} (tolerance 5%)")

    for ds, b in (bh["forecast.coverage_by_dataset"] or {}).items():
        cur = (lh["forecast.coverage_by_dataset"] or {}).get(ds)
        if b is None:
            continue
        if cur is None:
            problems += _missing(f"forecast coverage {ds}", fast)
        elif abs(cur - NOMINAL_COVERAGE) > abs(b - NOMINAL_COVERAGE) + COVERAGE_DRIFT:
            problems.append(
                f"P10–P90 coverage on {ds} moved from {b} to {cur}, further from 0.80 by more "
                "than 3 pts"
            )

    b, cur = bh["verifier.catch_rate"], lh["verifier.catch_rate"]
    if b is not None and (cur is None or cur < b):
        problems.append(f"Verifier catch rate fell from {b} to {cur} (no drop allowed)")

    b_loc, l_loc = target_met(baseline, "E-LOC"), target_met(latest, "E-LOC")
    for tid, met in b_loc.items():
        if tid in LOC_DETERMINISTIC and met is True and l_loc.get(tid) is not True:
            if tid not in l_loc and fast:
                continue
            problems.append(f"{tid} no longer passes (was met in the baseline)")

    # A target that was measured in the baseline must still be measured: a missing recording
    # turns a target into "unmeasured", which a per-run gate would otherwise treat as a pass.
    ran = set(latest.get("suites_run") or [])
    for sid, b_targets in (baseline.get("targets") or {}).items():
        if sid not in ran:
            continue
        l_met = target_met(latest, sid)
        for t in b_targets:
            tid = str(t["id"])
            if t.get("met") is not None and l_met.get(tid) is None:
                if fast:  # the fast subset skips slow measurements; the full run must measure them
                    continue
                problems.append(f"{sid} {tid} is no longer measured (was measured in the baseline)")

    for sid in ("E-ORC", "E-AUD"):
        if sid in (latest.get("suites_run") or []) and latest["gates"].get(sid) != "pass":
            problems.append(f"{sid} failed (any orchestration or audit failure blocks)")
    for sid, err in (latest.get("errors") or {}).items():
        problems.append(f"{sid} raised an error: {err}")
    return problems


def changelog_problem(baseline: dict[str, Any], changelog: Path) -> str | None:
    run_id = str(baseline.get("run_id") or "")
    text = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
    if not run_id or run_id not in text:
        return (
            f"baseline {run_id or '(no run_id)'} has no entry in {changelog.name}; add a line "
            "saying why it was accepted"
        )
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--latest", type=Path, default=RESULTS / "latest.json")
    parser.add_argument("--baseline", type=Path, default=RESULTS / "baseline.json")
    parser.add_argument("--changelog", type=Path, default=CHANGELOG)
    args = parser.parse_args(argv)

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    latest = json.loads(args.latest.read_text(encoding="utf-8"))
    problems = compare(latest, baseline)
    note = changelog_problem(baseline, args.changelog)
    if note:
        problems.insert(0, note)
    if problems:
        print("eval regression gate: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"eval regression gate: pass ({latest['run_id']} vs baseline {baseline['run_id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
