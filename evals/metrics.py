"""Metric functions for the eval suites (docs/09 §5.2, §7.3, §12). Pure; no I/O."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence


def accuracy(gold: Sequence[str], pred: Sequence[str]) -> float | None:
    if len(gold) != len(pred):
        raise ValueError("gold and pred differ in length")
    if not gold:
        return None
    return sum(g == p for g, p in zip(gold, pred, strict=True)) / len(gold)


def per_class_f1(gold: Sequence[str], pred: Sequence[str]) -> dict[str, dict[str, float | int]]:
    """Precision, recall, F1 and support for every gold class (classes with support only)."""
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    for g, p in zip(gold, pred, strict=True):
        if g == p:
            tp[g] += 1
        else:
            fp[p] += 1
            fn[g] += 1
    support = Counter(gold)
    out: dict[str, dict[str, float | int]] = {}
    for k in sorted(support):
        prec = tp[k] / (tp[k] + fp[k]) if tp[k] + fp[k] else 0.0
        rec = tp[k] / (tp[k] + fn[k]) if tp[k] + fn[k] else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        out[k] = {"precision": prec, "recall": rec, "f1": f1, "support": support[k]}
    return out


def macro_f1(gold: Sequence[str], pred: Sequence[str]) -> float | None:
    """Mean F1 over the K gold classes with support (docs/09 §5.2)."""
    per = per_class_f1(gold, pred)
    return sum(float(v["f1"]) for v in per.values()) / len(per) if per else None


def weighted_f1(gold: Sequence[str], pred: Sequence[str]) -> float | None:
    per = per_class_f1(gold, pred)
    n = sum(int(v["support"]) for v in per.values())
    return sum(float(v["f1"]) * int(v["support"]) for v in per.values()) / n if n else None


def amount_weighted_accuracy(
    gold: Sequence[str], pred: Sequence[str], amounts: Sequence[int]
) -> float | None:
    total = sum(abs(a) for a in amounts)
    if not total:
        return None
    hit = sum(abs(a) for g, p, a in zip(gold, pred, amounts, strict=True) if g == p)
    return hit / total


def coverage_at(
    gold: Sequence[str], pred: Sequence[str], confidence: Sequence[float], tau: float
) -> tuple[float | None, float | None]:
    """(coverage, selective accuracy) at confidence threshold τ."""
    if not gold:
        return None, None
    kept = [(g, p) for g, p, c in zip(gold, pred, confidence, strict=True) if c >= tau]
    cov = len(kept) / len(gold)
    sel = sum(g == p for g, p in kept) / len(kept) if kept else None
    return cov, sel


def ece(
    gold: Sequence[str], pred: Sequence[str], confidence: Sequence[float], bins: int = 10
) -> float | None:
    """Expected calibration error over equal-width confidence bins."""
    n = len(gold)
    if not n:
        return None
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(confidence) if (lo < c <= hi) or (b == 0 and c == 0.0)]
        if not idx:
            continue
        acc = sum(gold[i] == pred[i] for i in idx) / len(idx)
        conf = sum(confidence[i] for i in idx) / len(idx)
        total += len(idx) / n * abs(acc - conf)
    return total


def confusion(gold: Sequence[str], pred: Sequence[str]) -> dict[str, dict[str, int]]:
    """gold → predicted → count."""
    out: dict[str, dict[str, int]] = {}
    for g, p in zip(gold, pred, strict=True):
        out.setdefault(g, {})
        out[g][p] = out[g].get(p, 0) + 1
    return {g: dict(sorted(row.items())) for g, row in sorted(out.items())}


def mae(pred: Sequence[float], actual: Sequence[float]) -> float | None:
    if len(pred) != len(actual):
        raise ValueError("pred and actual differ in length")
    if not pred:
        return None
    return sum(abs(p - a) for p, a in zip(pred, actual, strict=True)) / len(pred)


def interval_coverage(
    lower: Sequence[float], upper: Sequence[float], actual: Sequence[float]
) -> float | None:
    """Share of actual values inside [lower, upper] (inclusive)."""
    if not actual:
        return None
    hits = sum(lo <= a <= hi for lo, hi, a in zip(lower, upper, actual, strict=True))
    return hits / len(actual)


def precision_recall(
    n_matched_pred: int, n_pred: int, n_matched_truth: int, n_truth: int
) -> tuple[float | None, float | None]:
    return (
        n_matched_pred / n_pred if n_pred else None,
        n_matched_truth / n_truth if n_truth else None,
    )


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson 95% interval for a proportion (docs/09 §12)."""
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def r4(x: float | None) -> float | None:
    return None if x is None else round(x, 4)
