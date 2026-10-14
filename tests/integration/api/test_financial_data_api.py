"""Financial data API: accounts with their known balance, a declared balance, and the income and
recurring payments the detectors found ("Check what we found", docs/01 F-10, F-17, F-25)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.api.contract import checked
from tests.integration.api.test_engine_api import P1_CSV, demo, new_profile, upload

pytestmark = pytest.mark.postgres


def test_demo_lists_its_account_balance_and_detected_flows(api: TestClient) -> None:
    demo(api)
    accounts: Any = checked(api, api.get("/api/accounts"), "/api/accounts")
    (account,) = accounts["accounts"]
    assert account["transactions"] > 0
    assert account["balance"]["provenance"] == "declared"  # P1 seeds a declared balance
    flows: Any = checked(api, api.get("/api/detected"), "/api/detected")
    assert flows["income"], "P1 is salaried"
    assert flows["income"][0]["payments"] >= 3
    labels = {r["category_key"] for r in flows["recurring"]}
    assert "housing.rent" in labels
    amounts = [r["amount"]["minor"] for r in flows["recurring"]]
    assert amounts == sorted(amounts, reverse=True)
    assert all(a > 0 for a in amounts)
    refused = api.post(
        f"/api/accounts/{account['account_id']}/balance",
        json={"as_of": date.today().isoformat(), "amount_minor": 100},
    )
    assert refused.status_code == 403


def test_a_monzo_import_has_no_balance_until_one_is_declared(api: TestClient) -> None:
    new_profile(api)
    upload(api, P1_CSV)
    (account,) = checked(api, api.get("/api/accounts"), "/api/accounts")["accounts"]
    assert account["balance"] is None  # Monzo exports carry no balance column
    path = f"/api/accounts/{account['account_id']}/balance"
    today = date.today().isoformat()
    sent = api.post(path, json={"as_of": today, "amount_minor": 218450})
    after = checked(api, sent, "/api/accounts/{account_id}/balance")
    assert after["balance"]["provenance"] == "declared"
    assert after["balance"]["money"]["minor"] == 218450
    future = (date.today() + timedelta(days=1)).isoformat()
    assert api.post(path, json={"as_of": future, "amount_minor": 1}).status_code == 422
    missing = "/api/accounts/acct_01JAAAAAAAAAAAAAAAAAAAAAAA/balance"
    assert api.post(missing, json={"as_of": today, "amount_minor": 1}).status_code == 404
    forecast = api.get("/api/forecast").json()
    assert forecast["chart"]["balance_mode"] == "absolute"
