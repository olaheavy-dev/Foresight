"""Calculation records: every displayed number is a persisted, recomputable calculation.

See docs/07 §3.4.

A Calculation stores what was computed (kind, params), from what (inputs_hash), with which engine
version, and the JSON-serialisable result. Recomputing from the same inputs must reproduce the
same result exactly; `recompute` checks that.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from typing import Any

import numpy as np


def to_jsonable(obj: Any) -> Any:
    """Convert engine values to plain JSON types with a stable, canonical shape."""
    if isinstance(obj, Enum):
        return to_jsonable(obj.value)
    if isinstance(obj, datetime | date | time):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Mapping):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, frozenset | set):
        return sorted((to_jsonable(v) for v in obj), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(obj, list | tuple):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [to_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, str | int | float | bool) or obj is None:
        return obj
    raise TypeError(f"Cannot serialise {type(obj).__name__} for hashing")


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, canonical value shapes."""
    return json.dumps(to_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Calculation:
    id: str  # calc_<hash prefix>
    kind: str  # e.g. "forecast", "simulation"
    inputs_hash: str
    params: dict[str, Any]
    result: dict[str, Any]
    engine_version: str


def record(
    kind: str,
    inputs: Any,
    params: Mapping[str, Any],
    result: Any,
    engine_version: str,
) -> Calculation:
    """Build a Calculation. The id depends only on what was asked (kind, inputs, params,
    engine version), so the same question always maps to the same id."""
    inputs_hash = content_hash(inputs)
    jparams = to_jsonable(dict(params))
    key = canonical_json(
        {"kind": kind, "inputs": inputs_hash, "params": jparams, "engine": engine_version}
    )
    calc_id = "calc_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return Calculation(
        id=calc_id,
        kind=kind,
        inputs_hash=inputs_hash,
        params=jparams,
        result=to_jsonable(result),
        engine_version=engine_version,
    )


def recompute(
    calc: Calculation, inputs: Any, compute: Callable[[Any], Any]
) -> tuple[Calculation, bool]:
    """Recompute a calculation from its inputs and report whether the result is identical.

    Raises ValueError if the inputs are not the ones the calculation was made from.
    """
    if content_hash(inputs) != calc.inputs_hash:
        raise ValueError(f"inputs do not match {calc.id}")
    fresh = record(calc.kind, inputs, calc.params, compute(inputs), calc.engine_version)
    same = fresh.id == calc.id and canonical_json(fresh.result) == canonical_json(calc.result)
    return fresh, same
