from __future__ import annotations

from evals.gates import ALL_SUITES, gate
from evals.suites import security


def test_e_sec_runs_deterministically_and_meets_its_measured_targets() -> None:
    out = security.run()
    # SEC-1's model half replays the recorded Understand calls; it is never faked: a missing
    # recording makes it null, and it never gates the deterministic build (stage1=False).
    sec1 = out["metrics"]["sec1_understand"]
    if sec1["not_recorded"]:
        assert out["metrics"]["sec1_attack_success_chat"] is None
    else:
        assert out["metrics"]["sec1_attack_success_chat"] == len(sec1["reaching_specialists"])
    measured = {t["id"]: t["met"] for t in out["targets"] if t["stage1"]}
    assert set(measured) == {"SEC-2", "SEC-3", "SEC-4", "SEC-5", "SEC-6"}
    assert all(measured.values()), out["targets"]
    # SEC-1 is measured (from recordings) and currently misses, so the suite gate reports it.
    result = gate({**out, "error": None})
    sec1 = next(t for t in out["targets"] if t["id"] == "SEC-1")
    assert (result["status"] == "fail") == (sec1["met"] is False)
    assert out["metrics"]["dev"]["misses"] == []
    assert "E-SEC" in ALL_SUITES
