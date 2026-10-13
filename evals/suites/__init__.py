"""Deterministic eval suites. Each module exposes `SUITE_ID`, `NAME` and `run(fast) -> dict`."""

from __future__ import annotations

from typing import Any

Target = dict[str, Any]


def target(
    tid: str,
    label: str,
    value: float | None,
    op: str,
    threshold: float | tuple[float, float],
    dataset: str,
    *,
    stage1: bool = True,
) -> Target:
    """A docs/09 TARGET compared with a measured value. `met` is None when not measured; a null
    value is never treated as met. `stage1=False` marks targets for arms not built yet (they are
    reported but do not decide the gate)."""
    met: bool | None
    if value is None:
        met = None
    elif op == ">=":
        assert isinstance(threshold, int | float)
        met = value >= threshold
    elif op == "<=":
        assert isinstance(threshold, int | float)
        met = value <= threshold
    elif op == "==":
        met = value == threshold
    elif op == "range":
        assert isinstance(threshold, tuple)
        met = threshold[0] <= value <= threshold[1]
    else:
        raise ValueError(op)
    shown = (
        f"{threshold[0]}–{threshold[1]}" if isinstance(threshold, tuple) else f"{op} {threshold}"
    )
    return {
        "id": tid,
        "label": label,
        "dataset": dataset,
        "value": value,
        "target": shown,
        "met": met,
        "stage1": stage1,
    }
