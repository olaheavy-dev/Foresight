"""E-INC: income detection, amount and payday rule (docs/09 §6.4 INC-1…INC-4).

Streams are detected from the imported, rules-categorised ledger. A detected stream is matched to
the truth stream that most of its member transactions belong to (truth `income` key).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.finance_core.calendar import next_payday, paydays_between
from backend.finance_core.detect.income import detect_income_streams
from backend.finance_core.types import Cadence, IncomeStream, PaydayRule
from evals.common import build_ledger, load_dataset, majority, uk_categorisation_pack, uk_holidays
from evals.metrics import r4
from evals.suites import Target, target

SUITE_ID = "E-INC"
NAME = "income"
DATASETS = ["P1-base", "P2-base", "S8-salary-split", "S11-fourweekly"]
FAST = ["P1-base", "S11-fourweekly"]
SALARIED = {"monthly", "four_weekly"}


def _truth_rule(spec: dict[str, Any]) -> tuple[PaydayRule, str]:
    rule = spec.get("payday_rule") or {}
    shift = "next_working_day" if rule.get("next_working_day") else "previous_working_day"
    anchor = rule.get("anchor_date")
    return (
        PaydayRule(
            kind=str(rule.get("kind")),
            day_of_month=rule.get("day_of_month"),
            anchor_date=date.fromisoformat(anchor) if anchor else None,
            december_day=rule.get("december_day"),
        ),
        shift,
    )


def _dataset(name: str) -> dict[str, Any]:
    ds = load_dataset(name)
    pack = uk_categorisation_pack()
    ledger = build_ledger(ds)
    hol = uk_holidays(ds.as_of.year - 2, ds.as_of.year + 1)
    streams = detect_income_streams(
        ledger.txns, ledger.cats, hol, pack.payday_shift, pack.one_off_multiple
    )
    truth = [
        s
        for s in ds.truth_json("truth_income_streams.json")["income_streams"]
        if s.get("provenance_expected") == "detected" and s.get("cadence") != "one_off"
    ]
    truth_rows: dict[str, set[str]] = {}
    for tid, truth_row in ledger.truth.items():
        if truth_row.get("income"):
            truth_rows.setdefault(str(truth_row["income"]), set()).add(tid)

    matched: dict[str, list[IncomeStream]] = {}
    detected_out: list[dict[str, Any]] = []
    for s in streams:
        key = majority(
            str(ledger.truth[m].get("income") or "") for m in s.member_ids if m in ledger.truth
        )
        if key:
            matched.setdefault(key, []).append(s)
        detected_out.append(
            {
                "key": s.key,
                "source": s.source,
                "cadence": s.cadence.value,
                "amount_minor": s.amount_minor,
                "members": len(s.member_ids),
                "matched_truth": key,
            }
        )
    valid_keys = {str(s["key"]) for s in truth}

    rows: list[dict[str, Any]] = []
    for spec in truth:
        key = str(spec["key"])
        found = matched.get(key, [])
        salaried = spec["cadence"] in SALARIED
        # recall: the detected streams hold at least half of this stream's truth rows; a salaried
        # stream only counts when found as a regular (non-irregular) stream
        regular = [s for s in found if s.cadence is not Cadence.IRREGULAR]
        members = {m for s in (regular if salaried else found) for m in s.member_ids}
        need = truth_rows.get(key, set())
        recalled = bool(need) and len(members & need) >= len(need) / 2
        row: dict[str, Any] = {
            "key": key,
            "cadence": spec["cadence"],
            "salaried": salaried,
            "detected": recalled,
        }
        if salaried and recalled:
            amount = sum(s.amount_minor for s in regular)
            want = int(spec["net_amount_minor"])
            row["amount_minor"] = amount
            row["amount_error"] = r4(abs(amount - want) / want)
            row["amount_ok"] = abs(amount - want) <= 0.02 * want
            row["cadence_detected"] = regular[0].cadence.value
            row["cadence_ok"] = regular[0].cadence.value == spec["cadence"]
            rule = regular[0].payday_rule
            pays = [date.fromisoformat(d) for d in spec.get("paydays") or []]
            truth_rule, truth_shift = _truth_rule(spec)
            if rule is not None and pays:
                pred = paydays_between(
                    rule, pays[0], pays[-1], hol, uk_categorisation_pack().payday_shift
                )
                expected_next = next_payday(truth_rule, ds.as_of, hol, truth_shift)
                got_next = next_payday(rule, ds.as_of, hol, uk_categorisation_pack().payday_shift)
                # the truth rule's own paydays: a late or missed credit is the payer's doing,
                # not a wrong rule (INC-3 scores the rule; credits are reported alongside)
                rule_pays = paydays_between(truth_rule, pays[0], pays[-1], hol, truth_shift)
                row["payday_rule"] = {
                    "kind": rule.kind,
                    "day_of_month": rule.day_of_month,
                    "december_day": rule.december_day,
                    "shift": rule.shift.value if rule.shift is not None else "pack default",
                }
                row["history_paydays_match_rule"] = pred == rule_pays
                row["history_paydays_exact"] = pred == pays
                row["history_payday_misses"] = sorted(
                    {d.isoformat() for d in set(pred) ^ set(pays)}
                )
                row["next_payday"] = got_next.isoformat() if got_next else None
                row["expected_next_payday"] = expected_next.isoformat() if expected_next else None
                row["payday_ok"] = pred == rule_pays and got_next == expected_next
            else:
                row["payday_ok"] = False
        rows.append(row)
    precise = sum(1 for d in detected_out if d["matched_truth"] in valid_keys)
    return {
        "detected": detected_out,
        "truth": rows,
        "precision_all": r4(precise / len(detected_out)) if detected_out else None,
        "valid_keys": sorted(valid_keys),
    }


def run(fast: bool = False) -> dict[str, Any]:
    names = FAST if fast else DATASETS
    per = {n: _dataset(n) for n in names}
    sal = [r for d in per.values() for r in d["truth"] if r["salaried"]]
    sal_found = [r for r in sal if r["detected"]]
    sal_detected = [d for p in per.values() for d in p["detected"] if d["cadence"] in SALARIED]
    sal_true = [
        d
        for p in per.values()
        for d in p["detected"]
        if d["cadence"] in SALARIED and d["matched_truth"] in p["valid_keys"]
    ]
    amount_ok = [r.get("amount_ok", False) for r in sal_found]
    payday_ok = [r.get("payday_ok", False) for r in sal_found if r["cadence"] == "monthly"]
    s11 = per.get("S11-fourweekly")
    four_weekly_ok = (
        any(r.get("cadence_detected") == "four_weekly" for r in s11["truth"]) if s11 else None
    )
    credits_exact = [
        r.get("history_paydays_exact", False) for r in sal_found if r["cadence"] == "monthly"
    ]
    metrics: dict[str, Any] = {
        "salaried_precision": r4(len(sal_true) / len(sal_detected)) if sal_detected else None,
        "salaried_recall": r4(len(sal_found) / len(sal)) if sal else None,
        "amount_within_2pct": r4(sum(amount_ok) / len(amount_ok)) if amount_ok else None,
        "payday_rule_ok": r4(sum(payday_ok) / len(payday_ok)) if payday_ok else None,
        "paydays_equal_credit_dates": r4(sum(credits_exact) / len(credits_exact))
        if credits_exact
        else None,
        "four_weekly_cadence_ok": four_weekly_ok,
        "by_dataset": per,
    }
    targets: list[Target] = [
        target(
            "INC-1-P",
            "Salaried stream precision",
            metrics["salaried_precision"],
            ">=",
            0.95,
            ", ".join(names),
        ),
        target(
            "INC-1-R",
            "Salaried stream recall",
            metrics["salaried_recall"],
            ">=",
            0.95,
            ", ".join(names),
        ),
        target(
            "INC-2",
            "Amount within ±2% (matched salaried)",
            metrics["amount_within_2pct"],
            ">=",
            1.0,
            ", ".join(names),
        ),
        target(
            "INC-3",
            "Payday rule and next payday exact (monthly)",
            metrics["payday_rule_ok"],
            ">=",
            1.0,
            ", ".join(n for n in names if n != "S11-fourweekly"),
        ),
        target(
            "INC-4",
            "Four-weekly pay detected as 28-day cadence",
            None if four_weekly_ok is None else float(four_weekly_ok),
            "==",
            1,
            "S11",
        ),
    ]
    notes = [
        "Detected streams are matched to truth by the majority truth `income` key of their "
        "member transactions; a truth stream counts as found when ≥ 50% of its rows are members "
        "(of regular streams, for salaried truth streams).",
        "INC-3 compares the detected rule's paydays over the history with the truth rule's "
        "paydays (a payer's late or missed credit is not a wrong rule), and the predicted next "
        "payday after as_of with the truth rule's next payday. paydays_equal_credit_dates reports "
        "how often the rule also matches every actual credit date (P2's client paid June late).",
        "S8 split salary: amounts of the streams matched to one truth source are summed (INC-7).",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
