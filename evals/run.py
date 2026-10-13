"""Run the deterministic eval suites and write results (docs/09 §13–§14).

    python -m evals.run --suite all            # every deterministic suite
    python -m evals.run --suite forecast       # one suite (name or ID, e.g. E-FC)
    python -m evals.run --suite all --fast     # < 60 s subset for the local loop

Writes evals/results/<UTC>_<sha7>_deterministic/{summary.json, report.md, <suite>.json} and
copies the summary to evals/results/latest.json. No model calls: LLM arms stay null.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from backend.finance_core.forecast.engine import ENGINE_VERSION
from evals.common import RESULTS, ROOT
from evals.gates import gates
from evals.generator import GENERATOR_VERSION, PRIMARY_SEED
from evals.report import render_report
from evals.suites import (
    anomalies,
    audit,
    categorisation,
    conversation,
    forecast,
    grounding,
    income,
    ingestion,
    locales,
    orchestration,
    recurring,
    scenarios,
    security,
    simulation,
    ui,
    verifier,
)

SCHEMA_VERSION = "1.1"
MODE = "deterministic"
SUITES: tuple[ModuleType, ...] = (
    ingestion,
    locales,
    categorisation,
    income,
    recurring,
    anomalies,
    forecast,
    simulation,
    security,
    scenarios,
    verifier,
    grounding,
    conversation,
    ui,
    orchestration,
    audit,
)
# Bulky per-row detail stays in the per-suite JSON; summary.json keeps the numbers.
_DETAIL_KEYS = frozenset(
    {"by_dataset", "detail", "files", "confusion", "per_class", "top_errors", "cases", "tables"}
)


def _git(*args: str) -> str:
    try:
        return subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _condense(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _condense(v) for k, v in value.items() if k not in _DETAIL_KEYS}
    return value


def select(names: list[str]) -> list[ModuleType]:
    if names == ["all"]:
        return list(SUITES)
    by_key = {m.NAME: m for m in SUITES} | {m.SUITE_ID: m for m in SUITES}
    unknown = [n for n in names if n not in by_key]
    if unknown:
        choices = ", ".join(["all", *(m.NAME for m in SUITES)])
        raise SystemExit(f"unknown suite {', '.join(unknown)}; choose from {choices}")
    return [by_key[n] for n in names]


def run_suite(module: ModuleType, fast: bool) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        out: dict[str, Any] = module.run(fast=fast)
        out["error"] = None
    except Exception as exc:  # noqa: BLE001 - a failing suite is reported, not fatal
        out = {
            "metrics": {},
            "targets": [],
            "notes": [],
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
    out["suite"] = module.SUITE_ID
    out["name"] = module.NAME
    out["duration_s"] = round(time.perf_counter() - started, 2)
    return out


def build_summary(
    results: dict[str, dict[str, Any]], *, fast: bool, sha: str, dirty: bool, now: datetime
) -> dict[str, Any]:
    gate_map, gate_detail = gates(results)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"evalrun_{now.strftime('%Y%m%dT%H%M%SZ')}_{sha[:7] or 'nogit'}",
        "timestamp_utc": stamp,
        "git_sha": sha or None,
        "git_dirty": dirty,
        "mode": MODE,
        "fast": fast,
        "engine_version": ENGINE_VERSION,
        "generator_version": GENERATOR_VERSION,
        "holdout_version": None,
        "layout_set_version": None,
        "locales": ["uk"],
        "home_currency_primary": "GBP",
        "mesh_models": {"coordinator": None, "ledger": None, "advisor": None, "verifier": None},
        "prompt_versions": {},
        "seeds": [PRIMARY_SEED],
        "suites_run": sorted(results),
        "suites": {r["name"]: _condense(r["metrics"]) for r in results.values()},
        "targets": {sid: r["targets"] for sid, r in results.items()},
        "errors": {sid: r["error"] for sid, r in results.items() if r["error"]},
        "durations_s": {sid: r["duration_s"] for sid, r in results.items()},
        "gates": gate_map,
        "gate_detail": gate_detail,
        "notes": [
            "Deterministic suites only: every LLM arm (hybrid/llm-only categorisation, profile "
            "proposals, Verifier, orchestration, grounding, UI) is Stage 2+ and null here.",
            "null = not run. Gates: a suite that did not run is 'fail'; see gate_detail.rule.",
        ],
    }


def write_results(
    results: dict[str, dict[str, Any]], summary: dict[str, Any], out_root: Path
) -> Path:
    sha7 = (summary["git_sha"] or "nogit")[:7]
    stamp = summary["timestamp_utc"].replace("-", "").replace(":", "")
    run_dir = out_root / f"{stamp}_{sha7}_{MODE}"
    run_dir.mkdir(parents=True, exist_ok=True)
    for r in results.values():
        path = run_dir / f"{r['name']}.json"
        path.write_text(json.dumps(r, indent=2, sort_keys=True, default=str) + "\n", "utf-8")
    text = json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n"
    (run_dir / "summary.json").write_text(text, encoding="utf-8")
    (run_dir / "report.md").write_text(render_report(summary, results), encoding="utf-8")
    shutil.copyfile(run_dir / "summary.json", out_root / "latest.json")
    return run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--suite", nargs="+", default=["all"], help="suite name(s) or 'all'")
    parser.add_argument("--fast", action="store_true", help="the < 60 s subset (docs/09 §16)")
    parser.add_argument(
        "--results-dir", type=Path, default=RESULTS, help="where run folders and latest.json go"
    )
    args = parser.parse_args(argv)

    modules = select(args.suite)
    results: dict[str, dict[str, Any]] = {}
    for module in modules:
        print(f"running {module.SUITE_ID} ({module.NAME}) …", file=sys.stderr, flush=True)
        results[module.SUITE_ID] = run_suite(module, args.fast)
        r = results[module.SUITE_ID]
        state = f"error: {r['error']}" if r["error"] else "ok"
        print(f"  {state} in {r['duration_s']} s", file=sys.stderr, flush=True)
    sha = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    summary = build_summary(
        results, fast=args.fast, sha=sha, dirty=dirty, now=datetime.now(timezone.utc)
    )
    run_dir = write_results(results, summary, args.results_dir)
    print(f"results: {run_dir}", file=sys.stderr)
    for sid in summary["suites_run"]:
        d = summary["gate_detail"][sid]
        print(f"  {sid:7} {d['status']:4}  ({d['rule']})", file=sys.stderr)
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
