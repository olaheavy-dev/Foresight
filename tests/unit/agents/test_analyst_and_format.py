"""Behaviour Analyst wording checks and ranking (AGT-04), deterministic finding candidates, and
the ING-13 format proposal (shapes only, validation, parse check). Mesh is a scripted fake."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from backend.agents import analyst as an
from backend.agents import findings as fd
from backend.agents import format_profile as fp
from backend.agents.guard import output_screen
from backend.agents.ledger_nodes import period_range
from backend.finance_core.importers.table_locator import decode, locate_tables
from evals.common import (
    build_ledger,
    expected_rows,
    import_bytes,
    load_dataset,
    row_precision_recall,
    uk_categorisation_pack,
)
from tests.unit.mesh.fakes import ScriptedCompletions, client, json_ok

# ------------------------------------------------------------------------------ findings


def _p1_specs() -> list[fd.CandidateSpec]:
    ds = load_dataset("P1-base")
    ledger = build_ledger(ds)
    return fd.build_candidates(
        ledger.txns, ledger.cats, uk_categorisation_pack(),
        as_of=fd.data_end(ledger.txns, ds.as_of), workspace_id="wsp_test", currency="GBP",
    )  # fmt: skip


def test_p1_has_a_food_delivery_spike_with_hydratable_placeholders() -> None:
    specs = _p1_specs()
    spike = next(s for s in specs if s.dedupe_key == "category_spike:food.delivery")
    assert spike.strength in {"strong", "moderate"}
    assert spike.stats["recent_minor"] > spike.stats["usual_minor"] > 0
    assert all(p.startswith("{{" + spike.calc_id + "#") for p in spike.placeholders.values())
    # template wording never carries a numeral outside its placeholders
    for s in specs:
        assert output_screen(s.headline + " " + s.detail) == []


def test_candidates_are_deterministic() -> None:
    a, b = _p1_specs(), _p1_specs()
    assert [(s.dedupe_key, s.calc_id) for s in a] == [(s.dedupe_key, s.calc_id) for s in b]


# ------------------------------------------------------------------------------ analyst


def _pairs() -> list[tuple[str, fd.CandidateSpec]]:
    # P1 has two candidate findings; the third id (a repeat of the first spec) is the one discarded.
    specs = _p1_specs()
    return [(f"fnd_{i}", s) for i, s in enumerate((specs + specs)[:3])]


def test_problems_flag_numerals_and_foreign_placeholders() -> None:
    allowed = {"{{calc_a#x|money}}"}
    assert an.problems("Up {{calc_a#x|money}} on usual", allowed, "uk") == []
    assert an.problems("Up £45 on usual", allowed, "uk")
    assert an.problems("Up {{calc_b#x|money}}", allowed, "uk")
    assert an.problems("Open a savings account at https://example.com", allowed, "uk")


def test_model_wording_is_kept_when_clean_and_replaced_when_not() -> None:
    pairs = _pairs()
    (f0, s0), (f1, s1) = pairs[0], pairs[1]
    good = {
        "finding_id": f0,
        "salience": 5,
        "headline": f"Food delivery is up {s0.placeholders['change']}",
        "explanation": f"You spent {s0.placeholders['recent']} recently.",
    }
    bad = {"finding_id": f1, "salience": 3, "headline": "Up 41% on usual", "explanation": "x"}
    answer = json_ok(
        {"findings": [good, bad], "discarded": [{"finding_id": pairs[2][0], "reason": "weak"}]}
    )
    fake = ScriptedCompletions(answer, answer)
    out = an.rank_with_model(pairs, client(fake))
    assert len(fake.calls) == 2
    assert out.repaired
    by_id = {w.finding_id: w for w in out.ranked}
    assert by_id[f0].source == "llm"
    assert by_id[f0].salience == 5
    assert by_id[f1].source == "template"
    assert by_id[f1].headline == s1.headline
    assert out.discarded == {pairs[2][0]: "weak"}
    assert out.ranked[0].finding_id == f0
    assert out.violations[f1]


def test_finding_ids_are_an_enum() -> None:
    schema = an.output_model(["fnd_a", "fnd_b"]).model_json_schema()
    assert schema["$defs"]["RankedFinding"]["properties"]["finding_id"]["enum"] == [
        "fnd_a",
        "fnd_b",
    ]


def test_template_ranking_without_a_model() -> None:
    out = an.template_ranking(_pairs())
    assert out.calls == []
    assert all(w.source == "template" for w in out.ranked)


# ------------------------------------------------------------------------------ ING-13


def test_shape_hides_values() -> None:
    assert fp.shape("-1,234.56") == "-9,999.99"
    assert fp.shape("12 Mar 2026") == "99 <MON> 9999"
    assert fp.shape("TESCO STORES 5113") == "<TEXT>"
    assert fp.shape("") == ""


def _c1() -> tuple[str, bytes, Any]:
    ds = load_dataset("C1-pennine")
    file = next(iter(ds.layout))
    return file, ds.file_bytes(file), ds


def _c1_answer(kwargs: dict[str, Any]) -> Any:
    payload = json.loads(kwargs["messages"][-1]["content"])
    titles = {c["title"].lower(): c["index"] for c in payload["columns"]}
    assert all("<TEXT>" in row or any("9" in v for v in row) for row in payload["sample_rows"])
    assert len(payload["sample_rows"]) <= fp.MAX_SAMPLE_ROWS
    return json_ok(
        {
            "date": titles["posting date"],
            "description": titles["narrative"],
            "amount": None,
            "money_in": titles["lodgements"],
            "money_out": titles["withdrawals"],
            "balance": titles["running total"],
            "id": None,
            "bank_category": None,
            "bank_type": None,
            "currency": None,
            "time": None,
            "sign_convention": "in_out",
            "confidence": 0.9,
        }  # fmt: skip
    )


def test_c1_proposal_parses_the_file_exactly_once_confirmed() -> None:
    file, data, ds = _c1()
    table = next(t for t in locate_tables(decode(data)) if t.rows)
    fake = ScriptedCompletions(_c1_answer)
    proposal = fp.propose(table.headers, [c for _r, c in table.rows], client(fake))
    sent = fake.calls[0]["messages"][-1]["content"]
    assert "SAINSBURY" not in sent
    assert "2721.87" not in sent
    assert proposal.profile is not None
    assert proposal.problems == []
    profile = fp.confirmed(proposal.profile)
    fi = import_bytes(file, data, home_currency="GBP", saved_profiles=[profile])
    answers = {
        q.kind: q.preselected or q.options[0]
        for t in fi.tables
        for q in t.result.questions
        if q.kind in {"date_order", "currency", "decimal_separator"}
    }
    if answers:
        fi = import_bytes(
            file, data, home_currency="GBP", saved_profiles=[profile], answers=answers
        )
    rows = [r for t in fi.tables for r in t.result.rows]
    p, r, *_ = row_precision_recall(rows, [t for t in expected_rows(ds) if t["file"] == file])
    assert (p, r) == (1.0, 1.0)


def test_invalid_proposals_are_refused() -> None:
    headers = ["A", "B", "C"]
    value = fp.ColumnProposal(
        date=0, description=0, amount=None, money_in=None, money_out=None, balance=None, id=None,
        bank_category=None, bank_type=None, currency=None, time=None,
        sign_convention="signed", confidence=0.5,
    )  # fmt: skip
    _roles, issues = fp.validate(value, headers)
    assert any("same column" in i for i in issues)
    assert any("amount" in i for i in issues)


# ------------------------------------------------------------------------------ queries


def test_period_range() -> None:
    today = date(2026, 10, 11)
    assert period_range("last_30d", today) == (today - timedelta(days=29), today)
    assert period_range("March", today) == (date(2026, 3, 1), date(2026, 3, 31))
    assert period_range("November", today) == (date(2025, 11, 1), date(2025, 11, 30))
    assert period_range("last month", today) == (date(2026, 9, 1), date(2026, 9, 30))
    assert period_range("someday", today) == (None, None)
