"""API-01: plan/hydrated models, the answer skeleton, currency, numerals and fallbacks."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from pydantic import ValidationError

from backend.app.ui_contracts.blocks import (
    EvidencePanel,
    FanSeries,
    FinancialMetricGroup,
    InterventionCard,
    Narrative,
    RiskAssessment,
    SpendingOverTime,
)
from backend.app.ui_contracts.money import display_money, money_value
from backend.app.ui_contracts.plan import MetricPlan, NarrativePlan, ResponsePlan
from backend.app.ui_contracts.primitives import AcceptRecommendationAction, MoneyAmount
from backend.app.ui_contracts.response import AgentResponse
from backend.app.ui_contracts.validation import (
    check_currency,
    check_plan_text,
    check_skeleton,
    enforce_skeleton,
    numeric_literals,
    parse_plan,
    parse_response,
    strip_numeral_sentences,
    visible_tabs,
)

U = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
CALC = f"calc_{U}"


def overview(slot: str) -> dict[str, str]:
    return {"area": "overview", "slot": slot}


def tab(name: str) -> dict[str, str]:
    return {"area": "tab", "tab": name}


def money(minor: int, currency: str = "GBP") -> dict[str, Any]:
    return {"kind": "money", "minor": minor, "currency": currency, "display": "x",
            "precision": "exact", "ref": f"{CALC}#result.value"}  # fmt: skip


def narrative(bid: str, placement: dict[str, str]) -> Narrative:
    return Narrative.model_validate(
        {
            "type": "Narrative",
            "block_id": bid,
            "placement": placement,
            "segments": [{"kind": "text", "text": "Hello"}],
        }  # fmt: skip
    )


def metrics(bid: str, n: int, placement: dict[str, str] | None = None) -> FinancialMetricGroup:
    metric = {"label": "Spent", "value": money(100), "tone": "neutral", "emphasis": "secondary"}
    return FinancialMetricGroup.model_validate(
        {
            "type": "FinancialMetricGroup",
            "block_id": bid,
            "currency": "GBP",
            "placement": placement or overview("key_numbers"),
            "metrics": [metric] * n,
        }  # fmt: skip
    )


def risk(bid: str, placement: dict[str, str]) -> RiskAssessment:
    return RiskAssessment.model_validate(
        {"type": "RiskAssessment", "block_id": bid, "placement": placement,
         "risks": [{"risk_id": "r1", "level": "watch", "headline": "Tight", "status": "open"}]}
    )  # fmt: skip


def evidence(bid: str, placement: dict[str, str]) -> EvidencePanel:
    return EvidencePanel.model_validate(
        {
            "type": "EvidencePanel",
            "block_id": bid,
            "placement": placement,
            "items": [
                {
                    "ref": CALC,
                    "kind": "calculation",
                    "title": "Sum",
                    "provenance": "observed",
                    "summary_lines": [],
                }
            ],
        }  # fmt: skip
    )


def card(status: str = "shown") -> dict[str, Any]:
    pct = {"kind": "percent", "value": 0.5, "display": "50%"}
    return {
        "type": "InterventionCard", "block_id": "c1", "placement": overview("what_to_do"),
        "currency": "GBP", "recommendation_id": f"rec_{U}", "version_id": "v1", "title": "Move it",
        "rationale_segments": [], "actions": [{"type": "timing", "label": "Move", "detail": ""}],
        "impact": {"p_breach_before": pct, "p_breach_after": pct,
                   "p_breach_window": {"from": "2026-10-01", "to": "2026-10-31"}},
        "verification": {"verdict": "approved", "revisions": 1, "checks_passed": 5,
                         "checks_total": 5, "verification_id": f"ver_{U}"},
        "status": status,
    }  # fmt: skip


def envelope(blocks: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": "agent_response/1", "response_id": f"rsp_{U}", "run_id": f"run_{U}",
        "surface": "workspace", "created_at": "2026-10-13T08:00:00Z", "as_of": "2026-10-13",
        "workspace_id": f"wsp_{U}", "currency": "GBP", "locale": "en-GB", "data_version": 1,
        "prefs_version": 1, "engine_version": "0.1.0", "status": "complete", "blocks": blocks,
        "provenance": {}, **extra,
    }  # fmt: skip


# --- Money -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("minor", "currency", "locale", "precision", "expected"),
    [
        (123456, "GBP", "en-GB", "exact", "£1,234.56"),
        (123456, "GBP", "en-GB", "rounded", "£1,235"),
        (123449, "GBP", "en-GB", "rounded", "£1,234"),
        (123450, "GBP", "en-GB", "rounded", "£1,235"),
        (-12250, "GBP", "en-GB", "rounded", "−£123"),
        (11500000, "INR", "en-IN", "exact", "₹1,15,000.00"),
        (4785012, "INR", "en-IN", "rounded", "₹47,850"),
        (1234, "JPY", "ja-JP", "exact", "1,234 JPY"),
        (1234567, "KWD", "en-GB", "rounded", "1,235 KWD"),
    ],
)
def test_money_display_is_server_formatted(
    minor: int, currency: str, locale: str, precision: Any, expected: str
) -> None:
    assert display_money(minor, currency, locale, precision) == expected


def test_money_value_keeps_exact_minor_units_when_rounded() -> None:
    value = money_value(MoneyAmount(amount_minor=60449, currency="GBP"), "en-GB", "rounded")
    assert (value.minor, value.display, value.precision) == (60449, "£604", "rounded")


# --- Models ------------------------------------------------------------------------------------


def test_plan_carries_references_not_numbers() -> None:
    with pytest.raises(ValidationError):
        MetricPlan.model_validate({"label": "Spent", "value_ref": "28640", "format": "money"})
    with pytest.raises(ValidationError, match="extra"):
        NarrativePlan.model_validate({"type": "Narrative", "text": "Hi", "amount_minor": 100})
    ok = MetricPlan.model_validate(
        {"label": "Spent", "value_ref": f"{CALC}#result.current_minor", "format": "money"}
    )
    assert ok.value_ref.endswith("current_minor")


def test_state_changing_follow_ups_need_confirmation() -> None:
    raw = {
        "action_id": "fu_1",
        "label": "Accept",
        "kind": "accept_recommendation",
        "payload": {"recommendation_id": f"rec_{U}"},
        "requires_confirmation": False,
    }
    with pytest.raises(ValidationError, match="confirmation"):
        AcceptRecommendationAction.model_validate(raw)
    assert AcceptRecommendationAction.model_validate({**raw, "requires_confirmation": True})


@pytest.mark.parametrize("status", ["drafting", "rejected", "withdrawn", "expired"])
def test_only_checked_recommendations_render_as_cards(status: str) -> None:
    InterventionCard.model_validate(card())
    with pytest.raises(ValidationError, match="cannot be shown as checked"):
        InterventionCard.model_validate(card(status))


def test_series_lengths_must_line_up() -> None:
    with pytest.raises(ValidationError, match="differ in length"):
        FanSeries(dates=["2026-10-13"], p10=[1], p50=[1, 2], p90=[1])  # type: ignore[list-item]
    with pytest.raises(ValidationError, match="one value per x bucket"):
        SpendingOverTime.model_validate(
            {
                "type": "SpendingBreakdownChart",
                "mode": "over_time",
                "block_id": "b",
                "placement": tab("details"),
                "period": {"from": "2026-09-01", "to": "2026-09-30"},
                "total": money(1),
                "x": ["w1", "w2"],
                "series": [{"key": "k", "label": "K", "values": [1]}],
            }  # fmt: skip
        )


def test_spending_chart_shape_is_chosen_by_mode() -> None:
    raw = envelope([
        {"type": "SpendingBreakdownChart", "mode": "by_category", "block_id": "b",
         "currency": "GBP", "placement": overview("main_visual"),
         "period": {"from": "2026-09-01", "to": "2026-09-30"}, "total": money(300),
         "series": [{"key": "food", "label": "Food", "nature": "essential", "value": money(300),
                     "tone": "neutral"}]},
    ])  # fmt: skip
    assert type(AgentResponse.model_validate(raw).blocks[0]).__name__ == "SpendingByCategory"


# --- Numerals in plan text ---------------------------------------------------------------------


def test_numerals_outside_placeholders_are_flagged() -> None:
    text = f"Up {{{{{CALC}#result.pct|pct_change}}}} since {{{{fnd_{U}}}}}; that's £40 or 12%."
    assert numeric_literals(text) == ["£40", "12%"]
    assert numeric_literals(f"Spent {{{{{CALC}#result.total|money}}}} so far.") == []


def test_plan_text_check_covers_labels_and_bad_placeholders() -> None:
    plan = ResponsePlan.model_validate({
        "schema": "response_plan/1", "intent": "spending_question",
        "blocks": [
            {"type": "Narrative", "text": f"See {{{{{CALC}#result.total}}}} and {{{{txn_{U}}}}}."},
            {"type": "FinancialMetricGroup", "metrics": [
                {"label": "Last 30 days", "value_ref": f"{CALC}#result.a", "format": "money"},
                {"label": "Usual", "value_ref": f"{CALC}#result.b", "format": "money"}]},
        ],
        "follow_ups": [{"kind": "ask", "label": "Cap at £100?", "payload": {"question": "q"}}],
    })  # fmt: skip
    codes = [(i.code, i.message.split(":")[0]) for i in check_plan_text(plan)]
    assert codes == [
        ("placeholder_invalid", "blocks.0.text"),
        ("placeholder_invalid", "blocks.0.text"),
        ("narrative_numeral", "blocks.1.metrics.0.label"),
        ("narrative_numeral", "follow_ups.0.label"),
    ]


def test_failed_repair_strips_only_sentences_with_numbers() -> None:
    text = "Spending rose. It went up by 41%. Most of it was one app."
    assert strip_numeral_sentences(text) == "Spending rose. Most of it was one app."


# --- Answer skeleton ---------------------------------------------------------------------------


def raw(kind: str, placement: dict[str, str], **extra: Any) -> dict[str, Any]:
    return {"type": kind, "block_id": kind, "placement": placement, **extra}


def test_skeleton_accepts_the_standard_frame() -> None:
    blocks = [
        raw("Narrative", overview("verdict")),
        raw("FinancialMetricGroup", overview("key_numbers"), metrics=[1, 2, 3]),
        raw("ScenarioComparison", overview("main_visual")),
        raw("InterventionCard", overview("what_to_do")),
        raw("CashFlowForecastChart", tab("details")),
        raw("AgentExecutionTimeline", tab("checked")),
    ]
    assert check_skeleton(blocks) == []
    assert visible_tabs(blocks) == ["details", "checked"]


@pytest.mark.parametrize(
    ("visuals", "ok"),
    [
        ([], False),
        (["ScenarioComparison"], True),
        (["ScenarioComparison", "CashFlowForecastChart"], False),
        (["RiskAssessment", "CashFlowForecastChart"], True),  # risk_check pair (§7a)
        (["InterventionCard"] * 3, True),  # advice_request
        (["InterventionCard"] * 4, False),
    ],
)
def test_exactly_one_main_visual(visuals: list[str], ok: bool) -> None:
    blocks = [
        raw("Narrative", overview("verdict")),
        raw("FinancialMetricGroup", overview("key_numbers"), metrics=[1, 2]),
    ] + [raw(v, overview("main_visual")) for v in visuals]
    assert (check_skeleton(blocks) == []) is ok


def test_verdict_only_answers_need_no_main_visual() -> None:
    assert check_skeleton([raw("ClarifyingQuestion", overview("verdict"))]) == []


def test_skeleton_reports_order_budget_type_and_duplicates() -> None:
    blocks = [
        raw("SpendingBreakdownChart", overview("main_visual")),
        raw("Narrative", overview("verdict")),
        raw("Narrative", overview("verdict")),
        raw("FinancialMetricGroup", overview("key_numbers"), metrics=[1, 2, 3, 4]),
        raw("TransactionTable", overview("what_to_do")),
        raw("EvidencePanel", tab("checked")),
        raw("EvidencePanel", tab("checked")),
    ]
    codes = sorted({i.code for i in check_skeleton(blocks)})
    assert codes == [
        "skeleton_budget", "skeleton_slot_order", "skeleton_slot_type", "skeleton_tab_duplicate",
    ]  # fmt: skip


def test_enforce_moves_overflow_to_tabs_never_drops_it(caplog: pytest.LogCaptureFixture) -> None:
    blocks = [
        risk("r1", overview("main_visual")),
        metrics("m1", 4),
        narrative("n1", overview("verdict")),
        evidence("e1", overview("main_visual")),
        narrative("n2", overview("verdict")),
        evidence("e0", tab("checked")),
    ]
    with caplog.at_level(logging.WARNING, logger="foresight.ui_contracts"):
        out, issues = enforce_skeleton(blocks)
    placed = [(b.block_id, b.placement.model_dump()) for b in out]
    assert placed == [
        ("n1", overview("verdict")),
        ("m1", overview("key_numbers")),
        ("r1", overview("main_visual")),
        ("n2", tab("details")),
        ("m1-more", tab("details")),
        ("e0", tab("checked")),
    ]
    assert [len(b.metrics) for b in out if isinstance(b, FinancialMetricGroup)] == [3, 1]
    # e1 has nowhere to go: Checked already holds an EvidencePanel.
    assert [i.code for i in issues] == [
        "overview_overflow", "overview_overflow", "skeleton_tab_duplicate",
    ]  # fmt: skip
    assert caplog.text.count("overview_overflow") == 2
    assert check_skeleton(out) == []


def test_enforce_reports_a_missing_main_visual() -> None:
    _, issues = enforce_skeleton([narrative("n", overview("verdict")), metrics("m", 2)])
    assert [i.code for i in issues] == ["skeleton_main_visual"]


# --- Currency ----------------------------------------------------------------------------------


def test_one_currency_per_block_and_per_response() -> None:
    usd = metrics("m", 2).model_dump(mode="json")
    usd["metrics"][1]["value"] = money(100, "USD")
    no_currency = {**metrics("k", 2, overview("main_visual")).model_dump(mode="json")}
    no_currency["currency"] = None
    eur = {**evidence("e", tab("checked")).model_dump(mode="json"), "currency": "EUR"}
    codes = [(i.code, i.block_id) for i in check_currency(envelope([usd, no_currency, eur]))]
    assert codes == [
        ("currency_mix", "m"), ("block_currency_missing", "k"), ("currency_mix", "e"),
    ]  # fmt: skip


# --- Fallbacks ---------------------------------------------------------------------------------


def test_unknown_plan_block_becomes_a_narrative_with_a_logged_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_plan = {
        "schema": "response_plan/1", "intent": "spending_question",
        "blocks": [{"type": "PieChart", "slices": []}, {"type": "Narrative", "text": "Hi"}],
        "follow_ups": [{"kind": "open_tab", "label": "Go", "payload": {}}],
    }  # fmt: skip
    with caplog.at_level(logging.WARNING, logger="foresight.ui_contracts"):
        plan, issues = parse_plan(raw_plan)
    assert isinstance(plan.blocks[0], NarrativePlan)
    assert "couldn't show this view" in plan.blocks[0].text
    assert plan.follow_ups == []
    assert [i.code for i in issues] == ["unknown_block", "invalid_follow_up"]
    assert "unknown block type 'PieChart'" in caplog.text


def test_invalid_hydrated_block_keeps_its_place_and_degrades_the_response() -> None:
    bad = {**card(), "version_id": None}
    response, issues = parse_response(
        envelope([narrative("n", overview("verdict")).model_dump(mode="json"), bad])
    )
    fallback = response.blocks[1]
    assert isinstance(fallback, Narrative)
    assert fallback.block_id == "c1"
    assert fallback.placement.model_dump() == overview("what_to_do")
    assert "the recommendation" in fallback.segments[0].text  # type: ignore[union-attr]
    assert response.status == "degraded"
    assert [i.code for i in issues] == ["invalid_block"]
