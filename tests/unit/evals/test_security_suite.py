from __future__ import annotations

from evals.gates import ALL_SUITES, gate
from evals.suites import security


def test_e_sec_runs_deterministically_and_meets_its_measured_targets() -> None:
    out = security.run()
    assert out["metrics"]["sec1_attack_success_chat"] is None  # needs models: never faked
    measured = {t["id"]: t["met"] for t in out["targets"] if t["stage1"]}
    assert set(measured) == {"SEC-2", "SEC-3", "SEC-4", "SEC-5", "SEC-6"}
    assert all(measured.values()), out["targets"]
    assert gate({**out, "error": None})["status"] == "pass"
    assert out["metrics"]["dev"]["misses"] == []
    assert "E-SEC" in ALL_SUITES
