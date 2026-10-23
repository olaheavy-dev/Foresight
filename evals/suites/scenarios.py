"""E-SCN: what-if text → ScenarioSpec (docs/09 §9.1) on the 80 authored prompts.

Each prompt goes through the real Forecaster parse (`backend.agents.forecaster.parse_scenario`)
with the persona's categories, recurring payments and income streams, in replay by default.

Scoring (labels and names are free text and not scored):
- **exact match**: the parsed modifiers equal the gold modifiers on every other field;
- **field accuracy** per gold modifier, matched by type in order: type, amount, date (`date`,
  `start_date`, `from_date`), target (`category_key`, `recurring_id`, `income_stream_id`),
  duration (`to_date`, `days`, `instalments`, `occurrences`);
- **clarification** precision and recall on the 10 ambiguous prompts.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from typing import Any

from backend.agents.forecaster import ModifierModel, parse_scenario
from backend.mesh.mesh_client import MeshCallError
from evals.authored import AUTHORED_DIR
from evals.common import load_dataset, read_jsonl, uk_categorisation_pack
from evals.mesh_eval import NOT_RECORDED, eval_mesh, eval_mode
from evals.metrics import r4
from evals.suites import Target, target

SUITE_ID = "E-SCN"
NAME = "scenarios"
CASES = AUTHORED_DIR / "scenario_prompts.jsonl"
FAST_CASES = 12
FIELDS = {
    "type": ("type",),
    "amount": ("amount_minor", "monthly_cap_minor", "buffer_minor", "pct"),
    "date": ("date", "start_date", "from_date"),
    "target": ("category_key", "recurring_id", "income_stream_id"),
    "duration": ("to_date", "days", "instalments", "occurrences", "cadence"),
}
UNSCORED = frozenset({"label"})
# A one-off's category is scored only when the gold names one (the gold leaves it out where no
# category fits, e.g. a car repair).
OPTIONAL_WHEN_GOLD_SILENT = {
    "one_off_outflow": {"category_key"},
    "one_off_inflow": {"category_key"},
}
# Defaults the prompt states ("today if not stated", "1 unless the user says otherwise").
DEFAULTS = {"occurrences": 1}


def _context(dataset: str) -> dict[str, Any]:
    ds = load_dataset(dataset)
    recurring = [
        {"recurring_id": r["key"], "label": str(r.get("label") or r["key"])}
        for r in ds.truth_json("truth_recurring.json")["recurring"]
    ]
    income = [
        {"income_stream_id": s["key"], "label": str(s.get("source") or s["key"])}
        for s in ds.truth_json("truth_income_streams.json")["income_streams"]
    ]
    pack = uk_categorisation_pack()
    return {
        "today": ds.as_of,
        "currency": ds.home_currency,
        "categories": sorted(pack.categories),
        "recurring": recurring,
        "income": income,
    }


def _norm(mod: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in mod.items() if v is not None and k not in UNSCORED}
    if out.get("type") == "split_outflow" and "date" in out and "start_date" not in out:
        out["start_date"] = out.pop("date")
    for k, v in DEFAULTS.items():
        if out.get("type") == "income_delay":
            out.setdefault(k, v)
    return out


def _field_hits(gold: dict[str, Any], got: dict[str, Any] | None) -> dict[str, bool]:
    hits = {}
    for name, keys in FIELDS.items():
        relevant = [k for k in keys if k in gold]
        if not relevant:
            continue
        hits[name] = got is not None and all(got.get(k) == gold[k] for k in relevant)
    return hits


def score_case(case: dict[str, Any], parsed: Any) -> dict[str, Any]:
    clar_expected = bool(case["needs_clarification"])
    clar_got = parsed.status == "needs_clarification"
    row: dict[str, Any] = {
        "id": case["id"],
        "clarify_expected": clar_expected,
        "clarify_got": clar_got,
        "exact": False,
        "fields": {},
    }
    if clar_expected or clar_got or parsed.spec is None:
        row["exact"] = clar_expected and clar_got
        return row
    gold = [_norm(m) for m in case["gold"]["modifiers"]]
    got = [
        _norm(ModifierModel.model_validate(m.model_dump()).model_dump())
        for m in parsed.spec.modifiers
    ]
    remaining = list(got)
    fields: dict[str, list[bool]] = defaultdict(list)
    for g in gold:
        match = next((x for x in remaining if x.get("type") == g["type"]), None)
        if match is not None:
            remaining.remove(match)
        for name, ok in _field_hits(g, match).items():
            fields[name].append(ok)
    row["fields"] = {k: all(v) for k, v in fields.items()}
    row["field_lists"] = dict(fields)
    trimmed = [
        {
            k: v
            for k, v in x.items()
            if k not in OPTIONAL_WHEN_GOLD_SILENT.get(str(x.get("type")), set())
            or any(g.get("type") == x.get("type") and k in g for g in gold)
        }
        for x in got
    ]
    row["exact"] = sorted(json.dumps(x, sort_keys=True) for x in gold) == sorted(
        json.dumps(x, sort_keys=True) for x in trimmed
    )
    if not row["exact"]:
        row["gold"] = gold
        row["got"] = got
    return row


def _rate(n: int, d: int) -> float | None:
    return r4(n / d) if d else None


def run(fast: bool = False) -> dict[str, Any]:
    cases = read_jsonl(CASES)
    if fast:
        cases = cases[:FAST_CASES]
    mesh = eval_mesh()
    notes: list[str] = [f"mode: {eval_mode()}"]
    rows: list[dict[str, Any]] = []
    missing = 0
    contexts: dict[str, dict[str, Any]] = {}
    if mesh is not None:
        for case in cases:
            ctx = contexts.setdefault(case["dataset"], _context(case["dataset"]))
            try:
                out = parse_scenario(
                    case["prompt"],
                    mesh,
                    today=ctx["today"] if isinstance(ctx["today"], date) else ctx["today"],
                    currency=ctx["currency"],
                    categories=ctx["categories"],
                    recurring=ctx["recurring"],
                    income=ctx["income"],
                )
            except NOT_RECORDED:
                missing += 1
                continue
            except MeshCallError as exc:
                rows.append(
                    {
                        "id": case["id"],
                        "error": type(exc).__name__,
                        "exact": False,
                        "fields": {},
                        "clarify_expected": case["needs_clarification"],
                        "clarify_got": False,
                    }
                )
                continue
            row = score_case(case, out.parse)
            row["tier"] = out.tier.value
            rows.append(row)
    measured = bool(rows) and missing == 0
    if missing:
        notes.append(f"{missing} prompts have no recorded model response: LLM metrics not measured")
    scored = [r for r in rows if not r["clarify_expected"]]
    ambiguous = [r for r in rows if r["clarify_expected"]]
    asked = [r for r in rows if r["clarify_got"]]
    field_acc: dict[str, float | None] = {}
    for name in FIELDS:
        values = [ok for r in scored for ok in r.get("field_lists", {}).get(name, [])]
        field_acc[name] = _rate(sum(values), len(values)) if measured else None
    exact = _rate(sum(r["exact"] for r in scored), len(scored)) if measured else None
    clar_recall = (
        _rate(sum(r["clarify_got"] for r in ambiguous), len(ambiguous)) if measured else None
    )
    clar_precision = (
        _rate(sum(r["clarify_expected"] for r in asked), len(asked)) if measured and asked else None
    )
    metrics = {
        "cases": len(cases),
        "scored": len(rows),
        "exact_match": exact,
        "field_accuracy": field_acc,
        "clarification_precision": clar_precision,
        "clarification_recall": clar_recall,
        "tiers": {t: sum(r.get("tier") == t for r in rows) for t in ("fast", "reasoning")},
        "errors": sum(1 for r in rows if r.get("error")),
        "detail": {"misses": [r for r in rows if not r["exact"]][:40]},
    }
    targets: list[Target] = [
        target(
            "SCN-exact",
            "Exact match of the ScenarioSpec",
            exact,
            ">=",
            0.85,
            "80 prompts",
        ),
        target(
            "SCN-amount", "Amount field accuracy", field_acc.get("amount"), ">=", 0.95, "80 prompts"
        ),
        target("SCN-date", "Date field accuracy", field_acc.get("date"), ">=", 0.95, "80 prompts"),
        target(
            "SCN-clarify-R", "Clarification recall", clar_recall, ">=", 0.8, "10 ambiguous prompts"
        ),
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
