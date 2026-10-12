from __future__ import annotations

import pytest

from backend.finance_core.categorise.normalise import normalise_narration, parse_narration
from backend.finance_core.types import Channel, FlowKind
from tests.unit.categorise.helpers import uk_pack


def test_pack_loads_taxonomy_and_rules() -> None:
    pack = uk_pack()
    assert pack.country == "GB"
    assert pack.currency == "GBP"
    assert "food.delivery" in pack.categories
    assert pack.categories["family_support_abroad"].default_flow_kind == FlowKind.COMMITMENT
    assert pack.protected_categories == {"family_support_abroad", "savings_investment"}
    assert pack.seasonal_defaults["housing.council_tax"] == frozenset(
        {4, 5, 6, 7, 8, 9, 10, 11, 12, 1}
    )
    rule_categories = {r.category for r in pack.rules}
    assert rule_categories <= set(pack.categories), "every rule targets a taxonomy key"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("DELIVEROO 12 OCT ****1234", "DELIVEROO"),
        ("TFL TRAVEL CH 14/10/26 10:42", "TFL TRAVEL CH"),
        ("AMAZON EU AMAZON.CO.UK GBR", "AMAZON EU AMAZON.CO.UK GBR"),
        ("FPO J SMITH REF 77123456 RENT", "FPO J SMITH REF RENT"),
        ("TESCO STORES 3412  £12.40", "TESCO STORES 3412"),
    ],
)
def test_normalise_strips_cards_dates_refs_and_amounts(raw: str, expected: str) -> None:
    assert normalise_narration(raw) == expected


def test_normalised_output_contains_no_long_numbers() -> None:
    out = normalise_narration("BGC ACME LTD PAYROLL 12345678 ACC 87654321 SORT 401162")
    assert not any(ch.isdigit() for ch in out)


@pytest.mark.parametrize(
    ("description", "bank_type", "channel"),
    [
        ("NORTHSIDE LETTINGS SO", None, Channel.STANDING_ORDER),
        ("YORKSHIRE WATER DD", None, Channel.DIRECT_DEBIT),
        ("ACME ANALYTICS LTD", "Bacs (Direct Credit)", Channel.BACS_CREDIT),
        ("Deliveroo", "Card payment", Channel.CARD),
        ("LINK ATM WITHDRAWAL", "ATM", Channel.CASH),
        ("SOMETHING ELSE", None, Channel.OTHER),
    ],
)
def test_channel_from_pack(description: str, bank_type: str | None, channel: Channel) -> None:
    assert parse_narration(description, bank_type, uk_pack()).channel == channel


def test_counterparty_drops_codes_and_noise() -> None:
    parsed = parse_narration("DD YORKSHIRE WATER LTD", None, uk_pack())
    assert parsed.counterparty == "YORKSHIRE WATER"
