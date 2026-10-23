"""E-CAT: categorisation on the generated test split (docs/09 §5).

`rules_only` is the finance_core rules engine as shipped (merchant rules, inflow ladder, bank
category as a weak prior, no merchant memory). `hybrid` sends the spending rows the rules leave
below 0.85 to the Ledger Agent (fast tier, docs/06 §4.1); `llm_only` sends every test row.
Both model arms run from recorded model responses (`evals/cassettes`, replay: no key, no network);
`MODEL_CASSETTE_MODE=record` re-records them. A missing recording leaves the arm null with a note
rather than inventing numbers. The UK hand-labelled holdout is not built yet, so its rows are null.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any

from backend.agents.ledger import categorise_with_model, is_candidate, merge
from backend.finance_core.categorise.pack import CategorisationPack
from backend.finance_core.types import Categorisation, Transaction
from backend.llm.client import CassetteMiss, ModelCallError, ModelClient, ModelConfigError
from backend.settings import Settings
from evals.common import (
    Ledger,
    build_ledger,
    categorisation_test_start,
    load_dataset,
    uk_categorisation_pack,
)
from evals.metrics import (
    accuracy,
    amount_weighted_accuracy,
    confusion,
    coverage_at,
    ece,
    macro_f1,
    per_class_f1,
    r4,
    weighted_f1,
    wilson,
)
from evals.suites import Target, target

SUITE_ID = "E-CAT"
NAME = "categorisation"
DATASETS = ["P1-base", "P2-base"]
TAUS = (0.5, 0.7, 0.85, 0.95)
CASSETTES = Path(__file__).resolve().parents[1] / "cassettes"


def eval_model_client() -> ModelClient:
    """Replay by default; `MODEL_CASSETTE_MODE=record` (with OPENAI_API_KEY) re-records."""
    mode = os.environ.get("MODEL_CASSETTE_MODE", "replay")
    if mode not in {"replay", "record"}:
        mode = "replay"  # evals never run open-ended live calls
    return ModelClient(
        Settings(
            model_cassette_mode=mode,
            model_cassette_dir=str(CASSETTES),
            build_sha="eval",
        )
    )


def _model_arm(
    name: str,
    rows: list[tuple[Transaction, Categorisation, str, str]],
    pack: CategorisationPack,
    model_client: ModelClient,
) -> dict[str, Any]:
    """Score one model arm. `rows` = (txn, rule answer, gold category, gold flow) for test rows."""
    hybrid = name == "hybrid"
    send = [t for t, c, _g, _f in rows if (is_candidate(t, c) if hybrid else True)]
    try:
        llm = categorise_with_model(send, pack, model_client, outflow_only=hybrid)
    except (CassetteMiss, ModelConfigError, ModelCallError) as exc:
        return {
            "accuracy": None,
            "macro_f1": None,
            "flow_class_accuracy": None,
            "llm_call_rate": None,
            "note": f"not measured: no recorded model response ({type(exc).__name__}); "
            "re-record with MODEL_CASSETTE_MODE=record",
        }
    gold, pred, conf, amounts, gold_flow, pred_flow = [], [], [], [], [], []
    for t, c, g, gf in rows:
        model = llm.results.get(t.id)
        if hybrid:
            final = merge(c, model)
        else:
            final = model or Categorisation(
                t.id, "uncategorised", pack.default_flow_kind("uncategorised"), c.method, 0.0
            )
        gold.append(g)
        pred.append(final.category_key)
        conf.append(final.confidence)
        amounts.append(t.amount_minor)
        gold_flow.append(gf)
        pred_flow.append(final.flow_kind.value)
    scored = _score(gold, pred, conf, amounts, gold_flow, pred_flow)
    scored["llm_call_rate"] = r4(llm.sent / len(rows)) if rows else None
    scored["llm"] = {
        "rows_sent": llm.sent,
        "rows_withheld_suspicious": llm.withheld,
        "invalid_or_missing_items": llm.invalid,
        "failed_batches": llm.failed_batches,
        "calls": len(llm.calls),
        "batches": llm.batches,
        "models": llm.models,
        "prompt_version": llm.prompt_version,
        "tokens": sum(r.usage.total_tokens for r in llm.calls),
        "usd_estimate": r4(sum(r.cost_estimate or 0.0 for r in llm.calls)),
        "replayed": all(r.replayed for r in llm.calls) if llm.calls else None,
    }
    return scored


def _split(ledger: Ledger, as_of: Any) -> tuple[list[int], list[int]]:
    start = categorisation_test_start(as_of)
    dev: list[int] = []
    test: list[int] = []
    for i, t in enumerate(ledger.txns):
        if t.id not in ledger.truth:
            continue
        (test if t.posted_on >= start else dev).append(i)
    return dev, test


def _score(
    gold: list[str],
    pred: list[str],
    conf: list[float],
    amounts: list[int],
    gold_flow: list[str],
    pred_flow: list[str],
) -> dict[str, Any]:
    acc = accuracy(gold, pred)
    n_ok = sum(g == p for g, p in zip(gold, pred, strict=True))
    ci = wilson(n_ok, len(gold))
    cov = {
        str(t): dict(
            zip(
                ("coverage", "selective_accuracy"),
                map(r4, coverage_at(gold, pred, conf, t)),
                strict=True,
            )
        )
        for t in TAUS
    }
    return {
        "n": len(gold),
        "accuracy": r4(acc),
        "accuracy_ci95": [r4(ci[0]), r4(ci[1])] if ci else None,
        "macro_f1": r4(macro_f1(gold, pred)),
        "weighted_f1": r4(weighted_f1(gold, pred)),
        "amount_weighted_accuracy": r4(amount_weighted_accuracy(gold, pred, amounts)),
        "flow_class_accuracy": r4(accuracy(gold_flow, pred_flow)),
        "coverage": cov,
        "abstention_rate": r4(sum(p == "uncategorised" for p in pred) / len(pred))
        if pred
        else None,
        "ece": r4(ece(gold, pred, conf)),
        "llm_call_rate": 0.0,
    }


def run(fast: bool = False) -> dict[str, Any]:
    pack = uk_categorisation_pack()
    gold: list[str] = []
    pred: list[str] = []
    conf: list[float] = []
    amounts: list[int] = []
    gold_flow: list[str] = []
    pred_flow: list[str] = []
    dev_labels: Counter[str] = Counter()
    monzo_gold: list[str] = []
    monzo_pred: list[str] = []
    monzo_rules: list[str] = []
    per_dataset: dict[str, Any] = {}
    arm_rows: list[tuple[Transaction, Categorisation, str, str]] = []
    for name in DATASETS:
        ds = load_dataset(name)
        ledger = build_ledger(ds)
        dev, test = _split(ledger, ds.as_of)
        dev_labels.update(str(ledger.truth[ledger.txns[i].id]["category"]) for i in dev)
        g = [str(ledger.truth[ledger.txns[i].id]["category"]) for i in test]
        p = [ledger.cats[i].category_key for i in test]
        c = [ledger.cats[i].confidence for i in test]
        a = [ledger.txns[i].amount_minor for i in test]
        gf = [str(ledger.truth[ledger.txns[i].id]["flow"]) for i in test]
        pf = [ledger.cats[i].flow_kind.value for i in test]
        per_dataset[name] = {"rules_only": _score(g, p, c, a, gf, pf), "dev_n": len(dev)}
        arm_rows += [(ledger.txns[i], ledger.cats[i], g[k], gf[k]) for k, i in enumerate(test)]
        gold += g
        pred += p
        conf += c
        amounts += a
        gold_flow += gf
        pred_flow += pf
        priors = pack.bank_category_priors.get("monzo", {})
        for i in test:
            t = ledger.txns[i]
            if t.bank_category is None:
                continue
            monzo_gold.append(str(ledger.truth[t.id]["category"]))
            monzo_pred.append(priors.get(t.bank_category.lower(), "uncategorised"))
            monzo_rules.append(ledger.cats[i].category_key)

    rules = _score(gold, pred, conf, amounts, gold_flow, pred_flow)
    model_client = eval_model_client()
    hybrid = _model_arm("hybrid", arm_rows, pack, model_client)
    llm_only = _model_arm("llm_only", arm_rows, pack, model_client)
    majority = dev_labels.most_common(1)[0][0] if dev_labels else "uncategorised"
    maj_pred = [majority] * len(gold)
    errors = Counter((g, p) for g, p in zip(gold, pred, strict=True) if g != p)
    metrics: dict[str, Any] = {
        "dataset": "generated test split (last 3 months) of " + ", ".join(DATASETS),
        "arms": {
            "rules_only": rules,
            "majority_class": {
                "label": majority,
                "accuracy": r4(accuracy(gold, maj_pred)),
                "macro_f1": r4(macro_f1(gold, maj_pred)),
            },
            "monzo_category_mapped": {
                "n": len(monzo_gold),
                "accuracy": r4(accuracy(monzo_gold, monzo_pred)),
                "macro_f1": r4(macro_f1(monzo_gold, monzo_pred)),
                "rules_only_on_same_rows": r4(accuracy(monzo_gold, monzo_rules)),
            },
            "hybrid": hybrid,
            "llm_only": llm_only,
        },
        "holdout": {
            "dataset": "holdout_narrations@h-1",
            "accuracy": None,
            "macro_f1": None,
            "note": "UK hand-labelled holdout not built yet",
        },
        "by_dataset": per_dataset,
        "per_class": {
            k: {m: r4(float(v)) if m != "support" else v for m, v in row.items()}
            for k, row in per_class_f1(gold, pred).items()
        },
        "confusion": confusion(gold, pred),
        "top_errors": [{"gold": g, "pred": p, "count": n} for (g, p), n in errors.most_common(15)],
    }
    targets: list[Target] = [
        target(
            "CAT-hybrid-acc-generated",
            "Accuracy, hybrid (generated test split)",
            hybrid.get("accuracy"),
            ">=",
            0.93,
            "P1, P2 test split",
            stage1=False,
        ),
        target(
            "CAT-hybrid-acc",
            "Accuracy, hybrid (holdout)",
            None,
            ">=",
            0.85,
            "UK holdout",
            stage1=False,
        ),
        target(
            "CAT-hybrid-f1",
            "Macro-F1, hybrid (holdout)",
            None,
            ">=",
            0.80,
            "UK holdout",
            stage1=False,
        ),
        target(
            "CAT-hybrid-flow",
            "Flow-class accuracy, hybrid (holdout)",
            None,
            ">=",
            0.95,
            "UK holdout",
            stage1=False,
        ),
        target(
            "CAT-selective",
            "Selective accuracy@0.85 (holdout)",
            None,
            ">=",
            0.95,
            "UK holdout",
            stage1=False,
        ),
    ]
    for tgt in targets:
        if tgt["dataset"] == "UK holdout" and tgt.get("met") is None:
            # Review R7: excluded explicitly, never counted as a pass. Disclosed in the README.
            tgt["gated"] = False
            tgt["not_gated_kind"] = "dataset_missing"
            tgt["not_gated_because"] = (
                "the independent, hand-labelled UK holdout doesn't exist yet; hybrid accuracy is "
                "measured on the generated test split (CAT-hybrid-acc-generated)"
            )
    notes = [
        "Hybrid and LLM-only arms replay recorded model responses (evals/cassettes); the "
        "holdout targets stay null until the UK hand-labelled holdout exists.",
        f"Majority-class baseline predicts '{majority}' (most frequent dev-split label).",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
