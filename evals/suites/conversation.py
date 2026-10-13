"""E-CTX: follow-ups and the exact answer cache (docs/09 §10c, §3.10; docs/05 §4.2).

Runs the real Understand step (replayed from cassettes) over `followup_cases.jsonl`:

- 40 conversations of 2–4 turns: each turn is understood with the earlier turns' standalone
  questions as history, exactly as the runner sends them. CTX-1 intent accuracy and CTX-2 slot
  exact match are scored on follow-up turns (turn ≥ 2); CTX-3 re-asks each predicted standalone
  question with no history and checks the intent and slots come back the same.
- 20 paraphrase pairs must give the same answer-cache key (CTX-4 hit rate); 20 near-miss pairs
  must not (CTX-5 false hits; a pair with a data change between is keyed on a new data version).
"""

from __future__ import annotations

import time
from typing import Any

from evals.assistant import (
    USAGE,
    NotRecorded,
    cache_key,
    canonical,
    eval_mesh,
    eval_mode,
    slots_match,
    understand,
)
from evals.authored import AUTHORED_DIR
from evals.common import read_jsonl
from evals.metrics import r4
from evals.suites import Target, target

SUITE_ID = "E-CTX"
NAME = "conversation"
CASES = AUTHORED_DIR / "followup_cases.jsonl"
DEV_CASES = AUTHORED_DIR / "followup_cases_dev.jsonl"  # the only set tuning may look at


def _rate(n: int, d: int) -> float | None:
    return r4(n / d) if d else None


def run(fast: bool = False, cases: Any = None) -> dict[str, Any]:
    rows = read_jsonl(cases or CASES)
    conversations = [r for r in rows if r["kind"] == "conversation"]
    pairs = [r for r in rows if r["kind"] in {"paraphrase_pair", "near_miss_pair"}]
    if fast:
        conversations, pairs = conversations[:5], pairs[:4] + pairs[20:24]
    mesh = eval_mesh()
    missing = 0
    calls = 0
    tokens_before = USAGE["tokens"]
    started = time.perf_counter()

    def ask(message: str, history: list[dict[str, Any]], as_of: str) -> Any:
        nonlocal missing, calls
        try:
            calls += 1
            return understand(mesh, message, history, as_of)
        except NotRecorded:
            missing += 1
            return None

    follow = {"turns": 0, "intent_ok": 0, "slots_ok": 0}
    adequacy = {"turns": 0, "same": 0}
    detail: list[dict[str, Any]] = []
    for conv in conversations:
        history: list[dict[str, Any]] = []
        for i, turn in enumerate(conv["turns"]):
            pred = ask(turn["user"], history, conv["as_of"])
            row: dict[str, Any] = {"case": conv["id"], "turn": i + 1, "recorded": pred is not None}
            if pred is not None:
                intent_ok = pred.intent == turn["intent"]
                slots_ok = slots_match(turn.get("slots") or {}, dict(pred.slots))
                row.update(intent=pred.intent, intent_ok=intent_ok, slots_ok=slots_ok,
                           standalone=pred.standalone_question)  # fmt: skip
                if i > 0:
                    follow["turns"] += 1
                    follow["intent_ok"] += intent_ok
                    follow["slots_ok"] += slots_ok
                    alone = ask(pred.standalone_question, [], conv["as_of"])
                    if alone is not None:
                        adequacy["turns"] += 1
                        same = alone.intent == pred.intent and canonical(
                            dict(alone.slots)
                        ) == canonical(dict(pred.slots))
                        adequacy["same"] += same
                        row["standalone_alone_same"] = same
                # Exactly what the runner sends (backend.agents.runner._history): the question as
                # understood plus its intent and slots.
                history.append({"question": pred.standalone_question, "intent": pred.intent,
                                "slots": dict(pred.slots)})  # fmt: skip
            else:
                history.append({"question": turn["standalone"]})
            detail.append(row)

    hits = {"paraphrase": 0, "paraphrase_n": 0, "near_miss_hits": 0, "near_miss_n": 0}
    pair_detail: list[dict[str, Any]] = []
    for pair in pairs:
        a = ask(pair["a"], [], pair["as_of"])
        b = ask(pair["b"], [], pair["as_of"])
        if a is None or b is None:
            pair_detail.append({"case": pair["id"], "recorded": False})
            continue
        bumped = 1 if pair.get("event_between") else 0
        hit = cache_key(a) == cache_key(b, data_version=bumped)
        if pair["kind"] == "paraphrase_pair":
            hits["paraphrase_n"] += 1
            hits["paraphrase"] += hit
        else:
            hits["near_miss_n"] += 1
            hits["near_miss_hits"] += hit
        pair_detail.append(
            {"case": pair["id"], "kind": pair["kind"], "hit": hit,
             "a": [a.intent, dict(a.slots)], "b": [b.intent, dict(b.slots)]}
        )  # fmt: skip

    tokens = USAGE["tokens"] - tokens_before
    metrics: dict[str, Any] = {
        "mode": eval_mode(),
        "requests": calls,
        "not_recorded": missing,
        "ctx1_followup_intent_accuracy": _rate(follow["intent_ok"], follow["turns"]),
        "ctx2_followup_slot_exact_match": _rate(follow["slots_ok"], follow["turns"]),
        "ctx3_standalone_adequacy": _rate(adequacy["same"], adequacy["turns"]),
        "ctx4_paraphrase_cache_hit_rate": _rate(hits["paraphrase"], hits["paraphrase_n"]),
        "ctx5_near_miss_false_hits": hits["near_miss_hits"] if hits["near_miss_n"] else None,
        "ctx6": {
            "model_calls_per_cache_miss": 1,
            "model_calls_per_cache_hit_after_understand": 0,
            "replay_seconds": round(time.perf_counter() - started, 2),
            "recorded_tokens_total": tokens,
        },
        "followup_turns_scored": follow["turns"],
        "pairs_scored": hits["paraphrase_n"] + hits["near_miss_n"],
        "detail": detail,
        "pairs": pair_detail,
    }
    targets: list[Target] = [
        target("CTX-1", "Follow-up intent accuracy (turn ≥ 2)",
               metrics["ctx1_followup_intent_accuracy"], ">=", 0.90,
               f"{follow['turns']} follow-up turns", stage1=False),
        target("CTX-2", "Follow-up slot exact match", metrics["ctx2_followup_slot_exact_match"],
               ">=", 0.85, f"{follow['turns']} follow-up turns", stage1=False),
        target("CTX-3", "Standalone rewrite adequacy", metrics["ctx3_standalone_adequacy"], ">=",
               0.90, f"{adequacy['turns']} rewrites", stage1=False),
        target("CTX-4", "Cache hit rate, paraphrase pairs",
               metrics["ctx4_paraphrase_cache_hit_rate"], ">=", 0.90,
               f"{hits['paraphrase_n']} pairs", stage1=False),
        target("CTX-5", "False cache hits, near-miss pairs",
               None if metrics["ctx5_near_miss_false_hits"] is None
               else float(metrics["ctx5_near_miss_false_hits"]),
               "==", 0, f"{hits['near_miss_n']} pairs", stage1=False),
    ]  # fmt: skip
    notes = [
        "Real Understand prompt and schema through the product's Mesh client, "
        f"{eval_mode()} mode; {missing} of {calls} requests not recorded."
        if missing
        else f"Real Understand prompt and schema through the product's Mesh client, "
        f"{eval_mode()} mode; every request recorded.",
        "Targets are Stage 2: reported, not gating the Stage 1 build (stage1=false).",
    ]
    return {"metrics": metrics, "targets": targets, "notes": notes}
