"""E-CAT: categorisation on the generated test split (docs/09 §5). Deterministic arms only.

`rules_only` is the finance_core rules engine as shipped (merchant rules, inflow ladder, bank
category as a weak prior, no merchant memory). `hybrid` and `llm_only` need the Ledger Agent and
are Stage 2 (null). The UK hand-labelled holdout is not built yet, so its rows are null too.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

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
            "hybrid": {
                "accuracy": None,
                "macro_f1": None,
                "flow_class_accuracy": None,
                "llm_call_rate": None,
                "note": "Stage 2",
            },
            "llm_only": {"accuracy": None, "macro_f1": None, "note": "Stage 2"},
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
            None,
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
    notes = [
        "Every docs/09 §5.3 target is for the hybrid arm or the UK holdout; neither exists in "
        "Stage 1, so they are listed unmet-unknown (null) and the gate uses 'ran without errors'.",
        f"Majority-class baseline predicts '{majority}' (most frequent dev-split label).",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
