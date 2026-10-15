"""R5: a CSV from a bank we don't recognise is answerable, not a dead end."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.api.contract import checked
from tests.integration.api.test_engine_api import new_profile

pytestmark = pytest.mark.postgres

ODD_BANK = (
    b"Posted On,Payee Text,Value (GBP),Running Total,Ref\n"
    b"01/10/2026,SALARY ACME LTD,2100.00,2600.00,A1\n"
    b"02/10/2026,TESCO STORES,-42.10,2557.90,A2\n"
    b"03/10/2026,RENT OCTOBER,-950.00,1607.90,A3\n"
    b"15/10/2026,DELIVEROO,-18.40,1589.50,A4\n"
)
MAPPING = {
    "date": "posted on",
    "description": "payee text",
    "amount": "value (gbp)",
    "balance": "running total",
}


def send(api: TestClient, name: str, answers: dict[str, Any] | None = None) -> Any:
    data = {"answers": json.dumps(answers)} if answers else None
    response = api.post("/api/imports", files=[("files", (name, ODD_BANK, "text/csv"))], data=data)
    assert response.status_code == 200, response.text
    return checked(api, response, "/api/imports")["files"][0]


def test_an_unrecognised_bank_is_mapped_once_then_imports_silently(api: TestClient) -> None:
    new_profile(api)
    first = send(api, "odd.csv")
    assert first["status"] == "needs_mapping"
    (q,) = first["questions"]
    assert q["kind"] == "columns"
    assert q["examples"][1] == "SALARY ACME LTD"
    assert q["proposed"]["amount"] == "value (gbp)"

    mapped = send(api, "odd.csv", {"columns": MAPPING})
    assert mapped["status"] == "imported"
    assert mapped["rows_imported"] == 4
    assert mapped["reconciliation"]["status"] == "passed"

    # The next export from this bank needs no answer: the choice was saved on the profile.
    later = send(api, "odd-november.csv")
    assert later["status"] == "imported"
    assert later["already_imported"] is True  # same rows, so nothing new


def test_a_mapping_must_use_known_roles(api: TestClient) -> None:
    new_profile(api)
    bad = api.post(
        "/api/imports",
        files=[("files", ("odd.csv", ODD_BANK, "text/csv"))],
        data={"answers": json.dumps({"columns": {"when": "posted on"}})},
    )
    assert bad.status_code == 422


def test_a_list_of_mappings_is_accepted(api: TestClient) -> None:
    """One mapping per unrecognised table (#42 Codex review); a single mapping still works."""
    new_profile(api)
    mapped = send(api, "odd.csv", {"columns": [MAPPING]})
    assert mapped["status"] == "imported"
