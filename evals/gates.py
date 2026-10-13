"""Per-suite gates for `summary.json` (docs/09 §14) and `tools/check_feature_flags.py`.

Rule, per suite:
1. The suite raised an error → fail.
2. Some docs/09 targets that apply to Stage 1 were measured → pass only if every measured one is
   met. Unmeasured (null) targets are listed and never counted as met.
3. No Stage 1 target was measured → pass if the suite ran without errors.
Suites that did not run are "fail" (not run is never a pass).
"""

from __future__ import annotations

from typing import Any

ALL_SUITES = (
    "E-ING",
    "E-LOC",
    "E-CAT",
    "E-ALIAS",
    "E-XFER",
    "E-ACCT",
    "E-INC",
    "E-REC",
    "E-ANOM",
    "E-FC",
    "E-SIM",
    "E-SCN",
    "E-GRD",
    "E-VER",
    "E-ORC",
    "E-UI",
    "E-AUD",
)

RULE_TARGETS = "docs/09 targets"
RULE_RAN = "ran without errors"
RULE_ERROR = "suite error"
RULE_NOT_RUN = "not run"


def gate(result: dict[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {"status": "fail", "rule": RULE_NOT_RUN, "failed": [], "unmeasured": []}
    if result.get("error"):
        return {
            "status": "fail",
            "rule": RULE_ERROR,
            "failed": [],
            "unmeasured": [],
            "error": result["error"],
        }
    stage1 = [t for t in result.get("targets", []) if t.get("stage1")]
    measured = [t for t in stage1 if t.get("met") is not None]
    unmeasured = [t["id"] for t in stage1 if t.get("met") is None]
    if measured:
        failed = [t["id"] for t in measured if t["met"] is not True]
        return {
            "status": "fail" if failed else "pass",
            "rule": f"{RULE_TARGETS} ({len(measured)} measured)",
            "failed": failed,
            "unmeasured": unmeasured,
        }
    return {"status": "pass", "rule": RULE_RAN, "failed": [], "unmeasured": unmeasured}


def gates(results: dict[str, dict[str, Any]]) -> tuple[dict[str, str], dict[str, Any]]:
    """(suite ID → pass|fail for every suite ID, suite ID → gate detail)."""
    detail = {sid: gate(results.get(sid)) for sid in ALL_SUITES}
    return {sid: d["status"] for sid, d in detail.items()}, detail
