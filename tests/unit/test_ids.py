"""Reproducible ids (evaluation databases only): the same allocation order gives the same ids, ids
keep the ULID shape and sort by creation order, and normal ids stay random outside the mode."""

from __future__ import annotations

from backend.storage.ids import new_id, reproducible_ids


def _run() -> list[str]:
    with reproducible_ids():
        return [new_id("wsp"), new_id("txn"), new_id("txn"), new_id("fnd"), new_id("txn")]


def test_same_allocation_order_gives_the_same_ids() -> None:
    first, second = _run(), _run()
    assert first == second
    txns = [i for i in first if i.startswith("txn_")]
    assert txns == sorted(txns)
    assert all(len(i.split("_", 1)[1]) == 26 for i in first)


def test_counters_are_per_prefix() -> None:
    with reproducible_ids():
        a = new_id("txn")
    with reproducible_ids():
        new_id("run")  # an unrelated allocation does not shift transaction ids
        b = new_id("txn")
    assert a == b


def test_outside_the_mode_ids_are_random() -> None:
    assert new_id("txn") != new_id("txn")
