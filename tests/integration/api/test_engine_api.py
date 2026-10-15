"""API-00: P1 import → forecast → simulate through HTTP with no agent, workspace isolation, and
every response checked against the contract its route declares."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.session import COOKIE
from tests.integration.api.contract import checked

pytestmark = pytest.mark.postgres

DATASETS = Path(__file__).resolve().parents[3] / "evals" / "datasets"
P1_CSV = DATASETS / "P1-base" / "exports" / "monzo.csv"
BROKEN = DATASETS / "CSV-CORRUPT" / "generic_01_broken_balance.csv"


def demo(client: TestClient, persona: str = "P1") -> Any:
    return checked(client, client.post(f"/api/session/demo?persona={persona}"),
                   "/api/session/demo")  # fmt: skip


def new_profile(client: TestClient) -> Any:
    response = client.post("/api/session/new")
    assert response.status_code == 201
    return checked(client, response, "/api/session/new")


def upload(client: TestClient, *paths: Path) -> Any:
    files = [("files", (p.name, p.read_bytes(), "text/csv")) for p in paths]
    response = client.post("/api/imports", files=files)
    assert response.status_code == 200, response.text
    return checked(client, response, "/api/imports")


def test_demo_forecast_simulate_and_evidence(api: TestClient) -> None:
    profile = demo(api)
    assert profile["kind"] == "demo"
    assert profile["read_only"] is False  # a private copy: corrections allowed, imports not
    assert api.cookies.get(COOKIE)

    first = api.get("/api/forecast")
    assert first.status_code == 200, first.text
    view = checked(api, first, "/api/forecast")
    chart = view["chart"]
    assert view["currency"] == "GBP"
    assert view["forecast_id"].startswith("fc_")
    assert chart["scope"]["kind"] == "mine"
    assert chart["balance_mode"] == "absolute"  # P1 seeds a declared balance
    assert chart["summary"]["starting_balance"]["provenance"] == "declared"
    fan = chart["forecast"]
    assert all(
        lo <= mid <= hi for lo, mid, hi in zip(fan["p10"], fan["p50"], fan["p90"], strict=True)
    )
    assert chart["pay_cycles"], "P1 is salaried: pay-cycle lows expected"
    assert len(chart["history"]["dates"]) == 90
    # The newest history point is the forecast's starting balance.
    assert (
        chart["history"]["balance_minor"][-1]
        == chart["summary"]["starting_balance"]["money"]["minor"]
    )

    # Same question, unchanged data → the same stored calculation.
    again = checked(api, api.get("/api/forecast"), "/api/forecast")
    assert again["forecast_id"] == view["forecast_id"]

    calc_id = "calc_" + view["forecast_id"].removeprefix("fc_")
    ref = chart["summary"]["min_balance"]["ref"]
    assert ref == f"{calc_id}#min_balance_p50_minor"
    calc = checked(api, api.get(f"/api/calculations/{calc_id}"), "/api/calculations/{calc_id}")
    assert calc["kind"] == "forecast"
    assert calc["currency"] == "GBP"
    assert calc["result"]["min_balance_p50_minor"] == chart["summary"]["min_balance"]["minor"]
    # The headline low is one of the pay-cycle lows shown, never a different figure.
    lowest = min(chart["pay_cycles"], key=lambda c: c["low"]["minor"])
    assert chart["summary"]["min_balance"]["minor"] == lowest["low"]["minor"]
    assert chart["summary"]["min_date"]["value"] == lowest["low_date"]

    as_of = date.fromisoformat(chart["as_of"])
    spec = {
        "schema": "scenario_spec/1",
        "name": "Car repair",
        "scope": "mine",
        "currency": "GBP",
        "modifiers": [
            {"type": "one_off_outflow", "date": (as_of + timedelta(days=5)).isoformat(),
             "amount_minor": 50000, "label": "Car repair"},
        ],
    }  # fmt: skip
    sim = api.post("/api/simulate", json=spec)
    assert sim.status_code == 200, sim.text
    body = checked(api, sim, "/api/simulate")
    comparison = body["comparison"]
    # Same seed and inputs: the comparison's baseline is exactly the stored forecast.
    assert comparison["baseline"]["series"]["p50"] == fan["p50"]
    scenario = comparison["scenarios"][0]
    assert min(scenario["series"]["p50"]) < min(fan["p50"])
    assert scenario["modifiers_summary"][0].startswith("Pay £500.00 on ")
    lowest = comparison["comparison_rows"][0]
    assert lowest["delta"][0]["minor"] < 0
    assert comparison["verdict"]["kind"] in {
        "comfortable",
        "tight",
        "breaches_buffer",
        "goes_negative",
    }
    sim_calc = "calc_" + body["simulation_id"].removeprefix("sim_")
    assert api.get(f"/api/calculations/{sim_calc}").json()["kind"] == "simulation"

    # The demo is fictional: real statements never go into it, even a private copy.
    refused = api.post(
        "/api/imports", files=[("files", (P1_CSV.name, P1_CSV.read_bytes(), "text/csv"))]
    )
    assert refused.status_code == 403
    checked(api, refused, "/api/imports")


def test_own_profile_import_is_idempotent_and_honest(api: TestClient) -> None:
    profile = new_profile(api)
    assert profile["kind"] == "user"
    assert profile["data_version"] == 0

    empty = api.get("/api/forecast")
    assert empty.status_code == 409
    checked(api, empty, "/api/forecast")

    summary = upload(api, P1_CSV)
    (file,) = summary["files"]
    assert file["status"] == "imported"
    assert not file["already_imported"]
    assert file["rows_imported"] == file["rows_read"] > 0
    assert file["matched_profile"]
    assert file["period"]["from"] < file["period"]["to"]
    # A Monzo-style export has no balance column: never labelled reconciled.
    assert file["reconciliation"]["status"] == "not_possible"
    assert summary["import_id"] == file["import_ids"][0]

    again = upload(api, P1_CSV)["files"][0]
    assert again["status"] == "imported"
    assert again["already_imported"]
    assert again["rows_imported"] == 0

    page = checked(api, api.get("/api/transactions?limit=25"), "/api/transactions")
    assert page["total"] == file["rows_imported"]
    assert len(page["items"]) == 25
    dates = [row["posted_on"] for row in page["items"]]
    assert dates == sorted(dates, reverse=True)
    category = next(r["category_key"] for r in page["items"] if r["category_key"])
    filtered = api.get("/api/transactions", params={"category": category, "limit": 500}).json()
    assert filtered["total"] >= 1
    assert {r["category_key"] for r in filtered["items"]} == {category}
    last = api.get("/api/transactions", params={"offset": page["total"] - 1}).json()
    assert len(last["items"]) == 1

    # No balance yet: a relative forecast with no buffer or breach chance, never an invented one.
    view = checked(api, api.get("/api/forecast"), "/api/forecast")
    chart = view["chart"]
    assert chart["balance_mode"] == "relative"
    assert chart["buffer_minor"] is None
    assert chart["summary"]["p_breach_buffer"] is None
    assert all(c["chance_below_buffer"] is None for c in chart["pay_cycles"])

    # An ambiguous date order is asked, never guessed; nothing is imported until it's answered.
    asked = upload(api, BROKEN)["files"][0]
    assert asked["status"] == "needs_mapping"
    assert asked["rows_imported"] == 0
    assert [q["kind"] for q in asked["questions"]] == ["date_order"]
    files = [("files", (BROKEN.name, BROKEN.read_bytes(), "text/csv"))]
    answered = api.post("/api/imports", files=files, data={"answers": '{"date_order": "DMY"}'})
    broken = checked(api, answered, "/api/imports")["files"][0]
    assert broken["status"] == "rejected"
    assert broken["rows_imported"] == 0
    assert broken["rejections"]
    assert broken["reconciliation"]["status"] == "failed"
    assert api.get("/api/transactions").json()["total"] == page["total"]

    bad = api.post("/api/imports", files=files, data={"answers": '{"delete": "all"}'})
    assert bad.status_code == 422
    checked(api, bad, "/api/imports")


def test_profiles_are_isolated(make_client: type[TestClient]) -> None:
    from backend.app.main import create_app

    with (
        make_client(create_app(), base_url="https://testserver") as alice,
        make_client(create_app(), base_url="https://testserver") as bob,
    ):
        demo(alice)
        calc_id = "calc_" + alice.get("/api/forecast").json()["forecast_id"].removeprefix("fc_")
        assert alice.get(f"/api/calculations/{calc_id}").status_code == 200

        new_profile(bob)
        hidden = bob.get(f"/api/calculations/{calc_id}")
        assert hidden.status_code == 404  # not 403: existence is not leaked
        assert bob.get("/api/transactions").json()["total"] == 0

        stranger = make_client(create_app(), base_url="https://testserver")
        assert stranger.get("/api/forecast").status_code == 401
        # A forged cookie naming Alice's workspace is refused.
        workspace_id = alice.get("/api/session").json()["workspace_id"]
        stranger.cookies.set(COOKIE, f"{workspace_id}.forged")
        assert stranger.get("/api/forecast").status_code == 401
        stranger.close()


def test_scope_and_scenario_validation(api: TestClient) -> None:
    demo(api)
    assert api.get("/api/forecast", params={"scope": "household"}).status_code == 422
    assert api.get("/api/forecast", params={"scope": "everything"}).status_code == 422
    account = api.get("/api/forecast").json()["chart"]["scope"]["account_ids"][0]
    assert api.get("/api/forecast", params={"scope": f"account:{account}"}).status_code == 200
    assert api.get("/api/forecast", params={"scope": "account:acct_nope"}).status_code == 422

    base = {"schema": "scenario_spec/1", "name": "x", "scope": "mine", "currency": "GBP"}
    payment = {"type": "one_off_outflow", "date": "2030-01-01", "amount_minor": 1}
    euro = api.post("/api/simulate", json={**base, "currency": "EUR", "modifiers": [payment]})
    assert euro.status_code == 422
    unsupported = api.post(
        "/api/simulate", json={**base, "modifiers": [{"type": "category_cut_pct"}]}
    )
    assert unsupported.status_code == 422
    checked(api, unsupported, "/api/simulate")
    outside = api.post("/api/simulate", json={**base, "modifiers": [
        {"type": "one_off_outflow", "date": "2099-01-01", "amount_minor": 100}]})  # fmt: skip
    assert outside.status_code == 422


def test_openapi_documents_every_engine_route(api: TestClient) -> None:
    paths = api.get("/openapi.json").json()["paths"]
    for path, method in [
        ("/api/session/demo", "post"), ("/api/session/new", "post"), ("/api/session", "get"),
        ("/api/imports", "post"), ("/api/transactions", "get"), ("/api/forecast", "get"),
        ("/api/simulate", "post"), ("/api/calculations/{calc_id}", "get"),
    ]:  # fmt: skip
        operation = paths[path][method]
        ok = operation["responses"].get("200") or operation["responses"]["201"]
        assert "$ref" in ok["content"]["application/json"]["schema"], path


def test_home_forecast_reads_the_stored_calculation_quickly(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """docs/05 A5: opening Home never recomputes. The demo seed stores the forecast, so even the
    first request reads it: the engine (~3 s live) must not run, and the read stays under 0.5 s."""
    import time

    from backend.pipeline import forecast as fc

    demo(api)

    def engine_called(*_a: object, **_k: object) -> None:
        raise AssertionError("Home recomputed a forecast that was already stored")

    monkeypatch.setattr(fc, "calibration_for", engine_called)
    monkeypatch.setattr(fc, "build_forecast", engine_called)
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        response = api.get("/api/forecast")
        timings.append(time.perf_counter() - started)
        assert response.status_code == 200, response.text
    assert max(timings) <= 0.5, timings


def test_every_modifier_type_runs_through_the_api(api: TestClient) -> None:
    """R6: what the engine supports, the API accepts, with the ids /api/detected returns."""
    demo(api)
    chart = api.get("/api/forecast").json()["chart"]
    as_of = date.fromisoformat(chart["as_of"])
    soon = (as_of + timedelta(days=7)).isoformat()
    flows = api.get("/api/detected").json()
    income_id = flows["income"][0]["income_stream_id"]  # an inc_ id, not an engine key
    bill = next(r for r in flows["recurring"] if r["category_key"] != "housing.rent")
    base = {"schema": "scenario_spec/1", "name": "What if", "scope": "mine", "currency": "GBP"}
    modifiers = [
        {"type": "split_outflow", "date": soon, "amount_minor": 90000, "instalments": 3,
         "cadence": "monthly", "label": "Laptop"},
        {"type": "income_change_pct", "income_stream_key": income_id, "pct": -10},
        {"type": "income_delay", "income_stream_key": income_id, "days": 3},
        {"type": "recurring_cancel", "recurring_id": bill["recurring_id"], "from_date": soon},
        {"type": "category_cut_pct", "category_key": "food.delivery", "pct": 50},
        {"type": "category_cap", "category_key": "food.delivery", "monthly_cap_minor": 5000},
        {"type": "buffer_override", "buffer_minor": 100000},
    ]  # fmt: skip
    for mod in modifiers:
        response = api.post("/api/simulate", json={**base, "modifiers": [mod]})
        assert response.status_code == 200, (mod["type"], response.text)
        checked(api, response, "/api/simulate")
    bad = api.post(
        "/api/simulate",
        json={**base, "modifiers": [{"type": "category_cut_pct", "category_key": "food.delivery",
                                     "pct": 150}]},
    )  # fmt: skip
    assert bad.status_code == 422
    assert "between 0 and 100" in bad.text
