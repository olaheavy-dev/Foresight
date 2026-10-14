from __future__ import annotations

from datetime import date

import pytest

from backend.finance_core.categorise.pack import bank_category_key
from backend.finance_core.categorise.rules import (
    CategoriseContext,
    MemoryEntry,
    categorise,
    learn,
    needs_review,
)
from backend.finance_core.types import CategorisationMethod, FlowKind
from tests.unit.categorise.helpers import txn, uk_pack


@pytest.mark.parametrize(
    ("description", "category", "flow"),
    [
        ("DELIVEROO", "food.delivery", FlowKind.SPENDING),
        ("UBER EATS LONDON", "food.delivery", FlowKind.SPENDING),
        ("UBER TRIP", "transport.taxi", FlowKind.SPENDING),
        ("TESCO STORES 3412", "groceries", FlowKind.SPENDING),
        ("LEMFI", "family_support_abroad", FlowKind.COMMITMENT),
        ("LEEDS CITY COUNCIL TAX DD", "housing.council_tax", FlowKind.SPENDING),
        ("OCTOPUS ENERGY DD", "utilities.energy", FlowKind.SPENDING),
        ("SKY TV DD", "utilities.broadband_tv", FlowKind.SPENDING),
        ("NOW ENTERTAINMENT", "subscriptions.streaming", FlowKind.SPENDING),
        ("PUREGYM", "subscriptions.fitness", FlowKind.SPENDING),
        ("SKY BET", "betting", FlowKind.BETTING),
        ("KLARNA", "debt.bnpl", FlowKind.LOAN_REPAYMENT),
        ("KWIKFIT LEEDS", "transport.car", FlowKind.SPENDING),
        ("OVERDRAFT FEE", "fees.bank", FlowKind.FEE),
        (
            "CAPITAL ONE PAYMENT",
            "credit_card_bill_unitemised",
            FlowKind.CREDIT_CARD_BILL_UNITEMISED,
        ),
        ("POT TRANSFER", "savings_investment", FlowKind.SAVINGS_INVESTMENT),
    ],
)
def test_outflow_rules(description: str, category: str, flow: FlowKind) -> None:
    result = categorise(txn(description, -1234), uk_pack())
    assert (result.category_key, result.flow_kind) == (category, flow)
    assert not needs_review(result)


def test_unknown_outflow_goes_to_review() -> None:
    result = categorise(txn("ZZQX TRADING", -500), uk_pack())
    assert result.category_key == "uncategorised"
    assert needs_review(result)


@pytest.mark.parametrize(
    ("bank", "bank_category"),
    [("monzo", "Eating out"), ("Monzo", "eating_out"), ("MONZO", "Eating-Out ")],
)
def test_bank_category_names_match_however_the_bank_writes_them(
    bank: str, bank_category: str
) -> None:
    row = txn("ZZQX BISTRO", -1800, bank_category=bank_category)
    result = categorise(row, uk_pack(), CategoriseContext(bank=bank))
    assert result.category_key == "food.eating_out"


def test_bank_category_key_is_canonical() -> None:
    assert bank_category_key("Eating out") == "eating_out"
    assert bank_category_key(" Personal care ") == "personal_care"
    assert bank_category_key("Bills & utilities") == "bills_utilities"
    assert set(uk_pack().bank_category_priors["revolut"]) >= {"restaurants", "groceries"}


def test_bank_category_is_only_a_weak_prior() -> None:
    row = txn("ZZQX KOSMOS", -1800, bank_category="eating_out")
    result = categorise(row, uk_pack(), CategoriseContext(bank="monzo"))
    assert result.category_key == "food.eating_out"
    assert result.confidence == pytest.approx(0.6)
    assert needs_review(result)


