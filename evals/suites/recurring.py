"""E-REC: recurring obligations (docs/09 §6.5), including the UK council-tax month pattern,
subscription overlap and the price-rise check."""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any

from backend.finance_core.calendar import shift
from backend.finance_core.detect.recurring import detect_recurring
from backend.finance_core.forecast._calendar import obligation_dates
from backend.finance_core.types import Cadence, FlowKind, RecurringObligation
from evals.common import (
    Ledger,
    build_ledger,
    load_dataset,
    majority,
    uk_categorisation_pack,
    uk_holidays,
)
from evals.metrics import r4
from evals.suites import Target, target

SUITE_ID = "E-REC"
NAME = "recurring"
DATASETS = ["P1-base", "P2-base"]
CYCLE_DAYS = 31


def _truth_amount(spec: dict[str, Any]) -> int:
    changes = spec.get("price_changes") or []
    return int(changes[-1]["amount_minor"]) if changes else int(spec["amount_minor"])


def _truth_next(spec: dict[str, Any], as_of: date, hol: frozenset[date]) -> date | None:
    """The truth obligation's first occurrence after as_of (monthly anchor + day rule)."""
    if spec.get("cadence") != "monthly" or spec.get("anchor_day") is None:
        return None
    active = set(spec.get("active_months") or range(1, 13))
    d = as_of + timedelta(days=1)
    for _ in range(400):
        if d.day == int(spec["anchor_day"]) and d.month in active:
            rule = spec.get("day_rule")
            return shift(d, "next_working_day", hol) if rule == "next_working_day" else d
        d += timedelta(days=1)
    return None


def _predicted_next(ob: RecurringObligation, as_of: date) -> date | None:
    days = obligation_dates(ob, as_of + timedelta(days=1), as_of + timedelta(days=400))
    return days[0] if days else None


def _rise_within_cycle(ledger: Ledger, subject: str, rise_on: date) -> dict[str, Any]:
    """Replay detection with the ledger cut one billing cycle after the price rise."""
    cut = rise_on + timedelta(days=CYCLE_DAYS)
    keep = [i for i, t in enumerate(ledger.txns) if t.posted_on <= cut]
    txns = [ledger.txns[i] for i in keep]
    report = detect_recurring(txns, [ledger.cats[i] for i in keep], uk_categorisation_pack())
    by_key = {ob.key: ob for ob in report.obligations}
    hit = False
    for change in report.price_changes:
        ob = by_key.get(change.obligation_key)
        if (
            ob is not None
            and majority(
                str(ledger.truth[m].get("recurring") or "")
                for m in ob.member_ids
                if m in ledger.truth
            )
            == subject
        ):
            hit = True
    return {
        "subject": subject,
        "rise_on": rise_on.isoformat(),
        "replayed_to": cut.isoformat(),
        "detected": hit,
    }


def _dataset(name: str) -> dict[str, Any]:
    ds = load_dataset(name)
    ledger = build_ledger(ds)
    report = detect_recurring(ledger.txns, ledger.cats, uk_categorisation_pack())
    hol = uk_holidays(ds.as_of.year - 1, ds.as_of.year + 1)
    truth = {str(s["key"]): s for s in ds.truth_json("truth_recurring.json")["recurring"]}
    det: list[dict[str, Any]] = []
    matched: dict[str, RecurringObligation] = {}
    for ob in report.obligations:
        key = majority(
            str(ledger.truth[m].get("recurring") or "") for m in ob.member_ids if m in ledger.truth
        )
        hit = key in truth and truth[key]["cadence"] == ob.cadence.value
        if hit and key not in matched:
            matched[str(key)] = ob
        det.append(
            {
                "key": ob.key,
                "label": ob.label,
                "cadence": ob.cadence.value,
                "amount_minor": ob.amount_minor,
                "matched_truth": key if hit else None,
            }
        )
    rows: list[dict[str, Any]] = []
    amount_errors: list[float] = []
    date_errors: list[int] = []
    council: dict[str, Any] | None = None
    for key, spec in truth.items():
        found = matched.get(key)
        row: dict[str, Any] = {"key": key, "label": spec.get("label"), "found": found is not None}
        if found is not None:
            ob = found
            want = _truth_amount(spec)
            err = abs(ob.amount_minor - want) / abs(want)
            amount_errors.append(err)
            row["amount_error"] = r4(err)
            t_next, p_next = _truth_next(spec, ds.as_of, hol), _predicted_next(ob, ds.as_of)
            if t_next and p_next:
                date_errors.append(abs((p_next - t_next).days))
                row["next_date_error_days"] = abs((p_next - t_next).days)
            if spec.get("category") == "housing.council_tax":
                council = {
                    "expected_months": sorted(int(m) for m in spec["active_months"]),
                    "detected_months": sorted(ob.active_months),
                    "exact": set(ob.active_months) == {int(m) for m in spec["active_months"]},
                }
        rows.append(row)
    to_truth = {ob.key: k for k, ob in matched.items()}
    overlaps = [sorted(to_truth.get(k, k) for k in o.obligation_keys) for o in report.overlaps]
    anomalies = ds.truth_json("truth_anomalies.json")["anomalies"]
    expected_overlaps = [
        sorted(a["subject"]) for a in anomalies if a.get("type") == "subscription_overlap"
    ]
    overlap_ok = all(any(set(e) <= set(o) for o in overlaps) for e in expected_overlaps)
    rises = [
        _rise_within_cycle(ledger, str(a["subject"]), date.fromisoformat(a["from"]))
        for a in anomalies
        if a.get("type") == "price_change"
    ]
    commitments = [k for k, s in truth.items() if s.get("is_commitment")]
    commit_ok = [
        bool(
            matched.get(k)
            and (matched[k].is_commitment or matched[k].flow_kind == FlowKind.COMMITMENT)
        )
        for k in commitments
    ]
    return {
        "n_truth": len(truth),
        "n_detected": len(det),
        "n_detected_matched": sum(1 for d in det if d["matched_truth"]),
        "n_truth_found": len(matched),
        "median_amount_error": r4(statistics.median(amount_errors)) if amount_errors else None,
        "median_next_date_error_days": statistics.median(date_errors) if date_errors else None,
        "council_tax": council,
        "price_rises": rises,
        "price_rises_ok": all(r["detected"] for r in rises),
        "overlaps_expected": expected_overlaps,
        "overlaps_detected": overlaps,
        "overlaps_ok": overlap_ok,
        "commitments_recognised": f"{sum(commit_ok)}/{len(commit_ok)}",
        "detected": det,
        "truth": rows,
        "assumptions": list(report.assumptions),
        "monthly_only_next_date": all(o.cadence in (Cadence.MONTHLY,) for o in matched.values()),
    }


