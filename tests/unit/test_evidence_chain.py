"""The evidence chain's source step (backend/app/views.py, mandatory F)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.app import views


def _ctx(batches: dict[str, Any]) -> Any:
    return SimpleNamespace(get=lambda model, row_id: batches.get(row_id))


def _batch(bid: str, name: str) -> Any:
    return SimpleNamespace(
        id=bid, filename=name, importer="csv_statement", reconciliation_status="reconciled"
    )


def test_a_finding_over_two_imports_names_both_files() -> None:
    """#62 review: rows from two statements are both accounted for, not only the larger file."""
    ids = {"imp_01ARZ3NDEKTSV4RRFFQ69G5FA1": "sep.csv", "imp_01ARZ3NDEKTSV4RRFFQ69G5FA2": "oct.csv"}
    a, b = ids
    batches = {k: _batch(k, v) for k, v in ids.items()}
    txns: Any = [SimpleNamespace(import_batch_id=a)] * 3 + [SimpleNamespace(import_batch_id=b)] * 5
    chain, files = views._source_chain(_ctx(batches), txns)
    assert chain is not None
    assert chain.filename == "oct.csv"
    assert chain.rows == "5 rows of this file"
    assert files == [("oct.csv", 5), ("sep.csv", 3)]


def test_no_imported_rows_means_no_source_chain() -> None:
    txns: Any = [SimpleNamespace(import_batch_id=None)]
    assert views._source_chain(_ctx({}), txns) == (None, [])