class TestInflowLadder:
    def test_salary_from_employer_by_bacs(self) -> None:
        row = txn("ACME ANALYTICS LTD", 405000, bank_type="Bacs (Direct Credit)")
        result = categorise(row, uk_pack())
        assert (result.category_key, result.flow_kind) == ("income.salary", FlowKind.INCOME)

    def test_own_name_is_transfer_not_income(self) -> None:
        row = txn("PAYMENT FROM A NWOSU", 15000, bank_type="Top up")
        ctx = CategoriseContext(self_aliases=("A NWOSU", "AMARA NWOSU"))
        result = categorise(row, uk_pack(), ctx)
        assert result.flow_kind == FlowKind.TRANSFER_FROM_UNTRACKED

    def test_paired_transfer_is_own(self) -> None:
        row = txn("TFR FROM SAVINGS", 20000)
        result = categorise(
            row, uk_pack(), CategoriseContext(paired_transfer_ids=frozenset({row.id}))
        )
        assert result.flow_kind == FlowKind.TRANSFER_OWN

    def test_refund_matches_earlier_debit(self) -> None:
        debit = txn("ASOS.COM", -4500, on=date(2026, 9, 20))
        refund = txn("ASOS.COM", 4500, on=date(2026, 10, 2))
        result = categorise(refund, uk_pack(), CategoriseContext(prior_debits=(debit,)))
        assert result.flow_kind == FlowKind.REFUND

    def test_government_payer_is_income(self) -> None:
        result = categorise(txn("DWP UC", 40000), uk_pack())
        assert (result.category_key, result.flow_kind) == ("income.benefits", FlowKind.INCOME)

    def test_betting_winnings_are_not_income(self) -> None:
        result = categorise(txn("SKY BET", 2500), uk_pack())
        assert result.flow_kind == FlowKind.BETTING_RETURN

    def test_money_from_a_person_is_unconfirmed(self) -> None:
        result = categorise(txn("T OKAFOR", 20000, bank_type="Faster payment"), uk_pack())
        assert result.flow_kind == FlowKind.INFLOW_UNCONFIRMED
        assert result.category_key == "inflow_unconfirmed"


def test_memory_overrides_rules_and_user_wins() -> None:
    row = txn("DELIVEROO", -1500)
    assert row.counterparty is not None
    memory = learn({}, row.counterparty, "food.eating_out", "user")
    memory = learn(memory, row.counterparty, "groceries", "learned")  # must not override the user
    result = categorise(row, uk_pack(), CategoriseContext(memory=memory))
    assert result.category_key == "food.eating_out"
    assert result.method == CategorisationMethod.USER
    assert result.confidence == 1.0
    learned = {row.counterparty: MemoryEntry("groceries", "learned")}
    assert categorise(row, uk_pack(), CategoriseContext(memory=learned)).method == (
        CategorisationMethod.MEMORY
    )


@pytest.mark.parametrize(
    ("description", "category"),
    [
        # Pack phrases and narrations compare the same way: "-" is a space, "&" is AND.
        ("CO-OP GROUP 6767", "groceries"),
        ("TONI AND GUY LEEDS", "personal_care"),
        ("TONI & GUY LEEDS", "personal_care"),
        # General UK merchants and keywords (13 Oct 2026, from the dev split).
        ("FIRST WEST YORKSHIRE", "transport.public"),
        ("WILKO 6772", "shopping.general"),
        ("THE ROYAL OAK PUB", "food.eating_out"),
        ("SKY", "utilities.broadband_tv"),
        ("NOW", "subscriptions.streaming"),
    ],
)
def test_general_merchant_matching(description: str, category: str) -> None:
    assert categorise(txn(description, -1234), uk_pack()).category_key == category


def test_bare_sky_does_not_swallow_sky_bet_and_first_direct_is_not_a_bus() -> None:
    assert categorise(txn("SKY BET", -1000), uk_pack()).category_key == "betting"
    assert categorise(txn("FIRST DIRECT", -1000), uk_pack()).category_key != "transport.public"


def test_standing_order_to_a_housing_company_is_rent_but_a_card_spend_is_not() -> None:
    assert categorise(txn("SO HARBOURSIDE HOMES", -95000), uk_pack()).category_key == "housing.rent"
    assert categorise(txn("DEB DUNELM HOMES", -4000), uk_pack()).category_key != "housing.rent"
