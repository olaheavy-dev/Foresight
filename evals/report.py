"""report.md for one eval run: headline, gates (with the rule that decided each), every target
with ✓/✗/—, and the notes each suite recorded. Generated from results; never edited by hand."""

from __future__ import annotations

from typing import Any

from evals.gates import is_gated
from evals.headline import headline


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def mark(met: bool | None) -> str:
    return "—" if met is None else ("✓" if met else "✗")


def render_report(summary: dict[str, Any], results: dict[str, dict[str, Any]]) -> str:
    h = headline(summary)
    lines = [
        f"# Eval run {summary['run_id']}",
        "",
        f"- Commit `{(summary.get('git_sha') or 'unknown')[:7]}`"
        + (" (uncommitted changes)" if summary.get("git_dirty") else "")
        + f" · {summary['timestamp_utc']} · mode {summary['mode']}"
        + (" · **fast subset**" if summary.get("fast") else ""),
        f"- Engine {summary['engine_version']} · generator {summary['generator_version']} · "
        f"seed {', '.join(str(s) for s in summary['seeds'])}",
        "- Deterministic suites only; LLM arms are Stage 2+ and shown as —.",
        "",
        "## Headline",
        "",
        "| Metric | Value | Comparison |",
        "|---|---|---|",
        f"| Categorisation accuracy · macro-F1 (rules-only, P1+P2 test split, "
        f"n={fmt(h['categorisation.n'])}) | {fmt(h['categorisation.accuracy'])} · "
        f"{fmt(h['categorisation.macro_f1'])} | majority class "
        f"{fmt(h['categorisation.majority_accuracy'])} |",
        f"| Forecast MAE @30 d, P1 (£) | {fmt(h['forecast.mae30_gbp'], 2)} | best baseline "
        f"{fmt(h['forecast.best_baseline_30'])} {fmt(h['forecast.best_baseline_mae30_gbp'], 2)} "
        f"(skill {fmt(h['forecast.skill_vs_best_30'])}) |",
        f"| Forecast P10–P90 coverage, P1 | {fmt(h['forecast.coverage'])} | nominal 0.80 |",
        f"| CSV reconciliation: corrupted files caught | "
        f"{fmt(h['reconciliation.corrupt_detected'])}/{fmt(h['reconciliation.corrupt_total'])} | "
        "clean tables rejected: "
        f"{fmt(h['reconciliation.clean_tables_rejected'])} |",
        "",
        "## Gates",
        "",
        "| Suite | Gate | Rule applied | Failed targets | Not measured |",
        "|---|---|---|---|---|",
    ]
    for sid in summary["suites_run"]:
        d = summary["gate_detail"][sid]
        lines.append(
            f"| {sid} | **{d['status']}** | {d['rule']} | {', '.join(d['failed']) or '—'} | "
            f"{', '.join(d['unmeasured']) or '—'} |"
        )
    not_run = [sid for sid, d in summary["gate_detail"].items() if d["rule"] == "not run"]
    lines += [
        "",
        f"Not run (gate `fail` until they exist): {', '.join(not_run) or 'none'}.",
        "",
        "Gate rule: a suite errors → fail; else if any docs/09 target that applies to Stage 1 was "
        "measured, every measured one must be met; else the suite passes if it ran without "
        "errors. A null target is never counted as met.",
        "",
        "## Targets",
        "",
    ]
    for sid, r in results.items():
        lines += [f"### {sid} ({r['name']}) · {r['duration_s']} s", ""]
        if r.get("error"):
            lines += [f"**Error:** `{r['error']}`", ""]
        if r["targets"]:
            lines += [
                "| ID | Check | Dataset | Value | Target | Met | Gated |",
                "|---|---|---|---|---|---|---|",
            ]
            for t in r["targets"]:
                gated = "yes" if is_gated(t) else "no (opted out)"
                lines.append(
                    f"| {t['id']} | {t['label']} | {t['dataset']} | {fmt(t['value'])} | "
                    f"{t['target']} | {mark(t['met'])} | {gated} |"
                )
            lines.append("")
        for note in r.get("notes", []):
            lines.append(f"- {note}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