def run(fast: bool = False) -> dict[str, Any]:
    names = ["P1-base"] if fast else DATASETS
    per = {n: _dataset(n) for n in names}
    n_det = sum(p["n_detected"] for p in per.values())
    n_det_ok = sum(p["n_detected_matched"] for p in per.values())
    n_truth = sum(p["n_truth"] for p in per.values())
    n_found = sum(p["n_truth_found"] for p in per.values())
    amount_errs = [
        p["median_amount_error"] for p in per.values() if p["median_amount_error"] is not None
    ]
    date_errs = [
        p["median_next_date_error_days"]
        for p in per.values()
        if p["median_next_date_error_days"] is not None
    ]
    councils = [p["council_tax"] for p in per.values() if p["council_tax"] is not None]
    council_exact = all(c["exact"] for c in councils) if councils else None
    rise_ok = all(p["price_rises_ok"] for p in per.values())
    overlap_ok = all(p["overlaps_ok"] for p in per.values())
    metrics: dict[str, Any] = {
        "precision": r4(n_det_ok / n_det) if n_det else None,
        "recall": r4(n_found / n_truth) if n_truth else None,
        "median_amount_error": r4(max(amount_errs)) if amount_errs else None,
        "median_next_date_error_days": max(date_errs) if date_errs else None,
        "council_tax_months_exact": council_exact,
        "price_rise_within_one_cycle": rise_ok,
        "subscription_overlap_detected": overlap_ok,
        "by_dataset": per,
    }
    targets: list[Target] = [
        target("REC-P", "Obligation precision", metrics["precision"], ">=", 0.90, ", ".join(names)),
        target("REC-R", "Obligation recall", metrics["recall"], ">=", 0.90, ", ".join(names)),
        target(
            "REC-amount",
            "Median amount error",
            metrics["median_amount_error"],
            "<=",
            0.02,
            ", ".join(names),
        ),
        target(
            "REC-next-date",
            "Median next-date error (days)",
            metrics["median_next_date_error_days"],
            "<=",
            2,
            ", ".join(names),
        ),
        target(
            "REC-council-tax",
            "Council tax active Apr–Jan only",
            None if council_exact is None else float(council_exact),
            "==",
            1,
            ", ".join(names),
        ),
    ]
    notes = [
        "A detected obligation matches a truth obligation when most of its member transactions "
        "carry that truth `recurring` key and the cadence agrees.",
        "Per-dataset medians are combined by taking the worst dataset.",
        "Next-date error: predicted first occurrence after as_of (finance_core obligation "
        "calendar) vs the truth anchor day and day rule.",
        "Price rise: detection replayed with the ledger cut one billing cycle (31 days) after the "
        "rise. Overlap: the truth pair must sit inside one detected subscription family. Both are "
        "reported, not gated (docs/09 §6.5 sets no numeric target for them).",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
