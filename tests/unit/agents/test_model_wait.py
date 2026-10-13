"""Step model wait (`AgentStep.model_ms`) and the E-EFF percentile (docs/09 E-EFF)."""

from __future__ import annotations

from backend.agents.runtime import concurrent_ms, model_ms
from backend.mesh.mesh_client import MeshResult, Usage
from evals.suites.efficiency import percentile


def call(ms: int, measured: bool = True) -> MeshResult:
    return MeshResult(
        text="", model="m", response_id="r", usage=Usage(1, 1, 2), latency_ms=ms,
        used_fallback=False, latency_measured=measured,
    )  # fmt: skip


def test_sequential_calls_add_up_and_an_unmeasured_call_voids_the_sum() -> None:
    assert model_ms([call(100), call(250)]) == 350
    assert model_ms([call(100), call(250, measured=False)]) is None
    assert model_ms([]) is None


def test_concurrent_groups_overlap_on_the_pool() -> None:
    # Three judge calls on three workers: the slowest one is the wait.
    assert concurrent_ms([[call(5000)], [call(9000)], [call(7000)]], 3) == 9000
    # A repair retry runs after its group's first call, on the same worker.
    assert concurrent_ms([[call(5000), call(4000)], [call(6000)]], 3) == 9000
    # Four groups on two workers: the third and fourth wait for a free worker.
    assert concurrent_ms([[call(3)], [call(5)], [call(4)], [call(1)]], 2) == 7
    assert concurrent_ms([[call(3)], [call(5, measured=False)]], 3) is None
    assert concurrent_ms([[], []], 3) is None


def test_percentile_interpolates() -> None:
    assert percentile([], 50) is None
    assert percentile([10.0], 95) == 10.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert percentile(list(map(float, range(1, 101))), 95) == 95.05
